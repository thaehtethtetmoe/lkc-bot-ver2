"""
elentra_client.py
All Elentra HTTP helpers shared between app.py and the WebJob.
No Flask imports — safe to import from anywhere.

app.py imports all of these at line 66-77.
scheduler.py imports what it needs directly from here.
"""

import re
import time
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

BASE_URL = "https://ntu.elentra.cloud"

# ── Per-process caches (fine for WebJob; app.py also uses these) ───────────
attendance_marked_cache: dict = {}

_absence_policy_cache      = None
_absence_policy_cached_at  = None


# ════════════════════════════════════════════════════════
# ELENTRA LOGIN
# ════════════════════════════════════════════════════════

def elentra_login(username, password):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": BASE_URL})

    try:
        login_page = session.get(f"{BASE_URL}/", timeout=10)
    except requests.exceptions.Timeout:
        raise Exception("ELENTRA_TIMEOUT")
    except requests.exceptions.ConnectionError:
        raise Exception("ELENTRA_UNREACHABLE")

    soup       = BeautifulSoup(login_page.text, "html.parser")
    csrf_input = soup.find("input", {"name": "_token"})
    csrf_token = csrf_input["value"] if csrf_input else ""

    try:
        session.post(f"{BASE_URL}/", data={
            "action": "login", "ssobypass": "1",
            "username": username, "password": password, "_token": csrf_token
        }, timeout=10)
    except requests.exceptions.Timeout:
        raise Exception("ELENTRA_TIMEOUT")
    except requests.exceptions.ConnectionError:
        raise Exception("ELENTRA_UNREACHABLE")

    jwt_token = None
    try:
        dashboard = session.get(f"{BASE_URL}/", timeout=10)
        jwt_match = re.search(r"var JWT\s*=\s*'([^']+)'", dashboard.text)
        if jwt_match:
            jwt_token = jwt_match.group(1)
            print("[LOGIN] JWT extracted successfully")
        else:
            print("[LOGIN] JWT not found in page")
    except requests.exceptions.Timeout:
        raise Exception("ELENTRA_TIMEOUT")
    except requests.exceptions.ConnectionError:
        raise Exception("ELENTRA_UNREACHABLE")

    try:
        test = session.get(f"{BASE_URL}/api/events-calendar.api.php", params={
            "dtype": "week", "dstamp": int(time.time()),
            "local_timezone": "Asia/Singapore", "viewtype": "list",
            "parentonly": "no", "pv": "1"
        }, timeout=10)
    except requests.exceptions.Timeout:
        raise Exception("ELENTRA_TIMEOUT")
    except requests.exceptions.ConnectionError:
        raise Exception("ELENTRA_UNREACHABLE")

    try:
        data = test.json()
    except Exception:
        if test.status_code in (200, 302) and "login" in test.text.lower():
            raise Exception("INVALID_CREDENTIALS")
        raise Exception("ELENTRA_UNSTABLE")

    if "events" not in data:
        raise Exception("INVALID_CREDENTIALS")

    return session, jwt_token


# ════════════════════════════════════════════════════════
# EVENTS
# ════════════════════════════════════════════════════════

def fetch_events(session, weeks=3):
    all_events = []
    now = int(time.time())
    for week_offset in range(weeks):
        ts   = now + (week_offset * 7 * 24 * 3600)
        resp = session.get(f"{BASE_URL}/api/events-calendar.api.php", params={
            "dtype": "week", "dstamp": ts,
            "local_timezone": "Asia/Singapore", "viewtype": "list",
            "parentonly": "no", "pv": "1"
        })
        try:
            data = resp.json()
            all_events.extend(data.get("events", []))
        except Exception:
            continue
    return all_events


def event_start_datetime(event):
    try:
        event_time = event["time"].split()[0]
        return datetime.strptime(f"{event['date']} {event_time}", "%A, %d %b %Y %H:%M")
    except Exception:
        return datetime.max


def filter_events_between(events, start_dt, end_dt):
    return [e for e in events if start_dt <= event_start_datetime(e) < end_dt]


def format_events(events):
    result = []
    for e in events:
        start = datetime.strptime(e["start_date"], "%Y-%m-%d %H:%M")
        end   = datetime.strptime(e["end_date"],   "%Y-%m-%d %H:%M")
        result.append({
            "id":             e["event_id"],
            "title":          e["text"],
            "course_code":    e["course_code"],
            "date":           start.strftime("%A, %d %b %Y"),
            "time":           f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')}",
            "start_dt":       start.strftime("%Y-%m-%d %H:%M"),
            "duration_hours": round((end - start).seconds / 3600, 1),
            "location":       e["event_location"],
            "attendance":     "Required" if (
                str(e.get("attendance_required", "0")) in ("1", "true", "True") or
                e.get("attendance_method") == "location"
            ) else "Optional"
        })
    result.sort(key=event_start_datetime)
    return result


def format_events_text(title, events, empty_message):
    if not events:
        return empty_message
    lines = [title]
    current_date = None
    for event in events:
        if event["date"] != current_date:
            current_date = event["date"]
            lines.extend(["", current_date])
        lines.append(
            f"- {event['title']}\n"
            f"  Time: {event['time']}\n"
            f"  Location: {event['location']}\n"
            f"  Course: {event['course_code']}\n"
            f"  Attendance: {event['attendance']}"
        )
    return "\n".join(lines)


# ════════════════════════════════════════════════════════
# ABSENCES / LOA
# ════════════════════════════════════════════════════════

def fetch_absences(session, jwt_token=None):
    try:
        if not jwt_token:
            print("[ABSENCES] No JWT token available")
            return None, None

        headers  = {"Authorization": f"Bearer {jwt_token}"}
        req_resp = session.get(
            f"{BASE_URL}/api/v2/absences/details/my-requests", headers=headers
        )
        tot_resp = session.get(
            f"{BASE_URL}/api/v2/absences/users/totals", headers=headers
        )
        raw_req = req_resp.json()
        raw_tot = tot_resp.json()

        if (isinstance(raw_req, list) and raw_req and raw_req[0] == "not_authorized") or \
           (isinstance(raw_tot, list) and raw_tot and raw_tot[0] == "not_authorized"):
            print("[ABSENCES] Still not authorized")
            return None, None

        requests_data = raw_req if isinstance(raw_req, list) else raw_req.get("details", [])
        totals_data   = raw_tot if isinstance(raw_tot, list) else raw_tot.get("totals",  [])
        return requests_data, totals_data

    except Exception as ex:
        print(f"[ABSENCES] fetch error: {ex}")
        return None, None


def format_absences(requests_data, totals_data):
    quotas = []
    for pool in totals_data:
        if not isinstance(pool, dict):
            continue
        pending  = next((t["total"] for t in pool.get("totals", []) if isinstance(t, dict) and t.get("title") == "Pending"),  0)
        approved = next((t["total"] for t in pool.get("totals", []) if isinstance(t, dict) and t.get("title") == "Approved"), 0)
        rejected = next((t["total"] for t in pool.get("totals", []) if isinstance(t, dict) and t.get("title") == "Rejected"), 0)
        quotas.append({
            "academic_year": pool.get("title", "Unknown"),
            "total_allowed": pool.get("amount", 0),
            "approved":      approved,
            "pending":       pending,
            "rejected":      rejected,
            "remaining":     pool.get("amount", 0) - approved
        })

    absence_list = []
    for r in requests_data:
        if not isinstance(r, dict):
            continue
        from_dt = datetime.fromtimestamp(r["from"]).strftime("%d %b %Y") if r.get("from") else "N/A"
        to_dt   = datetime.fromtimestamp(r["to"]).strftime("%d %b %Y")   if r.get("to")   else "N/A"
        covered = []
        for req in r.get("requests", []):
            ev = req.get("event", {})
            if ev and ev.get("event_start"):
                covered.append(
                    datetime.fromtimestamp(ev["event_start"]).strftime("%d %b %Y") +
                    f" — {ev.get('event_title','')}"
                )
        absence_list.append({
            "reference":      r.get("reference_code", "N/A"),
            "reason":         r.get("reason", {}).get("title", "Unknown reason"),
            "status":         r.get("status", {}).get("title", "Unknown"),
            "from":           from_dt,
            "to":             to_dt,
            "events_covered": covered,
            "has_files":      len(r.get("files", [])) > 0,
            "messages":       len(r.get("messages", []))
        })

    return quotas, absence_list


def fetch_absence_policy(session):
    """Scrape absence policy page. Cached for 1 hour."""
    global _absence_policy_cache, _absence_policy_cached_at

    if _absence_policy_cache and _absence_policy_cached_at:
        if (datetime.now() - _absence_policy_cached_at).seconds < 3600:
            return _absence_policy_cache

    try:
        resp = session.get(f"{BASE_URL}/community/ihub:forms/absence_application")
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "button"]):
            tag.decompose()

        content = (
            soup.find("div", {"class": "content-wrap"}) or
            soup.find("div", {"id":    "content"}) or
            soup.find("main") or
            soup.find("div", {"class": "community-section"}) or
            soup.body
        )
        if not content:
            return None

        text  = content.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        seen, cleaned = set(), []
        for line in lines:
            if line not in seen:
                seen.add(line)
                cleaned.append(line)

        result = "\n".join(cleaned)[:10000]

        _absence_policy_cache     = result
        _absence_policy_cached_at = datetime.now()
        print(f"[POLICY] Cached {len(result)} chars")
        return result

    except Exception as ex:
        print(f"[POLICY] Fetch error: {ex}")
        return _absence_policy_cache


# ════════════════════════════════════════════════════════
# BUS SCHEDULE
# ════════════════════════════════════════════════════════

BUS_SCHEDULE = {
    "operating_days": "Monday to Friday (except Public Holidays)",
    "departure_times": ["8:15", "9:15", "11:15", "14:15", "16:15", "17:30"],
    "locations": {
        "ntu_yunnan": {
            "name": "NTU Yunnan Campus",
            "pickup_point": "Experimental Medicine Building",
            "additional_stops": [
                "NIE / Lee Wee Nam Library bus stop",
                "ADM bus stop",
                "Hall 11 bus stop"
            ]
        },
        "ntu_novena": {
            "name": "NTU Novena Campus",
            "pickup_point": "Toh Kian Chui Annex"
        }
    },
    "notes": [
        "Please arrive 5 minutes before the scheduled time",
        "No eating, drinking, or littering in the bus",
        "Non-hazardous research items can be transported (seek driver assistance)",
        "Staff should not claim travel expense reimbursement between campuses"
    ],
    "contact": "shuttlebus@ntu.edu.sg"
}


def get_upcoming_buses(direction=None):
    """Get upcoming buses for today based on current time."""
    now = datetime.now()
    today_name    = now.strftime("%A")
    today_weekday = now.weekday()

    if today_weekday >= 5:
        return []

    upcoming = []
    for time_str in BUS_SCHEDULE["departure_times"]:
        hour, minute = map(int, time_str.split(":"))
        departure_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if departure_time <= now:
            continue

        bus_info = {
            "time": time_str,
            "day":  today_name,
            "departure_datetime": departure_time.isoformat(),
            "minutes_until": int((departure_time - now).total_seconds() / 60)
        }

        if direction == "to_novena" or direction is None:
            upcoming.append({
                **bus_info,
                "from":      f"{BUS_SCHEDULE['locations']['ntu_yunnan']['name']} ({BUS_SCHEDULE['locations']['ntu_yunnan']['pickup_point']})",
                "to":        f"{BUS_SCHEDULE['locations']['ntu_novena']['name']} ({BUS_SCHEDULE['locations']['ntu_novena']['pickup_point']})",
                "direction": "to_novena"
            })

        if direction == "to_ntu" or direction is None:
            upcoming.append({
                **bus_info,
                "from":      f"{BUS_SCHEDULE['locations']['ntu_novena']['name']} ({BUS_SCHEDULE['locations']['ntu_novena']['pickup_point']})",
                "to":        f"{BUS_SCHEDULE['locations']['ntu_yunnan']['name']} ({BUS_SCHEDULE['locations']['ntu_yunnan']['pickup_point']})",
                "direction": "to_ntu"
            })

    upcoming.sort(key=lambda x: x["minutes_until"])
    return upcoming


def get_next_bus(direction=None):
    upcoming = get_upcoming_buses(direction)
    return upcoming[0] if upcoming else None


def get_all_buses_today():
    now           = datetime.now()
    today_name    = now.strftime("%A")
    today_weekday = now.weekday()

    if today_weekday >= 5:
        return []

    all_buses = []
    for time_str in BUS_SCHEDULE["departure_times"]:
        all_buses.append({
            "time": time_str, "day": today_name,
            "from": "NTU Yunnan (Experimental Medicine Building)",
            "to":   "NTU Novena (Toh Kian Chui Annex)",
            "direction": "to_novena"
        })
        all_buses.append({
            "time": time_str, "day": today_name,
            "from": "NTU Novena (Toh Kian Chui Annex)",
            "to":   "NTU Yunnan (Experimental Medicine Building)",
            "direction": "to_ntu"
        })

    all_buses.sort(key=lambda x: int(x["time"].split(":")[0]) * 60 + int(x["time"].split(":")[1]))
    return all_buses


def format_bus_schedule_for_prompt():
    today_name    = datetime.now().strftime("%A")
    today_weekday = datetime.now().weekday()
    now           = datetime.now()

    text  = "── INTER-CAMPUS SHUTTLE BUS SCHEDULE ──\n"
    text += "Service: Monday to Friday (except Public Holidays)\n\n"
    text += f"Departure times from BOTH campuses:\n  {', '.join(BUS_SCHEDULE['departure_times'])}\n\n"
    text += "Locations:\n"
    text += "  NTU Yunnan: Experimental Medicine Building\n"
    text += "    (Also stops at: NIE/Library, ADM, Hall 11)\n"
    text += "  NTU Novena: Toh Kian Chui Annex\n\n"

    if today_weekday >= 5:
        text += "⚠️ No bus service today (weekend/public holiday)\n"
    else:
        text += f"Current time: {now.strftime('%H:%M')}\n\nAll buses today ({today_name}):\n"
        for bus in get_all_buses_today():
            icon = "🟢" if bus["direction"] == "to_novena" else "🔵"
            bh, bm = map(int, bus["time"].split(":"))
            bus_dt = now.replace(hour=bh, minute=bm, second=0, microsecond=0)
            mins   = int((bus_dt - now).total_seconds() / 60)
            status = f"in {mins} min" if bus_dt > now else "passed"
            text  += f"  {icon} {bus['time']} ({status}) - {bus['from']} → {bus['to']}\n"

    text += "\nPlease arrive 5 minutes before departure\n"
    return text


# ════════════════════════════════════════════════════════
# ATTENDANCE CHECK
# ════════════════════════════════════════════════════════

def _text_says_attendance_marked(html_text):
    """
    Robustly detect whether a page says attendance was marked.
    Strips all HTML tags, collapses whitespace, case-insensitive regex.
    Returns True (marked), False (not marked), or None (can't determine).
    """
    if not html_text:
        return None

    plain = re.sub(r'<[^>]+>', ' ', html_text)
    plain = re.sub(r'\s+', ' ', plain).strip()

    match = re.search(
        r'attendance\s*taken\s*:?\s*(attendance\s*marked|yes|present|marked|no|not\s*marked)',
        plain, re.IGNORECASE
    )
    if not match:
        return None

    value = match.group(1).lower()
    return False if value in ("no", "not marked") else True


def check_if_attendance_marked(session, event_id, force_refresh=False, username=None):
    """Check if attendance is marked for a given event."""
    if not force_refresh and event_id in attendance_marked_cache:
        print(f"[CACHE HIT] Event {event_id} = {attendance_marked_cache[event_id]}")
        return attendance_marked_cache[event_id]

    print(f"[CACHE {'FORCED REFRESH' if force_refresh else 'MISS'}] Event {event_id} - checking API")

    if force_refresh:
        try:
            detail_resp = session.get(
                f"{BASE_URL}/api/events.api.php?id={event_id}", timeout=10
            )
            result = _text_says_attendance_marked(detail_resp.text)
            if result is True:
                attendance_marked_cache[event_id] = True
                print(f"[ATTENDANCE] Event {event_id} - event details API says MARKED")
                return True
            elif result is False:
                attendance_marked_cache.pop(event_id, None)
                print(f"[ATTENDANCE] Event {event_id} - event details API says NOT MARKED")
                return False
            print(f"[ATTENDANCE] Event {event_id} - event details API: couldn't determine, falling through")
        except Exception as detail_ex:
            print(f"[ATTENDANCE] Event details API failed: {detail_ex}, falling back")

    try:
        api_resp = session.get(f"{BASE_URL}/api/events-calendar.api.php", params={
            "dtype": "week", "dstamp": int(time.time()),
            "local_timezone": "Asia/Singapore", "viewtype": "list",
            "parentonly": "no", "pv": "1"
        })
        data = api_resp.json()

        for event in data.get("events", []):
            if str(event.get("event_id")) == str(event_id):
                marked = (
                    event.get("attendance_taken") in [1, "1", True, "true"]
                    or bool(event.get("attendance_taken_date"))
                    or event.get("attendance_status") == "present"
                )
                if marked:
                    attendance_marked_cache[event_id] = True
                    print(f"[ATTENDANCE] Event {event_id} - calendar API says MARKED")
                    return True
                attendance_marked_cache.pop(event_id, None)
                return False

        # Fallback: scrape event pages
        print(f"[ATTENDANCE] Event {event_id} - not in calendar, checking event pages...")
        for url in [
            f"{BASE_URL}/api/events.api.php?id={event_id}",
            f"{BASE_URL}/events/view/{event_id}",
            f"{BASE_URL}/events/detail/{event_id}",
            f"{BASE_URL}/learningevents?event_id={event_id}",
            f"{BASE_URL}/events/{event_id}",
            f"{BASE_URL}/event/{event_id}",
        ]:
            try:
                result = _text_says_attendance_marked(session.get(url, timeout=10).text)
                if result is True:
                    attendance_marked_cache[event_id] = True
                    print(f"[ATTENDANCE] ✅ Event {event_id} - marked (via {url})")
                    return True
            except Exception as url_ex:
                print(f"[ATTENDANCE] URL {url} failed: {url_ex}")

        attendance_marked_cache.pop(event_id, None)
        print(f"[ATTENDANCE] Event {event_id} - NOT MARKED")
        return False

    except Exception as e:
        print(f"[ATTENDANCE] check error: {e}")
        return False


def check_attendance_type(session, event_id):
    """Determine attendance type: 'location' or 'self'."""
    try:
        resp = session.get(f"{BASE_URL}/api/events-calendar.api.php", params={
            "dtype": "week", "dstamp": int(time.time()),
            "local_timezone": "Asia/Singapore", "viewtype": "list",
            "parentonly": "no", "pv": "1"
        })
        data = resp.json()
        for event in data.get("events", []):
            if str(event.get("event_id")) == str(event_id):
                if event.get("attendance_method") == "location":
                    return "location"
                elif event.get("attendance_required") in [1, "1", True, "true"]:
                    return "self"
                break
    except Exception:
        pass
    return "self"


def mark_self_attendance(session, event_id, jwt_token):
    """Mark self-attendance for an event."""
    try:
        headers  = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        resp = session.post(
            f"{BASE_URL}/api/v2/events/store-attendance-from-event",
            json={"event_id": str(event_id)}, headers=headers
        )
        print(f"[MARK] Status: {resp.status_code}")
        if resp.status_code == 201:
            attendance_marked_cache[event_id] = True
            return True
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("status") == "success" or data.get("success"):
                    attendance_marked_cache[event_id] = True
                    return True
            except Exception:
                pass
        print(f"[MARK] ❌ Failed. Status: {resp.status_code}")
        return False
    except Exception as e:
        print(f"[MARK] ❌ Error: {e}")
        return False


def mark_location_attendance(session, event_id, latitude=1.3483, longitude=103.6831):
    """Mark location-based attendance."""
    try:
        resp = session.post(
            f"{BASE_URL}/api/events-location-attendance.api.php",
            data={"event_id": str(event_id), "user_lat": str(latitude), "user_lng": str(longitude)}
        )
        try:
            if resp.json().get("success"):
                attendance_marked_cache[event_id] = True
                return True
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"[MARK LOCATION] ❌ Error: {e}")
        return False


def mark_attendance(session, event_id, jwt_token=None):
    """Smart attendance marking — detects type then marks."""
    attendance_type = check_attendance_type(session, event_id)
    if not attendance_type:
        return False
    if attendance_type == "self":
        return mark_self_attendance(session, event_id, jwt_token) if jwt_token else False
    elif attendance_type == "location":
        return mark_location_attendance(session, event_id)
    return False


# ════════════════════════════════════════════════════════
# ATTENDANCE QUERY HELPERS  (used by scheduler + chat)
# ════════════════════════════════════════════════════════

def get_upcoming_attendance_events(session, minutes_ahead=15):
    """Events starting in ~X minutes that require attendance (not yet marked)."""
    formatted    = format_events(fetch_events(session, weeks=1))
    now          = datetime.now()
    target_start = now + timedelta(minutes=minutes_ahead)
    target_end   = target_start + timedelta(minutes=5)

    result = []
    for event in formatted:
        if event["attendance"] != "Required":
            continue
        try:
            event_time = event_start_datetime(event)
            if target_start <= event_time <= target_end:
                if not check_if_attendance_marked(session, event["id"]):
                    result.append(event)
        except Exception:
            continue
    return result


def get_events_ending_soon(session, minutes_before_end=15):
    """Events ending in ~X minutes where attendance not yet marked."""
    formatted    = format_events(fetch_events(session, weeks=1))
    now          = datetime.now()
    target_end   = now + timedelta(minutes=minutes_before_end)
    window_start = target_end - timedelta(minutes=2)
    window_end   = target_end + timedelta(minutes=2)

    result = []
    for event in formatted:
        if event["attendance"] != "Required":
            continue
        try:
            event_start = event_start_datetime(event)
            event_end   = event_start + timedelta(hours=event["duration_hours"])
            if window_start <= event_end <= window_end:
                if not check_if_attendance_marked(session, event["id"], username=None):
                    result.append({
                        **event,
                        "minutes_until_end": int((event_end - now).total_seconds() / 60),
                        "event_end_time":    event_end.strftime("%H:%M"),
                        "reminder_type":     "end_of_class"
                    })
        except Exception:
            continue
    return result


def get_recent_unmarked_attendance(session, hours_ago=4):
    """Events that started recently where attendance hasn't been marked."""
    formatted = format_events(fetch_events(session, weeks=1))
    now       = datetime.now()
    cutoff    = now - timedelta(hours=hours_ago)

    result = []
    for event in formatted:
        if event["attendance"] != "Required":
            continue
        try:
            event_time = event_start_datetime(event)
            if cutoff <= event_time <= now:
                if check_if_attendance_marked(session, event["id"]) is False:
                    minutes_ago = int((now - event_time).total_seconds() / 60)
                    result.append({
                        **event,
                        "minutes_since_start": minutes_ago,
                        "urgent": minutes_ago > 60
                    })
        except Exception:
            continue

    result.sort(key=lambda x: x["minutes_since_start"], reverse=True)
    return result


def get_events_requiring_attendance(session, hours_ahead=1):
    """Upcoming events requiring attendance within the next X hours."""
    formatted = format_events(fetch_events(session, weeks=1))
    now       = datetime.now()
    cutoff    = now + timedelta(hours=hours_ahead)

    result = []
    for event in formatted:
        if event["attendance"] != "Required":
            continue
        try:
            if now <= event_start_datetime(event) <= cutoff:
                result.append(event)
        except Exception:
            continue
    return result


def get_past_events_without_attendance(session, hours_ago=2):
    """Events that ended recently where attendance might still need marking."""
    formatted = format_events(fetch_events(session, weeks=1))
    now       = datetime.now()
    cutoff    = now - timedelta(hours=hours_ago)

    result = []
    for event in formatted:
        if event["attendance"] != "Required":
            continue
        try:
            event_start = event_start_datetime(event)
            event_end   = event_start + timedelta(hours=event["duration_hours"])
            if cutoff <= event_end <= now:
                if check_if_attendance_marked(session, event["id"]) is False:
                    result.append({**event, "attendance_marked": False})
        except Exception:
            continue
    return result
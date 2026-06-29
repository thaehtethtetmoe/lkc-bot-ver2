"""
elentra_client.py
Shared Elentra HTTP helpers used by BOTH app.py and the WebJob.
No Flask imports — safe to import anywhere.

In app.py, REPLACE:
    def elentra_login(...): ...
    def fetch_events(...): ...
    def format_events(...): ...
    def fetch_absences(...): ...

With:
    from elentra_client import elentra_login, fetch_events, format_events, fetch_absences
"""

import re
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup

BASE_URL = "https://ntu.elentra.cloud"


# ── Login ─────────────────────────────────────────────────

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


# ── Events ────────────────────────────────────────────────

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


def _event_start_datetime(event):
    try:
        event_time = event["time"].split()[0]
        return datetime.strptime(f"{event['date']} {event_time}", "%A, %d %b %Y %H:%M")
    except Exception:
        return datetime.max


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
    result.sort(key=_event_start_datetime)
    return result


def filter_events_between(events, start_dt, end_dt):
    return [e for e in events if start_dt <= _event_start_datetime(e) < end_dt]


# ── Absences ──────────────────────────────────────────────

def fetch_absences(session, jwt_token=None):
    try:
        if not jwt_token:
            return None, None
        headers   = {"Authorization": f"Bearer {jwt_token}"}
        req_resp  = session.get(f"{BASE_URL}/api/v2/absences/details/my-requests", headers=headers)
        tot_resp  = session.get(f"{BASE_URL}/api/v2/absences/users/totals",        headers=headers)
        raw_req   = req_resp.json()
        raw_tot   = tot_resp.json()
        if (isinstance(raw_req, list) and raw_req and raw_req[0] == "not_authorized") or \
           (isinstance(raw_tot, list) and raw_tot and raw_tot[0] == "not_authorized"):
            return None, None
        requests_data = raw_req if isinstance(raw_req, list) else raw_req.get("details", [])
        totals_data   = raw_tot if isinstance(raw_tot, list) else raw_tot.get("totals",  [])
        return requests_data, totals_data
    except Exception as ex:
        print(f"[ABSENCES] fetch error: {ex}")
        return None, None
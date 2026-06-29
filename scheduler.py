"""
scheduler.py
Runs as a background thread inside Flask.
Every day at 9pm SGT it loops through all registered students,
logs into Elentra, fetches tomorrow's events, and emails them.
"""

import os
import time
import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
_mc_reminder_lock = threading.Lock()
_ending_reminder_lock = threading.Lock()
_attendance_reminder_lock = threading.Lock()
_loa_reminder_lock = threading.Lock()

# ── Dedup caches ─────────────────────────────────────
_sent_reminders = {}          # 1-hour before reminders
_sent_ending_reminders = {}   # Ending-soon reminders
_sent_mc_reminders = {}       # End-of-day MC reminders
_sent_bus_reminders = {}
_sent_attendance = {}         # ← ADD THIS: Attendance alerts

BASE_URL = "https://ntu.elentra.cloud"

# These are imported from app.py when scheduler is started
# We use late imports to avoid circular dependency
_elentra_login_fn  = None
_fetch_events_fn   = None
_format_events_fn  = None
_scheduler_initialized = False   # True once init_scheduler() has run

SGT = pytz.timezone("Asia/Singapore")

# # ── ADD THIS ENTIRE BLOCK ──
# def _get_elentra_session(username, info):
#     """Try stored session first (SSO users), fall back to password login."""
#     import requests as req
#     if info.get("session"):
#         try:
#             test = info["session"].get(
#                 "https://ntu.elentra.cloud/api/events-calendar.api.php",
#                 params={"dtype": "week", "dstamp": int(time.time()),
#                         "local_timezone": "Asia/Singapore", "viewtype": "list",
#                         "parentonly": "no", "pv": "1"},
#                 timeout=5
#             )
#             if test.status_code == 200 and "events" in test.json():
#                 return info["session"], info.get("jwt_token")
#         except:
#             pass
#     if info.get("password"):
#         try:
#             return _elentra_login_fn(username, info["password"])
#         except:
#             pass
#     return None, None

# ── Shared Elentra session cache ──────────────────────
# Every scheduler job (MC reminder, attendance, ending-class, bus, LOA,
# 1-hour-before, etc.) used to call _get_elentra_session() independently,
# each one doing a brand-new blocking login (3 sequential HTTP calls,
# up to ~30s worst case). With several jobs running every few minutes for
# the same student, that's many redundant logins stacking up on the same
# 4 gunicorn threads that also have to serve real user requests — which is
# what causes the multi-minute "frozen" web app.
#
# Fix: cache one session per student for a short TTL and reuse it across
# jobs/cycles instead of logging in fresh every single call.
_session_cache = {}          # { username: {"session", "jwt", "expires_at"} }
_session_cache_lock = threading.Lock()
SESSION_CACHE_TTL_SECONDS = 4 * 60   # reuse a session for up to 4 minutes


def _get_elentra_session(username, info, force_new=False):
    """
    Return a (session, jwt_token) pair for this student, reusing a cached
    session if one was created recently. Falls back to a fresh password
    login if there's no valid cached session, or if force_new=True.

    NOTE: `username` here may be a normalized (lowercased) storage key —
    database.py normalizes usernames so that login-casing differences don't
    create duplicate student records (the fix for LOA rejection emails being
    re-sent every login). That normalization must NOT leak into the actual
    Elentra login call, since Elentra's own login may be case-sensitive.
    `info["username"]` always holds the original, as-typed casing, so we use
    that for the real login while still caching/logging under the lookup key.
    """
    now = time.time()
    login_username = info.get("username", username)

    if not force_new:
        with _session_cache_lock:
            cached = _session_cache.get(username)
        if cached and cached["expires_at"] > now:
            print(f"[SESSION] {username}: ♻️ reusing cached session")
            return cached["session"], cached["jwt"]

    if not info.get("password"):
        print(f"[SESSION] {username}: ❌ no password in reminder_store")
        return None, None

    try:
        session, jwt = _elentra_login_fn(login_username, info["password"])
        print(f"[SESSION] {username}: ✅ logged in via password")
        with _session_cache_lock:
            _session_cache[username] = {
                "session": session,
                "jwt": jwt,
                "expires_at": now + SESSION_CACHE_TTL_SECONDS,
            }
        return session, jwt
    except Exception as ex:
        print(f"[SESSION] {username}: ❌ password login failed: {ex}")
        with _session_cache_lock:
            _session_cache.pop(username, None)
        return None, None


def init_scheduler(elentra_login, fetch_events, format_events):
    """
    Call this once from app.py to wire up the scheduler with the Elentra
    helpers. No reminder_store is passed in anymore — every job reads
    student data directly from the database (database.py) each time it
    runs, so there's no separate in-memory copy to keep in sync.
    """
    global _elentra_login_fn, _fetch_events_fn, _format_events_fn, _scheduler_initialized

    _elentra_login_fn  = elentra_login
    _fetch_events_fn   = fetch_events
    _format_events_fn  = format_events
    _scheduler_initialized = True

    hour   = int(os.getenv("REMINDER_HOUR",   19)) #changed to 7pm
    minute = int(os.getenv("REMINDER_MINUTE",  0))

    scheduler = BackgroundScheduler(timezone=SGT)
    
    # ── Job 1: Daily 7pm tomorrow's events ──
    scheduler.add_job(
        func    = send_all_reminders,
        trigger = CronTrigger(hour=hour, minute=minute, timezone=SGT),
        id      = "daily_reminder",
        name    = "Daily 7pm event reminder",
        replace_existing = True
    )
    
    # ── Job 2: Every 5 min — attendance starting soon ──
    scheduler.add_job(
        func    = send_attendance_reminders,
        trigger = CronTrigger(minute="*/5", timezone=SGT),
        id      = "attendance_reminder",
        name    = "Every 5 min attendance check",
        replace_existing = True
    )
    
    # ── Job 3: Every 5 min — post-event MC reminder (fires once after LAST event of day) ──
    scheduler.add_job(
        func    = send_missing_attendance_mc_reminder,
        trigger = CronTrigger(minute="*/5", timezone=SGT),
        id      = "mc_reminder",
        name    = "Post-event MC reminder (end of day)",
        replace_existing = True
    )
    
    # ── Job 4: Every 5 min — 1 hour before event reminder ──
    # (was every 15 min with a 35-min-wide window, so it could fire anywhere
    #  from 45-80 min before class. Now checks more often with a tighter window
    #  so it consistently lands close to the 60-min mark.)
    scheduler.add_job(
        func               = check_and_send_event_reminders,
        trigger            = "interval",
        minutes            = 5,
        id                 = "event_reminder",
        name               = "Every 5min event start reminder",
        replace_existing   = True,
        misfire_grace_time = 300
    )
    
    # ── Job 5: Every 3 min — class ending soon reminder ──
    # (was every 5 min with a ±5min window, so it could fire 10-20 min before
    #  end instead of the intended 15. Now checks every 3 min with a ±3min
    #  window for tighter, more consistent timing.)
    scheduler.add_job(
        func               = check_ending_classes_reminders,
        trigger            = "interval",
        minutes            = 3,
        id                 = "ending_class_reminder",
        name               = "Every 3 min class ending check",
        replace_existing   = True,
        misfire_grace_time = 120
    )

    # ── Job 5b: Every 30 min — LOA/absence rejection check ──
    # Previously LOA rejections were only checked once, at login time (/link).
    # A student who didn't log back in would never get notified of a rejection
    # that happened after their last login. This makes it a recurring check
    # like every other reminder type.
    scheduler.add_job(
        func               = check_loa_rejections,
        trigger            = CronTrigger(minute="*/30", timezone=SGT),
        id                 = "loa_rejection_check",
        name               = "Every 30 min LOA rejection check",
        replace_existing   = True
    )

    # ── Job 6: Every 1 min — bus reminders ──
    scheduler.add_job(
        func=check_bus_reminders,
        trigger=CronTrigger(minute="*", timezone=SGT),
        id="bus_reminder",
        name="Every minute bus reminder check",
        replace_existing=True
    )

    # ── Clean up bus dedup cache daily at midnight ──
    scheduler.add_job(
        func=lambda: _sent_bus_reminders.clear(),
        trigger=CronTrigger(hour=0, minute=1, timezone=SGT),
        id="clear_bus_cache",
        name="Clear bus reminder dedup cache",
        replace_existing=True
    )

    # Add this job for Weekly Monday 8am summary
    scheduler.add_job(
        func    = send_all_weekly_summaries,
        # trigger = CronTrigger(day_of_week='mon', hour=8, minute=0, timezone=SGT),
        trigger = CronTrigger(day_of_week='thu', hour=15, minute=28, timezone=SGT),
        id      = "weekly_summary",
        name    = "Weekly Monday 8am summary",
        replace_existing = True
    )

    scheduler.start()
    # Print all jobs to verify they're registered
    for job in scheduler.get_jobs():
        print(f"[SCHEDULER] Job: {job.name} (next run: {job.next_run_time})")
    print(f"[SCHEDULER] Started — daily {hour:02d}:{minute:02d} SGT + attendance/ending checks")
    return scheduler



def send_all_reminders():
    from mailer import send_reminder_email

    from database import get_all_reminder_students
    students = get_all_reminder_students()

    if not students:
        print("[SCHEDULER] No students registered for reminders.")
        return

    print(f"[SCHEDULER] Running reminder job — {len(students)} student(s) registered")

    for username, info in list(students.items()):
        prefs = info.get("preferences", {})
        if not prefs.get("daily_tonight", True):
            continue

        try:
            print(f"[SCHEDULER] Processing {username}...")
            session, jwt_token = _get_elentra_session(username, info)
            if not session:
                print(f"[SCHEDULER] No session/password for {username}, skipping")
                continue
            events = get_tomorrow_events(username, info)
            send_reminder_email(
                to_email = info["email"],
                username = username,
                events   = events
            )
        except Exception as ex:
            print(f"[SCHEDULER] Failed for {username}: {ex}")

    print("[SCHEDULER] Reminder job complete.")

def send_attendance_reminders():
    # Acquire lock at the VERY beginning
    if not _attendance_reminder_lock.acquire(blocking=False):
        print("[ATTENDANCE] Another attendance job already running, skipping")
        return
    
    try:
        from mailer import send_attendance_alert_email
        
        from database import get_all_reminder_students
        students = get_all_reminder_students()

        if not students:
            print("[ATTENDANCE] No reminder store")
            return

        for username, info in list(students.items()):
            prefs = info.get("preferences", {})
            if not prefs.get("attendance_alert", True):
                print(f"[ATTENDANCE] {username}: skipped — pref off")
                continue

            try:
                print(f"[ATTENDANCE] {username}: getting session...")
                session, jwt_token = _get_elentra_session(username, info)
                if not session:
                    print(f"[ATTENDANCE] {username}: ❌ no session — password={bool(info.get('password'))}")
                    continue
                print(f"[ATTENDANCE] {username}: ✅ session ok, fetching events...")
                all_events = _fetch_events_fn(session, weeks=1)
                formatted = _format_events_fn(all_events)
                selected_modules = prefs.get("selected_modules", [])
                if selected_modules:
                    formatted = _filter_by_modules(formatted, selected_modules)
                print(f"[ATTENDANCE] {username}: got {len(formatted)} events")
                
                now = datetime.now(SGT)
                target_start = now - timedelta(minutes=2)
                target_end = now + timedelta(minutes=3)
                
                upcoming = []
                for event in formatted:
                    # Attendance alerts only for Required events
                    if event["attendance"] != "Required":
                        continue
                    
                    try:
                        event_time_str = event["time"].split()[0]
                        event_date_str = event["date"]
                        event_dt = datetime.strptime(
                            f"{event_date_str} {event_time_str}",
                            "%A, %d %b %Y %H:%M"
                        )
                        event_dt = SGT.localize(event_dt) if event_dt.tzinfo is None else event_dt
                        if target_start <= event_dt <= target_end:
                            # CHECK IF ALREADY MARKED BEFORE ADDING
                            # from app import check_if_attendance_marked
                            from elentra_client import check_if_attendance_marked
                            already_marked = check_if_attendance_marked(session, event["id"], username=username)
                            if already_marked:
                                print(f"[ATTENDANCE] {username}: ⏭️ SKIP (already marked) {event['title']}")
                            else:
                                upcoming.append(event)
                                print(f"[ATTENDANCE] {username}: 🎯 event in window: {event['title']} at {event_time_str}")
                    except Exception as parse_ex:
                        print(f"[ATTENDANCE] {username}: parse error: {parse_ex}")
                        continue
                
                print(f"[ATTENDANCE] {username}: {len(upcoming)} event(s) in window")
                if upcoming:
                    # Change to HOUR precision to prevent duplicates within same hour
                    now_key = now.strftime("%Y-%m-%d_%H")  # ← HOUR, not minute
                    # Build new list instead of modifying while iterating
                    deduped = []
                    for event in upcoming:
                        cache_key = f"attendance_{username}_{event['id']}_{now_key}"
                        if cache_key in _sent_attendance:
                            print(f"[ATTENDANCE] {username}: ⏭️ SKIP duplicate for event {event['id']}")
                        else:
                            deduped.append(event)
                            _sent_attendance[cache_key] = True
                    
                    if deduped:
                        send_attendance_alert_email(
                            to_email=info["email"],
                            username=username,
                            events=deduped
                        )
                        print(f"[ATTENDANCE] {username}: ✅ alert sent for {len(deduped)} event(s)")
                    
            except Exception as ex:
                import traceback
                print(f"[ATTENDANCE] {username}: ❌ EXCEPTION: {ex}")
                traceback.print_exc()
    
    finally:
        # Release lock ONLY after ALL students are processed
        _attendance_reminder_lock.release()

def send_missing_attendance_mc_reminder(force=False):
    """
    Runs every 5 minutes. 
    Fires ONLY ONCE after ALL of today's events have ended.
    Checks for any unmarked attendance across ALL today's events.
    Sends one consolidated MC reminder if any were missed.
    
    Args:
        force: If True, bypasses time window check and dedup cache (for testing)
    """
    
    # Prevent concurrent execution
    if not _mc_reminder_lock.acquire(blocking=False):
        print("[MC DEBUG] Another MC reminder job is already running, skipping")
        return
    
    try:
        from mailer import send_mc_reminder_email
        # from app import check_if_attendance_marked
        from elentra_client import check_if_attendance_marked
        
        print(f"\n{'='*60}")
        print(f"[MC DEBUG] send_missing_attendance_mc_reminder() called | force={force}")
        print(f"[MC DEBUG] Current time: {datetime.now(SGT)}")
        
        if not _scheduler_initialized:
            print("[MC DEBUG] ❌ Scheduler not initialized — returning")
            return
        
        from database import get_all_reminder_students
        students = get_all_reminder_students()

        print(f"[MC DEBUG] Students registered: {list(students.keys())}")
        
        for username, info in list(students.items()):
            print(f"\n[MC DEBUG] ── Processing {username} ──")
            
            prefs = info.get("preferences", {})
            print(f"[MC DEBUG] {username}: preferences = {prefs}")
            
            if not prefs.get("missing_attendance", True):
                print(f"[MC DEBUG] {username}: ❌ missing_attendance pref is False, skipping")
                continue

            try:
                session, jwt_token = _get_elentra_session(username, info)
                if not session:
                    print(f"[MC DEBUG] {username}: ❌ No session or password, skipping")
                    continue
                print(f"[MC DEBUG] {username}: Using Elentra session...")
                
                print(f"[MC DEBUG] {username}: Fetching events...")
                all_events = _fetch_events_fn(session, weeks=1)
                formatted = _format_events_fn(all_events)
                selected_modules = prefs.get("selected_modules", [])
                if selected_modules:
                    formatted = _filter_by_modules(formatted, selected_modules)
                print(f"[MC DEBUG] {username}: Got {len(all_events)} raw events, {len(formatted)} formatted")
                
                now = datetime.now(SGT)
                # Make now timezone-naive for comparison
                now_naive = now.replace(tzinfo=None)
                today_str = now.strftime("%A, %d %b %Y")
                print(f"[MC DEBUG] {username}: Today's date string: '{today_str}'")
                
                # Get only today's events that require attendance
                today_events = [e for e in formatted 
                              if e["date"] == today_str and e["attendance"] == "Required"]
                
                print(f"[MC DEBUG] {username}: Today's events requiring attendance: {len(today_events)}")
                
                if not today_events:
                    print(f"[MC DEBUG] {username}: ❌ No attendance-required events today, skipping")
                    continue
                
                # Print each today event for debugging
                for i, event in enumerate(today_events):
                    print(f"[MC DEBUG] {username}:   Event {i+1}: {event['title'][:50]}... | {event['time']} | ID: {event['id']}")
                
                # Find the LATEST end time of today's events
                latest_end = None
                for event in today_events:
                    try:
                        # Parse end time correctly
                        time_parts = event["time"].split("–")
                        end_time_str = time_parts[-1].strip()
                        event_date_str = event["date"]
                        print(f"[MC DEBUG] {username}:   Parsing end time: date='{event_date_str}', time='{end_time_str}'")
                        
                        event_end_dt = datetime.strptime(
                            f"{event_date_str} {end_time_str}", 
                            "%A, %d %b %Y %H:%M"
                        )
                        # Make it timezone-naive for comparison
                        event_end_naive = event_end_dt.replace(tzinfo=None)
                        print(f"[MC DEBUG] {username}:   Event ends at (naive): {event_end_naive}")
                        
                        if latest_end is None or event_end_naive > latest_end:
                            latest_end = event_end_naive
                    except Exception as parse_ex:
                        print(f"[MC DEBUG] {username}:   ⚠️ Parse error: {parse_ex}")
                        continue
                
                if latest_end is None:
                    print(f"[MC DEBUG] {username}: ❌ Could not determine latest end time")
                    continue
                
                print(f"[MC DEBUG] {username}: Latest event ends at (naive): {latest_end}")
                
                # Calculate time difference using naive datetimes
                time_since_last_end = now_naive - latest_end
                print(f"[MC DEBUG] {username}: Time since last end: {time_since_last_end}")
                
                # Check if we're in the window (5-30 minutes after last event ends)
                in_window = timedelta(minutes=5) <= time_since_last_end <= timedelta(minutes=60)
                print(f"[MC DEBUG] {username}: In 5-30min window? {in_window} | Force? {force}")
                
                if not force and not in_window:
                    print(f"[MC DEBUG] {username}: ❌ Not in time window (and not forced), skipping")
                    continue
                
                # Dedup check — only send once per day per student
                cache_key = f"{username}:{today_str}:mc_daily"
                print(f"[MC DEBUG] {username}: Cache key: '{cache_key}'")
                
                if not force and cache_key in _sent_mc_reminders:
                    print(f"[MC DEBUG] {username}: ❌ Already sent MC reminder today, skipping")
                    continue
                
                # Check ALL today's events for unmarked attendance
                print(f"[MC DEBUG] {username}: Checking attendance for each event...")
                missed_events = []
                for event in today_events:
                    if event.get("attendance") != "Required":
                        print(f"[MC DEBUG] {username}:   Skipping optional event: {event['title'][:40]}")
                        continue
                    print(f"[MC DEBUG] {username}:   Checking event {event['id']}: {event['title'][:40]}...")
                    
                    # Force refresh to bypass cache
                    marked = check_if_attendance_marked(session, event["id"], force_refresh=True, username=username)
                    print(f"[MC DEBUG] {username}:   → Marked? {marked}")
                    print(f"[MC DEBUG] {username}:   → First check returned: {marked}")

                    # Double-check by fetching event details directly if needed
                    # if marked is False:
                    #     # Try to fetch fresh data for this specific event
                    #     try:
                    #         api_url = f"{BASE_URL}/api/events-calendar.api.php"
                    #         params = {
                    #             "dtype": "week", "dstamp": int(time.time()),
                    #             "local_timezone": "Asia/Singapore", "viewtype": "list",
                    #             "parentonly": "no", "pv": "1"
                    #         }
                    #         fresh_resp = session.get(api_url, params=params, timeout=10)
                    #         fresh_data = fresh_resp.json()
                    #         for fresh_event in fresh_data.get("events", []):
                    #             if str(fresh_event.get("event_id")) == str(event["id"]):
                    #                 # Check if attendance is already marked
                    #                 if fresh_event.get("attendance_taken") in [1, "1", True, "true"]:
                    #                     marked = True
                    #                 elif fresh_event.get("attendance_status") == "present":
                    #                     marked = True
                    #                 elif fresh_event.get("attendance_taken_date"):
                    #                     marked = True
                    #                 else:
                    #                     marked = False
                    #                 break
                    #     except Exception as double_check_ex:
                    #         print(f"[MC DEBUG] {username}:   Double-check failed: {double_check_ex}")
                    
                    print(f"[MC DEBUG] {username}:   → Final verdict: {'✅ MARKED' if marked else '❌ NOT MARKED'}")
                    
                    if marked is False:
                        print(f"[MC DEBUG] {username}:   → Adding to missed list")
                        missed_events.append(event)
                    elif marked is True:
                        print(f"[MC DEBUG] {username}:   → Already marked, skipping")
                
                print(f"[MC DEBUG] {username}: Total missed events: {len(missed_events)}")
                
                if missed_events:
                    print(f"[MC DEBUG] {username}: SENDING MC REMINDER EMAIL to {info['email']}...")
                    for me in missed_events:
                        print(f"[MC DEBUG] {username}:   - {me['title']} | {me['time']}")
                    
                    _sent_mc_reminders[cache_key] = True
                    
                    send_mc_reminder_email(
                        to_email=info["email"],
                        username=username,
                        events=missed_events
                    )
                    print(f"[MC DEBUG] {username}: ✅ MC reminder sent successfully!")
                else:
                    print(f"[MC DEBUG] {username}: ✅ All attendance marked, no email needed")
                    
            except Exception as ex:
                print(f"[MC DEBUG] {username}: ❌ EXCEPTION: {ex}")
                import traceback
                traceback.print_exc()

        
        print(f"{'='*60}\n")
    
    finally:
        _mc_reminder_lock.release()

def send_all_weekly_summaries():
    from mailer import send_weekly_summary_email
    from database import get_all_reminder_students
    students = get_all_reminder_students()

    if not students:
        print("[SCHEDULER] Weekly: no students registered.")
        return
 
    print(f"[SCHEDULER] Weekly summary — {len(students)} student(s)")

    for username, info in list(students.items()):
        # Guard: must have email
        if not info.get("email"):
            print(f"[SCHEDULER] Weekly: {username} has no email, skipping")
            continue

        prefs = info.get("preferences", {})
        if not prefs.get("weekly_monday", True):
            continue

        try:
            events = get_this_week_events(username, info)  # Pass full info dict
            # Guard: don't send blank email if login failed or no events
            if events is None:
                print(f"[SCHEDULER] Weekly: {username} — no events returned (login failed?), skipping")
                continue

            send_weekly_summary_email(
                to_email = info["email"],
                username = username,
                events   = events
            )
        except Exception as ex:
            print(f"[SCHEDULER] Weekly failed for {username}: {ex}")
 
    print("[SCHEDULER] Weekly summary job complete.")


def test_reminder_now(username, reminder_store, elentra_login, fetch_events, format_events):
    from mailer import send_reminder_email

    if username not in reminder_store:
        raise Exception("Student not registered for reminders")

    info = reminder_store[username]
    events = get_tomorrow_events(username, info)  # Use the updated function
    send_reminder_email(
        to_email = info["email"],
        username = username,
        events   = events
    )


def get_tomorrow_events_direct(username, password, elentra_login, fetch_events, format_events):
    """Standalone version used by test route (no globals needed)."""
    session, jwt_token = elentra_login(username, password)
    raw          = fetch_events(session, weeks=1)
    all_fmt      = format_events(raw)
    tomorrow_str = (datetime.now(SGT) + timedelta(days=1)).strftime("%A, %d %b %Y")
    return [e for e in all_fmt if e["date"] == tomorrow_str]


def get_this_week_events_direct(username, password, elentra_login, fetch_events, format_events):
    """Used by /weekly/test — no globals needed."""
    session, jwt_token = elentra_login(username, password)
    raw      = fetch_events(session, weeks=2)
    all_fmt  = format_events(raw)
 
    today  = datetime.now(SGT).date()
    sunday = today + timedelta(days=(6 - today.weekday()))
 
    week_events = []
    for e in all_fmt:
        try:
            event_date = datetime.strptime(e["date"], "%A, %d %b %Y").date()
            if today <= event_date <= sunday:
                week_events.append(e)
        except Exception:
            continue
 
    return week_events

def check_and_send_event_reminders():
    """
    Runs every 15 minutes.
    Sends a reminder email if an event starts in 45-75 minutes.
    """
    from mailer import send_event_reminder_email
    from database import get_all_reminder_students
    students = get_all_reminder_students()

    if not students:
        return

    now = datetime.now(SGT).replace(tzinfo=None)

    for username, info in list(students.items()):

        prefs = info.get("preferences", {})
        if not prefs.get("one_hour_before", True):
            continue

        session, _ = _get_elentra_session(username, info)
        if not session:
            continue
        try:
            raw = _fetch_events_fn(session, weeks=1)
            events = _format_events_fn(raw)
            selected_modules = prefs.get("selected_modules", [])
            if selected_modules:
                events = _filter_by_modules(events, selected_modules)

            for event in events:
                event_id = event["id"]
                cache_key = f"{username}:{event_id}"

                try:
                    event_time_str = event["time"].split("–")[0].strip()
                    event_date_str = event["date"]
                    start_dt = datetime.strptime(
                        f"{event_date_str} {event_time_str}",
                        "%A, %d %b %Y %H:%M"
                    )
                except Exception:
                    continue

                diff_minutes = (start_dt - now).total_seconds() / 60
                
                # Send reminder if in window AND not already sent
                # Window tightened from 45-80 (35 min wide) to 55-65 (10 min wide)
                # so the email consistently lands close to the 60-min mark.
                if 55 <= diff_minutes <= 65:
                    if cache_key in _sent_reminders:
                        continue  # Already sent, skip duplicate
                    
                    send_event_reminder_email(
                        to_email=info["email"],
                        username=username,
                        event=event
                    )
                    _sent_reminders[cache_key] = True
                    print(f"[SCHEDULER] 1h reminder sent to {username} for: {event['title']}")
                
                # Clear cache after event has passed (more than 2 hours after start)
                elif diff_minutes < -120:
                    _sent_reminders.pop(cache_key, None)

        except Exception as ex:
            print(f"[SCHEDULER] Event reminder failed for {username}: {ex}")
            
# send attendance reminders 15 minutes before event ends
def check_ending_classes_reminders():
    """
    Runs every 5 minutes. Checks for classes ending in ~15 minutes
    that still need attendance marked and sends email reminders.
    Only sends ONE reminder per event (dedup cache).
    """
    if not _ending_reminder_lock.acquire(blocking=False):
        print("[ENDING] Another ending reminder job already running, skipping")
        return
    
    try:
        from mailer import send_ending_class_reminder
        from database import get_all_reminder_students
        students = get_all_reminder_students()
        
        if not students:
            print("[ENDING] No reminder store")
            return
        
        for username, info in list(students.items()):
            prefs = info.get("preferences", {})
            if not prefs.get("ending_reminder", True):
                continue
            
            try:
                print(f"[ENDING] Checking {username}...")
                session, jwt_token = _get_elentra_session(username, info)
                if not session:
                    print(f"[ENDING] No session or password for {username}")
                    continue
                    
                all_events = _fetch_events_fn(session, weeks=1)
                formatted = _format_events_fn(all_events)
                selected_modules = prefs.get("selected_modules", [])
                if selected_modules:
                    formatted = _filter_by_modules(formatted, selected_modules)
                
                now = datetime.now(SGT)
                
                target_end = now + timedelta(minutes=15)
                window_start = target_end - timedelta(minutes=3)
                window_end = target_end + timedelta(minutes=3)
                
                print(f"[ENDING] Now: {now.strftime('%H:%M')} | Looking for classes ending: {target_end.strftime('%H:%M')} (window: {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')})")
                
                ending_soon = []
                for event in formatted:
                    if event["attendance"] != "Required":
                        continue
                    
                    cache_key = f"{username}:{event['id']}:ending"
                    
                    try:
                        time_parts = event["time"].split("–")
                        start_str = time_parts[0].strip()
                        end_str = time_parts[1].strip()
                        event_date_str = event["date"]
                        
                        end_dt = datetime.strptime(f"{event_date_str} {end_str}", "%A, %d %b %Y %H:%M")
                        end_dt = SGT.localize(end_dt) if end_dt.tzinfo is None else end_dt
                        
                        window_start_naive = window_start.replace(tzinfo=None)
                        window_end_naive = window_end.replace(tzinfo=None)
                        event_end_naive = end_dt.replace(tzinfo=None)
                        
                        if window_start_naive <= event_end_naive <= window_end_naive:
                            # from app import check_if_attendance_marked
                            from elentra_client import check_if_attendance_marked
                            
                            # Always check attendance fresh first — before consulting dedup cache
                            already_marked = check_if_attendance_marked(session, event["id"], force_refresh=True, username=username)
                            
                            print(f"[ENDING]   Event: {event['title'][:40]}... | Ends: {end_dt.strftime('%H:%M')} | Marked? {already_marked}")
                            
                            if already_marked:
                                # Mark in dedup cache so we stop processing this event entirely
                                _sent_ending_reminders[cache_key] = True
                                print(f"[ENDING]   → SKIPPING (already marked)")
                            elif cache_key in _sent_ending_reminders:
                                # Reminder already sent in a previous tick and still not marked — don't spam
                                print(f"[ENDING]   → SKIPPING (reminder already sent, still waiting on student)")
                            else:
                                # Not marked, reminder not yet sent — send it now
                                _sent_ending_reminders[cache_key] = True
                                minutes_until_end = int((end_dt - now).total_seconds() / 60)
                                ending_soon.append({
                                    **event,
                                    "minutes_until_end": minutes_until_end,
                                    "event_end_time": end_dt.strftime("%H:%M")
                                })
                                print(f"[ENDING]   → Adding to reminder list (not marked)")
                    except Exception as e:
                        print(f"[ENDING] Parse error: {e}")
                        continue
                
                print(f"[ENDING] → {len(ending_soon)} event(s) ending soon for {username}")
                
                if ending_soon:
                    send_ending_class_reminder(
                        to_email=info["email"],
                        username=username,
                        events=ending_soon
                    )
                    print(f"[SCHEDULER] Ending class alert sent to {username} - {len(ending_soon)} event(s)")
                    
            except Exception as ex:
                print(f"[SCHEDULER] Ending class reminder failed for {username}: {ex}")
                import traceback
                traceback.print_exc()
    
    finally:
        _ending_reminder_lock.release()


def check_loa_rejections():
    """
    Runs every 30 minutes.
    Checks each student's LOA/MC (absence) applications for any that were
    rejected in the last 7 days, and emails them once per rejection.
    Consolidates multi-day absences into a single email with date range.
    """
    if not _loa_reminder_lock.acquire(blocking=False):
        print("[LOA] Another LOA rejection job already running, skipping")
        return

    try:
        from mailer import send_loa_rejection_email
        # from app import fetch_absences
        from elentra_client import fetch_absences
        from database import save_student_config, get_all_reminder_students
 
        # Read from database (source of truth)
        students = {}
        try:
            students = get_all_reminder_students()
            if not students:
                print("[LOA] No students found in database for LOA check")
                return
            print(f"[LOA] Loaded {len(students)} students from database")
        except Exception as db_ex:
            print(f"[LOA] Failed to load students from database: {db_ex}")
            return
 
        for username, info in list(students.items()):
            prefs = info.get("preferences", {})
            if not prefs.get("loa_rejection", True):
                print(f"[LOA] {username}: LOA rejection pref disabled, skipping")
                continue
 
            email = info.get("email")
            if not email:
                print(f"[LOA] {username}: no email configured, skipping")
                continue

            try:
                session, jwt_token = _get_elentra_session(username, info)
                if not session or not jwt_token:
                    print(f"[LOA] {username}: no session/jwt, skipping")
                    continue

                requests_data, totals_data = fetch_absences(session, jwt_token)
                if not requests_data:
                    continue

                sorted_requests = sorted(
                    requests_data,
                    key=lambda r: int(r.get("created_date", 0)),
                    reverse=True
                )
                seven_days_ago = datetime.now() - timedelta(days=7)
                already_notified = info.get("loa_rejection_notified", [])

                # ── GROUP REJECTIONS BY REFERENCE CODE ──
                rejected_by_ref = {}
                for r in sorted_requests:
                    if not isinstance(r, dict) or r.get("status", {}).get("title") != "Rejected":
                        continue

                    created_ts = int(r.get("created_date", 0))
                    created_dt = datetime.fromtimestamp(created_ts)
                    if created_dt < seven_days_ago:
                        break  # sorted newest-first, so we can stop here

                    ref_code = r.get("reference_code", "N/A")
                    if ref_code in already_notified:
                        continue

                    if ref_code not in rejected_by_ref:
                        rejected_by_ref[ref_code] = {
                            "dates": [],
                            "reason": r.get("reason", {}).get("title", "Unknown reason"),
                            "created_date": created_dt,
                            "from_ts": r.get("from"),
                            "to_ts": r.get("to")
                        }
                    
                    # Store the date range for this entry
                    from_dt = datetime.fromtimestamp(r["from"]).strftime("%d %b %Y") if r.get("from") else "N/A"
                    to_dt = datetime.fromtimestamp(r["to"]).strftime("%d %b %Y") if r.get("to") else "N/A"
                    rejected_by_ref[ref_code]["dates"].append((from_dt, to_dt))

            # ── SEND ONE EMAIL PER REFERENCE CODE ──
            for ref_code, data in rejected_by_ref.items():
                # Format date display
                date_ranges = data["dates"]
                if len(date_ranges) == 1:
                    from_date, to_date = date_ranges[0]
                    if from_date == to_date:
                        date_display = from_date
                    else:
                        date_display = f"{from_date} to {to_date}"
                else:
                    # Multiple days: show full range
                    first_from = date_ranges[0][0]
                    last_to = date_ranges[-1][1]
                    # Check if it's a continuous range
                    if len(date_ranges) > 1:
                        date_display = f"{first_from} to {last_to}"
                    else:
                        date_display = f"{first_from} - {last_to}"
                    
                    # Also list individual dates if they're not continuous
                    if len(date_ranges) > 1:
                        date_display += f" ({len(date_ranges)} days)"

                # ── STEP 1: SAVE TO DATABASE FIRST ──
                try:
                    already_notified.append(ref_code)
                    info["loa_rejection_notified"] = already_notified
                    
                    save_student_config(
                        username=username,
                        password=info.get("password", ""),
                        email=email,
                        preferences=prefs,
                        bus_config=info.get("bus_config", {}),
                        loa_rejection_notified=already_notified
                    )
                    print(f"[LOA] {username}: ✅ saved notification status for ref {ref_code}")
                except Exception as db_ex:
                    print(f"[LOA] {username}: DB save failed: {db_ex}")
                    continue  # Skip sending if save fails

                # ── STEP 2: SEND EMAIL ──
                try:
                    send_loa_rejection_email(
                        to_email=email,
                        username=username,
                        reference=ref_code,
                        from_date=date_display,
                        reason=data["reason"]
                    )
                    print(f"[LOA] {username}: ✅ rejection email sent for ref {ref_code} (consolidated {len(date_ranges)} day(s))")
                except Exception as mail_ex:
                    print(f"[LOA] {username}: email failed for ref {ref_code}: {mail_ex}")

            except Exception as ex:
                print(f"[LOA] {username}: check failed: {ex}")

    finally:
        _loa_reminder_lock.release()

def check_bus_reminders():
    """
    Runs every minute. Checks all registered students for bus reminders.
    Always reads from database to get latest config.
    """
    from mailer import send_bus_reminder_email
    
    # ALWAYS read from database as the only source of truth
    students = {}
    try:
        from database import get_all_reminder_students
        students = get_all_reminder_students()
        print(f"[BUS] Loaded {len(students)} students from database")
    except Exception as e:
        print(f"[BUS] Database load failed: {e}")
    
    if not students:
        return
    
    now = datetime.now(SGT)
    today_name = now.strftime("%A")
    today_weekday = now.weekday()
    
    # No buses on weekends
    if today_weekday >= 5:
        return
    
    BUS_TIMES = ["8:15", "9:15", "11:15", "14:15", "16:15", "17:30"]
    YUNNAN_FROM = "Yunnan Campus (Experimental Medicine Building)"
    NOVENA_FROM = "Novena Campus (Toh Kian Chui Annex)"
    YUNNAN_TO = "Yunnan Campus"
    NOVENA_TO = "Novena Campus"
    today_key = now.strftime("%Y-%m-%d")
    
    for bus_username, info in students.items():
        bus_config = info.get("bus_config", {})
        
        if not bus_config or not bus_config.get("active", False):
            continue
        
        remind_before = bus_config.get("remind_before_minutes", 5)
        preferred_direction = bus_config.get("direction", "both")
        preferred_times = bus_config.get("preferred_times", [])
        
        for time_str in BUS_TIMES:
            if preferred_times and time_str not in preferred_times:
                continue
            
            hour, minute = map(int, time_str.split(":"))
            departure_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            remind_time = departure_time - timedelta(minutes=remind_before)
            time_diff = (now - remind_time).total_seconds()

            # Only fire if we're at or just past the reminder time (within 90 seconds)
            if time_diff < 0 or time_diff > 90:
                continue
            
            cache_key = f"{bus_username}:{today_key}:bus:{time_str}:{preferred_direction}"
            if cache_key in _sent_bus_reminders:
                continue
            
            _sent_bus_reminders[cache_key] = True
            
            print(f"🚌 [BUS] Sending reminder to {bus_username} for {time_str} ({preferred_direction})")
            print(f"   Config: remind_before={remind_before}, times={preferred_times}")
            
            directions = []
            if preferred_direction in ("both", "to_novena"):
                directions.append(("to_novena", YUNNAN_FROM, NOVENA_TO))
            if preferred_direction in ("both", "to_ntu"):
                directions.append(("to_ntu", NOVENA_FROM, YUNNAN_TO))
            
            for direction, from_loc, to_loc in directions:
                try:
                    send_bus_reminder_email(
                        to_email=info["email"],
                        username=bus_username,
                        bus_time=time_str,
                        remind_before=remind_before,
                        direction=direction,
                        from_location=from_loc,
                        to_location=to_loc
                    )
                    print(f"✅ [BUS] Email sent to {info['email']}")
                except Exception as ex:
                    print(f"❌ [BUS] Failed for {bus_username}: {ex}")

def get_tomorrow_events(username, info):
    """Login to Elentra and return only tomorrow's formatted events,
    filtered by the student's module preferences."""
    session, jwt_token = _get_elentra_session(username, info)
    if not session:
        return []
    
    raw = _fetch_events_fn(session, weeks=1)
    all_fmt = _format_events_fn(raw)

    tomorrow_str = (datetime.now(SGT) + timedelta(days=1)).strftime("%A, %d %b %Y")
    tomorrow_events = [e for e in all_fmt if e["date"] == tomorrow_str]
    
    # Filter by selected modules
    selected_modules = info.get("preferences", {}).get("selected_modules", [])
    if selected_modules:
        tomorrow_events = [
            e for e in tomorrow_events
            if e.get("course_code") in selected_modules
        ]

    return tomorrow_events


def get_this_week_events(username, info):
    """Login to Elentra and return this week's formatted events,
    filtered by module preferences."""
    session, jwt_token = _get_elentra_session(username, info)
    if not session:
        return []
    
    raw = _fetch_events_fn(session, weeks=2)
    all_fmt = _format_events_fn(raw)

    today = datetime.now(SGT).date()
    sunday = today + timedelta(days=(6 - today.weekday()))

    selected_modules = info.get("preferences", {}).get("selected_modules", [])
    
    week_events = []
    for e in all_fmt:
        try:
            event_date = datetime.strptime(e["date"], "%A, %d %b %Y").date()
            if today <= event_date <= sunday:
                # Filter by module if preferences are set
                if selected_modules and e.get("course_code") not in selected_modules:
                    continue
                week_events.append(e)
        except Exception:
            continue

    return week_events

def _filter_by_modules(events, selected_modules):
    """Helper: filter events by selected modules if preferences are set."""
    if not selected_modules:
        return events
    return [e for e in events if e.get("course_code") in selected_modules]
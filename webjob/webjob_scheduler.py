# import sys
# import os

# # Add parent directory to path
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# from app import elentra_login, fetch_events, format_events
# from scheduler import init_scheduler
# import time

# def run():
#     scheduler = init_scheduler(elentra_login, fetch_events, format_events)
#     print("[WEBJOB] Scheduler started!")
    
#     try:
#         while True:
#             time.sleep(60)
#     except KeyboardInterrupt:
#         scheduler.shutdown()

# if __name__ == "__main__":
#     run()

"""
webjob/webjob_scheduler.py
WebJob entry point — imports from elentra_client (NOT from app.py).
Runs APScheduler in blocking mode and reads all student data from
Azure Table Storage directly via database.py.
"""

import sys
import os
import time
import math
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Locate the actual web app root ──────────────────────────────────
# A continuous WebJob lives 4 folders deep:
#   <site root>/App_Data/jobs/continuous/<job_name>/webjob_scheduler.py
# So "go up 2 levels" (the old logic) lands inside App_Data/jobs/continuous,
# NOT the site root where app.py actually lives — `from app import ...`
# would fail with ModuleNotFoundError once deployed.
#
# Azure always sets HOME=/home (Linux) or D:\home (Windows) for both the
# web app and its WebJobs, and the actual app code always lives at
# <HOME>/site/wwwroot — regardless of how deep the WebJob folder is. That
# makes it the reliable way to find the app root, instead of counting
# relative directory levels.
AZURE_HOME = os.environ.get("HOME")
if AZURE_HOME:
    APP_ROOT = os.path.join(AZURE_HOME, "site", "wwwroot")
else:
    # Local/dev fallback: walk up from this file until we find app.py
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.exists(os.path.join(APP_ROOT, "app.py")):
            break
        APP_ROOT = os.path.dirname(APP_ROOT)

sys.path.insert(0, APP_ROOT)
print(f"[WEBJOB] App root resolved to: {APP_ROOT}")

from elentra_client import elentra_login, fetch_events, format_events, fetch_absences
from scheduler import init_scheduler
import time

def run():
    scheduler = init_scheduler(elentra_login, fetch_events, format_events)
    print("[WEBJOB] Scheduler started!")
    
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()

if __name__ == "__main__":
    run()
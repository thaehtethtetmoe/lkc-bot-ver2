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

# ── Path setup (so we can import root-level modules) ──────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from elentra_client import elentra_login, fetch_events, format_events, fetch_absences
from scheduler import init_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Worker pool config ─────────────────────────────────────
# Automatically scales workers based on how many students are registered.
# Change STUDENTS_PER_WORKER to tune the ratio.
#
#   7 students  → 2 workers   (min floor)
#   20 students → 5 workers
#   50 students → 13 workers
#   100 students → 25 workers
#   400 students → 40 workers (max ceiling for B1, 1 vCore)
#
STUDENTS_PER_WORKER = 4   # one worker per N students
MIN_WORKERS         = 2   # never go below this
MAX_WORKERS         = 40  # hard cap for B1 (raise to 80 on P1v3)

def calc_workers(student_count: int) -> int:
    raw = math.ceil(student_count / STUDENTS_PER_WORKER)
    return min(max(raw, MIN_WORKERS), MAX_WORKERS)


def run_parallel(students: dict, job_fn, job_name: str):
    """
    Run job_fn(username, info) for every student in parallel.
    Worker count auto-scales with student count.
    """
    if not students:
        log.info(f"[{job_name}] No students, skipping")
        return

    n_workers = calc_workers(len(students))
    log.info(f"[{job_name}] {len(students)} students → {n_workers} workers")

    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(job_fn, username, info): username
            for username, info in students.items()
        }
        for future in as_completed(futures):
            username = futures[future]
            try:
                future.result()
                ok += 1
            except Exception as e:
                log.error(f"[{job_name}] {username} failed: {e}")
                fail += 1

    log.info(f"[{job_name}] done — {ok} ok, {fail} failed, {n_workers} workers")


def run():
    log.info("[WEBJOB] Starting — importing scheduler")

    # ── init_scheduler wires up the Elentra helpers ───────
    # It no longer needs reminder_store because every job reads
    # from Azure Table Storage via database.get_all_reminder_students()
    scheduler = init_scheduler(
        elentra_login=elentra_login,
        fetch_events=fetch_events,
        format_events=format_events,
    )

    log.info("[WEBJOB] Scheduler started — running until killed")

    # Keep the process alive; APScheduler runs jobs in background threads
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("[WEBJOB] Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        log.info("[WEBJOB] Stopped")
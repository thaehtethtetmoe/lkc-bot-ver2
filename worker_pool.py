"""
worker_pool.py
Drop-in replacement for the for-loop in each scheduler job.
Workers scale automatically based on how many students are registered.
"""

import math
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

# ── Tuning knobs (adjust these as you grow) ────────────────
STUDENTS_PER_WORKER = 4   # how many students one worker handles at a time
MIN_WORKERS         = 2   # always keep at least this many (avoids 1-worker edge case)
MAX_WORKERS         = 40  # hard cap — B1 has 1 vCore, beyond ~40 threads you get
                          # context-switch overhead with no speed gain.
                          # Raise to 80 if you upgrade to P1v3 (2 vCores).

def calc_workers(student_count: int) -> int:
    """
    student_count=7   → 2  workers  (ceil(7/4)=2,  clamped to MIN=2)
    student_count=20  → 5  workers  (ceil(20/4)=5)
    student_count=50  → 13 workers  (ceil(50/4)=13)
    student_count=100 → 25 workers  (ceil(100/4)=25)
    student_count=400 → 40 workers  (ceil(400/4)=100, clamped to MAX=40)
    """
    raw = math.ceil(student_count / STUDENTS_PER_WORKER)
    return min(max(raw, MIN_WORKERS), MAX_WORKERS)


def run_job_for_all_students(
    students: dict,
    job_fn,          # callable(username: str, info: dict) → None
    job_name: str = "job",
) -> dict:
    """
    Run job_fn for every student in parallel, with worker count scaled
    automatically to the number of students.

    Returns:
        {
          "success": [...usernames],
          "failed":  [...usernames],
          "workers_used": N,
          "student_count": N,
        }
    """
    student_count = len(students)
    if student_count == 0:
        log.info(f"[{job_name}] No students, skipping")
        return {"success": [], "failed": [], "workers_used": 0, "student_count": 0}

    n_workers = calc_workers(student_count)
    log.info(f"[{job_name}] {student_count} students → {n_workers} workers")

    success, failed = [], []

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        future_to_user = {
            pool.submit(job_fn, username, info): username
            for username, info in students.items()
        }
        for future in as_completed(future_to_user):
            username = future_to_user[future]
            try:
                future.result()
                success.append(username)
            except Exception as e:
                log.error(f"[{job_name}] {username} failed: {e}")
                failed.append(username)

    log.info(
        f"[{job_name}] done — {len(success)} ok, {len(failed)} failed, "
        f"{n_workers} workers used"
    )
    return {
        "success":       success,
        "failed":        failed,
        "workers_used":  n_workers,
        "student_count": student_count,
    }
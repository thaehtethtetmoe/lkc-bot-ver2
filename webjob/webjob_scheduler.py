import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import elentra_login, fetch_events, format_events
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
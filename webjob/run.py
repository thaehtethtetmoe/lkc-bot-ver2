import sys
import os

# webjob_scheduler.py resolves the app root itself (via Azure's HOME env var),
# so this file just needs to be able to import its sibling module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from webjob_scheduler import run

if __name__ == "__main__":
    run()
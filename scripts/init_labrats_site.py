#!/usr/bin/env python3
"""
Initialize the San Diego LabRats website tables in an existing database.

Creates labrats_settings, labrats_programs, labrats_pages, labrats_sessions (and the inquiry and
assignment tables) if they are missing, and loads model/labrats_seed/*.json into any that are empty.
Existing rows are never changed, so it is safe to run again. scripts/db_init.py does the same for a
fresh database.

Usage:
    python scripts/init_labrats_site.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app  # noqa: E402  (registers every model before tables are created)
from model.labrats_inquiry import initLabRatsInquiries  # noqa: E402
from model.labrats_assignment import initLabRatsAssignments  # noqa: E402
from model.labrats_site import LabRatsPage, LabRatsSession, initLabRatsSite  # noqa: E402

if __name__ == "__main__":
    with app.app_context():
        initLabRatsInquiries()
        initLabRatsAssignments()
        initLabRatsSite()
        print(f"LabRats website tables ready: {LabRatsPage.query.count()} pages, {LabRatsSession.query.count()} sessions.")

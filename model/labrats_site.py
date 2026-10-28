""" San Diego LabRats website content: site settings, pages, and registration sessions.

The frontend stores no data. Every page shell asks GET /api/labrats/page?path=... and renders what
comes back, so organization facts, navigation, page text, program facts, and session dates all live
in these tables. initLabRatsSite() creates the tables and loads model/labrats_seed/*.json the first
time and adds new seed content later; staff change sessions and the announcement from the admin console.

Page bodies are HTML written by LabRats (seed data and code review), not visitor input. They hold
placeholders the frontend fills from the same bundle:
  data-labrats-org="phone"                 text from the `org` setting
  data-labrats-org-href="mailto:{charter_email}"  attribute filled from the `org` setting
  data-labrats-block="help_paying_families"       shared HTML from the `blocks` setting
  data-labrats-widget="session-list" ...    lists built from programs and sessions
  data-labrats-form-slot="contact"          a form the frontend owns
"""
import json
import os
import re
from datetime import datetime

from __init__ import db
from model.labrats_programs import LabRatsProgram, all_programs

SEED_DIR = os.path.join(os.path.dirname(__file__), "labrats_seed")
SESSION_STATUSES = ("open", "closed")
MAX_SHORT_TEXT = 200
MAX_LONG_TEXT = 2000
PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]*$")


class LabRatsSetting(db.Model):
    __tablename__ = "labrats_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, key, value):
        self.key = key
        self.value = value


class LabRatsPage(db.Model):
    __tablename__ = "labrats_pages"

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(255), unique=True, nullable=False)
    template = db.Column(db.String(20), nullable=False, default="default")
    title = db.Column(db.String(255), nullable=False)
    fields = db.Column(db.JSON, nullable=False, default=dict)
    body = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, path, template, title, fields=None, body=""):
        self.path = path
        self.template = template
        self.title = title
        self.fields = fields or {}
        self.body = body

    def read(self):
        """Template-specific fields (heading, lead, facts, redirect_to, ...) sit beside the core ones."""
        return {**(self.fields or {}), "path": self.path, "template": self.template, "title": self.title, "body": self.body}


class LabRatsSession(db.Model):
    """One registration page's session: an afterschool month, a camp, an event, or a payment form."""
    __tablename__ = "labrats_sessions"

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(255), unique=True, nullable=False)
    program = db.Column(db.String(64), nullable=True)
    grades = db.Column(db.String(40), nullable=True)
    term = db.Column(db.String(MAX_SHORT_TEXT), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="closed")
    summary = db.Column(db.Text, nullable=True)
    times = db.Column(db.JSON, nullable=False, default=list)
    donorbox_campaign = db.Column(db.String(40), nullable=True)
    schedule_order = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, path, term, program=None, grades=None, status="closed", summary=None, times=None,
                 donorbox_campaign=None, schedule_order=None):
        self.path = path
        self.term = term
        self.program = program
        self.grades = grades
        self.status = status
        self.summary = summary
        self.times = times or []
        self.donorbox_campaign = str(donorbox_campaign) if donorbox_campaign is not None else None
        self.schedule_order = schedule_order

    def update(self, cleaned):
        for field, value in cleaned.items():
            setattr(self, field, value)
        db.session.commit()
        return self

    def read(self):
        return {
            "id": self.id,
            "path": self.path,
            "program": self.program,
            "grades": self.grades,
            "term": self.term,
            "status": self.status,
            "summary": self.summary,
            "times": self.times or [],
            "donorbox_campaign": self.donorbox_campaign,
            "schedule_order": self.schedule_order,
        }


# ---------- Reading ----------

def site_settings():
    return {setting.key: setting.value for setting in LabRatsSetting.query.all()}


def get_setting(key, default=None):
    setting = db.session.get(LabRatsSetting, key)
    return setting.value if setting else default


def set_setting(key, value):
    setting = db.session.get(LabRatsSetting, key)
    if setting is None:
        db.session.add(LabRatsSetting(key, value))
    else:
        setting.value = value
    db.session.commit()
    return value


def scholarship_program_values():
    return {choice["value"] for choice in get_setting("scholarship_programs", [])}


def all_sessions():
    """Sessions in schedule order; sessions without an order come last."""
    sessions = LabRatsSession.query.all()
    return [session.read() for session in sorted(
        sessions, key=lambda s: (s.schedule_order is None, s.schedule_order or 0, s.term or "", s.grades or ""))]


def normalize_path(path):
    """'/camps' and '/camps/index.html' both mean '/camps/'. Returns None for anything else odd."""
    if not isinstance(path, str) or not PATH_PATTERN.match(path) or ".." in path:
        return None
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    return path


def find_page(path):
    path = normalize_path(path)
    if path is None:
        return None
    page = LabRatsPage.query.filter_by(path=path).first()
    if page is None and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        page = LabRatsPage.query.filter_by(path=path + "/").first()
    return page


def page_bundle(path):
    """Everything one page needs in a single response, or None when no page has that path."""
    page = find_page(path)
    if page is None:
        return None
    session = LabRatsSession.query.filter_by(path=page.path).first()
    return {
        "site": site_settings(),
        "page": page.read(),
        "session": session.read() if session else None,
        "programs": all_programs(),
        "sessions": all_sessions(),
    }


# ---------- Admin edits ----------

def _short_text(data, field, errors, cleaned, required=False, limit=MAX_SHORT_TEXT):
    if field not in data:
        return
    value = data[field]
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[field] = f"{field.replace('_', ' ').capitalize()} is required."
        cleaned[field] = None
        return
    if not isinstance(value, str) or len(value.strip()) > limit:
        errors[field] = f"{field.replace('_', ' ').capitalize()} must be text up to {limit} characters."
        return
    cleaned[field] = value.strip()


def validate_session_update(data):
    """Return (cleaned, errors) for an admin's change to a session; any subset of fields."""
    if not isinstance(data, dict):
        raise ValueError("Session changes must be a JSON object")
    cleaned, errors = {}, {}
    if "status" in data:
        if data["status"] not in SESSION_STATUSES:
            errors["status"] = "Status must be open or closed."
        cleaned["status"] = data["status"]
    _short_text(data, "term", errors, cleaned, required=True)
    _short_text(data, "grades", errors, cleaned, limit=40)
    _short_text(data, "summary", errors, cleaned, limit=MAX_LONG_TEXT)
    _short_text(data, "donorbox_campaign", errors, cleaned, limit=40)
    if cleaned.get("donorbox_campaign") and not cleaned["donorbox_campaign"].isdigit():
        errors["donorbox_campaign"] = "The Donorbox campaign is the number from the event's embed code."
    if "schedule_order" in data:
        order = data["schedule_order"]
        if order is not None and (not isinstance(order, int) or isinstance(order, bool) or not 0 <= order <= 9999):
            errors["schedule_order"] = "Schedule order must be a whole number from 0 to 9999."
        cleaned["schedule_order"] = order
    if "times" in data:
        times = data["times"]
        valid = isinstance(times, list) and len(times) <= 12 and all(
            isinstance(row, dict) and set(row) <= {"day", "time", "dates"}
            and all(isinstance(row.get(key, ""), str) and len(row.get(key, "")) <= MAX_SHORT_TEXT for key in ("day", "time", "dates"))
            for row in times)
        if not valid:
            errors["times"] = "Times must be up to 12 rows of day, time, and dates."
        else:
            cleaned["times"] = [{key: row.get(key, "").strip() for key in ("day", "time", "dates")} for row in times]
    return cleaned, errors


def validate_announcement(data):
    """Return (cleaned, errors). A shown announcement needs text and a link on this site."""
    if not isinstance(data, dict):
        raise ValueError("The announcement must be a JSON object")
    cleaned, errors = {"show": bool(data.get("show"))}, {}
    for field, limit in (("text", 300), ("link_text", 80)):
        value = data.get(field) or ""
        if not isinstance(value, str) or len(value.strip()) > limit:
            errors[field] = f"Keep this under {limit} characters."
        cleaned[field] = value.strip() if isinstance(value, str) else ""
    url = data.get("url") or ""
    if url and normalize_path(url.split("#")[0]) is None:
        errors["url"] = "Link to a page on this site, like /camps/."
    cleaned["url"] = url
    if cleaned["show"] and not cleaned["text"]:
        errors["text"] = "Write the announcement, or turn it off."
    if cleaned["link_text"] and not url:
        errors["url"] = "Add the page the link goes to."
    return cleaned, errors


def save_announcement(cleaned):
    """New wording gets a new id, so visitors who dismissed the old notice see the new one."""
    current = get_setting("announcement", {}) or {}
    changed = any(current.get(key) != cleaned[key] for key in ("text", "link_text", "url"))
    announcement_id = f"announcement-{datetime.utcnow():%Y%m%d%H%M%S}" if changed else current.get("id", "announcement")
    return set_setting("announcement", {**cleaned, "id": announcement_id})


# ---------- Seed ----------

def _seed(name):
    with open(os.path.join(SEED_DIR, f"{name}.json"), encoding="utf-8") as handle:
        return json.load(handle)


def initLabRatsSite():
    """Create the website tables and add any seed content they are missing. Safe to rerun.

    New seed rows (a page path, a session path, a program slug, a setting key) and new entries
    inside a setting (such as a new shared block) are added. Rows that already exist are never
    changed, so edits staff made in the admin console are kept.
    """
    db.create_all()
    for key, value in _seed("settings").items():
        setting = db.session.get(LabRatsSetting, key)
        if setting is None:
            db.session.add(LabRatsSetting(key, value))
        elif isinstance(value, dict) and isinstance(setting.value, dict):
            missing = {name: entry for name, entry in value.items() if name not in setting.value}
            if missing:
                setting.value = {**setting.value, **missing}
    known_programs = {slug for (slug,) in db.session.query(LabRatsProgram.slug).all()}
    for program in _seed("programs"):
        if program["slug"] not in known_programs:
            db.session.add(LabRatsProgram(**program))
    known_pages = {path for (path,) in db.session.query(LabRatsPage.path).all()}
    for page in _seed("pages"):
        if page["path"] not in known_pages:
            db.session.add(LabRatsPage(**page))
    known_sessions = {path for (path,) in db.session.query(LabRatsSession.path).all()}
    for session in _seed("sessions"):
        if session["path"] not in known_sessions:
            db.session.add(LabRatsSession(**session))
    db.session.commit()

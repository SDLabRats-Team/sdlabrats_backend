""" San Diego LabRats assignments and student turn-ins.

Admins post assignments (for example an at-home lab to try between classes); signed-in students
turn in a written response and an optional link; admins read the turn-ins and leave feedback.
Each student has at most one turn-in per assignment; turning in again replaces it.
"""
import re
from datetime import date, datetime

from __init__ import db

MAX_TITLE_LENGTH = 200
MAX_TEXT_LENGTH = 5000
MAX_LINK_LENGTH = 500
TURNIN_STATUSES = ("submitted", "reviewed")
LINK_PATTERN = re.compile(r"^https?://[^\s]+$")


class LabRatsAssignment(db.Model):
    __tablename__ = "labrats_assignments"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(MAX_TITLE_LENGTH), nullable=False)
    instructions = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    is_open = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    turnins = db.relationship("LabRatsTurnIn", backref="assignment", cascade="all, delete-orphan", lazy="dynamic")

    def __init__(self, title, instructions, due_date=None, is_open=True):
        self.title = title
        self.instructions = instructions
        self.due_date = due_date
        self.is_open = is_open

    def create(self):
        db.session.add(self)
        db.session.commit()
        return self

    def update(self, cleaned):
        for field in ("title", "instructions", "due_date", "is_open"):
            if field in cleaned:
                setattr(self, field, cleaned[field])
        db.session.commit()
        return self

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def read(self):
        return {
            "id": self.id,
            "title": self.title,
            "instructions": self.instructions,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "is_open": self.is_open,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "turnin_count": self.turnins.count(),
            "reviewed_count": self.turnins.filter_by(status="reviewed").count(),
        }


class LabRatsTurnIn(db.Model):
    __tablename__ = "labrats_turnins"
    __table_args__ = (db.UniqueConstraint("assignment_id", "user_id", name="uq_labrats_turnin_student"),)

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("labrats_assignments.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    response = db.Column(db.Text, nullable=False, default="")
    link = db.Column(db.String(MAX_LINK_LENGTH), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="submitted")
    feedback = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    student = db.relationship("User", lazy="joined")

    def __init__(self, assignment_id, user_id):
        self.assignment_id = assignment_id
        self.user_id = user_id

    def submit(self, cleaned):
        """Save (or replace) the student's work; a resubmission goes back to "submitted"."""
        self.response = cleaned["response"]
        self.link = cleaned.get("link")
        self.status = "submitted"
        self.submitted_at = datetime.utcnow()
        self.reviewed_at = None
        if self.id is None:
            db.session.add(self)
        db.session.commit()
        return self

    def review(self, cleaned):
        if "feedback" in cleaned:
            self.feedback = cleaned["feedback"]
        if "status" in cleaned:
            self.status = cleaned["status"]
            self.reviewed_at = datetime.utcnow() if cleaned["status"] == "reviewed" else None
        db.session.commit()
        return self

    def read(self):
        return {
            "id": self.id,
            "assignment_id": self.assignment_id,
            "student": {"uid": self.student.uid, "name": self.student.name} if self.student else None,
            "response": self.response,
            "link": self.link,
            "status": self.status,
            "feedback": self.feedback,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


def _text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def validate_assignment(data, partial=False):
    """Return (cleaned, errors) for an assignment. `partial` allows updating only some fields."""
    if not isinstance(data, dict):
        raise ValueError("Assignment must be a JSON object")
    cleaned, errors = {}, {}
    for field, limit, label in (("title", MAX_TITLE_LENGTH, "a title"), ("instructions", MAX_TEXT_LENGTH, "instructions")):
        if field in data or not partial:
            value = _text(data.get(field), limit)
            if not value:
                errors[field] = f"Please enter {label}."
            cleaned[field] = value
    if "due_date" in data:
        raw = data.get("due_date")
        if raw in (None, ""):
            cleaned["due_date"] = None
        else:
            try:
                cleaned["due_date"] = date.fromisoformat(raw)
            except (TypeError, ValueError):
                errors["due_date"] = "Use a date like 2026-10-31."
    if "is_open" in data:
        if not isinstance(data["is_open"], bool):
            errors["is_open"] = "is_open must be true or false."
        else:
            cleaned["is_open"] = data["is_open"]
    return cleaned, errors


def validate_turnin(data):
    """Return (cleaned, errors) for a student's turn-in: a response, a link, or both."""
    if not isinstance(data, dict):
        raise ValueError("Turn-in must be a JSON object")
    cleaned = {"response": _text(data.get("response"), MAX_TEXT_LENGTH)}
    errors = {}
    link = _text(data.get("link"), MAX_LINK_LENGTH)
    if link:
        if LINK_PATTERN.match(link):
            cleaned["link"] = link
        else:
            errors["link"] = "Links must start with http:// or https://."
    if not cleaned["response"] and not link:
        errors["response"] = "Write about your work or add a link to it."
    return cleaned, errors


def validate_review(data):
    """Return (cleaned, errors) for an admin's feedback on a turn-in."""
    if not isinstance(data, dict):
        raise ValueError("Review must be a JSON object")
    cleaned, errors = {}, {}
    if "feedback" in data:
        cleaned["feedback"] = _text(data.get("feedback"), MAX_TEXT_LENGTH) or None
    if "status" in data:
        if data["status"] in TURNIN_STATUSES:
            cleaned["status"] = data["status"]
        else:
            errors["status"] = f"Status must be one of: {', '.join(TURNIN_STATUSES)}."
    if not cleaned and not errors:
        errors["feedback"] = "Send feedback, a status, or both."
    return cleaned, errors


def delete_turnins_for_user(user_id):
    """Remove a student's turn-ins (used before deleting the account)."""
    LabRatsTurnIn.query.filter_by(user_id=user_id).delete()
    db.session.commit()


def initLabRatsAssignments():
    """Create the assignment tables if they do not exist. Safe to run on an existing database."""
    db.create_all()

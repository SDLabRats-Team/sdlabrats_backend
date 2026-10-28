
"""Submissions from San Diego LabRats website forms.

One table holds every form (contact, scholarship, partnership, video topic,
newsletter, survey). Shared fields are columns; form-specific answers are
stored as JSON in `details`.

`validate_inquiry` validates incoming form data on the backend.
"""

import json
import re
from datetime import datetime

from __init__ import db
from model.labrats_programs import program_slugs
from model.labrats_site import scholarship_program_values


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MAX_TEXT_LENGTH = 2000
MAX_FIELD_LENGTH = 200
STATUSES = ("new", "handled")


# Required fields per form, with labels used in error messages.
FORM_RULES = {
    "contact": {
        "first_name": "first name",
        "last_name": "last name",
        "email": "email",
        "interest": "what you're asking about",
    },
    "newsletter": {
        "first_name": "first name",
        "last_name": "last name",
        "email": "email",
    },
    "video_topic": {
        "first_name": "first name",
        "last_name": "last name",
        "email": "email",
        "subjects": "subjects",
    },
    "partnership": {
        "company": "company name",
        "first_name": "first name",
        "last_name": "last name",
        "job_title": "title",
        "email": "business email",
    },
    "scholarship": {
        "student_first_name": "student's first name",
        "student_last_name": "student's last name",
        "student_grade": "grade",
        "student_school": "school",
        "parent_first_name": "parent's first name",
        "parent_last_name": "parent's last name",
        "email": "email",
        "phone": "phone",
    },
    "survey": {
        "first_name": "first name",
        "last_name": "last name",
        "email": "email",
        "program": "program",
        "rating": "rating",
    },
}


# Optional fields each form may send.
# Unknown fields are ignored.
OPTIONAL_FIELDS = {
    "contact": ("message",),
    "newsletter": (),
    "video_topic": ("source_page",),
    "partnership": (),
    "scholarship": (
        "programs",
        "income_under_limit",
        "military_family",
    ),
    "survey": ("message",),
}


LONG_TEXT_FIELDS = {"message", "subjects"}
SCHOLARSHIP_GRADES = {"K", "1", "2", "3", "4", "5", "6", "7", "8"}
YES_NO = {"yes", "no"}

SURVEY_PROGRAMS = {
    "After-School STEM",
    "Summer Camps",
    "Workshops",
}
SURVEY_RATINGS = {"1", "2", "3", "4", "5"}


class LabRatsInquiry(db.Model):
    __tablename__ = "labrats_inquiries"

    id = db.Column(db.Integer, primary_key=True)
    form = db.Column(db.String(32), nullable=False, index=True)
    first_name = db.Column(db.String(MAX_FIELD_LENGTH), nullable=False)
    last_name = db.Column(db.String(MAX_FIELD_LENGTH), nullable=False)
    email = db.Column(db.String(MAX_FIELD_LENGTH), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    details = db.Column(db.Text, nullable=False, default="{}")
    status = db.Column(db.String(16), nullable=False, default="new")
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        index=True,
    )

    def __init__(
        self,
        form,
        first_name,
        last_name,
        email,
        phone=None,
        details=None,
    ):
        self.form = form
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.phone = phone
        self.details = json.dumps(details or {})
        self.status = "new"

    def create(self):
        db.session.add(self)
        db.session.commit()
        return self

    def update_status(self, status):
        if status not in STATUSES:
            raise ValueError(f"Unknown inquiry status '{status}'")
        self.status = status
        db.session.commit()
        return self

    def read(self):
        return {
            "id": self.id,
            "form": self.form,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "details": json.loads(self.details or "{}"),
            "status": self.status,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at
                else None
            ),
        }

    @staticmethod
    def from_cleaned(cleaned):
        """Build an inquiry from validated form data."""
        form = cleaned["form"]
        prefix = "parent_" if form == "scholarship" else ""

        details = {
            key: value
            for key, value in cleaned.items()
            if key not in (
                "form",
                "email",
                "phone",
                f"{prefix}first_name",
                f"{prefix}last_name",
            )
        }

        return LabRatsInquiry(
            form=form,
            first_name=cleaned[f"{prefix}first_name"],
            last_name=cleaned[f"{prefix}last_name"],
            email=cleaned["email"],
            phone=cleaned.get("phone"),
            details=details,
        )


def _clean_text(value, limit):
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def validate_inquiry(data):
    """Return cleaned data and validation errors for a form submission."""
    if not isinstance(data, dict):
        raise ValueError("Inquiry payload must be a JSON object")

    form = data.get("form")

    if form not in FORM_RULES:
        raise ValueError(f"Unknown LabRats form '{form}'")

    cleaned = {"form": form}
    errors = {}

    # Validate required fields.
    for field, label in FORM_RULES[form].items():
        limit = (
            MAX_TEXT_LENGTH
            if field in LONG_TEXT_FIELDS
            else MAX_FIELD_LENGTH
        )

        value = _clean_text(data.get(field), limit)

        if not value:
            errors[field] = f"Please enter your {label}."

        cleaned[field] = value

    # Validate optional fields.
    for field in OPTIONAL_FIELDS[form]:
        if field == "programs":
            programs = data.get("programs") or []
            allowed = scholarship_program_values()

            cleaned["programs"] = (
                [p for p in programs if p in allowed]
                if isinstance(programs, list)
                else []
            )
        else:
            limit = (
                MAX_TEXT_LENGTH
                if field in LONG_TEXT_FIELDS
                else MAX_FIELD_LENGTH
            )

            value = _clean_text(data.get(field), limit)

            if value:
                cleaned[field] = value

    # Validate email.
    if cleaned.get("email") and not EMAIL_PATTERN.match(cleaned["email"]):
        errors["email"] = (
            "Please enter an email address like name@example.com."
        )

    # Contact form validation.
    if form == "contact":
        if (
            cleaned.get("interest")
            and cleaned["interest"] not in program_slugs() | {"other"}
        ):
            errors["interest"] = "Please choose one of the listed options."

    # Scholarship form validation.
    if form == "scholarship":
        errors.update(_validate_scholarship(cleaned))

    # Survey form validation.
    if form == "survey":
        if cleaned.get("program") not in SURVEY_PROGRAMS:
            errors["program"] = "Please select a valid program."

        if cleaned.get("rating") not in SURVEY_RATINGS:
            errors["rating"] = "Please select a rating from 1 to 5."

    return cleaned, errors


def _validate_scholarship(cleaned):
    errors = {}

    if (
        cleaned.get("student_grade")
        and cleaned["student_grade"] not in SCHOLARSHIP_GRADES
    ):
        errors["student_grade"] = "Please choose a grade from K to 8."

    if (
        cleaned.get("phone")
        and len(re.sub(r"\D", "", cleaned["phone"])) < 10
    ):
        errors["phone"] = "Please enter a phone number with area code."

    if not cleaned.get("programs"):
        errors["programs"] = "Choose at least one program."

    income = cleaned.get("income_under_limit")
    military = cleaned.get("military_family")

    if income not in YES_NO:
        errors["eligibility"] = (
            "Please answer the household income question."
        )
    elif income != "yes" and military != "yes":
        errors["eligibility"] = (
            "Scholarships are for households under $89,000 a year "
            "or military families. If your situation is different, "
            "contact us and we will talk it through."
        )

    return errors


def initLabRatsInquiries():
    """Create the inquiries table if needed."""
    db.create_all()

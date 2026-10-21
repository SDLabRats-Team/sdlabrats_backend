""" Rules for LabRats accounts that admins create and manage.

LabRats families and staff sign in with a username chosen by an admin, so these accounts skip
the GitHub-account check that the general /api/user signup applies. An admin creating an account
is the verification step upstream Flask requires, so new LabRats accounts start active.
"""
import re

ROLES = ("User", "Teacher", "Admin")
UID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,40}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MIN_PASSWORD_LENGTH = 8


def public_user(user):
    """The fields the admin console shows; never includes the password hash."""
    return {"id": user.id, "uid": user.uid, "name": user.name, "email": user.email, "role": user.role,
            "active": user.active}


def validate_account(data, creating):
    """Return (cleaned, errors). Creating requires name, uid, and password; updates accept any subset."""
    if not isinstance(data, dict):
        raise ValueError("Account must be a JSON object")
    cleaned, errors = {}, {}

    if creating or "name" in data:
        name = (data.get("name") or "").strip()
        if len(name) < 2:
            errors["name"] = "Name must be at least 2 characters."
        cleaned["name"] = name[:120]

    if creating:
        uid = (data.get("uid") or "").strip()
        if not UID_PATTERN.match(uid):
            errors["uid"] = "Usernames are 2-40 letters, numbers, dots, dashes, or underscores."
        cleaned["uid"] = uid

    if "email" in data and data.get("email"):
        email = data["email"].strip()
        if not EMAIL_PATTERN.match(email):
            errors["email"] = "Please enter an email address like name@example.com."
        cleaned["email"] = email[:120]

    if creating or data.get("password"):
        password = data.get("password") or ""
        if len(password) < MIN_PASSWORD_LENGTH or password.startswith("pbkdf2:"):
            errors["password"] = f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters."
        cleaned["password"] = password

    if creating or "role" in data:
        role = data.get("role") or "User"
        if role not in ROLES:
            errors["role"] = f"Role must be one of: {', '.join(ROLES)}."
        cleaned["role"] = role

    if "active" in data:
        if not isinstance(data["active"], bool):
            errors["active"] = "Active must be true or false."
        cleaned["active"] = data["active"]

    return cleaned, errors

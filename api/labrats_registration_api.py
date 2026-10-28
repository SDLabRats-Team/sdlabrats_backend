"""Public LabRats registration and email verification.

Register blueprint in main.py and create the EmailVerificationToken table with your
normal migration process before enabling these endpoints.
"""
import hashlib
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

from flask import Blueprint, current_app, request
from flask_restful import Api, Resource
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from __init__ import db
from model.user import User
from model.labrats_accounts import EMAIL_PATTERN, validate_account
from model.google_token import verified_student_email

labrats_registration_api = Blueprint(
    "labrats_registration_api", __name__, url_prefix="/api/labrats"
)
api = Api(labrats_registration_api)


class EmailVerificationToken(db.Model):
    __tablename__ = "labrats_email_verification_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _send_verification(email, token):
    host = os.environ["LABRATS_SMTP_HOST"]
    port = int(os.environ.get("LABRATS_SMTP_PORT", "587"))
    sender = os.environ["LABRATS_SMTP_FROM"]
    username = os.environ["LABRATS_SMTP_USER"]
    password = os.environ["LABRATS_SMTP_PASSWORD"]
    base_url = os.environ["LABRATS_VERIFY_URL"]
    link = base_url + ("&" if "?" in base_url else "?") + urlencode({"token": token})

    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = "Verify your SD Lab Rats email"
    message.set_content(
        "Thanks for registering for SD Lab Rats. Verify your email using this link "
        f"(valid for 24 hours):\n\n{link}\n\nIf you did not register, ignore this message."
    )
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(message)


class Register(Resource):
    def post(self):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return {"message": "Send a JSON object."}, 400

        # Only a Google-verified school account can register.
        google_token = data.get("google_id_token")
        if not isinstance(google_token, str) or len(google_token) > 10000:
            return {"message": "Google school-email verification is required."}, 403

        verified_email = verified_student_email(google_token)
        if not verified_email:
            return {
                "message": "Sign in with a verified @stu.powayusd.com Google account."
            }, 403

        submitted_email = data.get("email")
        if (
            not isinstance(submitted_email, str)
            or submitted_email.strip().lower() != verified_email
        ):
            return {"message": "Email must match your verified Google account."}, 400

        # Never accept public role or activation choices.
        safe_data = {
            key: data.get(key)
            for key in ("name", "uid", "password")
        }
        cleaned, errors = validate_account(safe_data, creating=True)

        if errors:
            return {
                "message": "Some fields need attention.",
                "errors": errors,
            }, 400

        uid = cleaned["uid"]

        if User.query.filter(func.lower(User._uid) == uid.lower()).first():
            return {"message": "Username is unavailable."}, 409

        if User.query.filter(
            func.lower(User._email) == verified_email
        ).first():
            return {"message": "Email is already registered."}, 409

        account = User(
            name=cleaned["name"],
            uid=uid,
            password=cleaned["password"],
            role="User",
        )
        account.email = verified_email
        account.active = True
        account.last_verified = datetime.utcnow()

        try:
            db.session.add(account)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {"message": "Username or email is unavailable."}, 409

        return {
            "message": "Student account created. You can now sign in."
        }, 201


class VerifyEmail(Resource):
    def post(self):
        data = request.get_json(silent=True)
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or len(token) > 256 or not token:
            return {"message": "A verification token is required."}, 400
        entry = EmailVerificationToken.query.filter_by(token_hash=_digest(token)).first()
        if not entry or entry.used_at or entry.expires_at <= datetime.utcnow():
            return {"message": "Invalid or expired verification link."}, 400
        account = db.session.get(User, entry.user_id)
        if account is None:
            return {"message": "Invalid verification link."}, 400
        entry.used_at = datetime.utcnow()
        account.active = True
        account.last_verified = datetime.utcnow()
        db.session.commit()
        return {"message": "Email verified. You can now sign in."}, 200


api.add_resource(Register, "/register")
api.add_resource(VerifyEmail, "/verify-email")

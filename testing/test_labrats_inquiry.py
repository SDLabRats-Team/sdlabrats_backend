""" Tests for the San Diego LabRats inquiry rules and API.

Run from the project root:  python -m unittest testing/test_labrats_inquiry.py

The API tests use the development SQLite database and delete every row they create.
"""
import os
import sys
import logging
import smtplib
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app, db  # noqa: E402  (path setup must run first)
from model.labrats_inquiry import LabRatsInquiry, validate_inquiry, initLabRatsInquiries  # noqa: E402
from model.labrats_notify import build_notification, notify_staff  # noqa: E402
from model.labrats_site import initLabRatsSite  # noqa: E402

CONTACT = {
    "form": "contact", "first_name": "Ana", "last_name": "Lopez",
    "email": "ana@example.com", "interest": "afterschool", "message": "Do you have Monday classes?",
}

SCHOLARSHIP = {
    "form": "scholarship",
    "student_first_name": "Leo", "student_last_name": "Lopez", "student_grade": "3", "student_school": "Park Elementary",
    "programs": ["afterschool", "winter-camps"], "income_under_limit": "no", "military_family": "yes",
    "parent_first_name": "Ana", "parent_last_name": "Lopez", "email": "ana@example.com", "phone": "(760) 555-0100",
}


class ValidateInquiryTests(unittest.TestCase):
    # Program and scholarship choices come from the website tables, so validation needs the app.
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            initLabRatsSite()

    def setUp(self):
        context = app.app_context()
        context.push()
        self.addCleanup(context.pop)

    def test_complete_contact_form_is_valid(self):
        cleaned, errors = validate_inquiry(dict(CONTACT))
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["interest"], "afterschool")

    def test_missing_required_fields_are_reported_by_name(self):
        _, errors = validate_inquiry({"form": "newsletter", "email": "ana@example.com"})
        self.assertEqual(set(errors), {"first_name", "last_name"})

    def test_bad_email_is_rejected(self):
        _, errors = validate_inquiry({**CONTACT, "email": "not-an-email"})
        self.assertIn("email", errors)

    def test_interest_must_be_a_catalog_program(self):
        _, errors = validate_inquiry({**CONTACT, "interest": "rocketry"})
        self.assertIn("interest", errors)

    def test_military_family_qualifies_for_scholarship(self):
        _, errors = validate_inquiry(dict(SCHOLARSHIP))
        self.assertEqual(errors, {})

    def test_scholarship_needs_income_or_military_yes(self):
        _, errors = validate_inquiry({**SCHOLARSHIP, "military_family": "no"})
        self.assertIn("eligibility", errors)

    def test_scholarship_needs_a_program_and_valid_phone(self):
        _, errors = validate_inquiry({**SCHOLARSHIP, "programs": ["pottery"], "phone": "555"})
        self.assertIn("programs", errors)
        self.assertIn("phone", errors)

    def test_unknown_form_is_a_client_error(self):
        with self.assertRaises(ValueError):
            validate_inquiry({"form": "pottery_class"})

    def test_survey_needs_one_answer_and_the_name_is_optional(self):
        _, errors = validate_inquiry({"form": "survey", "name": "Ana"})
        self.assertEqual(set(errors), {"liked"})
        cleaned, errors = validate_inquiry({"form": "survey", "improvements": "  Bigger buttons  "})
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["improvements"], "Bigger buttons")
        self.assertNotIn("name", cleaned)

    def test_long_text_is_truncated(self):
        cleaned, _ = validate_inquiry({**CONTACT, "message": "x" * 5000})
        self.assertEqual(len(cleaned["message"]), 2000)


class InquiryApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created = []
        with app.app_context():
            initLabRatsInquiries()

    def tearDown(self):
        with app.app_context():
            for inquiry_id in self.created:
                inquiry = db.session.get(LabRatsInquiry, inquiry_id)
                if inquiry:
                    db.session.delete(inquiry)
            db.session.commit()

    def test_valid_scholarship_is_stored_with_parent_as_contact(self):
        response = self.client.post("/api/labrats/inquiries", json=SCHOLARSHIP)
        self.assertEqual(response.status_code, 201)
        self.created.append(response.get_json()["id"])
        with app.app_context():
            stored = db.session.get(LabRatsInquiry, self.created[0]).read()
        self.assertEqual(stored["first_name"], "Ana")
        self.assertEqual(stored["details"]["student_first_name"], "Leo")
        self.assertEqual(stored["details"]["programs"], ["afterschool", "winter-camps"])
        self.assertEqual(stored["status"], "new")

    def test_invalid_submission_returns_field_errors(self):
        response = self.client.post("/api/labrats/inquiries", json={"form": "contact", "email": "bad"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("first_name", response.get_json()["errors"])

    def test_honeypot_submission_is_accepted_but_not_stored(self):
        with app.app_context():
            before = LabRatsInquiry.query.count()
        response = self.client.post("/api/labrats/inquiries", json={**CONTACT, "website": "http://spam.example"})
        self.assertEqual(response.status_code, 201)
        with app.app_context():
            self.assertEqual(LabRatsInquiry.query.count(), before)

    def test_anonymous_survey_is_stored_and_listed_for_admins(self):
        response = self.client.post("/api/labrats/inquiries", json={
            "form": "survey", "name": "", "liked": "Easy to find camps", "improvements": "Add photos of the lab",
        })
        self.assertEqual(response.status_code, 201)
        self.created.append(response.get_json()["id"])
        admin = app.test_client()
        signed_in = admin.post("/api/authenticate", json={"uid": app.config["ADMIN_UID"], "password": app.config["ADMIN_PASSWORD"]})
        if signed_in.status_code != 200:
            self.skipTest("Default admin account missing; run scripts/db_init.py first")
        listed = admin.get("/api/labrats/inquiries?form=survey").get_json()
        mine = next(item for item in listed if item["id"] == self.created[-1])
        self.assertEqual((mine["first_name"], mine["email"]), ("Anonymous", ""))
        self.assertEqual(mine["details"], {"liked": "Easy to find camps", "improvements": "Add photos of the lab"})

    def test_empty_survey_is_refused(self):
        response = self.client.post("/api/labrats/inquiries", json={"form": "survey", "name": "Ana"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("liked", response.get_json()["errors"])

    def test_listing_requires_authentication(self):
        response = self.client.get("/api/labrats/inquiries")
        self.assertEqual(response.status_code, 401)

    def test_programs_catalog_lists_contact_interests(self):
        response = self.client.get("/api/programs/")
        slugs = {program["slug"] for program in response.get_json()}
        self.assertEqual(slugs, {"afterschool", "camps", "assemblies", "stem-at-home", "courses-workshops"})


STORED = {
    "id": 7, "form": "scholarship", "first_name": "Ana", "last_name": "Lopez", "email": "ana@example.com",
    "phone": "(760) 555-0100", "created_at": "2026-10-06T18:00:00",
    "details": {"student_first_name": "Leo", "programs": ["afterschool", "winter-camps"]},
}
SMTP_CONFIG = {"LABRATS_NOTIFY_TO": "staff@example.org, ed@example.org", "SMTP_HOST": "smtp.example.org",
               "SMTP_USER": "site@example.org", "SMTP_PASSWORD": "secret"}
LOGGER = logging.getLogger("labrats-test")


class NotifyStaffTests(unittest.TestCase):
    def test_message_lists_answers_and_replies_to_the_family(self):
        message = build_notification(STORED, "site@example.org", ["staff@example.org"])
        self.assertIn("Scholarship application from Ana Lopez", message["Subject"])
        self.assertEqual(message["Reply-To"], "ana@example.com")
        body = message.get_content()
        self.assertIn("Programs: afterschool, winter-camps", body)
        self.assertIn("Phone: (760) 555-0100", body)

    def test_survey_message_has_no_reply_to(self):
        survey = {"id": 8, "form": "survey", "first_name": "Anonymous", "last_name": "", "email": "", "phone": None,
                  "created_at": "2026-10-26T18:00:00", "details": {"liked": "Clear menus"}}
        message = build_notification(survey, "site@example.org", ["staff@example.org"])
        self.assertEqual(message["Subject"], "[sdlabrats.org] Website survey from Anonymous")
        self.assertIsNone(message["Reply-To"])
        self.assertIn("Liked: Clear menus", message.get_content())
        self.assertNotIn("Email:", message.get_content())

    def test_skips_quietly_when_not_configured(self):
        with mock.patch("smtplib.SMTP") as smtp:
            self.assertFalse(notify_staff(STORED, {}, LOGGER))
        smtp.assert_not_called()

    def test_sends_to_every_configured_address(self):
        with mock.patch("smtplib.SMTP") as smtp:
            self.assertTrue(notify_staff(STORED, SMTP_CONFIG, LOGGER))
        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with("site@example.org", "secret")
        sent = server.send_message.call_args[0][0]
        self.assertEqual(sent["To"], "staff@example.org, ed@example.org")

    def test_failed_send_still_stores_the_inquiry(self):
        client = app.test_client()
        with app.app_context():
            initLabRatsInquiries()
        with mock.patch.dict(app.config, SMTP_CONFIG), \
                mock.patch("smtplib.SMTP", side_effect=smtplib.SMTPConnectError(421, "down")):
            response = client.post("/api/labrats/inquiries", json=CONTACT)
        self.assertEqual(response.status_code, 201)
        with app.app_context():
            inquiry = db.session.get(LabRatsInquiry, response.get_json()["id"])
            self.assertIsNotNone(inquiry)
            db.session.delete(inquiry)
            db.session.commit()


if __name__ == "__main__":
    unittest.main()

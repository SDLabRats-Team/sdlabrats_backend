""" Tests for the LabRats website content API (the frontend keeps no data of its own).

Run from the project root:  python -m unittest testing/test_labrats_site.py

Uses the development database. initLabRatsSite() only fills empty tables, and every test that
changes a session or the announcement puts it back.
"""
import os
import re
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app, db  # noqa: E402  (path setup must run first)
from model.labrats_site import (  # noqa: E402
    LabRatsPage, LabRatsSession, initLabRatsSite, normalize_path, validate_session_update, validate_announcement,
)


class ContentRuleTests(unittest.TestCase):
    def test_paths_are_normalized_and_unsafe_ones_refused(self):
        self.assertEqual(normalize_path("/camps/index.html"), "/camps/")
        self.assertEqual(normalize_path("/camps/"), "/camps/")
        for unsafe in ("camps", "/../etc/passwd", "/<script>", None, "https://evil.example/"):
            self.assertIsNone(normalize_path(unsafe), unsafe)

    def test_session_changes_are_checked(self):
        _, errors = validate_session_update({"status": "maybe", "term": "", "donorbox_campaign": "abc", "schedule_order": -1})
        self.assertEqual(set(errors), {"status", "term", "donorbox_campaign", "schedule_order"})
        cleaned, errors = validate_session_update({"status": "open", "times": [{"day": "Fridays", "time": "4-6 pm", "dates": "Nov 6"}]})
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["times"][0]["day"], "Fridays")
        self.assertIn("times", validate_session_update({"times": [{"day": "x", "room": "y"}]})[1])

    def test_announcement_needs_text_and_an_on_site_link(self):
        self.assertIn("text", validate_announcement({"show": True, "text": ""})[1])
        self.assertIn("url", validate_announcement({"show": True, "text": "Camps open", "link_text": "Dates", "url": "https://evil.example"})[1])
        cleaned, errors = validate_announcement({"show": False})
        self.assertEqual((cleaned["show"], errors), (False, {}))


class PageApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            initLabRatsSite()
        cls.client = app.test_client()

    def bundle(self, path):
        response = self.client.get("/api/labrats/page", query_string={"path": path})
        self.assertEqual(response.status_code, 200, path)
        return response.get_json()

    def test_every_page_has_a_template_and_title(self):
        with app.app_context():
            pages = LabRatsPage.query.all()
        self.assertGreaterEqual(len(pages), 90)
        templates = {"home", "program", "registration", "archive", "redirect", "default"}
        for page in pages:
            self.assertIn(page.template, templates, page.path)
            self.assertTrue(page.title, page.path)
            self.assertNotRegex(page.body, r"\{[{%]", f"{page.path} still has Liquid")

    def test_home_bundle_carries_the_site_and_catalog(self):
        bundle = self.bundle("/")
        self.assertEqual(bundle["page"]["template"], "home")
        self.assertEqual(bundle["site"]["org"]["phone"], "(760) 450-4717")
        self.assertEqual([section["id"] for section in bundle["site"]["sections"]], ["programs", "schedule", "about", "give"])
        self.assertIn("afterschool", [program["slug"] for program in bundle["programs"]])

    def test_registration_page_includes_its_session(self):
        bundle = self.bundle("/fall-camp-k-3/")
        self.assertEqual(bundle["page"]["template"], "registration")
        self.assertEqual(bundle["session"]["program"], "camps")
        self.assertTrue(bundle["session"]["times"])

    def test_redirects_and_short_paths_resolve(self):
        self.assertEqual(self.bundle("/ways-to-donate/")["page"]["redirect_to"], "/contact/#donate")
        self.assertEqual(self.bundle("/camps")["page"]["path"], "/camps/")

    def test_survey_page_and_home_invite_are_seeded(self):
        bundle = self.bundle("/survey/")
        self.assertIn('data-labrats-form-slot="survey"', bundle["page"]["body"])
        self.assertIn('href="/survey/"', bundle["site"]["blocks"]["survey_invite"])

    def test_reseeding_adds_new_content_without_overwriting_edits(self):
        with app.app_context():
            from model.labrats_site import LabRatsSetting
            blocks = db.session.get(LabRatsSetting, "blocks")
            original = dict(blocks.value)
            try:
                edited = {key: value for key, value in original.items() if key != "survey_invite"}
                edited["questions"] = "<p>Edited by staff</p>"
                blocks.value = edited
                db.session.commit()
                initLabRatsSite()
                after = db.session.get(LabRatsSetting, "blocks").value
                self.assertEqual(after["questions"], "<p>Edited by staff</p>")
                self.assertIn("survey_invite", after)
            finally:
                db.session.get(LabRatsSetting, "blocks").value = original
                db.session.commit()

    def test_enroll_page_lists_open_sessions(self):
        bundle = self.bundle("/enroll/")
        self.assertEqual(bundle["page"]["heading"], "Enroll in a class or camp")
        for program in ("afterschool", "camps", "event"):
            self.assertIn(f'data-program="{program}"', bundle["page"]["body"])
        self.assertTrue(any(session["status"] == "open" for session in bundle["sessions"]))

    def test_unknown_page_is_404(self):
        self.assertEqual(self.client.get("/api/labrats/page", query_string={"path": "/no-such-page/"}).status_code, 404)

    def test_every_internal_link_points_at_a_page(self):
        with app.app_context():
            pages = LabRatsPage.query.all()
            known = {page.path for page in pages}
        assets = ("/images/", "/assets/")
        for page in pages:
            targets = re.findall(r'href="(/[^"#]*)', page.body) + [page.read().get("redirect_to", "").split("#")[0]]
            for target in filter(None, targets):
                if not target.startswith(assets):
                    self.assertIn(target, known, f"{page.path} links to {target}")

    def test_every_session_has_its_registration_page(self):
        with app.app_context():
            pages = {page.path: page.template for page in LabRatsPage.query.all()}
            for session in LabRatsSession.query.all():
                self.assertEqual(pages.get(session.path), "registration", session.path)


class AdminContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            initLabRatsSite()
        cls.admin = app.test_client()
        response = cls.admin.post("/api/authenticate", json={
            "uid": app.config["ADMIN_UID"], "password": app.config["ADMIN_PASSWORD"],
        })
        if response.status_code != 200:
            raise unittest.SkipTest("Default admin account missing; run scripts/db_init.py first")

    def test_closing_a_session_takes_it_off_the_open_list(self):
        sessions = self.admin.get("/api/labrats/sessions").get_json()
        target = next(session for session in sessions if session["status"] == "open")
        try:
            closed = self.admin.put(f"/api/labrats/sessions/{target['id']}", json={"status": "closed"})
            self.assertEqual(closed.get_json()["status"], "closed")
            bundle = app.test_client().get("/api/labrats/page", query_string={"path": target["path"]}).get_json()
            self.assertEqual(bundle["session"]["status"], "closed")
        finally:
            self.admin.put(f"/api/labrats/sessions/{target['id']}", json={"status": "open"})

    def test_bad_session_change_is_refused(self):
        target = self.admin.get("/api/labrats/sessions").get_json()[0]
        response = self.admin.put(f"/api/labrats/sessions/{target['id']}", json={"status": "maybe"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.get_json()["errors"])

    def test_announcement_edit_gets_a_new_id_and_shows_on_pages(self):
        before = self.admin.get("/api/labrats/announcement").get_json()
        try:
            saved = self.admin.put("/api/labrats/announcement", json={
                "show": True, "text": "Spring camps are open.", "link_text": "See dates", "url": "/spring-break-camps/",
            }).get_json()
            self.assertNotEqual(saved["id"], before.get("id"))
            bundle = app.test_client().get("/api/labrats/page", query_string={"path": "/"}).get_json()
            self.assertEqual(bundle["site"]["announcement"]["text"], "Spring camps are open.")
        finally:
            with app.app_context():
                from model.labrats_site import set_setting
                set_setting("announcement", before)

    def test_visitors_cannot_edit_content(self):
        visitor = app.test_client()
        self.assertEqual(visitor.get("/api/labrats/sessions").status_code, 401)
        self.assertEqual(visitor.put("/api/labrats/announcement", json={"show": False}).status_code, 401)


if __name__ == "__main__":
    unittest.main()

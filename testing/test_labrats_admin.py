""" Tests for LabRats admin account control, assignments, and turn-ins.

Run from the project root:  python -m unittest testing/test_labrats_admin.py

The API tests sign in as the default admin account (ADMIN_UID / ADMIN_PASSWORD from __init__.py),
so run scripts/db_init.py first. They use the development database and delete what they create.
"""
import os
import sys
import unittest
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app, db  # noqa: E402  (path setup must run first)
from model.user import User  # noqa: E402
from model.labrats_accounts import validate_account  # noqa: E402
from model.labrats_assignment import (  # noqa: E402
    LabRatsAssignment, validate_assignment, validate_turnin, validate_review, initLabRatsAssignments,
)


class AccountRuleTests(unittest.TestCase):
    def test_new_account_needs_name_username_password(self):
        _, errors = validate_account({}, creating=True)
        self.assertEqual(set(errors), {"name", "uid", "password"})

    def test_username_characters_and_role_are_checked(self):
        _, errors = validate_account({"name": "Ana", "uid": "ana lopez", "password": "longenough", "role": "Owner"}, creating=True)
        self.assertEqual(set(errors), {"uid", "role"})

    def test_update_accepts_a_single_field(self):
        cleaned, errors = validate_account({"role": "Teacher"}, creating=False)
        self.assertEqual((cleaned, errors), ({"role": "Teacher"}, {}))

    def test_short_password_rejected_on_reset(self):
        _, errors = validate_account({"password": "short"}, creating=False)
        self.assertIn("password", errors)

    def test_active_must_be_true_or_false(self):
        self.assertIn("active", validate_account({"active": "yes"}, creating=False)[1])
        self.assertEqual(validate_account({"active": False}, creating=False), ({"active": False}, {}))


class AssignmentRuleTests(unittest.TestCase):
    def test_assignment_needs_title_and_instructions(self):
        _, errors = validate_assignment({})
        self.assertEqual(set(errors), {"title", "instructions"})

    def test_due_date_must_be_iso(self):
        _, errors = validate_assignment({"title": "Crystals", "instructions": "Grow one", "due_date": "10/31"})
        self.assertIn("due_date", errors)

    def test_partial_update_can_just_close(self):
        cleaned, errors = validate_assignment({"is_open": False}, partial=True)
        self.assertEqual((cleaned, errors), ({"is_open": False}, {}))

    def test_turnin_needs_response_or_link(self):
        self.assertIn("response", validate_turnin({})[1])
        self.assertEqual(validate_turnin({"link": "https://example.com/photo"})[1], {})
        self.assertIn("link", validate_turnin({"response": "Done", "link": "javascript:alert(1)"})[1])

    def test_review_status_is_checked(self):
        self.assertIn("status", validate_review({"status": "graded"})[1])


class AdminApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            initLabRatsAssignments()
        cls.admin = app.test_client()
        response = cls.admin.post("/api/authenticate", json={
            "uid": app.config["ADMIN_UID"], "password": app.config["ADMIN_PASSWORD"],
        })
        if response.status_code != 200:
            raise unittest.SkipTest("Default admin account missing; run scripts/db_init.py first")

    def setUp(self):
        self.suffix = uuid.uuid4().hex[:8]
        self.users = []
        self.assignments = []

    def tearDown(self):
        for uid in self.users:
            self.admin.delete(f"/api/labrats/users/{uid}")
        with app.app_context():
            for assignment_id in self.assignments:
                assignment = db.session.get(LabRatsAssignment, assignment_id)
                if assignment:
                    assignment.delete()

    def make_student(self):
        uid = f"student-{self.suffix}"
        response = self.admin.post("/api/labrats/users", json={
            "name": "Test Student", "uid": uid, "password": "labrats-test-1", "role": "User",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.users.append(uid)
        student = app.test_client()
        self.assertEqual(student.post("/api/authenticate", json={"uid": uid, "password": "labrats-test-1"}).status_code, 200)
        return uid, student

    def make_assignment(self, **extra):
        response = self.admin.post("/api/labrats/assignments", json={
            "title": f"Grow a crystal {self.suffix}", "instructions": "Follow the crystal lab and describe what grew.",
            "due_date": "2026-10-31", **extra,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assignments.append(response.get_json()["id"])
        return response.get_json()

    def test_admin_creates_updates_and_deletes_an_account(self):
        uid, _ = self.make_student()
        listed = self.admin.get(f"/api/labrats/users?q={uid}").get_json()
        self.assertEqual([user["uid"] for user in listed], [uid])
        self.assertNotIn("password", listed[0])

        updated = self.admin.put(f"/api/labrats/users/{uid}", json={"role": "Teacher", "email": "t@example.com"})
        self.assertEqual(updated.get_json()["role"], "Teacher")

        reset = self.admin.put(f"/api/labrats/users/{uid}", json={"password": "a-new-password"})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(app.test_client().post("/api/authenticate", json={"uid": uid, "password": "a-new-password"}).status_code, 200)

        self.assertEqual(self.admin.delete(f"/api/labrats/users/{uid}").status_code, 200)
        self.users.remove(uid)
        with app.app_context():
            self.assertIsNone(User.query.filter_by(_uid=uid).first())

    def test_accounts_admins_create_can_sign_in(self):
        uid, student = self.make_student()
        self.assertTrue(self.admin.get(f"/api/labrats/users?q={uid}").get_json()[0]["active"])
        self.assertEqual(student.get("/api/id").get_json()["uid"], uid)

    def test_inactive_accounts_wait_until_an_admin_activates_them(self):
        uid, student = self.make_student()
        self.assertFalse(self.admin.put(f"/api/labrats/users/{uid}", json={"active": False}).get_json()["active"])
        # Upstream Flask still issues the cookie, then refuses the inactive account.
        self.assertEqual(student.get("/api/id").status_code, 403)
        self.assertEqual(student.get("/api/labrats/assignments").status_code, 403)

        self.assertTrue(self.admin.put(f"/api/labrats/users/{uid}", json={"active": True}).get_json()["active"])
        self.assertEqual(student.get("/api/id").status_code, 200)

    def test_duplicate_username_is_rejected(self):
        uid, _ = self.make_student()
        response = self.admin.post("/api/labrats/users", json={"name": "Again", "uid": uid, "password": "labrats-test-1"})
        self.assertEqual(response.status_code, 409)

    def test_admin_cannot_lock_themselves_out(self):
        me = app.config["ADMIN_UID"]
        self.assertEqual(self.admin.put(f"/api/labrats/users/{me}", json={"role": "User"}).status_code, 400)
        self.assertEqual(self.admin.put(f"/api/labrats/users/{me}", json={"active": False}).status_code, 400)
        self.assertEqual(self.admin.delete(f"/api/labrats/users/{me}").status_code, 400)

    def test_students_cannot_use_admin_endpoints(self):
        _, student = self.make_student()
        self.assertEqual(student.get("/api/labrats/users").status_code, 403)
        self.assertEqual(student.post("/api/labrats/assignments", json={"title": "x", "instructions": "y"}).status_code, 403)
        self.assertEqual(student.get("/api/labrats/inquiries").status_code, 403)
        self.assertEqual(app.test_client().get("/api/labrats/assignments").status_code, 401)

    def test_turn_in_review_and_feedback_round_trip(self):
        _, student = self.make_student()
        assignment = self.make_assignment()

        visible = student.get("/api/labrats/assignments").get_json()
        mine = next(item for item in visible if item["id"] == assignment["id"])
        self.assertIsNone(mine["my_turnin"])

        turned_in = student.put(f"/api/labrats/assignments/{assignment['id']}/turnin",
                                json={"response": "Blue crystals grew on the string.", "link": "https://example.com/p.jpg"})
        self.assertEqual(turned_in.status_code, 200)

        turnins = self.admin.get(f"/api/labrats/assignments/{assignment['id']}/turnins").get_json()
        self.assertEqual(len(turnins), 1)
        self.assertEqual(turnins[0]["student"]["name"], "Test Student")

        reviewed = self.admin.put(f"/api/labrats/turnins/{turnins[0]['id']}", json={"feedback": "Great notes!", "status": "reviewed"})
        self.assertEqual(reviewed.get_json()["status"], "reviewed")

        mine = next(item for item in student.get("/api/labrats/assignments").get_json() if item["id"] == assignment["id"])
        self.assertEqual(mine["my_turnin"]["feedback"], "Great notes!")

        # Turning in again replaces the work and puts it back in the review queue.
        student.put(f"/api/labrats/assignments/{assignment['id']}/turnin", json={"response": "Second try."})
        again = self.admin.get(f"/api/labrats/assignments/{assignment['id']}/turnins").get_json()
        self.assertEqual((len(again), again[0]["status"], again[0]["response"]), (1, "submitted", "Second try."))

    def test_closed_assignment_rejects_turn_ins_and_hides_from_students(self):
        _, student = self.make_student()
        assignment = self.make_assignment()
        self.admin.put(f"/api/labrats/assignments/{assignment['id']}", json={"is_open": False})
        response = student.put(f"/api/labrats/assignments/{assignment['id']}/turnin", json={"response": "Late"})
        self.assertEqual(response.status_code, 409)
        ids = [item["id"] for item in student.get("/api/labrats/assignments").get_json()]
        self.assertNotIn(assignment["id"], ids)

    def test_deleting_a_student_removes_their_turn_ins(self):
        uid, student = self.make_student()
        assignment = self.make_assignment()
        student.put(f"/api/labrats/assignments/{assignment['id']}/turnin", json={"response": "Done"})
        self.assertEqual(self.admin.delete(f"/api/labrats/users/{uid}").status_code, 200)
        self.users.remove(uid)
        self.assertEqual(self.admin.get(f"/api/labrats/assignments/{assignment['id']}/turnins").get_json(), [])


if __name__ == "__main__":
    unittest.main()

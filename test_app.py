"""Smoke tests for the CampusQuest MVP. Run with: py -m unittest discover -s tests"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
TEMP_DB = tempfile.TemporaryDirectory(prefix="campusquest-tests-")
os.environ["DATABASE_PATH"] = str(Path(TEMP_DB.name) / "test.db")
os.environ["SECRET_KEY"] = "test-only-secret-key-not-for-production"
os.environ["APP_ENV"] = "test"
os.environ["ENABLE_DEMO_LOGIN"] = "0"
sys.path.insert(0, str(PROJECT_DIR))

import app as app_module  # noqa: E402
from app import app  # noqa: E402


class CampusQuestSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    def setUp(self):
        self.client = app.test_client()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)"', response.data)
        self.assertIsNotNone(match, "The landing page must include a CSRF token meta tag.")
        self.csrf = match.group(1).decode()

    def post_json(self, path: str, payload: dict, csrf: str | None = None):
        return self.client.post(
            path,
            json=payload,
            headers={"X-CSRF-Token": csrf or self.csrf},
        )

    def register(self, name="Test Student", email=None):
        email = email or f"student-{id(self)}@example.test"
        response = self.post_json("/api/auth/register", {
            "name": name,
            "email": email,
            "password": "student-test-password-123",
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return email

    def test_health_and_landing_page(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        response = self.client.get("/")
        self.assertIn(b"themeToggle", response.data)
        self.assertIn(b"csrf-token", response.data)

    def test_state_changing_request_requires_csrf(self):
        response = self.client.post("/api/auth/demo", json={})
        self.assertEqual(response.status_code, 400)

    def test_demo_endpoint_is_disabled_when_demo_login_is_off(self):
        response = self.post_json("/api/auth/demo", {})
        self.assertEqual(response.status_code, 404)

    def test_register_and_login(self):
        email = self.register(email="register-login@example.test")
        self.post_json("/api/auth/logout", {})
        response = self.post_json("/api/auth/login", {
            "email": email,
            "password": "student-test-password-123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["role"], "student")

    def test_same_day_checkin_cannot_be_duplicated(self):
        self.register(email="checkin@example.test")
        challenges = self.client.get("/api/challenges").get_json()["challenges"]
        challenge_id = challenges[0]["id"]
        joined = self.post_json(f"/api/challenges/{challenge_id}/join", {})
        self.assertEqual(joined.status_code, 200)
        first = self.post_json(f"/api/challenges/{challenge_id}/checkin", {"note": "Worked on today's step."})
        second = self.post_json(f"/api/challenges/{challenge_id}/checkin", {"note": "Trying to repeat it."})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_new_community_challenge_waits_for_moderation(self):
        self.register(email="creator@example.test")
        title = "A small community quest"
        response = self.post_json("/api/challenges/create", {
            "title": title,
            "category": "Creative",
            "duration_days": 3,
            "description": "Make and share a small creative thing with classmates.",
        })
        self.assertEqual(response.status_code, 200)
        public_titles = [item["title"] for item in self.client.get("/api/challenges").get_json()["challenges"]]
        self.assertNotIn(title, public_titles)
        denied = self.client.get("/api/admin/pending-challenges")
        self.assertEqual(denied.status_code, 403)


    def test_activity_catalog_has_multiple_categories_and_activity_types(self):
        response = self.client.get("/api/challenges")
        self.assertEqual(response.status_code, 200)
        challenges = response.get_json()["challenges"]
        categories = {item["category"] for item in challenges}
        activity_types = {item["activity_type"] for item in challenges}
        self.assertGreaterEqual(len(categories), 8)
        self.assertIn("Sports", categories)
        self.assertIn("Career", categories)
        self.assertIn("Sustainability", categories)
        self.assertIn("Friendly competition", activity_types)
        self.assertIn("Peer learning", activity_types)

    def test_student_can_propose_new_activity_type(self):
        self.register(email="activity-creator@example.test")
        response = self.post_json("/api/challenges/create", {
            "title": "A tiny campus design jam",
            "category": "Creative",
            "activity_type": "Creative jam",
            "duration_days": 3,
            "description": "Create a small poster with another student and share your process.",
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        with app_module.get_db() as db:
            row = db.execute("SELECT category, activity_type, status FROM challenges WHERE title=?", ("A tiny campus design jam",)).fetchone()
        self.assertEqual(row["activity_type"], "Creative jam")
        self.assertEqual(row["status"], "pending")

    def test_weekly_quest_returns_a_seeded_approved_challenge(self):
        response = self.client.get("/api/weekly-quest")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["challenge"]["title"])
        self.assertIn("week", payload)

    def test_final_work_requires_review_before_completion_badge(self):
        self.register(email="final-review@example.test")
        challenge = self.client.get("/api/challenges").get_json()["challenges"][0]
        challenge_id = challenge["id"]
        duration = challenge["duration_days"]
        joined = self.post_json(f"/api/challenges/{challenge_id}/join", {})
        self.assertEqual(joined.status_code, 200)

        first_day = date(2026, 2, 1)
        for offset in range(duration):
            with patch.object(app_module, "app_today", return_value=first_day + timedelta(days=offset)):
                checked = self.post_json(
                    f"/api/challenges/{challenge_id}/checkin",
                    {"note": f"Worked on step {offset + 1}."},
                )
            self.assertEqual(checked.status_code, 200, checked.get_data(as_text=True))
        self.assertEqual(checked.get_json()["status"], "ready_to_submit")

        submitted = self.post_json(f"/api/challenges/{challenge_id}/submit", {
            "note": "I completed the quest and documented what I learned.",
            "proof_url": "https://example.com/my-work",
        })
        self.assertEqual(submitted.status_code, 200, submitted.get_data(as_text=True))
        quest_status = self.client.get("/api/my-quests").get_json()["quests"][0]["status"]
        self.assertEqual(quest_status, "submitted")

        # Use a separate moderator account so self-review is impossible.
        moderator_client = app.test_client()
        page = moderator_client.get("/")
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)"', page.data)
        moderator_csrf = match.group(1).decode()
        registered = moderator_client.post("/api/auth/register", json={
            "name": "Moderator", "email": "reviewer@example.test", "password": "moderator-test-password-123"
        }, headers={"X-CSRF-Token": moderator_csrf})
        self.assertEqual(registered.status_code, 200)
        with app_module.get_db() as db:
            db.execute("UPDATE users SET role='admin' WHERE email='reviewer@example.test'")
        moderator_client.post("/api/auth/logout", json={}, headers={"X-CSRF-Token": moderator_csrf})
        moderator_client.post("/api/auth/login", json={
            "email": "reviewer@example.test", "password": "moderator-test-password-123"
        }, headers={"X-CSRF-Token": moderator_csrf})
        pending = moderator_client.get("/api/admin/pending-submissions")
        self.assertEqual(pending.status_code, 200)
        submission_id = pending.get_json()["submissions"][0]["id"]
        changes = moderator_client.post(f"/api/admin/submissions/{submission_id}/review", json={
            "action": "needs_changes", "feedback": "Please add one clearer example of what you built."
        }, headers={"X-CSRF-Token": moderator_csrf})
        self.assertEqual(changes.status_code, 200, changes.get_data(as_text=True))
        final_quest = self.client.get("/api/my-quests").get_json()["quests"][0]
        self.assertEqual(final_quest["status"], "ready_to_submit")
        self.assertIn("Please add one clearer example", final_quest["final_review_feedback"])

        resubmitted = self.post_json(f"/api/challenges/{challenge_id}/submit", {
            "note": "I added an example and clarified the final outcome for review.",
            "proof_url": "https://example.com/my-improved-work",
        })
        self.assertEqual(resubmitted.status_code, 200, resubmitted.get_data(as_text=True))
        pending_again = moderator_client.get("/api/admin/pending-submissions").get_json()["submissions"]
        submission_id = pending_again[0]["id"]
        reviewed = moderator_client.post(f"/api/admin/submissions/{submission_id}/review", json={
            "action": "approve", "feedback": "Good work."
        }, headers={"X-CSRF-Token": moderator_csrf})
        self.assertEqual(reviewed.status_code, 200, reviewed.get_data(as_text=True))
        final_quest = self.client.get("/api/my-quests").get_json()["quests"][0]
        self.assertEqual(final_quest["status"], "completed")
        badges = self.client.get("/api/badges").get_json()["badges"]
        self.assertTrue(any(b["slug"] == "quest-finisher" and b["earned"] for b in badges))

    def test_report_can_only_be_submitted_once_per_student_per_quest(self):
        self.register(email="reporter@example.test")
        challenge = self.client.get("/api/challenges").get_json()["challenges"][0]
        route = f"/api/challenges/{challenge['id']}/report"
        first = self.post_json(route, {"reason": "spam", "details": "This looks like a duplicate."})
        second = self.post_json(route, {"reason": "spam", "details": "Repeated report."})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_team_join_requires_captain_approval(self):
        self.register(email="team-owner@example.test")
        challenges = self.client.get("/api/challenges").get_json()["challenges"]
        challenge = next(item for item in challenges if item["team_allowed"])
        challenge_id = challenge["id"]
        self.assertEqual(self.post_json(f"/api/challenges/{challenge_id}/join", {}).status_code, 200)
        created = self.post_json("/api/teams", {
            "name": "Quest Builders", "description": "A friendly test squad", "challenge_id": challenge_id
        })
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        team_id = created.get_json()["team_id"]

        member_client = app.test_client()
        page = member_client.get("/")
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)"', page.data)
        member_csrf = match.group(1).decode()
        member_client.post("/api/auth/register", json={
            "name": "Team Member", "email": "team-member@example.test", "password": "member-test-password-123"
        }, headers={"X-CSRF-Token": member_csrf})
        member_client.post(f"/api/challenges/{challenge_id}/join", json={}, headers={"X-CSRF-Token": member_csrf})
        request_response = member_client.post(f"/api/teams/{team_id}/join", json={}, headers={"X-CSRF-Token": member_csrf})
        self.assertEqual(request_response.status_code, 200, request_response.get_data(as_text=True))
        member_view = member_client.get(f"/api/teams/{team_id}").get_json()["team"]
        self.assertTrue(member_view["requested"])
        self.assertFalse(member_view["is_member"])

        owner_view = self.client.get(f"/api/teams/{team_id}").get_json()
        self.assertEqual(len(owner_view["requests"]), 1)
        request_id = owner_view["requests"][0]["id"]
        accepted = self.post_json(f"/api/team-requests/{request_id}/review", {"action": "accept"})
        self.assertEqual(accepted.status_code, 200, accepted.get_data(as_text=True))
        member_view = member_client.get(f"/api/teams/{team_id}").get_json()["team"]
        self.assertTrue(member_view["is_member"])
        self.assertFalse(member_view["requested"])

    def test_leaderboard_is_opt_in(self):
        self.register(name="Private Student", email="private@example.test")
        first = self.client.get("/api/leaderboard").get_json()["leaders"]
        self.assertNotIn("Private Student", [row["name"] for row in first])
        enabled = self.post_json("/api/privacy/leaderboard", {"show": True})
        self.assertEqual(enabled.status_code, 200)
        after = self.client.get("/api/leaderboard").get_json()["leaders"]
        self.assertIn("Private Student", [row["name"] for row in after])

    def test_hidden_report_closes_active_participation(self):
        self.register(email="report-admin@example.test")
        challenge = self.client.get("/api/challenges").get_json()["challenges"][0]
        challenge_id = challenge["id"]
        self.assertEqual(self.post_json(f"/api/challenges/{challenge_id}/join", {}).status_code, 200)
        report = self.post_json(f"/api/challenges/{challenge_id}/report", {
            "reason": "unsafe", "details": "This challenge needs a moderator review before more students join."
        })
        self.assertEqual(report.status_code, 200)
        with app_module.get_db() as db:
            db.execute("UPDATE users SET role='admin' WHERE email='report-admin@example.test'")
        reports = self.client.get("/api/admin/reports").get_json()["reports"]
        report_id = next(item["id"] for item in reports if item["challenge_title"] == challenge["title"])
        hidden = self.post_json(f"/api/admin/reports/{report_id}/review", {"action": "hide_challenge"})
        self.assertEqual(hidden.status_code, 200)
        quest = next(item for item in self.client.get("/api/my-quests").get_json()["quests"] if item["id"] == challenge_id)
        self.assertEqual(quest["status"], "challenge_closed")

    def test_student_profile_is_private_until_opted_in(self):
        self.register(email="profile-owner@example.test")
        me = self.client.get("/api/me").get_json()["user"]
        profile_id = me["id"]
        self.assertEqual(self.client.get(f"/api/profiles/{profile_id}").status_code, 200)
        other_client = app.test_client()
        page = other_client.get("/")
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)"', page.data)
        other_csrf = match.group(1).decode()
        other_client.post("/api/auth/register", json={
            "name": "Another Student", "email": "profile-viewer@example.test", "password": "viewer-test-password-123"
        }, headers={"X-CSRF-Token": other_csrf})
        self.assertEqual(other_client.get(f"/api/profiles/{profile_id}").status_code, 403)
        updated = self.post_json("/api/profile", {"department": "CSE", "study_year": "3rd Year", "profile_public": True})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(other_client.get(f"/api/profiles/{profile_id}").status_code, 200)


if __name__ == "__main__":
    unittest.main()

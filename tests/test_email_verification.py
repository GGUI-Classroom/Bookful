import hashlib
import hmac
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Teacher


class VerificationTestConfig:
    TESTING = True
    SECRET_KEY = "verification-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    PUBLIC_BASE_URL = "https://bookful.example"
    GMAIL_CLIENT_ID = "test-client"
    GMAIL_CLIENT_SECRET = "test-client-secret"
    GMAIL_REFRESH_TOKEN = "test-refresh-token"
    GMAIL_SENDER_EMAIL = "bookful.noreply@gmail.com"
    GMAIL_SENDER_NAME = "Bookful Reports"
    REPORT_ADMIN_EMAIL = "g.gui.cmpny@gmail.com"
    REPORT_JOB_SECRET = "scheduler-secret"


class EmailVerificationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(VerificationTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _login(self, teacher):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(teacher.id)
            session["_fresh"] = True

    def _digest(self, teacher_id, code):
        return hmac.new(
            VerificationTestConfig.SECRET_KEY.encode(),
            f"{teacher_id}:{code}".encode(),
            hashlib.sha256,
        ).hexdigest()

    @patch("app.auth.routes._issue_verification_code", return_value=(True, 0))
    def test_new_teacher_is_unverified_and_redirected_to_code_screen(self, mocked_issue):
        response = self.client.post(
            "/auth/signup",
            data={
                "username": "new-teacher",
                "email": "new@example.com",
                "password": "password123",
                "confirm_password": "password123",
            },
        )

        teacher = Teacher.query.filter_by(email="new@example.com").one()
        self.assertIsNone(teacher.email_verified_at)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/auth/verify-email"))
        mocked_issue.assert_called_once_with(teacher, enforce_cooldown=False)

    def test_unverified_teacher_is_forced_to_verification_screen(self):
        teacher = Teacher(username="pending", email="pending@example.com")
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.commit()
        self._login(teacher)

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/auth/verify-email"))

        verify_page = self.client.get("/auth/verify-email")
        self.assertEqual(verify_page.status_code, 200)
        self.assertIn(b"Make sure to check your junk or spam folder too", verify_page.data)
        self.assertIn(b'class="verification-stage"', verify_page.data)
        self.assertNotIn(b"<nav", verify_page.data)
        self.assertNotIn(b"app-nav", verify_page.data)

    def test_new_teacher_username_is_limited_to_fifteen_characters(self):
        response = self.client.post(
            "/auth/signup",
            data={
                "username": "sixteen-characters",
                "email": "longname@example.com",
                "password": "password123",
                "confirm_password": "password123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"15 characters", response.data)
        self.assertIsNone(Teacher.query.filter_by(email="longname@example.com").first())

    def test_correct_code_verifies_teacher(self):
        teacher = Teacher(
            username="pending",
            email="pending@example.com",
            email_verification_expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.flush()
        teacher.email_verification_code_hash = self._digest(teacher.id, "123456")
        db.session.commit()
        self._login(teacher)

        response = self.client.post("/auth/verify-email", data={"code": "123456"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))
        self.assertIsNotNone(teacher.email_verified_at)
        self.assertIsNone(teacher.email_verification_code_hash)

    def test_incorrect_code_counts_attempts(self):
        teacher = Teacher(
            username="pending",
            email="pending@example.com",
            email_verification_expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.flush()
        teacher.email_verification_code_hash = self._digest(teacher.id, "123456")
        db.session.commit()
        self._login(teacher)

        response = self.client.post("/auth/verify-email", data={"code": "000000"}, follow_redirects=True)

        self.assertIn(b"4 attempts remaining", response.data)
        self.assertEqual(teacher.email_verification_attempts, 1)
        self.assertIsNone(teacher.email_verified_at)

    @patch("app.reports.service.send_gmail_message", return_value="gmail-message-id")
    def test_verification_email_uses_gmail_sender_and_junk_folder_reminder(self, mocked_send):
        from app.reports.service import send_email_verification

        teacher = Teacher(username="pending", email="pending@example.com")
        with self.app.test_request_context("/"):
            message_id = send_email_verification(teacher, "654321")

        self.assertEqual(message_id, "gmail-message-id")
        recipient, subject, text_body, html_body = mocked_send.call_args.args
        self.assertEqual(recipient, "pending@example.com")
        self.assertIn("654321", subject)
        self.assertIn("junk or spam folder", text_body)
        self.assertIn("junk or spam folder", html_body)

    @patch("app.auth.routes.secrets.randbelow", return_value=123456)
    @patch("app.auth.routes.send_email_verification", return_value="gmail-message-id")
    def test_issued_code_is_hashed_and_resend_is_rate_limited(self, mocked_send, mocked_random):
        from app.auth.routes import _issue_verification_code

        teacher = Teacher(username="pending", email="pending@example.com")
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.commit()

        sent, retry_after = _issue_verification_code(teacher, enforce_cooldown=False)
        sent_again, retry_after_second = _issue_verification_code(teacher, enforce_cooldown=True)

        self.assertTrue(sent)
        self.assertEqual(retry_after, 0)
        self.assertFalse(sent_again)
        self.assertGreater(retry_after_second, 0)
        self.assertEqual(teacher.email_verification_code_hash, self._digest(teacher.id, "123456"))
        self.assertNotIn("123456", teacher.email_verification_code_hash)
        mocked_send.assert_called_once_with(teacher, "123456", 15)
        mocked_random.assert_called_once()

    def test_schema_upgrade_auto_verifies_preexisting_teacher(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            connection.execute(
                """
                CREATE TABLE teacher (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(80) UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255),
                    created_at DATETIME NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO teacher (id, username, email, password_hash, created_at) VALUES (1, ?, ?, ?, ?)",
                ("existing", "existing@example.com", "hash", "2026-07-01 12:00:00"),
            )
            connection.commit()
            connection.close()

            class LegacyConfig(VerificationTestConfig):
                SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"

            legacy_app = create_app(LegacyConfig)
            with legacy_app.app_context():
                existing_teacher = db.session.get(Teacher, 1)
                self.assertIsNotNone(existing_teacher.email_verified_at)
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from app.auth.routes import _password_reset_digest
from app.extensions import db
from app.models import Book, BroadcastMessage, CheckoutRecord, Classroom, Student, Teacher, TestReportDelivery


class PasswordSecurityTestConfig:
    TESTING = True
    SECRET_KEY = "password-security-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    GMAIL_CLIENT_ID = "test-client"
    GMAIL_CLIENT_SECRET = "test-client-secret"
    GMAIL_REFRESH_TOKEN = "test-refresh-token"
    GMAIL_SENDER_EMAIL = "bookful.noreply@gmail.com"
    GMAIL_SENDER_NAME = "Bookful Reports"
    REPORT_ADMIN_EMAIL = "g.gui.cmpny@gmail.com"
    REPORT_JOB_SECRET = "scheduler-secret"


class PasswordSecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(PasswordSecurityTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _teacher(self, email="teacher@example.com", password="password123"):
        teacher = Teacher(username="teacher", email=email, email_verified_at=datetime.utcnow())
        teacher.set_password(password)
        db.session.add(teacher)
        db.session.commit()
        return teacher

    def _login(self, teacher):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(teacher.id)
            session["_fresh"] = True

    @patch("app.auth.routes.send_password_reset_code", return_value="gmail-message-id")
    @patch("app.auth.routes.secrets.randbelow", return_value=123456)
    def test_forgot_password_emails_hashed_code(self, mocked_random, mocked_send):
        teacher = self._teacher()

        response = self.client.post(
            "/auth/forgot-password",
            data={"email": teacher.email},
            follow_redirects=True,
        )

        db.session.refresh(teacher)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"If a verified teacher account exists", response.data)
        self.assertIn(b"junk or spam folder", response.data)
        self.assertEqual(teacher.password_reset_code_hash, _password_reset_digest(teacher.id, "123456"))
        self.assertNotIn("123456", teacher.password_reset_code_hash)
        mocked_send.assert_called_once_with(teacher, "123456", 15)
        mocked_random.assert_called_once()

    @patch("app.auth.routes.send_password_reset_code")
    def test_unknown_email_uses_same_generic_response(self, mocked_send):
        response = self.client.post(
            "/auth/forgot-password",
            data={"email": "missing@example.com"},
            follow_redirects=True,
        )

        self.assertIn(b"If a verified teacher account exists", response.data)
        mocked_send.assert_not_called()

    def test_valid_reset_code_changes_password_and_cannot_be_reused(self):
        teacher = self._teacher()
        teacher.password_reset_code_hash = _password_reset_digest(teacher.id, "654321")
        teacher.password_reset_expires_at = datetime.utcnow() + timedelta(minutes=10)
        db.session.commit()
        with self.client.session_transaction() as session:
            session["password_reset_email"] = teacher.email

        response = self.client.post(
            "/auth/reset-password",
            data={"code": "654321", "password": "new-password-456", "confirm_password": "new-password-456"},
        )

        db.session.refresh(teacher)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/auth/login"))
        self.assertTrue(teacher.check_password("new-password-456"))
        self.assertIsNone(teacher.password_reset_code_hash)

    def test_invalid_reset_code_counts_attempts(self):
        teacher = self._teacher()
        teacher.password_reset_code_hash = _password_reset_digest(teacher.id, "654321")
        teacher.password_reset_expires_at = datetime.utcnow() + timedelta(minutes=10)
        db.session.commit()
        with self.client.session_transaction() as session:
            session["password_reset_email"] = teacher.email

        response = self.client.post(
            "/auth/reset-password",
            data={"code": "000000", "password": "new-password-456", "confirm_password": "new-password-456"},
        )

        self.assertIn(b"invalid or expired", response.data)
        self.assertEqual(teacher.password_reset_attempts, 1)

    def test_account_dropdown_and_password_change(self):
        teacher = self._teacher()
        self._login(teacher)

        account_page = self.client.get("/auth/account")
        self.assertIn(b"Account &amp; security", account_page.data)
        self.assertIn(b"Permanently delete account", account_page.data)

        response = self.client.post(
            "/auth/account/change-password",
            data={
                "current_password": "password123",
                "new_password": "changed-password-789",
                "confirm_password": "changed-password-789",
            },
            follow_redirects=True,
        )

        db.session.refresh(teacher)
        self.assertIn(b"updated successfully", response.data)
        self.assertTrue(teacher.check_password("changed-password-789"))

    def test_delete_account_requires_password_and_typed_confirmation(self):
        teacher = self._teacher()
        teacher_id = teacher.id
        classroom = Classroom(teacher_id=teacher_id, name="Room 1", join_code="DELETE1")
        db.session.add(classroom)
        db.session.flush()
        student = Student(teacher_id=teacher_id, classroom_id=classroom.id, name="Student")
        book = Book(teacher_id=teacher_id, title="Book", author="Author")
        db.session.add_all([student, book])
        db.session.flush()
        db.session.add_all(
            [
                CheckoutRecord(teacher_id=teacher_id, student_id=student.id, book_id=book.id),
                BroadcastMessage(
                    sent_by_teacher_id=teacher_id,
                    subject="Notice",
                    title="Notice",
                    message="Account deletion test message",
                ),
                TestReportDelivery(teacher_id=teacher_id, sent_on=datetime.utcnow().date()),
            ]
        )
        db.session.commit()
        self._login(teacher)

        rejected = self.client.post(
            "/auth/account/delete",
            data={"password": "wrong-password", "confirmation": "DELETE"},
        )
        self.assertIn(b"current password is incorrect", rejected.data)
        self.assertIsNotNone(db.session.get(Teacher, teacher_id))

        deleted = self.client.post(
            "/auth/account/delete",
            data={"password": "password123", "confirmation": "DELETE"},
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertIsNone(db.session.get(Teacher, teacher_id))
        self.assertEqual(Classroom.query.count(), 0)
        self.assertEqual(Student.query.count(), 0)
        self.assertEqual(Book.query.count(), 0)
        self.assertEqual(CheckoutRecord.query.count(), 0)
        self.assertEqual(BroadcastMessage.query.count(), 0)
        self.assertEqual(TestReportDelivery.query.count(), 0)

    @patch("app.reports.service.send_gmail_message", return_value="gmail-message-id")
    def test_password_reset_email_uses_code_and_junk_reminder(self, mocked_send):
        from app.reports.service import send_password_reset_code

        teacher = Teacher(username="teacher", email="teacher@example.com")
        with self.app.test_request_context("/"):
            send_password_reset_code(teacher, "246810")

        recipient, subject, text_body, html_body = mocked_send.call_args.args
        self.assertEqual(recipient, teacher.email)
        self.assertIn("246810", subject)
        self.assertIn("junk or spam folder", text_body)
        self.assertIn("junk or spam folder", html_body)


if __name__ == "__main__":
    unittest.main()

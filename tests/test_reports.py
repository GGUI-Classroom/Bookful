import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Book, BroadcastMessage, CheckoutRecord, Student, Teacher
from app.reports.service import (
    build_weekly_report_summary,
    is_weekly_report_due,
    send_broadcast_email,
    send_weekly_report,
)


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    REPORT_JOB_SECRET = "scheduler-secret"
    PUBLIC_BASE_URL = "https://bookful.example"
    GMAIL_CLIENT_ID = "test-client"
    GMAIL_CLIENT_SECRET = "test-client-secret"
    GMAIL_REFRESH_TOKEN = "test-refresh-token"
    GMAIL_SENDER_EMAIL = "bookfulreports@gmail.com"
    GMAIL_SENDER_NAME = "Bookful Reports"
    REPORT_ADMIN_EMAIL = "g.gui.cmpny@gmail.com"


class ReportsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()

        self.teacher = Teacher(username="teacher", email="teacher@example.com")
        self.teacher.set_password("password123")
        db.session.add(self.teacher)
        db.session.commit()

        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.teacher.id)
            session["_fresh"] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_summary_contains_aggregate_activity(self):
        student = Student(teacher_id=self.teacher.id, name="Student One")
        books = [
            Book(teacher_id=self.teacher.id, title=f"Book {number}", author="Author")
            for number in range(3)
        ]
        db.session.add_all([student, *books])
        db.session.flush()
        today = date(2026, 7, 20)
        db.session.add_all(
            [
                CheckoutRecord(
                    teacher_id=self.teacher.id,
                    student_id=student.id,
                    book_id=books[0].id,
                    checkout_date=today - timedelta(days=20),
                    due_date=today - timedelta(days=1),
                    status="checked_out",
                ),
                CheckoutRecord(
                    teacher_id=self.teacher.id,
                    student_id=student.id,
                    book_id=books[1].id,
                    checkout_date=today,
                    due_date=today + timedelta(days=4),
                    status="checked_out",
                ),
                CheckoutRecord(
                    teacher_id=self.teacher.id,
                    student_id=student.id,
                    book_id=books[2].id,
                    checkout_date=today - timedelta(days=10),
                    due_date=today,
                    return_date=today - timedelta(days=2),
                    status="returned",
                ),
            ]
        )
        db.session.commit()

        summary = build_weekly_report_summary(self.teacher.id, today=today)

        self.assertEqual(summary.student_count, 1)
        self.assertEqual(summary.book_count, 3)
        self.assertEqual(summary.active_checkout_count, 2)
        self.assertEqual(summary.overdue_count, 1)
        self.assertEqual(summary.due_soon_count, 1)
        self.assertEqual(summary.recent_return_count, 1)

    def test_due_check_respects_local_schedule_and_last_send(self):
        self.teacher.weekly_reports_enabled = True
        self.teacher.weekly_report_weekday = 0
        self.teacher.weekly_report_hour = 8
        self.teacher.weekly_report_timezone = "America/Los_Angeles"
        now = datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc)

        self.assertTrue(is_weekly_report_due(self.teacher, now))

        self.teacher.weekly_report_last_sent_at = datetime(2026, 7, 20, 15, 5)
        self.assertFalse(is_weekly_report_due(self.teacher, now))

        next_week = now + timedelta(days=7)
        self.assertTrue(is_weekly_report_due(self.teacher, next_week))

    def test_scheduler_requires_bearer_secret(self):
        response = self.client.post("/reports/tasks/send-weekly")
        self.assertEqual(response.status_code, 401)

    @patch("app.reports.routes.send_weekly_report", return_value="gmail-message-id")
    def test_scheduler_sends_only_once_per_delivery_day(self, mocked_send):
        now = datetime.now(timezone.utc)
        self.teacher.weekly_reports_enabled = True
        self.teacher.weekly_report_weekday = now.weekday()
        self.teacher.weekly_report_hour = 0
        self.teacher.weekly_report_timezone = "UTC"
        db.session.commit()
        headers = {"Authorization": "Bearer scheduler-secret"}

        first_response = self.client.post("/reports/tasks/send-weekly", headers=headers)
        second_response = self.client.post("/reports/tasks/send-weekly", headers=headers)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.get_json()["sent"], 1)
        self.assertEqual(second_response.get_json()["sent"], 0)
        mocked_send.assert_called_once()

    def test_settings_page_is_available_to_teacher(self):
        response = self.client.get("/reports/settings")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Weekly email reports", response.data)
        self.assertIn(b"teacher@example.com", response.data)

    @patch("app.reports.service.send_gmail_message", return_value="gmail-message-id")
    def test_report_renders_both_bodies_and_dashboard_link(self, mocked_send):
        with self.app.test_request_context("/"):
            message_id = send_weekly_report(self.teacher)

        self.assertEqual(message_id, "gmail-message-id")
        recipient, subject, text_body, html_body = mocked_send.call_args.args
        self.assertEqual(recipient, "teacher@example.com")
        self.assertEqual(subject, "Your weekly Bookful status report")
        self.assertIn("https://bookful.example/dashboard", text_body)
        self.assertIn("Open Bookful dashboard", html_body)

    def test_regular_teacher_cannot_open_broadcast_composer(self):
        response = self.client.get("/reports/broadcast")
        self.assertEqual(response.status_code, 403)

        navigation = self.client.get("/dashboard")
        self.assertNotIn(b"Send announcement", navigation.data)

    def _create_and_login_admin(self):
        admin = Teacher(username="bookful-admin", email="g.gui.cmpny@gmail.com")
        admin.set_password("admin-password-123")
        db.session.add(admin)
        db.session.commit()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(admin.id)
            session["_fresh"] = True
        return admin

    def test_admin_can_open_broadcast_composer(self):
        self._create_and_login_admin()
        response = self.client.get("/reports/broadcast")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Send a Bookful announcement", response.data)
        self.assertIn(b"Administrator only", response.data)

        navigation = self.client.get("/dashboard")
        self.assertIn(b"Send announcement", navigation.data)

    @patch("app.reports.routes.send_broadcast_email", return_value="gmail-message-id")
    def test_broadcast_requires_admin_password(self, mocked_send):
        self._create_and_login_admin()
        response = self.client.post(
            "/reports/broadcast",
            data={
                "subject": "Website maintenance",
                "title": "Bookful will be unavailable tonight",
                "message": "We will be completing scheduled maintenance tonight at 9 PM.",
                "theme": "maintenance",
                "password": "wrong-password",
                "confirm": "y",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"password is incorrect", response.data)
        mocked_send.assert_not_called()
        self.assertEqual(BroadcastMessage.query.count(), 0)

    @patch("app.reports.routes.send_broadcast_email", return_value="gmail-message-id")
    def test_admin_broadcast_sends_individually_and_creates_audit_log(self, mocked_send):
        admin = self._create_and_login_admin()
        response = self.client.post(
            "/reports/broadcast",
            data={
                "subject": "Website maintenance",
                "title": "Bookful will be unavailable tonight",
                "message": "We will be completing scheduled maintenance tonight at 9 PM.",
                "theme": "maintenance",
                "password": "admin-password-123",
                "confirm": "y",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"sent successfully to 2 registered teachers", response.data)
        self.assertEqual(mocked_send.call_count, 2)
        recipients = {call.args[0] for call in mocked_send.call_args_list}
        self.assertEqual(recipients, {"teacher@example.com", "g.gui.cmpny@gmail.com"})

        audit = BroadcastMessage.query.one()
        self.assertEqual(audit.sent_by_teacher_id, admin.id)
        self.assertEqual(audit.recipient_count, 2)
        self.assertEqual(audit.sent_count, 2)
        self.assertEqual(audit.failed_count, 0)

    @patch("app.reports.routes.send_broadcast_email", return_value="gmail-message-id")
    def test_duplicate_broadcast_is_blocked(self, mocked_send):
        self._create_and_login_admin()
        payload = {
            "subject": "Website maintenance",
            "title": "Bookful will be unavailable tonight",
            "message": "We will be completing scheduled maintenance tonight at 9 PM.",
            "theme": "maintenance",
            "password": "admin-password-123",
            "confirm": "y",
        }
        first_response = self.client.post("/reports/broadcast", data=payload)
        second_response = self.client.post("/reports/broadcast", data=payload, follow_redirects=True)

        self.assertEqual(first_response.status_code, 302)
        self.assertIn(b"already submitted recently", second_response.data)
        self.assertEqual(mocked_send.call_count, 2)
        self.assertEqual(BroadcastMessage.query.count(), 1)

    @patch("app.reports.service.send_gmail_message", return_value="gmail-message-id")
    def test_broadcast_template_is_branded_and_escapes_custom_content(self, mocked_send):
        with self.app.test_request_context("/"):
            message_id = send_broadcast_email(
                "teacher@example.com",
                "Website down",
                "Temporary outage",
                "Please wait <script>alert('unsafe')</script>",
                "urgent",
            )

        self.assertEqual(message_id, "gmail-message-id")
        _, subject, _, html_body = mocked_send.call_args.args
        self.assertEqual(subject, "Website down")
        self.assertIn("bookful-logo.svg", html_body)
        self.assertIn("Important notice", html_body)
        self.assertNotIn("<script>", html_body)
        self.assertIn("&lt;script&gt;", html_body)


if __name__ == "__main__":
    unittest.main()

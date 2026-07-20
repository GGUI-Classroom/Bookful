import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Book, CheckoutRecord, Student, Teacher
from app.reports.service import build_weekly_report_summary, is_weekly_report_due, send_weekly_report


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


if __name__ == "__main__":
    unittest.main()

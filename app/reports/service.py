import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app, render_template, url_for

from app.models import Book, CheckoutRecord, Student, Teacher


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
REQUIRED_GMAIL_SETTINGS = (
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "GMAIL_SENDER_EMAIL",
)


class EmailConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeeklyReportSummary:
    student_count: int
    book_count: int
    active_checkout_count: int
    overdue_count: int
    due_soon_count: int
    recent_return_count: int


def build_weekly_report_summary(teacher_id: int, today: date | None = None) -> WeeklyReportSummary:
    today = today or date.today()
    active_filter = (
        CheckoutRecord.teacher_id == teacher_id,
        CheckoutRecord.status == "checked_out",
    )

    return WeeklyReportSummary(
        student_count=Student.query.filter_by(teacher_id=teacher_id, is_archived=False).count(),
        book_count=Book.query.filter_by(teacher_id=teacher_id, is_archived=False).count(),
        active_checkout_count=CheckoutRecord.query.filter(*active_filter).count(),
        overdue_count=CheckoutRecord.query.filter(
            *active_filter,
            CheckoutRecord.due_date.isnot(None),
            CheckoutRecord.due_date < today,
        ).count(),
        due_soon_count=CheckoutRecord.query.filter(
            *active_filter,
            CheckoutRecord.due_date.isnot(None),
            CheckoutRecord.due_date >= today,
            CheckoutRecord.due_date <= today + timedelta(days=7),
        ).count(),
        recent_return_count=CheckoutRecord.query.filter(
            CheckoutRecord.teacher_id == teacher_id,
            CheckoutRecord.status == "returned",
            CheckoutRecord.return_date.isnot(None),
            CheckoutRecord.return_date >= today - timedelta(days=7),
        ).count(),
    )


def _dashboard_url() -> str:
    configured_base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    if configured_base_url:
        return f"{configured_base_url}{url_for('main.dashboard')}"
    return url_for("main.dashboard", _external=True)


def _report_timezone(teacher: Teacher):
    try:
        return ZoneInfo(teacher.weekly_report_timezone)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _gmail_credentials():
    missing = [name for name in REQUIRED_GMAIL_SETTINGS if not current_app.config.get(name)]
    if missing:
        raise EmailConfigurationError(f"Missing Gmail configuration: {', '.join(missing)}")

    from google.oauth2.credentials import Credentials

    return Credentials(
        token=None,
        refresh_token=current_app.config["GMAIL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=current_app.config["GMAIL_CLIENT_ID"],
        client_secret=current_app.config["GMAIL_CLIENT_SECRET"],
        scopes=[GMAIL_SEND_SCOPE],
    )


def send_gmail_message(recipient: str, subject: str, text_body: str, html_body: str) -> str:
    from googleapiclient.discovery import build

    sender_email = current_app.config["GMAIL_SENDER_EMAIL"]
    sender_name = current_app.config.get("GMAIL_SENDER_NAME", "Bookful Reports")

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = formataddr((sender_name, sender_email))
    message["Reply-To"] = sender_email
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    service = build("gmail", "v1", credentials=_gmail_credentials(), cache_discovery=False)
    result = service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()
    return result["id"]


def send_weekly_report(teacher: Teacher) -> str:
    local_today = datetime.now(timezone.utc).astimezone(_report_timezone(teacher)).date()
    summary = build_weekly_report_summary(teacher.id, today=local_today)
    template_context = {
        "teacher": teacher,
        "summary": summary,
        "dashboard_url": _dashboard_url(),
    }
    text_body = render_template("emails/weekly_report.txt", **template_context)
    html_body = render_template("emails/weekly_report.html", **template_context)
    return send_gmail_message(
        teacher.email,
        "Your weekly Bookful status report",
        text_body,
        html_body,
    )


def is_weekly_report_due(teacher: Teacher, now_utc: datetime | None = None) -> bool:
    if not teacher.weekly_reports_enabled:
        return False

    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    report_timezone = _report_timezone(teacher)
    local_now = now_utc.astimezone(report_timezone)
    if local_now.weekday() != teacher.weekly_report_weekday or local_now.hour < teacher.weekly_report_hour:
        return False

    if not teacher.weekly_report_last_sent_at:
        return True

    last_sent = teacher.weekly_report_last_sent_at
    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=timezone.utc)
    local_last_sent = last_sent.astimezone(report_timezone)
    return local_last_sent.date() != local_now.date()


def register_gmail_cli(app) -> None:
    import click

    @app.cli.command("gmail-authorize")
    @click.option(
        "--credentials",
        "credentials_path",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=str),
        help="Path to the OAuth Desktop client JSON downloaded from Google Cloud.",
    )
    @click.option("--sender", required=True, help="The dedicated Gmail address that will send reports.")
    def gmail_authorize(credentials_path: str, sender: str) -> None:
        """Authorize Bookful's dedicated Gmail sender and print Render variables."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, [GMAIL_SEND_SCOPE])
        credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        if not credentials.refresh_token:
            raise click.ClickException("Google did not return a refresh token. Revoke access and try again.")

        click.echo("\nAuthorization succeeded. Add these values to Render, then clear this terminal:")
        click.echo(f"GMAIL_CLIENT_ID={credentials.client_id}")
        click.echo(f"GMAIL_CLIENT_SECRET={credentials.client_secret}")
        click.echo(f"GMAIL_REFRESH_TOKEN={credentials.refresh_token}")
        click.echo(f"GMAIL_SENDER_EMAIL={sender.strip().lower()}")

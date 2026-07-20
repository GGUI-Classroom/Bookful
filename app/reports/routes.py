import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import csrf, db
from app.forms import BroadcastReportForm, WeeklyReportSettingsForm
from app.models import BroadcastMessage, Teacher
from app.reports import reports_bp
from app.reports.service import (
    EmailConfigurationError,
    is_weekly_report_due,
    send_broadcast_email,
    send_weekly_report,
)


def is_broadcast_admin(user) -> bool:
    configured_email = current_app.config.get("REPORT_ADMIN_EMAIL", "").strip().lower()
    user_email = getattr(user, "email", "").strip().lower()
    return bool(configured_email and user.is_authenticated and secrets.compare_digest(user_email, configured_email))


def broadcast_admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_broadcast_admin(current_user):
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


@reports_bp.app_context_processor
def inject_broadcast_permissions():
    return {"can_send_broadcasts": is_broadcast_admin(current_user)}


@reports_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    form = WeeklyReportSettingsForm(obj=current_user)
    if request.method == "GET":
        form.enabled.data = current_user.weekly_reports_enabled
        form.weekday.data = current_user.weekly_report_weekday
        form.hour.data = current_user.weekly_report_hour
        form.timezone.data = current_user.weekly_report_timezone

    if form.validate_on_submit():
        current_user.weekly_reports_enabled = form.enabled.data
        current_user.weekly_report_weekday = form.weekday.data
        current_user.weekly_report_hour = form.hour.data
        current_user.weekly_report_timezone = form.timezone.data
        db.session.commit()
        flash("Weekly report settings saved.", "success")
        return redirect(url_for("reports.settings"))

    return render_template("reports/settings.html", form=form)


@reports_bp.post("/send-test")
@login_required
def send_test():
    try:
        send_weekly_report(current_user)
    except EmailConfigurationError:
        current_app.logger.exception("Gmail reporting is not configured")
        flash("Email delivery is not configured yet. Finish the Gmail setup in Render.", "danger")
    except Exception:
        current_app.logger.exception("Could not send test report to teacher %s", current_user.id)
        flash("The test report could not be sent. Check the server logs for the delivery error.", "danger")
    else:
        flash(f"A test report was sent to {current_user.email}.", "success")
    return redirect(url_for("reports.settings"))


@reports_bp.route("/broadcast", methods=["GET", "POST"])
@login_required
@broadcast_admin_required
def broadcast():
    form = BroadcastReportForm()
    recipient_count = Teacher.query.count()

    if form.validate_on_submit():
        if not current_user.check_password(form.password.data):
            form.password.errors.append("Your Bookful password is incorrect.")
            return render_template("reports/broadcast.html", form=form, recipient_count=recipient_count)

        duplicate_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        recent_duplicate = BroadcastMessage.query.filter(
            BroadcastMessage.sent_by_teacher_id == current_user.id,
            BroadcastMessage.subject == form.subject.data.strip(),
            BroadcastMessage.title == form.title.data.strip(),
            BroadcastMessage.message == form.message.data.strip(),
            BroadcastMessage.created_at >= duplicate_cutoff,
        ).first()
        if recent_duplicate:
            flash("That exact announcement was already submitted recently, so it was not sent again.", "warning")
            return redirect(url_for("reports.broadcast"))

        recipients = Teacher.query.order_by(Teacher.id.asc()).all()
        audit = BroadcastMessage(
            sent_by_teacher_id=current_user.id,
            subject=form.subject.data.strip(),
            title=form.title.data.strip(),
            message=form.message.data.strip(),
            theme=form.theme.data,
            recipient_count=len(recipients),
        )
        db.session.add(audit)
        db.session.commit()

        sent = 0
        failed = 0
        for recipient in recipients:
            try:
                send_broadcast_email(
                    recipient.email,
                    audit.subject,
                    audit.title,
                    audit.message,
                    audit.theme,
                )
                sent += 1
            except Exception:
                failed += 1
                current_app.logger.exception(
                    "Broadcast %s failed for teacher %s",
                    audit.id,
                    recipient.id,
                )

        audit.sent_count = sent
        audit.failed_count = failed
        db.session.commit()

        if failed:
            flash(f"Announcement finished: {sent} sent and {failed} failed. Check the server logs.", "warning")
        else:
            flash(f"Announcement sent successfully to {sent} registered teachers.", "success")
        return redirect(url_for("reports.broadcast"))

    return render_template("reports/broadcast.html", form=form, recipient_count=recipient_count)


@reports_bp.post("/tasks/send-weekly")
@csrf.exempt
def send_scheduled_reports():
    configured_secret = current_app.config.get("REPORT_JOB_SECRET", "")
    supplied_authorization = request.headers.get("Authorization", "")
    expected_authorization = f"Bearer {configured_secret}"
    if not configured_secret:
        return jsonify(error="Scheduled reports are not configured."), 503
    if not secrets.compare_digest(supplied_authorization, expected_authorization):
        return jsonify(error="Unauthorized."), 401

    now_utc = datetime.now(timezone.utc)
    due_teachers = [
        teacher
        for teacher in Teacher.query.filter_by(weekly_reports_enabled=True).all()
        if is_weekly_report_due(teacher, now_utc)
    ]
    sent = 0
    failures = []

    for teacher in due_teachers:
        try:
            send_weekly_report(teacher)
            teacher.weekly_report_last_sent_at = now_utc.replace(tzinfo=None)
            db.session.commit()
            sent += 1
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Could not send scheduled report to teacher %s", teacher.id)
            failures.append(teacher.id)

    return jsonify(eligible=len(due_teachers), sent=sent, failed=len(failures), failed_teacher_ids=failures)

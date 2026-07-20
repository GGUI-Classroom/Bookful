import secrets
from datetime import datetime, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import csrf, db
from app.forms import WeeklyReportSettingsForm
from app.models import Teacher
from app.reports import reports_bp
from app.reports.service import EmailConfigurationError, is_weekly_report_due, send_weekly_report


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

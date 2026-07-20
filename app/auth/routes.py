import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError

from app.auth import auth_bp
from app.extensions import db
from app.forms import (
    ChangePasswordForm,
    DeleteAccountForm,
    EmailVerificationForm,
    ForgotPasswordForm,
    LoginForm,
    ResetPasswordForm,
    SignUpForm,
)
from app.models import (
    Book,
    BroadcastMessage,
    CheckoutRecord,
    Classroom,
    Student,
    StudentAccount,
    Teacher,
    TestReportDelivery,
)
from app.reports.service import EmailConfigurationError, send_email_verification, send_password_reset_code


VERIFICATION_CODE_TTL_MINUTES = 15
VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
VERIFICATION_MAX_ATTEMPTS = 5
PASSWORD_RESET_CODE_TTL_MINUTES = 15
PASSWORD_RESET_COOLDOWN_SECONDS = 60
PASSWORD_RESET_MAX_ATTEMPTS = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _code_digest(purpose: str, teacher_id: int, code: str) -> str:
    key = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    payload = f"{purpose}:{teacher_id}:{code}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _verification_digest(teacher_id: int, code: str) -> str:
    # Keep the original verification digest so codes already emailed before
    # this release remain valid.
    key = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    payload = f"{teacher_id}:{code}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _password_reset_digest(teacher_id: int, code: str) -> str:
    return _code_digest("reset-password", teacher_id, code)


def _issue_verification_code(teacher: Teacher, enforce_cooldown: bool = True) -> tuple[bool, int]:
    now = _utc_now()
    if enforce_cooldown and teacher.email_verification_sent_at:
        elapsed = (now - teacher.email_verification_sent_at).total_seconds()
        if elapsed < VERIFICATION_RESEND_COOLDOWN_SECONDS:
            return False, max(1, int(VERIFICATION_RESEND_COOLDOWN_SECONDS - elapsed))

    code = f"{secrets.randbelow(1_000_000):06d}"
    teacher.email_verification_code_hash = _verification_digest(teacher.id, code)
    teacher.email_verification_expires_at = now + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES)
    teacher.email_verification_attempts = 0
    db.session.commit()

    send_email_verification(teacher, code, VERIFICATION_CODE_TTL_MINUTES)
    teacher.email_verification_sent_at = now
    db.session.commit()
    return True, 0


def _issue_password_reset_code(teacher: Teacher) -> bool:
    now = _utc_now()
    if teacher.password_reset_sent_at:
        elapsed = (now - teacher.password_reset_sent_at).total_seconds()
        if elapsed < PASSWORD_RESET_COOLDOWN_SECONDS:
            return False

    code = f"{secrets.randbelow(1_000_000):06d}"
    teacher.password_reset_code_hash = _password_reset_digest(teacher.id, code)
    teacher.password_reset_expires_at = now + timedelta(minutes=PASSWORD_RESET_CODE_TTL_MINUTES)
    teacher.password_reset_attempts = 0
    db.session.commit()

    send_password_reset_code(teacher, code, PASSWORD_RESET_CODE_TTL_MINUTES)
    teacher.password_reset_sent_at = now
    db.session.commit()
    return True


@auth_bp.before_app_request
def require_verified_teacher_email():
    if not current_user.is_authenticated or current_user.email_verified_at:
        return None

    allowed_endpoints = {
        "auth.verify_email",
        "auth.resend_verification",
        "auth.logout",
        "static",
    }
    if request.endpoint not in allowed_endpoints:
        return redirect(url_for("auth.verify_email"))
    return None


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = SignUpForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()

        existing_username = Teacher.query.filter_by(username=username).first()
        if existing_username:
            form.username.errors.append("That username is already taken.")
            return render_template("auth/signup.html", form=form)

        existing_email = Teacher.query.filter_by(email=email).first()
        if existing_email:
            form.email.errors.append("That email is already registered.")
            return render_template("auth/signup.html", form=form)

        teacher = Teacher(username=username, email=email)
        teacher.set_password(form.password.data)
        db.session.add(teacher)
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("We could not create your account right now. Please try again.", "danger")
            return render_template("auth/signup.html", form=form)

        login_user(teacher)
        try:
            _issue_verification_code(teacher, enforce_cooldown=False)
        except EmailConfigurationError:
            current_app.logger.exception("Gmail verification is not configured")
            flash("Your account was created, but verification email is not configured yet. Try resending shortly.", "warning")
        except Exception:
            current_app.logger.exception("Could not send verification code to teacher %s", teacher.id)
            flash("Your account was created, but the verification code could not be sent. Please try again.", "warning")
        else:
            flash("We sent a six-digit verification code to your email.", "success")
        return redirect(url_for("auth.verify_email"))

    return render_template("auth/signup.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.identifier.data.strip()
        teacher = Teacher.query.filter_by(email=identifier.lower()).first()

        if teacher is None:
            teacher = Teacher.query.filter_by(username=identifier).first()

        if teacher and teacher.check_password(form.password.data):
            login_user(teacher)
            if not teacher.email_verified_at:
                flash("Verify your teacher email to continue.", "warning")
                return redirect(url_for("auth.verify_email"))
            flash("Welcome back.", "success")
            return redirect(url_for("main.dashboard"))

        flash("Invalid credentials.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        session["password_reset_email"] = email
        teacher = Teacher.query.filter_by(email=email).first()

        if teacher and teacher.email_verified_at and teacher.password_hash:
            try:
                _issue_password_reset_code(teacher)
            except Exception:
                current_app.logger.exception("Could not send password reset code to teacher %s", teacher.id)

        flash(
            "If a verified teacher account exists for that email, a reset code was sent. Check your junk or spam folder too.",
            "info",
        )
        return redirect(url_for("auth.reset_password"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))

    reset_email = session.get("password_reset_email", "")
    if not reset_email:
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        teacher = Teacher.query.filter_by(email=reset_email).first()
        now = _utc_now()
        reset_is_valid = bool(
            teacher
            and teacher.password_reset_code_hash
            and teacher.password_reset_expires_at
            and teacher.password_reset_expires_at >= now
            and teacher.password_reset_attempts < PASSWORD_RESET_MAX_ATTEMPTS
            and hmac.compare_digest(
                _password_reset_digest(teacher.id, form.code.data),
                teacher.password_reset_code_hash,
            )
        )

        if reset_is_valid:
            teacher.set_password(form.password.data)
            teacher.password_reset_code_hash = None
            teacher.password_reset_expires_at = None
            teacher.password_reset_sent_at = None
            teacher.password_reset_attempts = 0
            db.session.commit()
            session.pop("password_reset_email", None)
            flash("Your password has been reset. You can now log in.", "success")
            return redirect(url_for("auth.login"))

        if teacher and teacher.password_reset_code_hash:
            teacher.password_reset_attempts += 1
            if teacher.password_reset_attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
                teacher.password_reset_code_hash = None
                teacher.password_reset_expires_at = None
            db.session.commit()
        flash("That reset code is invalid or expired. Request a new code and try again.", "danger")

    return render_template("auth/reset_password.html", form=form, reset_email=reset_email)


@auth_bp.route("/verify-email", methods=["GET", "POST"])
@login_required
def verify_email():
    if current_user.email_verified_at:
        return redirect(url_for("main.dashboard"))

    form = EmailVerificationForm()
    if form.validate_on_submit():
        now = _utc_now()
        if (
            not current_user.email_verification_code_hash
            or not current_user.email_verification_expires_at
            or current_user.email_verification_expires_at < now
        ):
            flash("That verification code has expired. Request a new code.", "warning")
        elif current_user.email_verification_attempts >= VERIFICATION_MAX_ATTEMPTS:
            flash("Too many incorrect attempts. Request a new verification code.", "danger")
        else:
            supplied_digest = _verification_digest(current_user.id, form.code.data)
            if hmac.compare_digest(supplied_digest, current_user.email_verification_code_hash):
                current_user.email_verified_at = now
                current_user.email_verification_code_hash = None
                current_user.email_verification_expires_at = None
                current_user.email_verification_attempts = 0
                db.session.commit()
                flash("Your teacher email is verified. Welcome to Bookful!", "success")
                return redirect(url_for("main.dashboard"))

            current_user.email_verification_attempts += 1
            attempts_remaining = VERIFICATION_MAX_ATTEMPTS - current_user.email_verification_attempts
            if attempts_remaining <= 0:
                current_user.email_verification_code_hash = None
                current_user.email_verification_expires_at = None
                flash("Too many incorrect attempts. Request a new verification code.", "danger")
            else:
                flash(f"That code is incorrect. {attempts_remaining} attempts remaining.", "danger")
            db.session.commit()

    return render_template("auth/verify_email.html", form=form)


@auth_bp.post("/verify-email/resend")
@login_required
def resend_verification():
    if current_user.email_verified_at:
        return redirect(url_for("main.dashboard"))

    try:
        sent, retry_after = _issue_verification_code(current_user)
    except EmailConfigurationError:
        current_app.logger.exception("Gmail verification is not configured")
        flash("Verification email is not configured yet. Please try again later.", "danger")
    except Exception:
        current_app.logger.exception("Could not resend verification code to teacher %s", current_user.id)
        flash("We could not send a new code right now. Please try again.", "danger")
    else:
        if sent:
            flash("A new six-digit code was sent. Make sure to check your junk or spam folder too.", "success")
        else:
            flash(f"Please wait {retry_after} seconds before requesting another code.", "warning")
    return redirect(url_for("auth.verify_email"))


def _render_account(change_form=None, delete_form=None):
    return render_template(
        "auth/account.html",
        change_form=change_form or ChangePasswordForm(),
        delete_form=delete_form or DeleteAccountForm(),
    )


@auth_bp.get("/account")
@login_required
def account():
    return _render_account()


@auth_bp.post("/account/change-password")
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            form.current_password.errors.append("Your current password is incorrect.")
        elif current_user.check_password(form.new_password.data):
            form.new_password.errors.append("Choose a password different from your current password.")
        else:
            current_user.set_password(form.new_password.data)
            current_user.password_reset_code_hash = None
            current_user.password_reset_expires_at = None
            current_user.password_reset_sent_at = None
            current_user.password_reset_attempts = 0
            db.session.commit()
            flash("Your password was updated successfully.", "success")
            return redirect(url_for("auth.account"))
    return _render_account(change_form=form)


@auth_bp.post("/account/delete")
@login_required
def delete_account():
    form = DeleteAccountForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.password.data):
            form.password.errors.append("Your current password is incorrect.")
        else:
            teacher_id = current_user.id
            student_ids = db.session.query(Student.id).filter_by(teacher_id=teacher_id)
            StudentAccount.query.filter(StudentAccount.student_id.in_(student_ids)).delete(synchronize_session=False)
            CheckoutRecord.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
            Student.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
            Book.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
            Classroom.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
            BroadcastMessage.query.filter_by(sent_by_teacher_id=teacher_id).delete(synchronize_session=False)
            TestReportDelivery.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
            logout_user()
            Teacher.query.filter_by(id=teacher_id).delete(synchronize_session=False)
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                flash("We could not delete your account right now. Please try again.", "danger")
                return redirect(url_for("auth.login"))

            session.clear()
            flash("Your Bookful teacher account and its library data were permanently deleted.", "info")
            return redirect(url_for("main.home"))
    return _render_account(delete_form=form)


@auth_bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))

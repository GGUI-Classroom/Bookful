import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError

from app.auth import auth_bp
from app.extensions import db
from app.forms import EmailVerificationForm, LoginForm, SignUpForm
from app.models import Teacher
from app.reports.service import EmailConfigurationError, send_email_verification


VERIFICATION_CODE_TTL_MINUTES = 15
VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
VERIFICATION_MAX_ATTEMPTS = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _verification_digest(teacher_id: int, code: str) -> str:
    key = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    payload = f"{teacher_id}:{code}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


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


@auth_bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))

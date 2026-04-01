import re
import secrets

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError

from app.auth import auth_bp
from app.classlink import ClassLinkError, build_authorize_url, exchange_code_for_token, fetch_userinfo, is_enabled
from app.extensions import db
from app.forms import LoginForm, SignUpForm
from app.models import Teacher


def _normalize_username(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "teacher"


def _unique_username(base_value: str) -> str:
    candidate = _normalize_username(base_value)
    suffix = 1
    while Teacher.query.filter_by(username=candidate).first() is not None:
        suffix += 1
        candidate = f"{_normalize_username(base_value)}_{suffix}"
    return candidate


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
        flash("Account created successfully.", "success")
        return redirect(url_for("main.dashboard"))

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
            flash("Welcome back.", "success")
            return redirect(url_for("main.dashboard"))

        flash("Invalid credentials.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.get("/classlink/login")
def classlink_login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if not is_enabled():
        flash("ClassLink sign-in is not configured yet.", "warning")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(32)
    session["classlink_state"] = state
    session["classlink_next"] = request.args.get("next") or url_for("main.dashboard")
    return redirect(build_authorize_url(state))


@auth_bp.get("/classlink/callback")
def classlink_callback():
    if not is_enabled():
        flash("ClassLink sign-in is not configured yet.", "warning")
        return redirect(url_for("auth.login"))

    error = request.args.get("error")
    if error:
        flash("ClassLink sign-in was canceled or failed.", "danger")
        return redirect(url_for("auth.login"))

    expected_state = session.pop("classlink_state", None)
    returned_state = request.args.get("state")
    if not expected_state or expected_state != returned_state:
        flash("ClassLink sign-in could not be verified.", "danger")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    if not code:
        flash("ClassLink did not return an authorization code.", "danger")
        return redirect(url_for("auth.login"))

    try:
        access_token = exchange_code_for_token(code)
        profile = fetch_userinfo(access_token)
    except ClassLinkError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("auth.login"))

    email = (profile.get("email") or "").strip().lower()
    external_subject = (profile.get("sub") or profile.get("id") or "").strip()
    display_name = (profile.get("name") or profile.get("given_name") or email or "ClassLink User").strip()

    if not email:
        flash("ClassLink did not provide an email address.", "danger")
        return redirect(url_for("auth.login"))

    teacher = Teacher.query.filter_by(external_subject=external_subject).first()
    if teacher is None:
        teacher = Teacher.query.filter_by(email=email).first()

    if teacher is None:
        teacher = Teacher(
            username=_unique_username(display_name or email),
            email=email,
            auth_provider="classlink",
            external_subject=external_subject or None,
            external_email=email,
        )
        db.session.add(teacher)
    else:
        teacher.auth_provider = "classlink"
        if external_subject and not teacher.external_subject:
            teacher.external_subject = external_subject
        if not teacher.external_email:
            teacher.external_email = email

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("We could not finish the ClassLink sign-in right now.", "danger")
        return redirect(url_for("auth.login"))

    login_user(teacher)
    flash("Signed in with ClassLink.", "success")
    return redirect(session.pop("classlink_next", url_for("main.dashboard")))


@auth_bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))

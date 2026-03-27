from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import SQLAlchemyError

from app.auth import auth_bp
from app.extensions import db
from app.forms import LoginForm, SignUpForm
from app.models import Teacher


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


@auth_bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))

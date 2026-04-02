from __future__ import annotations

import secrets

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.classes import classes_bp
from app.extensions import db
from app.forms import ClassroomForm
from app.models import Classroom


def _generate_join_code() -> str:
    while True:
        code = secrets.token_hex(4).upper()
        existing = Classroom.query.filter_by(join_code=code).first()
        if existing is None:
            return code


@classes_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = ClassroomForm()
    classrooms = Classroom.query.filter_by(teacher_id=current_user.id).order_by(Classroom.created_at.desc()).all()

    if form.validate_on_submit():
        classroom = Classroom(
            teacher_id=current_user.id,
            name=form.name.data.strip(),
            join_code=_generate_join_code(),
            default_self_checkout_days=form.default_self_checkout_days.data or 14,
        )
        db.session.add(classroom)
        db.session.commit()
        flash("Class created.", "success")
        return redirect(url_for("classes.index"))

    return render_template("classes/index.html", form=form, classrooms=classrooms)


@classes_bp.post("/<int:classroom_id>/settings")
@login_required
def update_settings(classroom_id: int):
    classroom = Classroom.query.filter_by(id=classroom_id, teacher_id=current_user.id).first_or_404()

    classroom.allow_student_checkouts = request.form.get("allow_student_checkouts") == "on"

    due_days_raw = (request.form.get("default_self_checkout_days") or "").strip()
    try:
        due_days = int(due_days_raw)
    except ValueError:
        flash("Enter a valid number of days for self-checkout due dates.", "danger")
        return redirect(url_for("classes.index"))

    if due_days < 1:
        flash("Self-checkout due days must be at least 1.", "danger")
        return redirect(url_for("classes.index"))

    classroom.default_self_checkout_days = due_days
    db.session.commit()

    state = "enabled" if classroom.allow_student_checkouts else "disabled"
    flash(
        f"Student self-checkouts {state} for {classroom.name}; due date set to {classroom.default_self_checkout_days} day{'s' if classroom.default_self_checkout_days != 1 else ''}.",
        "success",
    )
    return redirect(url_for("classes.index"))


@classes_bp.get("/join/<string:join_code>")
def join(join_code: str):
    return redirect(url_for("portal.choose_account", join_code=join_code))

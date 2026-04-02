from __future__ import annotations

import secrets

from flask import flash, redirect, render_template, url_for
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
        )
        db.session.add(classroom)
        db.session.commit()
        flash("Class created.", "success")
        return redirect(url_for("classes.index"))

    return render_template("classes/index.html", form=form, classrooms=classrooms)


@classes_bp.post("/<int:classroom_id>/toggle-student-checkouts")
@login_required
def toggle_student_checkouts(classroom_id: int):
    classroom = Classroom.query.filter_by(id=classroom_id, teacher_id=current_user.id).first_or_404()
    classroom.allow_student_checkouts = not classroom.allow_student_checkouts
    db.session.commit()

    state = "enabled" if classroom.allow_student_checkouts else "disabled"
    flash(f"Student self-checkouts {state} for {classroom.name}.", "success")
    return redirect(url_for("classes.index"))


@classes_bp.get("/join/<string:join_code>")
def join(join_code: str):
    return redirect(url_for("portal.choose_account", join_code=join_code))

from flask import flash, render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import StudentForm
from app.models import Student
from app.students import students_bp


@students_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = StudentForm()

    if form.validate_on_submit():
        student = Student(
            teacher_id=current_user.id,
            name=form.name.data.strip(),
            grade=(form.grade.data or "").strip() or None,
        )
        db.session.add(student)
        db.session.commit()
        flash("Student added.", "success")

    students = (
        Student.query.filter_by(teacher_id=current_user.id)
        .order_by(Student.name.asc())
        .all()
    )

    return render_template("students/index.html", form=form, students=students)

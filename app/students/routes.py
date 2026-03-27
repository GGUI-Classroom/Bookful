from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import StudentForm
from app.models import Student
from app.students import students_bp


@students_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = StudentForm()
    search_query = request.args.get("q", "").strip()

    if form.validate_on_submit():
        student = Student(
            teacher_id=current_user.id,
            name=form.name.data.strip(),
            grade=None,
        )
        db.session.add(student)
        db.session.commit()
        flash("Student added.", "success")
        return redirect(url_for("students.index"))

    query = Student.query.filter_by(teacher_id=current_user.id)
    if search_query:
        query = query.filter(Student.name.ilike(f"%{search_query}%"))

    students = query.order_by(Student.name.asc()).all()

    return render_template(
        "students/index.html",
        form=form,
        students=students,
        search_query=search_query,
    )

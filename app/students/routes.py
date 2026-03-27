from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.forms import StudentForm
from app.models import CheckoutRecord, Student
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


@students_bp.get("/<int:student_id>")
@login_required
def detail(student_id: int):
    student = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first_or_404()

    active_records = (
        CheckoutRecord.query.options(joinedload(CheckoutRecord.book))
        .filter(
            CheckoutRecord.teacher_id == current_user.id,
            CheckoutRecord.student_id == student.id,
            CheckoutRecord.status == "checked_out",
        )
        .order_by(CheckoutRecord.checkout_date.desc(), CheckoutRecord.id.desc())
        .all()
    )

    previous_records = (
        CheckoutRecord.query.options(joinedload(CheckoutRecord.book))
        .filter(
            CheckoutRecord.teacher_id == current_user.id,
            CheckoutRecord.student_id == student.id,
            CheckoutRecord.status == "returned",
        )
        .order_by(CheckoutRecord.return_date.desc(), CheckoutRecord.id.desc())
        .all()
    )

    return render_template(
        "students/detail.html",
        student=student,
        active_records=active_records,
        previous_records=previous_records,
    )

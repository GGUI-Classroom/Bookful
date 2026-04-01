from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.forms import RosterImportForm, StudentForm
from app.models import Classroom, CheckoutRecord, Student
from app.students import students_bp
from app.utils.matching import normalize_name


def _classroom_choices():
    classrooms = Classroom.query.filter_by(teacher_id=current_user.id).order_by(Classroom.name.asc()).all()
    return [(0, "No class")] + [(classroom.id, classroom.name) for classroom in classrooms]


def _parse_roster_names(raw_text: str) -> list[str]:
    names: list[str] = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.lower() in {"name", "student name"}:
            continue
        if "," in cleaned:
            parts = [part.strip() for part in cleaned.split(",") if part.strip()]
            if parts and parts[0].lower() in {"name", "student name"}:
                continue
            if parts:
                cleaned = parts[0]
        names.append(cleaned)
    return names


@students_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = StudentForm()
    roster_form = RosterImportForm()
    form.classroom_id.choices = _classroom_choices()
    roster_form.classroom_id.choices = _classroom_choices()
    search_query = request.args.get("q", "").strip()

    if form.validate_on_submit():
        classroom_id = form.classroom_id.data or None
        student = Student(
            teacher_id=current_user.id,
            classroom_id=classroom_id,
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
        roster_form=roster_form,
        students=students,
        search_query=search_query,
    )


@students_bp.route("/import-roster", methods=["POST"])
@login_required
def import_roster():
    form = RosterImportForm()
    form.classroom_id.choices = _classroom_choices()

    if not form.validate_on_submit():
        flash("Choose a classroom and provide roster names or a file.", "danger")
        return redirect(url_for("students.index"))

    classroom_id = form.classroom_id.data or None
    classroom = Classroom.query.filter_by(id=classroom_id, teacher_id=current_user.id).first() if classroom_id else None

    raw_text = (form.roster_text.data or "").strip()
    if form.roster_file.data and getattr(form.roster_file.data, "filename", ""):
        raw_text = form.roster_file.data.read().decode("utf-8", errors="ignore")

    names = _parse_roster_names(raw_text)
    if not names:
        flash("No student names were found in that roster.", "danger")
        return redirect(url_for("students.index"))

    existing_names = {
        normalize_name(student.name)
        for student in Student.query.filter_by(teacher_id=current_user.id, classroom_id=classroom_id).all()
    }

    created_count = 0
    skipped_count = 0
    for name in names:
        normalized = normalize_name(name)
        if not normalized or normalized in existing_names:
            skipped_count += 1
            continue

        student = Student(
            teacher_id=current_user.id,
            classroom_id=classroom.id if classroom else None,
            name=name.strip(),
            grade=None,
        )
        db.session.add(student)
        existing_names.add(normalized)
        created_count += 1

    db.session.commit()
    flash(
        f"Imported {created_count} student{'s' if created_count != 1 else ''}. Skipped {skipped_count} duplicate{'s' if skipped_count != 1 else ''}.",
        "success",
    )
    return redirect(url_for("students.index"))


@students_bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def edit(student_id: int):
    student = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first_or_404()
    form = StudentForm(obj=student)
    form.classroom_id.choices = _classroom_choices()
    if request.method == "GET":
        form.classroom_id.data = student.classroom_id or 0
    form.submit.label.text = "Update Student"

    if form.validate_on_submit():
        student.name = form.name.data.strip()
        student.classroom_id = form.classroom_id.data or None
        db.session.commit()
        flash("Student updated.", "success")
        return redirect(url_for("students.detail", student_id=student.id))

    return render_template("students/edit.html", form=form, student=student)


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
        classroom=student.classroom,
        account=student.account,
        active_records=active_records,
        previous_records=previous_records,
    )

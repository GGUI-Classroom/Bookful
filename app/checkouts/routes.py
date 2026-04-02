import csv
from datetime import date, datetime
from io import StringIO

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.checkouts import checkouts_bp
from app.extensions import db
from app.forms import CheckoutForm, HistoryFilterForm, RecordImportForm
from app.models import Book, CheckoutRecord, Classroom, Student
from app.utils.matching import find_best_book_match, find_best_name_match


def _student_choices():
    students = (
        Student.query.filter_by(teacher_id=current_user.id, is_archived=False)
        .order_by(Student.name.asc())
        .all()
    )
    return [(0, "-- Select a student --")] + [(s.id, s.name) for s in students]


def _book_choices():
    books = (
        Book.query.filter_by(teacher_id=current_user.id, is_archived=False)
        .order_by(Book.title.asc())
        .all()
    )
    return [(0, "-- Select a book --")] + [(b.id, f"{b.title} by {b.author}") for b in books]


def _classroom_choices():
    classrooms = Classroom.query.filter_by(teacher_id=current_user.id).order_by(Classroom.name.asc()).all()
    return [(0, "All Classes")] + [(classroom.id, classroom.name) for classroom in classrooms]


def _parse_date(value: str | None):
    if not value:
        return None
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    return None


@checkouts_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_checkout():
    form = CheckoutForm()
    # Set default checkout date on GET requests
    if not form.is_submitted() and not form.checkout_date.data:
        form.checkout_date.data = date.today()
    form.existing_student_id.choices = _student_choices()
    form.existing_book_id.choices = _book_choices()

    if form.validate_on_submit():
        if form.existing_student_id.data:
            student = Student.query.filter_by(
                id=form.existing_student_id.data,
                teacher_id=current_user.id,
                is_archived=False,
            ).first()
            if student is None:
                abort(404)
        else:
            student = Student(
                teacher_id=current_user.id,
                name=form.new_student_name.data.strip(),
                grade=None,
            )
            db.session.add(student)
            db.session.flush()

        if form.existing_book_id.data:
            book = Book.query.filter_by(
                id=form.existing_book_id.data,
                teacher_id=current_user.id,
                is_archived=False,
            ).first()
            if book is None:
                abort(404)
        else:
            book = Book(
                teacher_id=current_user.id,
                title=form.new_book_title.data.strip(),
                author=form.new_book_author.data.strip(),
                isbn=(form.new_book_isbn.data or "").strip() or None,
            )
            db.session.add(book)
            db.session.flush()

        record = CheckoutRecord(
            teacher_id=current_user.id,
            student_id=student.id,
            book_id=book.id,
            checkout_date=form.checkout_date.data,
            due_date=form.due_date.data,
            status="checked_out",
        )

        db.session.add(record)
        db.session.commit()
        flash("Checkout created.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("checkouts/new.html", form=form)


@checkouts_bp.get("/records")
@login_required
def records():
    form = HistoryFilterForm(request.args)

    students = (
        Student.query.filter_by(teacher_id=current_user.id)
        .order_by(Student.name.asc())
        .all()
    )
    books = (
        Book.query.filter_by(teacher_id=current_user.id)
        .order_by(Book.title.asc())
        .all()
    )

    form.student_id.choices = [("", "All Students")] + [(str(s.id), s.name) for s in students]
    form.book_id.choices = [("", "All Books")] + [(str(b.id), b.title) for b in books]

    query = (
        CheckoutRecord.query.options(joinedload(CheckoutRecord.student), joinedload(CheckoutRecord.book))
        .filter(CheckoutRecord.teacher_id == current_user.id)
        .order_by(CheckoutRecord.checkout_date.desc(), CheckoutRecord.id.desc())
    )

    if form.student_id.data:
        query = query.filter(CheckoutRecord.student_id == int(form.student_id.data))

    if form.book_id.data:
        query = query.filter(CheckoutRecord.book_id == int(form.book_id.data))

    if form.status.data == "active":
        query = query.filter(CheckoutRecord.status == "checked_out", CheckoutRecord.return_date.is_(None))
    elif form.status.data == "returned":
        query = query.filter(CheckoutRecord.status == "returned")

    records = query.all()
    active_records = [record for record in records if record.status == "checked_out"]
    previous_records = [record for record in records if record.status == "returned"]

    return render_template(
        "checkouts/records.html",
        form=form,
        active_records=active_records,
        previous_records=previous_records,
        record_count=len(records),
    )


@checkouts_bp.get("/history")
@login_required
def history():
    return redirect(url_for("checkouts.records"))


@checkouts_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_records():
    form = RecordImportForm()
    form.classroom_id.choices = _classroom_choices()

    if form.validate_on_submit():
        classroom_id = form.classroom_id.data or None

        students_query = Student.query.filter_by(teacher_id=current_user.id)
        if classroom_id:
            students_query = students_query.filter_by(classroom_id=classroom_id)
        students = students_query.all()
        books = Book.query.filter_by(teacher_id=current_user.id).all()

        raw_text = form.records_file.data.read().decode("utf-8", errors="ignore")
        rows = list(csv.DictReader(StringIO(raw_text)))
        if not rows:
            flash("No CSV rows were found in that file.", "danger")
            return redirect(url_for("checkouts.records"))

        imported_count = 0
        skipped_rows: list[dict[str, str]] = []

        for row in rows:
            student_name = (row.get("student_name") or row.get("student") or row.get("name") or "").strip()
            book_title = (row.get("book_title") or row.get("title") or "").strip()
            book_isbn = (row.get("isbn") or row.get("book_isbn") or "").strip() or None
            checkout_date = _parse_date(row.get("checkout_date")) or date.today()
            due_date = _parse_date(row.get("due_date"))
            return_date = _parse_date(row.get("return_date"))
            status = (row.get("status") or "checked_out").strip().lower() or "checked_out"

            student, _student_score = find_best_name_match(student_name, students, lambda item: item.name, minimum_score=0.78)
            book, _book_score = find_best_book_match(book_title, books, lambda item, field: getattr(item, field), isbn=book_isbn)

            if student is None or book is None:
                skipped_rows.append({"student_name": student_name, "book_title": book_title})
                continue

            existing_record = CheckoutRecord.query.filter_by(
                teacher_id=current_user.id,
                student_id=student.id,
                book_id=book.id,
                checkout_date=checkout_date,
            ).first()
            if existing_record is not None:
                skipped_rows.append({"student_name": student_name, "book_title": book_title})
                continue

            record = CheckoutRecord(
                teacher_id=current_user.id,
                student_id=student.id,
                book_id=book.id,
                checkout_date=checkout_date,
                due_date=due_date,
                return_date=return_date,
                status="returned" if status == "returned" or return_date else "checked_out",
            )
            db.session.add(record)
            imported_count += 1

        db.session.commit()
        return render_template(
            "checkouts/import.html",
            form=form,
            imported_count=imported_count,
            skipped_rows=skipped_rows,
        )

    return render_template("checkouts/import.html", form=form)


@checkouts_bp.post("/<int:record_id>/return")
@login_required
def mark_returned(record_id: int):
    record = CheckoutRecord.query.filter_by(id=record_id, teacher_id=current_user.id).first()
    if record is None:
        abort(404)

    if record.status != "returned":
        record.status = "returned"
        record.return_date = date.today()
        db.session.commit()
        flash("Checkout marked as returned.", "success")

    return redirect(request.referrer or url_for("main.dashboard"))

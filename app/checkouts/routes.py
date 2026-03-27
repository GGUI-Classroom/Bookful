from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.checkouts import checkouts_bp
from app.extensions import db
from app.forms import CheckoutForm, HistoryFilterForm
from app.models import Book, CheckoutRecord, Student


def _student_choices():
    students = (
        Student.query.filter_by(teacher_id=current_user.id)
        .order_by(Student.name.asc())
        .all()
    )
    return [(0, "-- Select a student --")] + [(s.id, s.name) for s in students]


def _book_choices():
    books = (
        Book.query.filter_by(teacher_id=current_user.id)
        .order_by(Book.title.asc())
        .all()
    )
    return [(0, "-- Select a book --")] + [(b.id, f"{b.title} by {b.author}") for b in books]


@checkouts_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_checkout():
    form = CheckoutForm()
    form.existing_student_id.choices = _student_choices()
    form.existing_book_id.choices = _book_choices()

    if form.validate_on_submit():
        if form.existing_student_id.data:
            student = Student.query.filter_by(
                id=form.existing_student_id.data,
                teacher_id=current_user.id,
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

    return render_template(
        "checkouts/records.html",
        form=form,
        records=records,
        record_count=len(records),
    )


@checkouts_bp.get("/history")
@login_required
def history():
    return redirect(url_for("checkouts.records"))


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

from datetime import date, datetime
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.forms import PortalCodeForm, PortalNewAccountForm, PortalOldAccountForm
from app.models import Book, CheckoutRecord, Classroom, Student, StudentAccount
from app.portal import portal_bp
from app.utils.matching import find_best_name_match


def _current_student_account() -> StudentAccount | None:
    account_id = session.get("student_portal_account_id")
    if not account_id:
        return None
    return db.session.get(StudentAccount, account_id)


@portal_bp.app_context_processor
def inject_student_portal_context():
    account = _current_student_account()
    return {
        "student_portal_account": account,
        "student_portal_student": account.student if account else None,
        "student_portal_active": account is not None,
    }


def student_portal_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if _current_student_account() is None:
            flash("Sign in to your student account first.", "warning")
            return redirect(url_for("portal.index"))
        return view(*args, **kwargs)

    return wrapper


def _student_for_classroom(classroom: Classroom, name: str) -> Student | None:
    students = (
        Student.query.filter_by(teacher_id=classroom.teacher_id, classroom_id=classroom.id, is_archived=False)
        .options(joinedload(Student.account))
        .all()
    )
    student, _score = find_best_name_match(name, students, lambda item: item.name, minimum_score=0.78)
    return student


def _classroom_for_join_code(join_code: str) -> Classroom:
    return Classroom.query.filter_by(join_code=join_code.upper()).first_or_404()


@portal_bp.get("/")
def index():
    account = _current_student_account()
    if account:
        return redirect(url_for("portal.dashboard"))
    return redirect(url_for("portal.join_with_code"))


@portal_bp.route("/join", methods=["GET", "POST"])
def join_with_code():
    if _current_student_account() is not None:
        flash("You are already signed in.", "info")
        return redirect(url_for("portal.dashboard"))

    form = PortalCodeForm()

    if form.validate_on_submit():
        classroom = Classroom.query.filter_by(join_code=form.join_code.data.strip().upper()).first()
        if classroom is None:
            flash("That class code is not valid.", "danger")
            return render_template("portal/join_code.html", form=form)
        return redirect(url_for("portal.choose_account", join_code=classroom.join_code))

    return render_template("portal/join_code.html", form=form)


@portal_bp.get("/join/<string:join_code>")
def choose_account(join_code: str):
    if _current_student_account() is not None:
        flash("You are already signed in.", "info")
        return redirect(url_for("portal.dashboard"))

    classroom = _classroom_for_join_code(join_code)
    return render_template("portal/choose_account.html", classroom=classroom)


@portal_bp.route("/join/<string:join_code>/new", methods=["GET", "POST"])
def new_account(join_code: str):
    if _current_student_account() is not None:
        flash("You are already signed in.", "info")
        return redirect(url_for("portal.dashboard"))

    classroom = _classroom_for_join_code(join_code)
    form = PortalNewAccountForm()

    if form.validate_on_submit():
        student = _student_for_classroom(classroom, form.student_name.data)
        if student is None:
            flash("We could not match that name to the class roster.", "danger")
            return render_template("portal/new_account.html", form=form, classroom=classroom)

        if student.account is not None:
            flash("This student already has an account. Choose Old Account.", "info")
            return redirect(url_for("portal.old_account", join_code=classroom.join_code))

        account = StudentAccount(student_id=student.id)
        account.set_password(form.password.data)
        db.session.add(account)

        account.last_login_at = datetime.utcnow()
        db.session.commit()

        session["student_portal_account_id"] = account.id
        flash("Student account created.", "success")
        return redirect(url_for("portal.dashboard"))

    return render_template("portal/new_account.html", form=form, classroom=classroom)


@portal_bp.route("/join/<string:join_code>/old", methods=["GET", "POST"])
def old_account(join_code: str):
    if _current_student_account() is not None:
        flash("You are already signed in.", "info")
        return redirect(url_for("portal.dashboard"))

    classroom = _classroom_for_join_code(join_code)
    form = PortalOldAccountForm()

    if form.validate_on_submit():
        student = _student_for_classroom(classroom, form.student_name.data)
        if student is None or student.account is None:
            flash("No student account was found for that name.", "danger")
            return render_template("portal/old_account.html", form=form, classroom=classroom)

        if not student.account.check_password(form.password.data):
            flash("Incorrect password.", "danger")
            return render_template("portal/old_account.html", form=form, classroom=classroom)

        student.account.last_login_at = datetime.utcnow()
        db.session.commit()

        session["student_portal_account_id"] = student.account.id
        flash("Welcome back.", "success")
        return redirect(url_for("portal.dashboard"))

    return render_template("portal/old_account.html", form=form, classroom=classroom)


@portal_bp.get("/dashboard")
@student_portal_required
def dashboard():
    account = _current_student_account()
    student = account.student

    active_checkouts = (
        CheckoutRecord.query.options(joinedload(CheckoutRecord.book))
        .filter(
            CheckoutRecord.student_id == student.id,
            CheckoutRecord.status == "checked_out",
        )
        .order_by(CheckoutRecord.due_date.asc().nullslast(), CheckoutRecord.checkout_date.desc())
        .all()
    )

    previous_checkouts = (
        CheckoutRecord.query.options(joinedload(CheckoutRecord.book))
        .filter(
            CheckoutRecord.student_id == student.id,
            CheckoutRecord.status == "returned",
        )
        .order_by(CheckoutRecord.return_date.desc().nullslast(), CheckoutRecord.checkout_date.desc())
        .limit(8)
        .all()
    )

    books = (
        Book.query.filter_by(teacher_id=student.teacher_id)
        .order_by(Book.title.asc())
        .all()
    )

    return render_template(
        "portal/dashboard.html",
        student=student,
        account=account,
        classroom=student.classroom,
        active_checkouts=active_checkouts,
        previous_checkouts=previous_checkouts,
        books=books,
    )


@portal_bp.get("/collection")
@student_portal_required
def collection():
    account = _current_student_account()
    student = account.student

    active_records = CheckoutRecord.query.filter_by(student_id=student.id, status="checked_out").all()
    active_by_book_id = {record.book_id: record for record in active_records}

    books = (
        Book.query.filter_by(teacher_id=student.teacher_id)
        .order_by(Book.title.asc())
        .all()
    )

    return render_template(
        "portal/collection.html",
        student=student,
        classroom=student.classroom,
        books=books,
        active_by_book_id=active_by_book_id,
    )


@portal_bp.get("/logout")
def logout():
    session.pop("student_portal_account_id", None)
    flash("You have been signed out of the student portal.", "info")
    return redirect(url_for("portal.index"))
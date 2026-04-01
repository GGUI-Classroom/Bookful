from datetime import date, datetime
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.forms import PortalClaimForm, PortalJoinForm, PortalLoginForm
from app.models import Book, CheckoutRecord, Classroom, Student, StudentAccount
from app.portal import portal_bp
from app.utils.matching import find_best_name_match


def _current_student_account() -> StudentAccount | None:
    account_id = session.get("student_portal_account_id")
    if not account_id:
        return None
    return db.session.get(StudentAccount, account_id)


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
        Student.query.filter_by(teacher_id=classroom.teacher_id, classroom_id=classroom.id)
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
    return render_template("portal/index.html")


@portal_bp.route("/join/<string:join_code>", methods=["GET", "POST"])
def join(join_code: str):
    classroom = _classroom_for_join_code(join_code)
    form = PortalJoinForm()

    if form.validate_on_submit():
        student = _student_for_classroom(classroom, form.student_name.data)
        if student is None:
            flash("We could not match that name to the class roster.", "danger")
            return render_template("portal/join.html", form=form, classroom=classroom)

        if student.account is not None:
            flash("That student already has an account. Sign in instead.", "info")
            return redirect(url_for("portal.login", join_code=classroom.join_code, student_name=form.student_name.data.strip()))

        session["student_portal_pending_student_id"] = student.id
        session["student_portal_pending_classroom_id"] = classroom.id
        session["student_portal_pending_student_name"] = student.name
        return redirect(url_for("portal.claim"))

    return render_template("portal/join.html", form=form, classroom=classroom)


@portal_bp.route("/claim", methods=["GET", "POST"])
def claim():
    student_id = session.get("student_portal_pending_student_id")
    if not student_id:
        flash("Start by joining a class first.", "warning")
        return redirect(url_for("portal.index"))

    student = db.session.get(Student, student_id)
    if student is None:
        session.pop("student_portal_pending_student_id", None)
        session.pop("student_portal_pending_classroom_id", None)
        session.pop("student_portal_pending_student_name", None)
        flash("We could not find that student record.", "danger")
        return redirect(url_for("portal.index"))

    classroom = student.classroom
    form = PortalClaimForm()

    if form.validate_on_submit():
        if student.account is None:
            account = StudentAccount(student_id=student.id)
            account.set_password(form.password.data)
            db.session.add(account)
        else:
            account = student.account
            account.set_password(form.password.data)

        account.last_login_at = datetime.utcnow()
        db.session.commit()

        session["student_portal_account_id"] = account.id
        session.pop("student_portal_pending_student_id", None)
        session.pop("student_portal_pending_classroom_id", None)
        session.pop("student_portal_pending_student_name", None)
        flash("Student account created.", "success")
        return redirect(url_for("portal.dashboard"))

    return render_template(
        "portal/claim.html",
        form=form,
        student=student,
        classroom=classroom,
    )


@portal_bp.route("/login", methods=["GET", "POST"])
def login():
    form = PortalLoginForm()
    join_code = request.args.get("join_code", "").strip()
    student_name = request.args.get("student_name", "").strip()
    if join_code and not form.join_code.data:
        form.join_code.data = join_code
    if student_name and not form.student_name.data:
        form.student_name.data = student_name

    if form.validate_on_submit():
        classroom = Classroom.query.filter_by(join_code=form.join_code.data.strip().upper()).first()
        if classroom is None:
            flash("That class code is not valid.", "danger")
            return render_template("portal/login.html", form=form)

        student = _student_for_classroom(classroom, form.student_name.data)
        if student is None or student.account is None:
            flash("No student account was found for that name.", "danger")
            return render_template("portal/login.html", form=form)

        if not student.account.check_password(form.password.data):
            flash("Incorrect password.", "danger")
            return render_template("portal/login.html", form=form)

        student.account.last_login_at = datetime.utcnow()
        db.session.commit()

        session["student_portal_account_id"] = student.account.id
        flash("Welcome back.", "success")
        return redirect(url_for("portal.dashboard"))

    return render_template("portal/login.html", form=form)


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
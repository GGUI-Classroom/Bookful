from datetime import date

from flask import redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.models import Book, CheckoutRecord, Student


@main_bp.get("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("home.html")


@main_bp.get("/how-to-use")
def how_to_use():
    return render_template("how_to_use.html")


@main_bp.get("/dashboard")
@login_required
def dashboard():
    student_count = Student.query.filter_by(teacher_id=current_user.id).count()
    book_count = Book.query.filter_by(teacher_id=current_user.id).count()
    active_checkout_count = CheckoutRecord.query.filter_by(
        teacher_id=current_user.id,
        status="checked_out",
    ).count()

    # Calculate overdue checkouts
    overdue_checkouts = (
        CheckoutRecord.query.options(
            joinedload(CheckoutRecord.student),
            joinedload(CheckoutRecord.book),
        )
        .filter(
            CheckoutRecord.teacher_id == current_user.id,
            CheckoutRecord.status == "checked_out",
            CheckoutRecord.due_date.isnot(None),
            CheckoutRecord.due_date < date.today(),
        )
        .order_by(CheckoutRecord.due_date.asc())
        .all()
    )
    overdue_count = len(overdue_checkouts)

    active_checkouts = (
        CheckoutRecord.query.options(
            joinedload(CheckoutRecord.student),
            joinedload(CheckoutRecord.book),
        )
        .filter(
            CheckoutRecord.teacher_id == current_user.id,
            CheckoutRecord.status == "checked_out",
        )
        .order_by(CheckoutRecord.checkout_date.desc(), CheckoutRecord.id.desc())
        .all()
    )

    # Get recent returns for activity summary (last 7 days)
    recent_returns = (
        CheckoutRecord.query.options(
            joinedload(CheckoutRecord.student),
            joinedload(CheckoutRecord.book),
        )
        .filter(
            CheckoutRecord.teacher_id == current_user.id,
            CheckoutRecord.status == "returned",
        )
        .order_by(CheckoutRecord.return_date.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "dashboard.html",
        student_count=student_count,
        book_count=book_count,
        active_checkout_count=active_checkout_count,
        overdue_count=overdue_count,
        overdue_checkouts=overdue_checkouts,
        active_checkouts=active_checkouts,
        recent_returns=recent_returns,
    )

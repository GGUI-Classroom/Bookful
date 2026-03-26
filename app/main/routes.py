from flask import redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.models import Book, CheckoutRecord, Student


@main_bp.get("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.get("/dashboard")
@login_required
def dashboard():
    student_count = Student.query.filter_by(teacher_id=current_user.id).count()
    book_count = Book.query.filter_by(teacher_id=current_user.id).count()
    active_checkout_count = CheckoutRecord.query.filter_by(
        teacher_id=current_user.id,
        status="checked_out",
    ).count()

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

    return render_template(
        "dashboard.html",
        student_count=student_count,
        book_count=book_count,
        active_checkout_count=active_checkout_count,
        active_checkouts=active_checkouts,
    )

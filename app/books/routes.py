from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.books import books_bp
from app.extensions import db
from app.forms import BookForm
from app.models import Book


@books_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = BookForm()
    search_query = request.args.get("q", "").strip()

    if form.validate_on_submit():
        book = Book(
            teacher_id=current_user.id,
            title=form.title.data.strip(),
            author=form.author.data.strip(),
            isbn=(form.isbn.data or "").strip() or None,
        )
        db.session.add(book)
        db.session.commit()
        flash("Book added.", "success")
        return redirect(url_for("books.index"))

    query = Book.query.filter_by(teacher_id=current_user.id)
    if search_query:
        query = query.filter(
            (Book.title.ilike(f"%{search_query}%"))
            | (Book.author.ilike(f"%{search_query}%"))
            | (Book.isbn.ilike(f"%{search_query}%"))
        )

    books = query.order_by(Book.title.asc()).all()

    return render_template(
        "books/index.html",
        form=form,
        books=books,
        search_query=search_query,
    )


@books_bp.route("/<int:book_id>/edit", methods=["GET", "POST"])
@login_required
def edit(book_id: int):
    book = Book.query.filter_by(id=book_id, teacher_id=current_user.id).first_or_404()
    form = BookForm(obj=book)
    form.submit.label.text = "Update Book"

    if form.validate_on_submit():
        book.title = form.title.data.strip()
        book.author = form.author.data.strip()
        book.isbn = (form.isbn.data or "").strip() or None
        db.session.commit()
        flash("Book updated.", "success")
        return redirect(url_for("books.index"))

    return render_template("books/edit.html", form=form, book=book)

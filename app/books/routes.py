import json
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import flash, jsonify, redirect, render_template, request, url_for
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


@books_bp.get("/open-library-search")
@login_required
def open_library_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])

    params = urlencode({"q": query, "limit": 5})
    endpoint = f"https://openlibrary.org/search.json?{params}"

    try:
        with urlopen(endpoint, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return jsonify([])

    results = []
    seen = set()
    for doc in payload.get("docs", []):
        title = (doc.get("title") or "").strip()
        if not title:
            continue

        author_names = doc.get("author_name") or []
        author = ", ".join(author_names[:2]).strip()

        isbn_list = doc.get("isbn") or []
        isbn = next((item for item in isbn_list if item), "")

        cover_id = doc.get("cover_i")
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else ""

        dedupe_key = f"{title}|{author}|{isbn}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        results.append(
            {
                "title": title,
                "author": author,
                "isbn": isbn,
                "cover_url": cover_url,
            }
        )

        if len(results) >= 5:
            break

    return jsonify(results)

from flask import Blueprint


books_bp = Blueprint("books", __name__, url_prefix="/books")

from app.books import routes  # noqa: E402,F401

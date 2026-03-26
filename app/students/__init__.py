from flask import Blueprint


students_bp = Blueprint("students", __name__, url_prefix="/students")

from app.students import routes  # noqa: E402,F401

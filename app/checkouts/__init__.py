from flask import Blueprint


checkouts_bp = Blueprint("checkouts", __name__, url_prefix="/checkouts")

from app.checkouts import routes  # noqa: E402,F401

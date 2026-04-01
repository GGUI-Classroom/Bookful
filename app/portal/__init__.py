from flask import Blueprint


portal_bp = Blueprint("portal", __name__, url_prefix="/portal")

from app.portal import routes  # noqa: E402,F401
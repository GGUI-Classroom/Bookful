from flask import Flask
from sqlalchemy import inspect, text

from app.extensions import csrf, db, login_manager, migrate
from app.models import Classroom, StudentAccount


def _ensure_schema_compatibility() -> None:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    # Add new teacher auth columns for older databases.
    if "teacher" in tables:
        teacher_columns = {column["name"] for column in inspector.get_columns("teacher")}
        if "auth_provider" not in teacher_columns:
            db.session.execute(text("ALTER TABLE teacher ADD COLUMN auth_provider VARCHAR(30) NOT NULL DEFAULT 'local'"))
        if "external_subject" not in teacher_columns:
            db.session.execute(text("ALTER TABLE teacher ADD COLUMN external_subject VARCHAR(255)"))
        if "external_email" not in teacher_columns:
            db.session.execute(text("ALTER TABLE teacher ADD COLUMN external_email VARCHAR(255)"))

    if "classroom" not in tables:
        Classroom.__table__.create(bind=db.engine, checkfirst=True)

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    if "student" in tables:
        student_columns = {column["name"] for column in inspector.get_columns("student")}
        if "classroom_id" not in student_columns:
            db.session.execute(text("ALTER TABLE student ADD COLUMN classroom_id INTEGER"))
        if "is_archived" not in student_columns:
            db.session.execute(text("ALTER TABLE student ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"))
        if "archived_at" not in student_columns:
            db.session.execute(text("ALTER TABLE student ADD COLUMN archived_at DATETIME"))

    if "book" in tables:
        book_columns = {column["name"] for column in inspector.get_columns("book")}
        if "is_archived" not in book_columns:
            db.session.execute(text("ALTER TABLE book ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"))
        if "archived_at" not in book_columns:
            db.session.execute(text("ALTER TABLE book ADD COLUMN archived_at DATETIME"))

    if "student_account" not in tables:
        StudentAccount.__table__.create(bind=db.engine, checkfirst=True)

    db.session.commit()


def create_app(config_object: str = "config.Config") -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app import models  # noqa: F401
    from app.auth import auth_bp
    from app.classes import classes_bp
    from app.books import books_bp
    from app.checkouts import checkouts_bp
    from app.main import main_bp
    from app.portal import portal_bp
    from app.students import students_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(classes_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(checkouts_bp)

    # Safety net for first deploys where migrations were not run yet.
    with app.app_context():
        db.create_all()
        _ensure_schema_compatibility()

    return app

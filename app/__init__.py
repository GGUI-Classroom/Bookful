from flask import Flask

from app.extensions import csrf, db, login_manager, migrate


def create_app(config_object: str = "config.Config") -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app import models  # noqa: F401
    from app.auth import auth_bp
    from app.books import books_bp
    from app.checkouts import checkouts_bp
    from app.main import main_bp
    from app.students import students_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(books_bp)
    app.register_blueprint(checkouts_bp)

    # Safety net for first deploys where migrations were not run yet.
    with app.app_context():
        db.create_all()

    return app

import secrets
from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager


@login_manager.user_loader
def load_user(user_id: str):
    return Teacher.query.get(int(user_id))


class Teacher(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    auth_provider = db.Column(db.String(30), nullable=False, default="local", index=True)
    external_subject = db.Column(db.String(255), unique=True, nullable=True, index=True)
    external_email = db.Column(db.String(255), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    students = db.relationship("Student", backref="teacher", lazy="dynamic", cascade="all, delete-orphan")
    books = db.relationship("Book", backref="teacher", lazy="dynamic", cascade="all, delete-orphan")
    checkouts = db.relationship("CheckoutRecord", backref="teacher", lazy="dynamic", cascade="all, delete-orphan")
    classrooms = db.relationship("Classroom", backref="teacher", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class Classroom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    join_code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    allow_student_checkouts = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    students = db.relationship("Student", backref="classroom", lazy="dynamic")

    def regenerate_join_code(self) -> None:
        self.join_code = secrets.token_urlsafe(8).replace("-", "").replace("_", "").upper()


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False, index=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classroom.id"), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    grade = db.Column(db.String(20), nullable=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)

    account = db.relationship("StudentAccount", backref="student", uselist=False, cascade="all, delete-orphan")
    checkout_records = db.relationship("CheckoutRecord", backref="student", lazy="dynamic")


class StudentAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    author = db.Column(db.String(255), nullable=False)
    isbn = db.Column(db.String(50), nullable=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)

    checkout_records = db.relationship("CheckoutRecord", backref="book", lazy="dynamic")


class CheckoutRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    book_id = db.Column(db.Integer, db.ForeignKey("book.id"), nullable=False, index=True)
    checkout_date = db.Column(db.Date, default=date.today, nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    return_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="checked_out", index=True)

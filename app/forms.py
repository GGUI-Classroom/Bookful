from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField, FileField, IntegerField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, ValidationError


class SignUpForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create Account")


class LoginForm(FlaskForm):
    identifier = StringField("Username or Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log In")


class StudentForm(FlaskForm):
    name = StringField("Student Name", validators=[DataRequired(), Length(max=120)])
    classroom_id = SelectField("Classroom", coerce=int, default=0)
    submit = SubmitField("Add Student")


class RosterImportForm(FlaskForm):
    classroom_id = SelectField("Classroom", coerce=int, default=0)
    roster_text = TextAreaField("Roster Names (one per line or CSV rows)", validators=[Optional(), Length(max=10000)])
    roster_file = FileField("Roster CSV or TXT", validators=[Optional()])
    submit = SubmitField("Import Roster")


class BookForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    author = StringField("Author", validators=[DataRequired(), Length(max=255)])
    isbn = StringField("ISBN (Optional)", validators=[Optional(), Length(max=50)])
    submit = SubmitField("Add Book")


class ClassroomForm(FlaskForm):
    name = StringField("Class Name", validators=[DataRequired(), Length(max=120)])
    default_self_checkout_days = IntegerField(
        "Self-Checkout Due In (Days)",
        validators=[DataRequired(), NumberRange(min=1, max=3650)],
        default=14,
    )
    submit = SubmitField("Create Class")


class JoinClassForm(FlaskForm):
    join_code = StringField("Class Code", validators=[DataRequired(), Length(max=32)])
    student_name = StringField("Student Name", validators=[DataRequired(), Length(max=120)])
    grade = StringField("Grade (Optional)", validators=[Optional(), Length(max=20)])
    submit = SubmitField("Join Class")


class PortalCodeForm(FlaskForm):
    join_code = StringField("Class Code", validators=[DataRequired(), Length(max=32)])
    submit = SubmitField("Continue")


class PortalNewAccountForm(FlaskForm):
    student_name = StringField("Registered Student Name", validators=[DataRequired(), Length(max=120)])
    password = PasswordField("Create Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create Account")


class PortalOldAccountForm(FlaskForm):
    student_name = StringField("Student Name", validators=[DataRequired(), Length(max=120)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign In")


class StudentBorrowForm(FlaskForm):
    book_id = SelectField("Book", coerce=int, default=0)
    submit = SubmitField("Borrow Book")


class RecordImportForm(FlaskForm):
    classroom_id = SelectField("Classroom", coerce=int, default=0)
    records_file = FileField("CSV File", validators=[DataRequired()])
    submit = SubmitField("Import Records")


class CheckoutForm(FlaskForm):
    existing_student_id = SelectField("Select Existing Student", coerce=int, default=0)
    new_student_name = StringField("Or Add New Student", validators=[Optional(), Length(max=120)])

    existing_book_id = SelectField("Select Existing Book", coerce=int, default=0)
    new_book_title = StringField("Or Add New Book Title", validators=[Optional(), Length(max=255)])
    new_book_author = StringField("New Book Author", validators=[Optional(), Length(max=255)])
    new_book_isbn = StringField("New Book ISBN (Optional)", validators=[Optional(), Length(max=50)])

    checkout_date = DateField("Checkout Date", validators=[DataRequired()])
    due_date = DateField("Due Date (Optional)", validators=[Optional()])

    submit = SubmitField("Create Checkout")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if not valid:
            return False

        has_existing_student = self.existing_student_id.data and self.existing_student_id.data > 0
        has_new_student = bool((self.new_student_name.data or "").strip())
        if not has_existing_student and not has_new_student:
            self.new_student_name.errors.append("Select an existing student or add a new one.")
            return False

        has_existing_book = self.existing_book_id.data and self.existing_book_id.data > 0
        has_new_book_title = bool((self.new_book_title.data or "").strip())
        has_new_book_author = bool((self.new_book_author.data or "").strip())

        if not has_existing_book and not has_new_book_title:
            self.new_book_title.errors.append("Select an existing book or add a new one.")
            return False

        if has_new_book_title and not has_new_book_author:
            self.new_book_author.errors.append("Author is required when creating a new book.")
            return False

        if self.due_date.data and self.due_date.data < self.checkout_date.data:
            self.due_date.errors.append("Due date cannot be before checkout date.")
            return False

        return True


class HistoryFilterForm(FlaskForm):
    student_id = SelectField("Student", choices=[("", "All Students")], default="")
    book_id = SelectField("Book", choices=[("", "All Books")], default="")
    status = SelectField(
        "Status",
        choices=[("", "All"), ("active", "Active"), ("returned", "Returned")],
        default="",
    )

    def validate_student_id(self, field):
        if field.data and not field.data.isdigit():
            raise ValidationError("Invalid student filter.")

    def validate_book_id(self, field):
        if field.data and not field.data.isdigit():
            raise ValidationError("Invalid book filter.")

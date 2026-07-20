import os
import ssl
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
    GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
    GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
    GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL", "")
    GMAIL_SENDER_NAME = os.getenv("GMAIL_SENDER_NAME", "Bookful Reports")
    REPORT_JOB_SECRET = os.getenv("REPORT_JOB_SECRET", "")
    REPORT_ADMIN_EMAIL = os.getenv("REPORT_ADMIN_EMAIL", "g.gui.cmpny@gmail.com").strip().lower()

    database_url = os.getenv("DATABASE_URL", "sqlite:///bookful_local.db")
    use_postgres_ssl = False

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if database_url.startswith("postgresql://"):
        use_postgres_ssl = True
        parsed_url = urlsplit(database_url)
        query = urlencode(
            [
                (key, value)
                for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)
                if key.lower() != "sslmode"
            ]
        )
        database_url = urlunsplit(parsed_url._replace(query=query))
        database_url = database_url.replace("postgresql://", "postgresql+pg8000://", 1)

    SQLALCHEMY_DATABASE_URI = database_url
    if use_postgres_ssl:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {"ssl_context": ssl_context},
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

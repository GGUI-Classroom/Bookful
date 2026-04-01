import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")

    CLASSLINK_ENABLED = os.getenv("CLASSLINK_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    CLASSLINK_AUTHORIZE_URL = os.getenv("CLASSLINK_AUTHORIZE_URL", "")
    CLASSLINK_TOKEN_URL = os.getenv("CLASSLINK_TOKEN_URL", "")
    CLASSLINK_USERINFO_URL = os.getenv("CLASSLINK_USERINFO_URL", "")
    CLASSLINK_CLIENT_ID = os.getenv("CLASSLINK_CLIENT_ID", "")
    CLASSLINK_CLIENT_SECRET = os.getenv("CLASSLINK_CLIENT_SECRET", "")
    CLASSLINK_REDIRECT_URI = os.getenv("CLASSLINK_REDIRECT_URI", "")
    CLASSLINK_SCOPES = os.getenv("CLASSLINK_SCOPES", "openid profile email")

    database_url = os.getenv("DATABASE_URL", "sqlite:///bookful_local.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+pg8000://", 1)

    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

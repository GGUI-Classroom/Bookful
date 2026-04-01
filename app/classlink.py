from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


class ClassLinkError(RuntimeError):
    pass


def is_enabled() -> bool:
    config = current_app.config
    required_values = [
        config.get("CLASSLINK_AUTHORIZE_URL"),
        config.get("CLASSLINK_TOKEN_URL"),
        config.get("CLASSLINK_USERINFO_URL"),
        config.get("CLASSLINK_CLIENT_ID"),
        config.get("CLASSLINK_CLIENT_SECRET"),
        config.get("CLASSLINK_REDIRECT_URI"),
    ]
    return bool(config.get("CLASSLINK_ENABLED") and all(required_values))


def build_authorize_url(state: str) -> str:
    config = current_app.config
    params = {
        "response_type": "code",
        "client_id": config["CLASSLINK_CLIENT_ID"],
        "redirect_uri": config["CLASSLINK_REDIRECT_URI"],
        "scope": config.get("CLASSLINK_SCOPES", "openid profile email"),
        "state": state,
    }
    return f"{config['CLASSLINK_AUTHORIZE_URL']}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> str:
    config = current_app.config
    payload = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config["CLASSLINK_REDIRECT_URI"],
            "client_id": config["CLASSLINK_CLIENT_ID"],
            "client_secret": config["CLASSLINK_CLIENT_SECRET"],
        }
    ).encode("utf-8")

    request = Request(
        config["CLASSLINK_TOKEN_URL"],
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ClassLinkError(f"Token request failed with status {exc.code}.") from exc
    except URLError as exc:
        raise ClassLinkError("Could not reach the ClassLink token endpoint.") from exc

    access_token = body.get("access_token")
    if not access_token:
        raise ClassLinkError("ClassLink token response did not include an access token.")
    return access_token


def fetch_userinfo(access_token: str) -> dict[str, Any]:
    config = current_app.config
    request = Request(
        config["CLASSLINK_USERINFO_URL"],
        headers={"Authorization": f"Bearer {access_token}"},
    )

    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ClassLinkError(f"ClassLink profile request failed with status {exc.code}.") from exc
    except URLError as exc:
        raise ClassLinkError("Could not reach the ClassLink profile endpoint.") from exc

import re
import secrets
from threading import Lock
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, redirect, request


app = Flask(__name__, static_folder=None)
urls = {}
# ponytail: one process-local lock; use atomic shared storage for multiple processes.
codes_lock = Lock()


class ExactRedirectResponse(Response):
    def get_wsgi_headers(self, environ):
        headers = super().get_wsgi_headers(environ)
        headers["Location"] = self.headers["Location"]
        return headers


@app.post("/shorten")
def shorten():
    data = request.get_json(silent=True)
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not (url := url.strip()):
        return jsonify(error="invalid URL"), 400

    try:
        parsed = urlsplit(url)
        valid = (
            re.search(r"[\s\\\x00-\x1f\x7f-\x9f]|%(?![0-9A-Fa-f]{2})", url) is None
            and "%" not in parsed.netloc
            and parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
        )
        if valid:
            port = parsed.port
            normalized = urlsplit(
                redirect(url).get_wsgi_headers(request.environ)["Location"]
            )
            userinfo, separator, _ = normalized.netloc.rpartition("@")
            host = normalized.hostname
            if parsed.netloc.rpartition("@")[2].startswith("["):
                host = f"[{parsed.hostname}]"
            netloc = f"{userinfo}{separator}{host}" + (
                f":{port}" if port is not None else ""
            )
            url = normalized._replace(netloc=netloc).geturl()
    except (UnicodeError, ValueError):
        valid = False
    if not valid:
        return jsonify(error="invalid URL"), 400

    code = secrets.token_urlsafe(6)
    with codes_lock:
        while code in urls:
            code = secrets.token_urlsafe(6)
        urls[code] = url
    return jsonify(code=code, short_url=f"/{code}"), 201


@app.get("/<code>")
def follow(code):
    if code not in urls:
        return jsonify(error="code not found"), 404
    return ExactRedirectResponse(status=302, headers={"Location": urls[code]})

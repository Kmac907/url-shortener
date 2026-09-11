import re
import secrets
from threading import Lock
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, request


app = Flask(__name__, static_folder=None)
urls = {}
# ponytail: one process-local lock; use atomic shared storage for multiple processes.
codes_lock = Lock()


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
            and parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
        )
        if valid:
            url = redirect(url).get_wsgi_headers(request.environ)["Location"]
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
    return redirect(urls[code])

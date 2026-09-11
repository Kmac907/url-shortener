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
        location = self.headers.pop("Location")
        try:
            headers = super().get_wsgi_headers(environ)
        finally:
            self.headers["Location"] = location
        headers["Location"] = location
        return headers


@app.post("/shorten")
def shorten():
    data = request.get_json(silent=True)
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not (url := url.strip()):
        return jsonify(error="invalid URL"), 400
    url = re.sub(
        r"^((?i:https?)://(?:[^/?#@]*@)?\[)V(?=[0-9A-Fa-f]+\.)", r"\1v", url
    )
    zone = re.search(
        r"^(?i:https?)://(?:[^/?#@]*@)?\[([0-9A-Fa-f:.]+)%25"
        r"((?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+)\]"
        r"(?=:\d*(?:[/?#]|$)|[/?#]|$)",
        url,
    )
    parse_url = url
    if zone:
        parse_url = (
            url[: zone.start(2)]
            + re.sub(r"%[0-9A-Fa-f]{2}", "x", zone[2])
            + url[zone.end(2) :]
        )

    try:
        parsed = urlsplit(parse_url)
        hostpart = parsed.netloc.rpartition("@")[2]
        valid = (
            re.search(r"[\s\\\x00-\x1f\x7f-\x9f]|%(?![0-9A-Fa-f]{2})", url) is None
            and re.search(r'["<>^`{|}]', parsed.netloc) is None
            and parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and (zone is not None or "%" not in parsed.hostname)
        )
        if valid:
            port = parsed.port
            normalized = urlsplit(
                redirect(parse_url).get_wsgi_headers(request.environ)["Location"]
            )
            userinfo, separator, _ = normalized.netloc.rpartition("@")
            host = normalized.hostname
            if hostpart.startswith("["):
                host = (
                    f"[{zone[1].lower()}%25{zone[2]}]"
                    if zone
                    else f"[{parsed.hostname}]"
                )
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

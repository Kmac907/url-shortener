import re
import secrets
from threading import Lock
from urllib.parse import quote, unquote, urlsplit

from flask import Flask, Response, jsonify, request


app = Flask(__name__, static_folder=None)
urls = {}
# ponytail: one process-local lock; use atomic shared storage for multiple processes.
codes_lock = Lock()


class ExactRedirectResponse(Response):
    def get_wsgi_headers(self, environ):
        location = self.headers["Location"]
        try:
            location.encode("latin-1")
        except UnicodeEncodeError:
            authority_start = location.index("://") + 3
            authority_end = min(
                (
                    position
                    for delimiter in "/?#"
                    if (position := location.find(delimiter, authority_start)) >= 0
                ),
                default=len(location),
            )
            userinfo_end = location.rfind("@", authority_start, authority_end)
            host_start = authority_start if userinfo_end < 0 else userinfo_end + 1
            if location.startswith("[", host_start):
                host_end = location.index("]", host_start, authority_end) + 1
                host = location[host_start:host_end]
            else:
                port_start = location.find(":", host_start, authority_end)
                host_end = authority_end if port_start < 0 else port_start
                host = location[host_start:host_end]
                if not host.isascii():
                    host = host.encode("idna").decode("ascii")
            location = (
                "".join(
                    character if character.isascii() else quote(character)
                    for character in location[:host_start]
                )
                + host
                + "".join(
                    character if character.isascii() else quote(character)
                    for character in location[host_end:]
                )
            )
            location.encode("ascii")

        self.headers.pop("Location")
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
    parse_url = re.sub(
        r"^((?i:https?)://(?:[^/?#@]*@)?\[)V(?=[0-9A-Fa-f]+\.)", r"\1v", url
    )
    zone = re.search(
        r"^(?i:https?)://(?:[^/?#@]*@)?\[([0-9A-Fa-f:.]+)%25"
        r"((?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+)\]"
        r"(?=:\d*(?:[/?#]|$)|[/?#]|$)",
        parse_url,
    )
    if zone:
        parse_url = (
            parse_url[: zone.start(2)]
            + re.sub(r"%[0-9A-Fa-f]{2}", "x", zone[2])
            + parse_url[zone.end(2) :]
        )

    try:
        parsed = urlsplit(parse_url)
        percent_hostname_valid = True
        if zone is None and parsed.hostname and "%" in parsed.hostname:
            decoded_hostname = unquote(parsed.hostname, errors="strict")
            ascii_hostname = decoded_hostname.encode("idna").decode("ascii")
            percent_hostname_valid = (
                re.fullmatch(r"[A-Za-z0-9._~-]+", ascii_hostname) is not None
            )
        valid = (
            re.search(r"[\s\\\x00-\x1f\x7f-\x9f]|%(?![0-9A-Fa-f]{2})", url) is None
            and re.search(r'["<>^`{|}]', parsed.netloc) is None
            and parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and percent_hostname_valid
        )
        if valid:
            parsed.port
            ExactRedirectResponse(
                status=302, headers={"Location": url}
            ).get_wsgi_headers(request.environ)
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

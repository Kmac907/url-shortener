import unittest
from unittest.mock import call, patch

from app import app, codes_lock, urls


class UrlShortenerTests(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()
        urls.clear()

    def test_valid_http_response(self):
        response = self.client.post(
            "/shorten", json={"url": "http://example.com/a/page"}
        )

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertTrue(body["code"])
        self.assertEqual(body["short_url"], f"/{body['code']}")
        self.assertEqual(urls[body["code"]], "http://example.com/a/page")

    def test_valid_https(self):
        response = self.client.post(
            "/shorten", json={"url": "  https://example.com/secure  "}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(urls[response.get_json()["code"]], "https://example.com/secure")

    def test_valid_normalized_urls(self):
        cases = [
            ("HTTP://example.com/a", "http://example.com/a"),
            ("HtTpS://example.com/a", "https://example.com/a"),
            ("https://EXAMPLE.COM/a", "https://example.com/a"),
            ("https://example.com/caf\u00e9", "https://example.com/caf%C3%A9"),
            ("https://\u00e9xample.com/a", "https://xn--xample-9ua.com/a"),
            ("https://example.com/a%20b", "https://example.com/a%20b"),
            ("http://127.0.0.1:8080/a?x=1#part", "http://127.0.0.1:8080/a?x=1#part"),
            ("https://[2001:db8::1]:8443/a", "https://[2001:db8::1]:8443/a"),
        ]

        for submitted, stored in cases:
            with self.subTest(url=submitted):
                created = self.client.post("/shorten", json={"url": submitted})
                body = created.get_json()

                self.assertEqual(created.status_code, 201)
                self.assertEqual(urls[body["code"]], stored)
                followed = self.client.get(body["short_url"])
                self.assertEqual(followed.status_code, 302)
                self.assertEqual(followed.headers["Location"], stored)

    def test_redirect(self):
        created = self.client.post(
            "/shorten", json={"url": "https://example.com/a/page?x=1"}
        ).get_json()

        response = self.client.get(created["short_url"])

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://example.com/a/page?x=1")

    def test_invalid_inputs(self):
        cases = [
            ("missing JSON", {}),
            (
                "malformed JSON",
                {"data": "{", "content_type": "application/json"},
            ),
            ("missing url", {"json": {}}),
            ("non-string url", {"json": {"url": 123}}),
            ("blank url", {"json": {"url": "  "}}),
            ("relative URL", {"json": {"url": "/a/page"}}),
            ("missing hostname", {"json": {"url": "https:///a/page"}}),
            ("non-HTTP scheme", {"json": {"url": "ftp://example.com/a"}}),
            ("malformed authority", {"json": {"url": "http://[invalid"}}),
            ("textual port", {"json": {"url": "https://example.com:port/a"}}),
            ("out-of-range port", {"json": {"url": "https://example.com:65536/a"}}),
            ("CR/LF target", {"json": {"url": "https://example.com/a\r\nX-Test: bad"}}),
            ("surrogate target", {"json": {"url": "https://example.com/" + chr(0xD800)}}),
            ("DEL in hostname", {"json": {"url": "http://exa\x7fmple.com/"}}),
            ("space in hostname", {"json": {"url": "http://exa mple.com/"}}),
            ("control in path", {"json": {"url": "http://example.com/\x01"}}),
            ("invalid percent escape", {"json": {"url": "https://example.com/%GG"}}),
            ("backslash", {"json": {"url": "https://example.com\\evil/"}}),
            ("space in path", {"json": {"url": "https://example.com/a b"}}),
            ("percent hostname", {"json": {"url": "http://%/"}}),
        ]

        for name, arguments in cases:
            with self.subTest(name=name):
                response = self.client.post("/shorten", **arguments)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": "invalid URL"})
                self.assertEqual(urls, {})

    def test_unknown_code(self):
        response = self.client.get("/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "code not found"})

    def test_collision_retries_without_overwriting(self):
        class LockedDict(dict):
            def __contains__(self, key):
                if not codes_lock.locked():
                    raise AssertionError("collision check must hold codes_lock")
                return super().__contains__(key)

            def __setitem__(self, key, value):
                if not codes_lock.locked():
                    raise AssertionError("insertion must hold codes_lock")
                return super().__setitem__(key, value)

        store = LockedDict({"taken": "https://first.example"})
        with (
            patch("app.urls", store),
            patch(
                "app.secrets.token_urlsafe",
                side_effect=["taken", "taken", "available"],
            ) as token_urlsafe,
        ):
            response = self.client.post(
                "/shorten", json={"url": "https://second.example"}
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["code"], "available")
        self.assertEqual(store["taken"], "https://first.example")
        self.assertEqual(store["available"], "https://second.example")
        self.assertEqual(token_urlsafe.call_args_list, [call(6), call(6), call(6)])

    @patch("app.secrets.token_urlsafe", side_effect=["first", "second"])
    def test_repeated_submissions_create_new_codes(self, token_urlsafe):
        first = self.client.post("/shorten", json={"url": "https://example.com"})
        second = self.client.post("/shorten", json={"url": "https://example.com"})

        self.assertEqual(first.get_json()["code"], "first")
        self.assertEqual(second.get_json()["code"], "second")
        self.assertEqual(urls, {"first": "https://example.com", "second": "https://example.com"})

    def test_route_map(self):
        routes = {
            (rule.rule, frozenset(rule.methods - {"HEAD", "OPTIONS"}))
            for rule in app.url_map.iter_rules()
        }

        self.assertIsNone(app.static_folder)
        self.assertEqual(
            routes,
            {
                ("/shorten", frozenset({"POST"})),
                ("/<code>", frozenset({"GET"})),
            },
        )


if __name__ == "__main__":
    unittest.main()

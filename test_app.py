import unittest
from unittest.mock import patch

from app import app, urls


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
        ]

        for name, arguments in cases:
            with self.subTest(name=name):
                response = self.client.post("/shorten", **arguments)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {"error": "invalid URL"})

    def test_unknown_code(self):
        response = self.client.get("/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "code not found"})

    @patch("app.secrets.token_urlsafe", side_effect=["taken", "taken", "available"])
    def test_collision_retries_without_overwriting(self, token_urlsafe):
        urls["taken"] = "https://first.example"

        response = self.client.post("/shorten", json={"url": "https://second.example"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["code"], "available")
        self.assertEqual(urls["taken"], "https://first.example")
        self.assertEqual(urls["available"], "https://second.example")
        self.assertEqual(token_urlsafe.call_count, 3)

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

# URL shortener

A two-endpoint, process-local Flask API.

```sh
python -m pip install Flask
python -m flask --app app run
```

Run the tests:

```sh
python -m unittest
```

Create and follow a short URL:

```sh
curl -X POST http://127.0.0.1:5000/shorten -H "Content-Type: application/json" -d '{"url":"https://example.com/a/page"}'
curl -i http://127.0.0.1:5000/RETURNED_CODE
```

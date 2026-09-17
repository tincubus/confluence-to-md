from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from confluence_to_md.cli import main

EMAIL = "op@example.com"
TOKEN = "test-token-not-for-live"
FIXTURES = Path(__file__).parent / "fixtures" / "sites"


def load_json(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


@contextmanager
def serve_spaces(
    responses: dict[str | None, Any], http_status: int = 200
) -> Iterator[str]:
    """HTTP Site for space-list JSON, keyed by cursor (None = first response)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if http_status != 200:
                self.send_error(http_status)
                return
            parsed = urlparse(self.path)
            if parsed.path != "/wiki/api/v2/spaces":
                self.send_error(404)
                return
            cursor = parse_qs(parsed.query).get("cursor", [None])[0]
            body = responses.get(cursor)
            if body is None:
                self.send_error(404)
                return
            payload = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_list_fails_when_credentials_are_missing(monkeypatch, capsys):
    monkeypatch.delenv("CONFLUENCE_EMAIL", raising=False)
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)

    code = main(["list", "https://example.atlassian.net"])

    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""


def test_list_prints_one_non_archived_space_per_line(monkeypatch, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    with serve_spaces({None: load_json("one-space/spaces.json")}) as site:
        code = main(["list", site])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "ENG Engineering\n"


def test_list_omits_archived_and_personal_spaces(monkeypatch, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    with serve_spaces({None: load_json("mixed-spaces/spaces.json")}) as site:
        code = main(["list", site])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "ENG Engineering\n"


def test_list_keeps_non_personal_types_and_identifies_personal_by_type(
    monkeypatch, capsys
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    with serve_spaces({None: load_json("space-types/spaces.json")}) as site:
        code = main(["list", site])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == (
        "ENG Engineering\nCOLAB Collab Space\nKB Knowledge Base\n~ops Ops\n"
    )


def test_list_prints_nothing_when_every_space_is_personal(monkeypatch, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    with serve_spaces({None: load_json("only-personal/spaces.json")}) as site:
        code = main(["list", site])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""


def test_list_follows_every_page_of_space_results(monkeypatch, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    responses = {
        None: load_json("paginated-spaces/first.json"),
        "second": load_json("paginated-spaces/second.json"),
    }
    with serve_spaces(responses) as site:
        code = main(["list", site])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "ENG Engineering\nTEAM Team Space\n"


def test_list_does_not_print_token_or_email(monkeypatch, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    with serve_spaces({None: load_json("one-space/spaces.json")}) as site:
        code = main(["list", site])

    captured = capsys.readouterr()
    assert code == 0
    combined = captured.out + captured.err
    assert EMAIL not in combined
    assert TOKEN not in combined


def test_list_fails_when_site_rejects_credentials(monkeypatch, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    with serve_spaces({None: {}}, http_status=401) as site:
        code = main(["list", site])

    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""
    combined = captured.out + captured.err
    assert EMAIL not in combined
    assert TOKEN not in combined

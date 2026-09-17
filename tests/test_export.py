from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from confluence_to_md.cli import main

EMAIL = "op@example.com"
TOKEN = "test-token-not-for-live"
FIXTURES = Path(__file__).parent / "fixtures" / "sites"


def load_json(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


@contextmanager
def serve_site(routes: dict[str, Any]) -> Iterator[str]:
    """HTTP Site for JSON keyed by URL path (query ignored)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = routes.get(urlparse(self.path).path)
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


def one_page_routes() -> dict[str, Any]:
    return {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": load_json("one-page/pages.json"),
    }


def test_export_fails_when_credentials_are_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("CONFLUENCE_EMAIL", raising=False)
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    vault = tmp_path / "vault"

    code = main(["export", "https://example.atlassian.net", str(vault), "ENG"])

    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""
    assert EMAIL not in captured.err
    assert TOKEN not in captured.err
    assert not vault.exists() or not any(vault.rglob("*.md"))


def test_export_fails_when_site_url_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    vault = tmp_path / "vault"

    code = main(["export", "", str(vault), "ENG"])

    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""
    assert EMAIL not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err
    assert not vault.exists() or not any(vault.rglob("*.md"))


def test_export_writes_one_note_for_one_page(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    vault = tmp_path / "vault"
    with serve_site(one_page_routes()) as site:
        code = main(["export", site, str(vault), "ENG"])
        source_url = f"{site}/wiki/spaces/ENG/pages/123456/Home"

    captured = capsys.readouterr()
    note = vault / "Engineering" / "Home" / "Home.md"
    text = note.read_text(encoding="utf-8")
    body = text.split("---", 2)[2].lstrip("\n")

    assert code == 0
    assert note.is_file()
    assert 'title: "Home"' in text
    assert 'confluence_id: "123456"' in text
    assert 'space_key: "ENG"' in text
    assert f'source_url: "{source_url}"' in text
    assert 'updated_at: "2026-09-17T04:00:00Z"' in text
    assert "parent_id:" not in text
    assert "labels:" not in text
    assert body.splitlines()[0] == f"[Home]({source_url})"
    assert EMAIL not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err
    assert EMAIL not in text
    assert TOKEN not in text

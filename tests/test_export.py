from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pytest

from confluence_to_md.cli import main

EMAIL = "op@example.com"
TOKEN = "test-token-not-for-live"
FIXTURES = Path(__file__).parent / "fixtures" / "sites"


def load_json(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


@contextmanager
def serve_site(routes: dict[str, Any]) -> Iterator[str]:
    """HTTP Site keyed by URL path (query ignored)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            body = routes.get(path)
            if isinstance(body, list):
                body = body.pop(0)
            if body is None and path.endswith("/attachments"):
                body = {"results": [], "_links": {}}
            if body is None or isinstance(body, int):
                self.send_error(404 if body is None else body)
                return
            if isinstance(body, bytes):
                payload = body
                content_type = "application/octet-stream"
            else:
                payload = json.dumps(body).encode("utf-8")
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
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


def make_page(
    page_id: str,
    title: str,
    *,
    space_key: str = "ENG",
    space_id: str = "111",
    parent_id: str | None = None,
    position: int | None = 0,
    body: str = "<p>Welcome</p>",
) -> dict[str, Any]:
    return {
        "id": page_id,
        "status": "current",
        "title": title,
        "spaceId": space_id,
        "parentId": parent_id,
        "position": position,
        "createdAt": "2026-09-17T04:00:00.000Z",
        "version": {
            "createdAt": "2026-09-17T04:00:00Z",
            "number": 1,
            "minorEdit": False,
        },
        "body": {"storage": {"representation": "storage", "value": body}},
        "_links": {"webui": f"/spaces/{space_key}/pages/{page_id}/{title}"},
    }


def make_attachment(
    attachment_id: str,
    title: str,
    *,
    page_id: str,
    media_type: str,
    download_path: str,
) -> dict[str, Any]:
    return {
        "id": attachment_id,
        "status": "current",
        "title": title,
        "pageId": page_id,
        "mediaType": media_type,
        "fileSize": 4,
        "downloadLink": download_path,
        "version": {
            "createdAt": "2026-09-17T04:00:00Z",
            "number": 3,
            "minorEdit": False,
        },
        "_links": {"download": download_path},
    }


def hierarchy_routes() -> dict[str, Any]:
    return {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("200", "Alpha", parent_id="100", position=1),
                make_page("400", "Grand", parent_id="200", position=0),
                make_page("100", "Home"),
                make_page("300", "Run book", parent_id="100", position=0),
            ],
            "_links": {},
        },
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
    assert "Welcome" in body
    assert EMAIL not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err
    assert EMAIL not in text
    assert TOKEN not in text


def test_export_sanitizes_slash_in_page_title(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = one_page_routes()
    page = routes["/wiki/api/v2/spaces/111/pages"]["results"][0]
    page["title"] = "Competitor Research (ข้อมูลคู่แข่ง/Market)"
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    folder = vault / "Engineering" / "Competitor Research (ข้อมูลคู่แข่ง-Market)"
    note = folder / "Competitor Research (ข้อมูลคู่แข่ง-Market).md"

    assert code == 0
    assert note.is_file()
    assert 'title: "Competitor Research (ข้อมูลคู่แข่ง/Market)"' in note.read_text(
        encoding="utf-8"
    )
    assert not (vault / "Engineering" / "Competitor Research (ข้อมูลคู่แข่ง").exists()


def test_export_drops_emoji_from_page_folder_and_note_name(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    title = "🔬  Competitor Research (ข้อมูลคู่แข่ง/Market) "
    routes = one_page_routes()
    page = routes["/wiki/api/v2/spaces/111/pages"]["results"][0]
    page["title"] = title
    page["_links"]["webui"] = f"/spaces/ENG/pages/123456/{title}"
    page["body"]["storage"]["value"] = "<p>See the 👋 notes</p>"
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        source_url = f"{site}/wiki/spaces/ENG/pages/123456/{title}"

    name = "Competitor Research (ข้อมูลคู่แข่ง-Market)"
    note = vault / "Engineering" / name / f"{name}.md"
    text = note.read_text(encoding="utf-8")

    assert code == 0
    assert note.is_file()
    assert not (vault / "Engineering" / title).exists()
    assert f'title: "{title}"' in text
    assert f"[{title}]({source_url})" in text
    assert "👋" in text


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("👨‍👩‍👧 Plans", "Plans"),
        ("❤️ Status", "Status"),
        ("⏰ ⭐ Status", "Status"),
        ("1️⃣ Page", "Page"),
        ("*️⃣", " (123456)"),
        ("©️ Legal", "Legal"),
        ("\U0001fc00 Future", "Future"),
    ],
)
def test_export_drops_emoji_sequences_and_pictographs(
    monkeypatch, tmp_path, title, name
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = one_page_routes()
    page = routes["/wiki/api/v2/spaces/111/pages"]["results"][0]
    page["title"] = title
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    note = vault / "Engineering" / name / f"{name}.md"

    assert code == 0
    assert note.is_file()
    assert f"title: {json.dumps(title, ensure_ascii=False)}" in note.read_text(
        encoding="utf-8"
    )
    assert not (vault / "Engineering" / title).exists()


def test_export_drops_emoji_from_space_folder_name(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = one_page_routes()
    routes["/wiki/api/v2/spaces"]["results"][0]["name"] = "🔬 Team / Ops"
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    note = vault / "Team - Ops" / "Home" / "Home.md"

    assert code == 0
    assert note.is_file()
    assert not (vault / "🔬 Team / Ops").exists()
    assert not (vault / "🔬 Team").exists()


def test_export_page_link_and_child_pages_use_sanitized_emoji_names(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>See "
        "<ac:link>"
        '<ri:page ri:content-title="🔬 Run book" ri:space-key="ENG" />'
        "<ac:plain-text-link-body><![CDATA[the runbook]]></ac:plain-text-link-body>"
        "</ac:link>"
        ".</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home", body=home_body),
                make_page("200", "🔬 Run book", parent_id="100", position=0),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    home_dir = vault / "Engineering" / "Home"
    home = (home_dir / "Home.md").read_text(encoding="utf-8")
    href = "Run%20book/Run%20book.md"
    link = f"[Run book]({href})"

    assert code == 0
    assert link in home
    assert "http" not in link
    assert (
        "<!-- confluence-to-md:children -->\n"
        "## Child pages\n"
        f"- {link}\n"
        "<!-- /confluence-to-md:children -->"
    ) in home
    assert (home_dir / unquote(href)).is_file()


def test_export_appends_page_id_when_sanitized_names_collide(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("1", "Home"),
                make_page("10", "Notes", parent_id="1", position=0),
                make_page("11", "🔬 Notes", parent_id="1", position=1),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    first = vault / "Engineering" / "Home" / "Notes" / "Notes.md"
    second = vault / "Engineering" / "Home" / "Notes (11)" / "Notes (11).md"

    assert code == 0
    assert first.is_file()
    assert second.is_file()
    assert 'title: "🔬 Notes"' in second.read_text(encoding="utf-8")


def test_export_appends_space_key_when_space_name_sanitizes_empty_or_collides(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": {
            "results": [
                {
                    "id": "111",
                    "key": "ENG",
                    "name": "🔬",
                    "type": "global",
                    "status": "current",
                },
                {
                    "id": "222",
                    "key": "TEAM",
                    "name": "🔬 Team",
                    "type": "global",
                    "status": "current",
                },
                {
                    "id": "333",
                    "key": "OPS",
                    "name": "Team",
                    "type": "global",
                    "status": "current",
                },
            ],
            "_links": {},
        },
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("1", "Home")],
            "_links": {},
        },
        "/wiki/api/v2/spaces/222/pages": {
            "results": [make_page("2", "Home", space_key="TEAM", space_id="222")],
            "_links": {},
        },
        "/wiki/api/v2/spaces/333/pages": {
            "results": [make_page("3", "Home", space_key="OPS", space_id="333")],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG", "TEAM", "OPS"])

    assert code == 0
    assert (vault / " (ENG)" / "Home" / "Home.md").is_file()
    assert (vault / "Team" / "Home" / "Home.md").is_file()
    assert (vault / "Team (OPS)" / "Home" / "Home.md").is_file()
    assert not (vault / "🔬").exists()
    assert not (vault / "🔬 Team").exists()


def test_export_nests_homepage_children_and_grandchild(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    vault = tmp_path / "vault"

    with serve_site(hierarchy_routes()) as site:
        code = main(["export", site, str(vault), "ENG"])

    homepage = vault / "Engineering" / "Home" / "Home.md"
    assert code == 0
    assert homepage.is_file()
    assert (vault / "Engineering" / "Home" / "Run book" / "Run book.md").is_file()
    assert (vault / "Engineering" / "Home" / "Alpha" / "Alpha.md").is_file()
    assert (vault / "Engineering" / "Home" / "Alpha" / "Grand" / "Grand.md").is_file()
    assert not (vault / "Engineering" / "Home" / "index.md").exists()
    assert not (vault / "Engineering" / "Alpha").exists()
    assert not (vault / "Engineering" / "Run book").exists()
    assert not (vault / "Engineering" / "Grand").exists()
    assert list(vault.rglob("index.md")) == []


def test_export_child_pages_section_uses_sibling_order_and_omits_leaves(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    vault = tmp_path / "vault"

    with serve_site(hierarchy_routes()) as site:
        code = main(["export", site, str(vault), "ENG"])

    home = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")
    alpha = (vault / "Engineering" / "Home" / "Alpha" / "Alpha.md").read_text(
        encoding="utf-8"
    )
    run_book = (vault / "Engineering" / "Home" / "Run book" / "Run book.md").read_text(
        encoding="utf-8"
    )
    grand = (vault / "Engineering" / "Home" / "Alpha" / "Grand" / "Grand.md").read_text(
        encoding="utf-8"
    )

    assert code == 0
    assert (
        "<!-- confluence-to-md:children -->\n"
        "## Child pages\n"
        "- [Run book](Run%20book/Run%20book.md)\n"
        "- [Alpha](Alpha/Alpha.md)\n"
        "<!-- /confluence-to-md:children -->"
    ) in home
    assert (
        "<!-- confluence-to-md:children -->\n"
        "## Child pages\n"
        "- [Grand](Grand/Grand.md)\n"
        "<!-- /confluence-to-md:children -->"
    ) in alpha
    assert "confluence-to-md:children" not in run_book
    assert "confluence-to-md:children" not in grand
    assert "## Child pages" not in run_book
    assert "## Child pages" not in grand


def test_export_makes_sibling_folder_names_unique_ignoring_case(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("1", "Home"),
                make_page("10", "Notes", parent_id="1", position=0),
                make_page("11", "notes", parent_id="1", position=1),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    home = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")
    first = vault / "Engineering" / "Home" / "Notes" / "Notes.md"
    second = vault / "Engineering" / "Home" / "notes (11)" / "notes (11).md"

    assert code == 0
    assert first.is_file()
    assert second.is_file()
    assert 'confluence_id: "10"' in first.read_text(encoding="utf-8")
    assert 'confluence_id: "11"' in second.read_text(encoding="utf-8")
    assert (
        "<!-- confluence-to-md:children -->\n"
        "## Child pages\n"
        "- [Notes](Notes/Notes.md)\n"
        "- [notes (11)](notes%20%2811%29/notes%20%2811%29.md)\n"
        "<!-- /confluence-to-md:children -->"
    ) in home


def test_export_appends_page_id_when_folder_name_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = one_page_routes()
    page = routes["/wiki/api/v2/spaces/111/pages"]["results"][0]
    page["title"] = "   "
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    note = vault / "Engineering" / " (123456)" / " (123456).md"
    text = note.read_text(encoding="utf-8")

    assert code == 0
    assert note.is_file()
    assert 'title: "   "' in text
    assert 'confluence_id: "123456"' in text


def test_export_places_page_under_space_when_parent_is_outside_selection(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("500", "Orphan", parent_id="999")],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    note = vault / "Engineering" / "Orphan" / "Orphan.md"
    text = note.read_text(encoding="utf-8")

    assert code == 0
    assert note.is_file()
    assert 'parent_id: "999"' in text
    assert not (vault / "Engineering" / "Home").exists()


def test_export_creates_space_folder_without_inventing_homepage(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {"results": [], "_links": {}},
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    space_folder = vault / "Engineering"
    assert code == 0
    assert space_folder.is_dir()
    assert list(space_folder.rglob("*.md")) == []


def test_export_writes_several_spaces_as_sibling_folders(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": {
            "results": [
                {
                    "id": "111",
                    "key": "ENG",
                    "name": "Engineering",
                    "type": "global",
                    "status": "current",
                },
                {
                    "id": "222",
                    "key": "TEAM",
                    "name": "Team",
                    "type": "global",
                    "status": "current",
                },
            ],
            "_links": {},
        },
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home")],
            "_links": {},
        },
        "/wiki/api/v2/spaces/222/pages": {
            "results": [
                make_page("200", "Team Home", space_key="TEAM", space_id="222")
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG", "TEAM"])

    assert code == 0
    assert (vault / "Engineering" / "Home" / "Home.md").is_file()
    assert (vault / "Team" / "Team Home" / "Team Home.md").is_file()


def test_export_rewrites_in_selection_page_link_to_relative_markdown(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>See "
        "<ac:link>"
        '<ri:page ri:content-title="Run book" ri:space-key="ENG" />'
        "<ac:plain-text-link-body><![CDATA[the runbook]]></ac:plain-text-link-body>"
        "</ac:link>"
        ".</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home", body=home_body),
                make_page("200", "Run book", parent_id="100", position=0),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    home = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")
    body = home.split("---", 2)[2]

    assert code == 0
    assert "[Run book](Run%20book/Run%20book.md)" in body
    assert "[[" not in body
    assert "ac:link" not in body


def test_export_keeps_heading_fragment_as_percent_encoded_text(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        '<ac:link ac:anchor="Setup steps">'
        '<ri:page ri:content-title="Run book" ri:space-key="ENG" />'
        "<ac:plain-text-link-body><![CDATA[setup]]></ac:plain-text-link-body>"
        "</ac:link>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home", body=home_body),
                make_page("200", "Run book", parent_id="100", position=0),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    body = (
        (vault / "Engineering" / "Home" / "Home.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
    )

    assert code == 0
    assert "[Run book](Run%20book/Run%20book.md#Setup%20steps)" in body
    assert "setup-steps" not in body


def test_export_keeps_out_of_selection_and_non_page_urls(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        "<ac:link>"
        '<ri:page ri:content-title="Outside" ri:space-key="ENG" />'
        "<ac:plain-text-link-body><![CDATA[missing]]></ac:plain-text-link-body>"
        "</ac:link>"
        ' <a href="https://example.com/docs">docs</a>'
        ' <a href="mailto:ops@example.com">mail</a>'
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        outside = f"{site}/wiki/spaces/ENG/pages/Outside"

    body = (
        (vault / "Engineering" / "Home" / "Home.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
    )

    assert code == 0
    assert f"[missing]({outside})" in body
    assert '<a href="https://example.com/docs">docs</a>' in body
    assert '<a href="mailto:ops@example.com">mail</a>' in body
    assert list(vault.rglob("*.md")) == [vault / "Engineering" / "Home" / "Home.md"]


def test_export_replaces_user_mention_with_display_name(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>Owner "
        "<ac:link>"
        '<ri:user ri:account-id="ada-1" />'
        "<ac:link-body>Ada Lovelace</ac:link-body>"
        "</ac:link>"
        ".</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    body = (
        (vault / "Engineering" / "Home" / "Home.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
    )

    assert code == 0
    assert "Ada Lovelace" in body
    assert "ri:user" not in body
    assert "ada-1" not in body
    assert list(vault.rglob("*.md")) == [vault / "Engineering" / "Home" / "Home.md"]


def test_export_rewrites_include_excerpt_and_smart_link(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        '<ac:structured-macro ac:name="include">'
        '<ac:parameter ac:name="">'
        '<ri:page ri:content-title="Run book" ri:space-key="ENG" />'
        "</ac:parameter>"
        "</ac:structured-macro>"
        "</p>"
        "<p>"
        '<ac:structured-macro ac:name="excerpt-include">'
        '<ac:parameter ac:name="">'
        '<ri:page ri:content-title="Outside" ri:space-key="ENG" />'
        "</ac:parameter>"
        "</ac:structured-macro>"
        "</p>"
        "<p>"
        '<ac:structured-macro ac:name="smart-link">'
        "</ac:structured-macro>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home", body=home_body),
                make_page(
                    "200",
                    "Run book",
                    parent_id="100",
                    position=0,
                    body="<p>Runbook secret</p>",
                ),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        outside = f"{site}/wiki/spaces/ENG/pages/Outside"

    home = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")
    body = home.split("---", 2)[2]
    run_book = (vault / "Engineering" / "Home" / "Run book" / "Run book.md").read_text(
        encoding="utf-8"
    )

    assert code == 0
    converted, _, _ = body.partition("<!-- confluence-to-md:children -->")
    assert "[Run book](Run%20book/Run%20book.md)" in converted
    assert f"[Outside]({outside})" in converted
    assert "Placeholder: smart-link" in converted
    assert "Runbook secret" in run_book
    assert "Runbook secret" not in converted
    assert "ac:structured-macro" not in converted


def test_export_reports_same_site_external_link(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        "<ac:link>"
        '<ri:page ri:content-title="Outside" ri:space-key="ENG" />'
        "<ac:plain-text-link-body><![CDATA[missing]]></ac:plain-text-link-body>"
        "</ac:link>"
        ' <a href="https://example.com/docs">docs</a>'
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        outside = f"{site}/wiki/spaces/ENG/pages/Outside"

    captured = capsys.readouterr()

    assert code == 0
    assert "100" in captured.out
    assert outside in captured.out
    assert "https://example.com/docs" not in captured.out
    assert list(vault.rglob("*.md")) == [vault / "Engineering" / "Home" / "Home.md"]


def test_export_relative_page_links_do_not_contain_site_url(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    run_body = (
        "<p>"
        "<ac:link>"
        '<ri:page ri:content-title="Home" ri:space-key="ENG" />'
        "<ac:plain-text-link-body><![CDATA[home]]></ac:plain-text-link-body>"
        "</ac:link>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home"),
                make_page(
                    "200", "Run book", parent_id="100", position=0, body=run_body
                ),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    body = (
        (vault / "Engineering" / "Home" / "Run book" / "Run book.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
    )

    assert code == 0
    assert "[Home](../Home.md)" in body
    assert f"]({site}" not in body.replace(f"[Run book]({site}", "", 1)


def test_export_rewrites_html_page_url_and_smart_link_url(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        '<a href="/wiki/spaces/ENG/pages/200/Run+book">run</a>'
        "</p>"
        "<p>"
        '<a href="/wiki/spaces/ENG/pages/999/Outside">gone</a>'
        "</p>"
        "<p>"
        '<ac:structured-macro ac:name="smart-link">'
        '<ac:parameter ac:name="url">/wiki/spaces/ENG/pages/200/Run+book</ac:parameter>'
        "</ac:structured-macro>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home", body=home_body),
                make_page("200", "Run book", parent_id="100", position=0),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        outside = f"{site}/wiki/spaces/ENG/pages/999/Outside"

    captured = capsys.readouterr()
    converted, _, _ = (
        (vault / "Engineering" / "Home" / "Home.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
        .partition("<!-- confluence-to-md:children -->")
    )

    assert code == 0
    assert converted.count("[Run book](Run%20book/Run%20book.md)") == 2
    assert f"[gone]({outside})" in converted
    assert "100" in captured.out
    assert outside in captured.out
    assert "ac:structured-macro" not in converted


def test_export_rewrites_page_link_across_spaces_in_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        "<ac:link>"
        '<ri:page ri:content-title="Team Home" ri:space-key="TEAM" />'
        "<ac:plain-text-link-body><![CDATA[team]]></ac:plain-text-link-body>"
        "</ac:link>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": {
            "results": [
                {
                    "id": "111",
                    "key": "ENG",
                    "name": "Engineering",
                    "type": "global",
                    "status": "current",
                },
                {
                    "id": "222",
                    "key": "TEAM",
                    "name": "Team",
                    "type": "global",
                    "status": "current",
                },
            ],
            "_links": {},
        },
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
        "/wiki/api/v2/spaces/222/pages": {
            "results": [
                make_page("200", "Team Home", space_key="TEAM", space_id="222")
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG", "TEAM"])

    body = (
        (vault / "Engineering" / "Home" / "Home.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
    )

    assert code == 0
    assert "[Team Home](../../Team/Team%20Home/Team%20Home.md)" in body


def test_export_rewrites_content_id_page_link(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        "<ac:link>"
        '<ri:content ri:id="200" />'
        "<ac:plain-text-link-body><![CDATA[run]]></ac:plain-text-link-body>"
        "</ac:link>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home", body=home_body),
                make_page("200", "Run book", parent_id="100", position=0),
            ],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    converted, _, _ = (
        (vault / "Engineering" / "Home" / "Home.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
        .partition("<!-- confluence-to-md:children -->")
    )

    assert code == 0
    assert "[Run book](Run%20book/Run%20book.md)" in converted


def test_export_external_content_id_url_includes_page_id(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        "<ac:link>"
        '<ri:page ri:content-title="Outside" ri:space-key="ENG" />'
        '<ri:content ri:id="999" />'
        "<ac:plain-text-link-body><![CDATA[missing]]></ac:plain-text-link-body>"
        "</ac:link>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        outside = f"{site}/wiki/spaces/ENG/pages/999/Outside"

    captured = capsys.readouterr()
    body = (
        (vault / "Engineering" / "Home" / "Home.md")
        .read_text(encoding="utf-8")
        .split("---", 2)[2]
    )

    assert code == 0
    assert f"[missing]({outside})" in body
    assert outside in captured.out
    assert "100" in captured.out


def test_export_embeds_image_links_file_and_lists_unreferenced(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        '<ac:image ac:alt="Architecture">'
        '<ri:attachment ri:filename="diagram.png" ri:version-at-save="1" />'
        "</ac:image>"
        "</p>"
        "<p>"
        "<ac:link>"
        '<ri:attachment ri:filename="spec.pdf" />'
        "</ac:link>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-img",
                    "diagram.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/diagram.png",
                ),
                make_attachment(
                    "att-pdf",
                    "spec.pdf",
                    page_id="100",
                    media_type="application/pdf",
                    download_path="/download/attachments/100/spec.pdf",
                ),
                make_attachment(
                    "att-sheet",
                    "sheet.xlsx",
                    page_id="100",
                    media_type="application/vnd.ms-excel",
                    download_path="/download/attachments/100/sheet.xlsx",
                ),
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/diagram.png": b"png-bytes",
        "/wiki/download/attachments/100/spec.pdf": b"pdf-bytes",
        "/wiki/download/attachments/100/sheet.xlsx": b"xlsx-bytes",
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    captured = capsys.readouterr()
    note = vault / "Engineering" / "Home" / "Home.md"
    text = note.read_text(encoding="utf-8")
    converted, marker, section = text.partition("<!-- confluence-to-md:attachments -->")
    files = vault / "Engineering" / "Home" / "attachments"

    assert code == 0
    assert (files / "diagram.png").read_bytes() == b"png-bytes"
    assert (files / "spec.pdf").read_bytes() == b"pdf-bytes"
    assert (files / "sheet.xlsx").read_bytes() == b"xlsx-bytes"
    assert "![Architecture](attachments/diagram.png)" in converted
    assert "[spec.pdf](attachments/spec.pdf)" in converted
    assert "sheet.xlsx" not in converted
    assert marker == "<!-- confluence-to-md:attachments -->"
    assert "- [sheet.xlsx](attachments/sheet.xlsx)" in section
    assert "<!-- /confluence-to-md:attachments -->" in section
    assert EMAIL not in text
    assert TOKEN not in text
    assert EMAIL not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err


def test_export_image_alt_falls_back_to_filename(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        '<ac:image><ri:attachment ri:filename="file name.png" /></ac:image>'
        '<ac:image><ri:attachment ri:filename="shot:1.png" /></ac:image>'
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-img",
                    "file name.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/file%20name.png",
                ),
                make_attachment(
                    "att-shot",
                    "shot:1.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/shot.png",
                ),
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/file%20name.png": b"png-bytes",
        "/wiki/download/attachments/100/shot.png": b"shot-bytes",
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    text = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")

    assert code == 0
    assert "![file name.png](attachments/file%20name.png)" in text
    assert "![shot:1.png](attachments/shot-1.png)" in text
    assert "<!-- confluence-to-md:attachments -->" not in text
    downloaded = vault / "Engineering" / "Home" / "attachments" / "file name.png"
    assert downloaded.read_bytes() == b"png-bytes"


def test_export_sanitizes_attachment_names_keeps_emoji_and_appends_id_on_collision(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home")],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-emoji",
                    "notes 📷.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/emoji.png",
                ),
                make_attachment(
                    "att-colon",
                    "report:q1.pdf",
                    page_id="100",
                    media_type="application/pdf",
                    download_path="/download/attachments/100/colon.pdf",
                ),
                make_attachment(
                    "att-b",
                    "report-q1.pdf",
                    page_id="100",
                    media_type="application/pdf",
                    download_path="/download/attachments/100/dup.pdf",
                ),
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/emoji.png": b"emoji-bytes",
        "/wiki/download/attachments/100/colon.pdf": b"colon-bytes",
        "/wiki/download/attachments/100/dup.pdf": b"dup-bytes",
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    files = vault / "Engineering" / "Home" / "attachments"
    text = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")

    assert code == 0
    assert (files / "notes 📷.png").read_bytes() == b"emoji-bytes"
    assert (files / "report-q1 (att-colon).pdf").read_bytes() == b"colon-bytes"
    assert (files / "report-q1 (att-b).pdf").read_bytes() == b"dup-bytes"
    assert "- [notes 📷.png](attachments/notes%20%F0%9F%93%B7.png)" in text
    colon = "- [report:q1.pdf](attachments/report-q1%20%28att-colon%29.pdf)"
    assert colon in text
    assert "- [report-q1.pdf](attachments/report-q1%20%28att-b%29.pdf)" in text


def test_export_body_link_to_duplicate_filename_uses_lowest_attachment_id(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        '<p><ac:image ac:alt="dup">'
        '<ri:attachment ri:filename="dup.png" /></ac:image></p>'
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-a",
                    "dup.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/dup-a.png",
                ),
                make_attachment(
                    "att-m",
                    "dup.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/dup-m.png",
                ),
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/dup-a.png": b"a-bytes",
        "/wiki/download/attachments/100/dup-m.png": b"m-bytes",
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    files = vault / "Engineering" / "Home" / "attachments"
    text = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")
    converted, _, section = text.partition("<!-- confluence-to-md:attachments -->")

    assert code == 0
    assert (files / "dup (att-a).png").read_bytes() == b"a-bytes"
    assert (files / "dup (att-m).png").read_bytes() == b"m-bytes"
    assert "![dup](attachments/dup%20%28att-a%29.png)" in converted
    assert "att-m" not in converted
    assert "- [dup.png](attachments/dup%20%28att-m%29.png)" in section


def test_export_failed_download_keeps_url_and_names_failure(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        '<ac:image ac:alt="Gone">'
        '<ri:attachment ri:filename="missing.png" />'
        "</ac:image>"
        "</p>"
        "<p>"
        "<ac:image>"
        '<ri:attachment ri:filename="notes 📷.png" />'
        "</ac:image>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-fail",
                    "missing.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/missing.png",
                ),
                make_attachment(
                    "att-emoji",
                    "notes 📷.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/emoji.png",
                ),
                make_attachment(
                    "att-orphan",
                    "orphan.csv",
                    page_id="100",
                    media_type="text/csv",
                    download_path="/download/attachments/100/orphan.csv",
                ),
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/missing.png": 404,
        "/wiki/download/attachments/100/emoji.png": b"emoji-bytes",
        "/wiki/download/attachments/100/orphan.csv": 404,
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        missing = f"{site}/wiki/download/attachments/100/missing.png"
        orphan = f"{site}/wiki/download/attachments/100/orphan.csv"

    captured = capsys.readouterr()
    note = vault / "Engineering" / "Home" / "Home.md"
    text = note.read_text(encoding="utf-8")

    assert code == 0
    assert note.is_file()
    assert f"![Gone]({missing})" in text
    assert "![notes 📷.png](attachments/notes%20%F0%9F%93%B7.png)" in text
    assert (vault / "Engineering" / "Home" / "attachments" / "notes 📷.png").is_file()
    assert not (vault / "Engineering" / "Home" / "attachments" / "missing.png").exists()
    assert f"- [orphan.csv]({orphan})" in text
    assert (
        "missing.png" not in text.split("<!-- confluence-to-md:attachments -->", 1)[-1]
    )
    assert "Failed to download Attachment: 100 att-fail Not Found" in captured.out
    assert "Failed to download Attachment: 100 att-orphan Not Found" in captured.out
    assert "Attachments downloaded: 1" in captured.out
    assert EMAIL not in text
    assert TOKEN not in text
    assert EMAIL not in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err


def test_export_reports_body_filename_that_is_not_listed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        '<p><ac:image ac:alt="Ghost">'
        '<ri:attachment ri:filename="ghost.png" /></ac:image></p>'
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])
        ghost = f"{site}/wiki/download/attachments/100/ghost.png"

    captured = capsys.readouterr()
    text = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")

    assert code == 0
    assert f"![Ghost]({ghost})" in text
    assert "Failed to download Attachment: 100 ghost.png not listed" in captured.out
    assert not (vault / "Engineering" / "Home" / "attachments").exists()


def test_export_downloads_diagram_source_and_embeds_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        "<p>"
        '<ac:structured-macro ac:name="drawio">'
        '<ac:parameter ac:name="diagramName">flow.drawio</ac:parameter>'
        "</ac:structured-macro>"
        "</p>"
        "<p>"
        '<ac:image ac:alt="preview">'
        '<ri:attachment ri:filename="flow-preview.png" />'
        "</ac:image>"
        "</p>"
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home", body=home_body)],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-src",
                    "flow.drawio",
                    page_id="100",
                    media_type="application/vnd.jgraph.mxfile",
                    download_path="/download/attachments/100/flow.drawio",
                ),
                make_attachment(
                    "att-prev",
                    "flow-preview.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/flow-preview.png",
                ),
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/flow.drawio": b"<mxfile/>",
        "/wiki/download/attachments/100/flow-preview.png": b"preview-png",
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    text = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")
    converted, _, section = text.partition("<!-- confluence-to-md:attachments -->")
    files = vault / "Engineering" / "Home" / "attachments"

    assert code == 0
    assert (files / "flow.drawio").read_bytes() == b"<mxfile/>"
    assert (files / "flow-preview.png").read_bytes() == b"preview-png"
    assert "![preview](attachments/flow-preview.png)" in converted
    assert "attachments/flow.drawio" not in converted
    assert "- [flow.drawio](attachments/flow.drawio)" in section
    assert "flow-preview.png" not in section


def test_export_omits_attachments_section_when_none_or_all_referenced(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    home_body = (
        '<p><ac:image><ri:attachment ri:filename="diagram.png" /></ac:image></p>'
    )
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [
                make_page("100", "Home", body=home_body),
                make_page("200", "Empty", parent_id="100", position=0),
            ],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-img",
                    "diagram.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/diagram.png",
                )
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/diagram.png": b"png-bytes",
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    home = (vault / "Engineering" / "Home" / "Home.md").read_text(encoding="utf-8")
    empty = (vault / "Engineering" / "Home" / "Empty" / "Empty.md").read_text(
        encoding="utf-8"
    )

    assert code == 0
    assert "![diagram.png](attachments/diagram.png)" in home
    assert "<!-- confluence-to-md:attachments -->" not in home
    assert "<!-- confluence-to-md:attachments -->" not in empty
    assert not (vault / "Engineering" / "Home" / "Empty" / "attachments").exists()


def test_export_retries_transient_attachment_download(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home")],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-img",
                    "diagram.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/diagram.png",
                )
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/diagram.png": [503, b"png-bytes"],
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    captured = capsys.readouterr()

    assert code == 0
    assert (
        vault / "Engineering" / "Home" / "attachments" / "diagram.png"
    ).read_bytes() == b"png-bytes"
    assert "Failed to download Attachment" not in captured.out + captured.err
    assert "Attachments downloaded: 1" in captured.out


def test_export_downloads_attachments_from_every_page_of_results(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CONFLUENCE_EMAIL", EMAIL)
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", TOKEN)
    routes = {
        "/wiki/api/v2/spaces": load_json("one-page/spaces.json"),
        "/wiki/api/v2/spaces/111/pages": {
            "results": [make_page("100", "Home")],
            "_links": {},
        },
        "/wiki/api/v2/pages/100/attachments": {
            "results": [
                make_attachment(
                    "att-img",
                    "diagram.png",
                    page_id="100",
                    media_type="image/png",
                    download_path="/download/attachments/100/diagram.png",
                )
            ],
            "_links": {"next": "/wiki/api/v2/pages/100/attachments-next"},
        },
        "/wiki/api/v2/pages/100/attachments-next": {
            "results": [
                make_attachment(
                    "att-sheet",
                    "sheet.xlsx",
                    page_id="100",
                    media_type="application/vnd.ms-excel",
                    download_path="/download/attachments/100/sheet.xlsx",
                )
            ],
            "_links": {},
        },
        "/wiki/download/attachments/100/diagram.png": b"png-bytes",
        "/wiki/download/attachments/100/sheet.xlsx": b"xlsx-bytes",
    }
    vault = tmp_path / "vault"

    with serve_site(routes) as site:
        code = main(["export", site, str(vault), "ENG"])

    captured = capsys.readouterr()
    files = vault / "Engineering" / "Home" / "attachments"

    assert code == 0
    assert (files / "diagram.png").read_bytes() == b"png-bytes"
    assert (files / "sheet.xlsx").read_bytes() == b"xlsx-bytes"
    assert "Attachments downloaded: 2" in captured.out

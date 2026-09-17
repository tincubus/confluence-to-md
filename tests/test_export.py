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

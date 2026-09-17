import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urljoin

EMAIL_ENV = "CONFLUENCE_EMAIL"
TOKEN_ENV = "CONFLUENCE_API_TOKEN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="confluence-to-md",
        description=(
            "Export Confluence Pages into a Vault. "
            f"Credentials come from {EMAIL_ENV} and {TOKEN_ENV}, not from arguments."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser(
        "list",
        help="Print Spaces the token can Export",
        description=(
            "Print non-archived Spaces the token can see, one per line, "
            "Space key then name. Archived Spaces and Personal Spaces are omitted. "
            "No prompt."
        ),
    )
    list_parser.add_argument(
        "site",
        help="Site URL, e.g. https://example.atlassian.net",
    )
    export_parser = subparsers.add_parser(
        "export",
        help="Write a Selection into a Vault",
        description=(
            "Export Pages into a Vault. The directory is the Vault root. "
            f"Credentials come from {EMAIL_ENV} and {TOKEN_ENV}, not from arguments."
        ),
    )
    export_parser.add_argument(
        "site",
        help="Site URL, e.g. https://example.atlassian.net",
    )
    export_parser.add_argument(
        "vault",
        help="Vault root directory",
    )
    export_parser.add_argument(
        "space_keys",
        metavar="space_key",
        nargs="+",
        help="Space key to Export. Repeat for several Spaces in one Vault.",
    )
    args = parser.parse_args(argv)
    if args.command == "list":
        return list_spaces(args.site)
    return export_spaces(args.site, args.vault, args.space_keys)


def load_credentials() -> tuple[str, str] | None:
    missing = []
    if not os.environ.get(EMAIL_ENV):
        missing.append(EMAIL_ENV)
    if not os.environ.get(TOKEN_ENV):
        missing.append(TOKEN_ENV)
    if missing:
        print(
            f"Missing credentials in the environment: {', '.join(missing)}",
            file=sys.stderr,
        )
        return None
    return os.environ[EMAIL_ENV], os.environ[TOKEN_ENV]


def list_spaces(site: str) -> int:
    account = load_credentials()
    if account is None:
        return 1
    email, token = account
    site = site.rstrip("/")
    url: str | None = f"{site}/wiki/api/v2/spaces?limit=250&status=current"
    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    try:
        while url:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Basic {credentials}",
                },
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.load(response)
            for space in data["results"]:
                if space.get("status") == "archived":
                    continue
                if space.get("type") == "personal":
                    continue
                print(f"{space['key']} {space['name']}")
            next_link = data.get("_links", {}).get("next")
            url = urljoin(site + "/", next_link) if next_link else None
    except urllib.error.URLError as err:
        print(f"Could not list Spaces: {err.reason}", file=sys.stderr)
        return 1
    return 0


def folder_name(title: str, page_id: str, used: set[str]) -> str:
    name = title.strip()
    for char in '\\/:*?"<>|':
        name = name.replace(char, "-")
    if not name or name.lower() in used:
        name = f"{name} ({page_id})"
    used.add(name.lower())
    return name


def sibling_sort_key(page: dict) -> tuple:
    position = page.get("position")
    if position is None:
        return (1, 0, page["title"])
    return (0, position, page["title"])


def export_spaces(site: str, vault: str, space_keys: list[str]) -> int:
    account = load_credentials()
    if account is None:
        return 1
    if not site:
        print("Missing Site URL", file=sys.stderr)
        return 1
    email, token = account
    site = site.rstrip("/")
    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {credentials}",
    }

    def fetch_json(url: str) -> dict:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    vault_root = Path(vault)
    for space_key in space_keys:
        try:
            spaces = fetch_json(
                f"{site}/wiki/api/v2/spaces?keys={quote(space_key, safe='')}&limit=250"
            )
            space = next(
                (item for item in spaces["results"] if item["key"] == space_key),
                None,
            )
            if space is None:
                print(
                    f"Could not Export the Selection: Space {space_key} was not found",
                    file=sys.stderr,
                )
                return 1
            pages = fetch_json(
                f"{site}/wiki/api/v2/spaces/{space['id']}/pages"
                "?body-format=storage&limit=250"
            )
        except urllib.error.URLError as err:
            print(f"Could not Export the Selection: {err.reason}", file=sys.stderr)
            return 1

        space_folder = vault_root / space["name"]
        space_folder.mkdir(parents=True, exist_ok=True)
        pages_by_id = {str(page["id"]): page for page in pages["results"]}
        children_of: dict[str, list[dict]] = {}
        roots: list[dict] = []
        for page in pages["results"]:
            parent_id = page.get("parentId")
            if parent_id and str(parent_id) in pages_by_id:
                children_of.setdefault(str(parent_id), []).append(page)
            else:
                roots.append(page)
        folder_names: dict[str, str] = {}
        for group in (roots, *children_of.values()):
            group.sort(key=sibling_sort_key)
            used: set[str] = set()
            for page in group:
                page_id = str(page["id"])
                folder_names[page_id] = folder_name(page["title"], page_id, used)
        for page in pages["results"]:
            title = page["title"]
            page_id = str(page["id"])
            source_url = f"{site}/wiki{page['_links']['webui']}"
            parts: list[str] = []
            current = page
            while True:
                current_id = str(current["id"])
                parts.append(folder_names[current_id])
                parent_id = current.get("parentId")
                if not parent_id or str(parent_id) not in pages_by_id:
                    break
                current = pages_by_id[str(parent_id)]
            parts.reverse()
            name = parts[-1]
            folder = space_folder / Path(*parts)
            folder.mkdir(parents=True, exist_ok=True)
            fields = {
                "title": title,
                "confluence_id": page_id,
                "space_key": space_key,
                "source_url": source_url,
            }
            parent_id = page.get("parentId")
            if parent_id:
                fields["parent_id"] = str(parent_id)
            fields["updated_at"] = page["version"]["createdAt"]
            lines = ["---"]
            for key, value in fields.items():
                lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
            lines.append("---")
            lines.append("")
            lines.append(f"[{title}]({source_url})")
            lines.append("")
            lines.append(page["body"]["storage"]["value"])
            lines.append("")
            children = children_of.get(page_id, [])
            if children:
                lines.append("<!-- confluence-to-md:children -->")
                lines.append("## Child pages")
                for child in children:
                    child_name = folder_names[str(child["id"])]
                    rel = (
                        f"{quote(child_name, safe='')}/{quote(child_name, safe='')}.md"
                    )
                    lines.append(f"- [{child['title']}]({rel})")
                lines.append("<!-- /confluence-to-md:children -->")
                lines.append("")
            (folder / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


def console() -> None:
    raise SystemExit(main())

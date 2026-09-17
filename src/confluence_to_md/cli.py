import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote_plus, urljoin

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


# Emoji and pictographs, including ZWJ sequences and emoji presentation variants.
_PICTOGRAPH = (
    "["
    "\u00a9\u00ae"
    "\u203c\u2049"
    "\u2122\u2139"
    "\u2194-\u2199"
    "\u21a9-\u21aa"
    "\u231a-\u231b"
    "\u2328\u23cf"
    "\u23e9-\u23f3"
    "\u23f8-\u23fa"
    "\u24c2"
    "\u25aa-\u25ab\u25b6\u25c0"
    "\u25fb-\u25fe"
    "\u2600-\u27bf"
    "\u2934-\u2935"
    "\u2b05-\u2b07"
    "\u2b1b-\u2b1c"
    "\u2b50\u2b55"
    "\u3030\u303d"
    "\u3297\u3299"
    "\U0001f000-\U0001faff"
    "]"
)
EMOJI = re.compile(
    "(?:"
    "[#*0-9]\ufe0f?\u20e3"
    "|"
    "\U0001f3f4[\U000e0020-\U000e007e]+\U000e007f"
    "|"
    + _PICTOGRAPH
    + "(?:\ufe0e|\ufe0f)?"
    + "(?:\u200d"
    + _PICTOGRAPH
    + "(?:\ufe0e|\ufe0f)?)*"
    ")"
)


def folder_name(title: str, suffix: str, used: set[str]) -> str:
    name = re.sub(r"\s+", " ", EMOJI.sub("", title)).strip()
    for char in '\\/:*?"<>|':
        name = name.replace(char, "-")
    if not name or name.lower() in used:
        name = f"{name} ({suffix})"
    used.add(name.lower())
    return name


def sibling_sort_key(page: dict) -> tuple:
    position = page.get("position")
    if position is None:
        return (1, 0, page["title"])
    return (0, position, page["title"])


AC_NS = "http://atlassian.com/content"
RI_NS = "http://atlassian.com/resource/identifier"
NS_PREFIX = {AC_NS: "ac", RI_NS: "ri"}
VOID_TAGS = {"br", "hr", "img", "page", "content", "user", "attachment"}
PAGE_HREF = re.compile(
    r"/wiki/spaces/(?P<space>[^/]+)/pages/(?P<id>\d+)(?:/(?P<title>[^?#]*))?"
)


def local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def qualified_name(tag: str) -> str:
    if tag.startswith("{"):
        namespace, name = tag[1:].split("}", 1)
        prefix = NS_PREFIX.get(namespace)
        return f"{prefix}:{name}" if prefix else name
    return tag


def get_attr(elem: ET.Element, name: str) -> str | None:
    for key, value in elem.attrib.items():
        if local_name(key) == name:
            return value
    return None


def find_local(elem: ET.Element, name: str) -> ET.Element | None:
    for child in elem:
        if local_name(child.tag) == name:
            return child
        found = find_local(child, name)
        if found is not None:
            return found
    return None


def esc_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_attr(value: str) -> str:
    return esc_text(value).replace('"', "&quot;")


def page_path_parts(
    page: dict, pages_by_id: dict[str, dict], folder_names: dict[str, str]
) -> list[str]:
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
    return parts


def relative_note_href(
    from_dir: Path, to_file: Path, fragment: str | None = None
) -> str:
    rel = to_file.relative_to(from_dir, walk_up=True)
    href = "/".join(
        ".." if part == ".." else quote(part, safe="") for part in rel.parts
    )
    if fragment:
        href += "#" + quote(fragment, safe="")
    return href


def link_label(elem: ET.Element, fallback: str) -> str:
    for child in elem:
        if local_name(child.tag) in {"plain-text-link-body", "link-body"}:
            text = "".join(child.itertext())
            if text:
                return text
    return fallback


class LinkRewrite:
    def __init__(
        self,
        site: str,
        space_key: str,
        page_id: str,
        note_dir: Path,
        note_paths: dict[str, Path],
        page_ids: dict[tuple[str, str], str],
        external_links: list[tuple[str, str]],
    ) -> None:
        self.site = site
        self.space_key = space_key
        self.page_id = page_id
        self.note_dir = note_dir
        self.note_paths = note_paths
        self.page_ids = page_ids
        self.external_links = external_links

    def page_href(
        self, space_key: str, title: str, page_id: str | None, fragment: str | None
    ) -> str:
        if page_id and page_id in self.note_paths:
            return relative_note_href(self.note_dir, self.note_paths[page_id], fragment)
        href = f"{self.site}/wiki/spaces/{quote(space_key, safe='')}/pages/"
        if page_id:
            href += page_id
            if title:
                href += f"/{quote(title, safe='')}"
        else:
            href += quote(title, safe="")
        if fragment:
            href += "#" + quote(fragment, safe="")
        self.external_links.append((self.page_id, href))
        return href

    def title_of(self, page_id: str, fallback: str) -> str:
        for (_, title), pid in self.page_ids.items():
            if pid == page_id:
                return title
        return fallback

    def note_name(self, page_id: str | None, fallback: str) -> str:
        if page_id and page_id in self.note_paths:
            return self.note_paths[page_id].stem
        return fallback


def convert_mention(elem: ET.Element) -> str | None:
    if local_name(elem.tag) != "link":
        return None
    if find_local(elem, "user") is None:
        return None
    return link_label(elem, "")


def convert_page_link(elem: ET.Element, ctx: LinkRewrite) -> str | None:
    if local_name(elem.tag) != "link":
        return None
    if find_local(elem, "attachment") is not None:
        return None
    if find_local(elem, "user") is not None:
        return None
    page = find_local(elem, "page")
    content = find_local(elem, "content")
    if page is None and content is None:
        return None
    title = ""
    target_space = ctx.space_key
    page_id = None
    if page is not None:
        title = get_attr(page, "content-title") or ""
        target_space = get_attr(page, "space-key") or ctx.space_key
        page_id = ctx.page_ids.get((target_space, title))
    if content is not None:
        content_id = get_attr(content, "id")
        if content_id:
            page_id = content_id
            title = ctx.title_of(page_id, title)
    href = ctx.page_href(target_space, title, page_id, get_attr(elem, "anchor"))
    return f"[{ctx.note_name(page_id, link_label(elem, title))}]({href})"


PAGE_MACROS = {"include", "excerpt-include"}
SMART_MACROS = {"smart-link", "applink-smartlink", "card"}


def parse_page_href(href: str, site: str) -> tuple[str, str, str, str | None] | None:
    path, _, fragment = href.partition("#")
    if path.startswith(("http://", "https://")):
        if path != site and not path.startswith(site + "/"):
            return None
    elif not path.startswith("/wiki/"):
        return None
    match = PAGE_HREF.search(path)
    if match is None:
        return None
    title = unquote_plus(match.group("title") or "")
    return match.group("space"), match.group("id"), title, fragment or None


def convert_href(ctx: LinkRewrite, href: str, label: str) -> str | None:
    parsed = parse_page_href(href, ctx.site)
    if parsed is None:
        return None
    _space_key, page_id, title, fragment = parsed
    title = ctx.title_of(page_id, title or page_id)
    label = ctx.note_name(page_id, label or title)
    if page_id in ctx.note_paths:
        return (
            f"[{label}]"
            f"({relative_note_href(ctx.note_dir, ctx.note_paths[page_id], fragment)})"
        )
    absolute = (
        href
        if href.startswith(("http://", "https://"))
        else urljoin(ctx.site + "/", href)
    )
    ctx.external_links.append((ctx.page_id, absolute))
    return f"[{label}]({absolute})"


def convert_anchor(elem: ET.Element, ctx: LinkRewrite) -> str | None:
    if local_name(elem.tag) != "a":
        return None
    href = elem.attrib.get("href")
    if not href:
        return None
    label = "".join(elem.itertext()) or href
    return convert_href(ctx, href, label)


def macro_param(elem: ET.Element, name: str) -> str | None:
    for child in elem.iter():
        if local_name(child.tag) == "parameter" and get_attr(child, "name") == name:
            text = "".join(child.itertext()).strip()
            return text or None
    return None


def convert_macro(elem: ET.Element, ctx: LinkRewrite) -> str | None:
    if local_name(elem.tag) != "structured-macro":
        return None
    name = get_attr(elem, "name")
    if name in PAGE_MACROS:
        page = find_local(elem, "page")
        if page is None:
            return f"Placeholder: {name}"
        title = get_attr(page, "content-title") or ""
        target_space = get_attr(page, "space-key") or ctx.space_key
        page_id = ctx.page_ids.get((target_space, title))
        if not title and page_id is None:
            return f"Placeholder: {name}"
        href = ctx.page_href(target_space, title, page_id, None)
        return f"[{ctx.note_name(page_id, title)}]({href})"
    if name in SMART_MACROS:
        url = macro_param(elem, "url")
        if not url:
            return f"Placeholder: {name}"
        converted = convert_href(ctx, url, "")
        if converted is not None:
            return converted
        return f"[{url}]({url})"
    return None


def render_children(elem: ET.Element, ctx: LinkRewrite) -> str:
    parts = [esc_text(elem.text) if elem.text else ""]
    for child in elem:
        parts.append(render_node(child, ctx))
    return "".join(parts)


def render_node(elem: ET.Element, ctx: LinkRewrite) -> str:
    converted = convert_mention(elem)
    if converted is None:
        converted = convert_page_link(elem, ctx)
    if converted is None:
        converted = convert_macro(elem, ctx)
    if converted is None:
        converted = convert_anchor(elem, ctx)
    tail = esc_text(elem.tail) if elem.tail else ""
    if converted is not None:
        return converted + tail
    return emit_element(elem, ctx) + tail


def emit_element(elem: ET.Element, ctx: LinkRewrite) -> str:
    tag = qualified_name(elem.tag)
    attrs = "".join(
        f' {qualified_name(key)}="{esc_attr(value)}"'
        for key, value in elem.attrib.items()
    )
    inner = render_children(elem, ctx)
    if inner == "" and local_name(elem.tag) in VOID_TAGS:
        return f"<{tag}{attrs} />"
    return f"<{tag}{attrs}>{inner}</{tag}>"


def rewrite_storage(
    storage: str,
    site: str,
    space_key: str,
    page_id: str,
    note_dir: Path,
    note_paths: dict[str, Path],
    page_ids: dict[tuple[str, str], str],
    external_links: list[tuple[str, str]],
) -> str:
    try:
        root = ET.fromstring(
            f'<root xmlns:ac="{AC_NS}" xmlns:ri="{RI_NS}">{storage}</root>'
        )
    except ET.ParseError:
        return storage
    return render_children(
        root,
        LinkRewrite(
            site, space_key, page_id, note_dir, note_paths, page_ids, external_links
        ),
    )


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
    used_space_folders: set[str] = set()
    external_links: list[tuple[str, str]] = []
    note_paths: dict[str, Path] = {}
    page_ids: dict[tuple[str, str], str] = {}
    prepared: list[tuple] = []
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

        space_folder = vault_root / folder_name(
            space["name"], space_key, used_space_folders
        )
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
        folders: dict[str, Path] = {}
        for page in pages["results"]:
            page_id = str(page["id"])
            parts = page_path_parts(page, pages_by_id, folder_names)
            folder = space_folder / Path(*parts)
            folders[page_id] = folder
            note_paths[page_id] = folder / f"{parts[-1]}.md"
            page_ids[(space_key, page["title"])] = page_id
        prepared.append(
            (space_key, pages["results"], children_of, folder_names, folders)
        )
    for space_key, space_pages, children_of, folder_names, folders in prepared:
        for page in space_pages:
            title = page["title"]
            page_id = str(page["id"])
            source_url = f"{site}/wiki{page['_links']['webui']}"
            folder = folders[page_id]
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
            lines.append(
                rewrite_storage(
                    page["body"]["storage"]["value"],
                    site,
                    space_key,
                    page_id,
                    folder,
                    note_paths,
                    page_ids,
                    external_links,
                )
            )
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
                    lines.append(f"- [{child_name}]({rel})")
                lines.append("<!-- /confluence-to-md:children -->")
                lines.append("")
            (folder / f"{folder_names[page_id]}.md").write_text(
                "\n".join(lines), encoding="utf-8"
            )
    for page_id, url in external_links:
        print(f"External link on the Site: {page_id} {url}")
    return 0


def console() -> None:
    raise SystemExit(main())

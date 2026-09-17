import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin

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
            "Space key then name. No prompt."
        ),
    )
    list_parser.add_argument(
        "site",
        help="Site URL, e.g. https://example.atlassian.net",
    )
    args = parser.parse_args(argv)
    return list_spaces(args.site)


def list_spaces(site: str) -> int:
    email = os.environ.get(EMAIL_ENV)
    token = os.environ.get(TOKEN_ENV)
    if not email or not token:
        missing = []
        if not email:
            missing.append(EMAIL_ENV)
        if not token:
            missing.append(TOKEN_ENV)
        print(
            f"Missing credentials in the environment: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1
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
                print(f"{space['key']} {space['name']}")
            next_link = data.get("_links", {}).get("next")
            url = urljoin(site + "/", next_link) if next_link else None
    except urllib.error.URLError as err:
        print(f"Could not list Spaces: {err.reason}", file=sys.stderr)
        return 1
    return 0


def console() -> None:
    raise SystemExit(main())

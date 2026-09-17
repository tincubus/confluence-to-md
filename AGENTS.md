# confluence-to-md

Python tool that exports Confluence Pages into a Vault: one Note per Page, Page links between them, Attachments stored with the Note, readable offline as a knowledge base. Obsidian is the reference reader.

## Reach for these

- [CONTEXT.md](CONTEXT.md) — when naming a domain concept in code, docs, or a commit message. Use those terms. When code and the glossary disagree, change them in the same edit so they match.
- [docs/requirements.md](docs/requirements.md) — when changing what an Export writes, how Page links or Attachments resolve, Vault layout, Re-export, or what is in scope. The work is done only when every acceptance scenario in that file holds.

## Coding

Implementation is Python 3.12 or newer. Use uv for installs and the lockfile, a src layout, pytest, and ruff for format and lint. No web framework and no Docker image in the first version. Apply the four rules below on every code change. A one-line fix skips the ceremony, not the rules.

**Think before coding.** State assumptions. When more than one reading fits, name each and ask before writing. When a simpler approach exists, say so first. When a step is unclear, stop and name what is unclear.

**Simplicity.** Write the smallest code that satisfies this request and the in-scope requirements it touches. Keep single-use code inline. Add a knob or an error path only when the request or the requirements name it. If a shorter version works, replace what you just wrote.

**Surgical.** Each changed line traces to the request. Match the style already in the file. Leave adjacent code, formatting, and pre-existing dead code alone; mention dead code instead of deleting it. Remove imports, names, and helpers that this change orphaned.

**Goal-driven.** Name the check, then loop until it holds. Export behavior is checked against the acceptance scenarios in [docs/requirements.md](docs/requirements.md). A bugfix starts from a failing test that reproduces the bug. A refactor keeps those checks passing before and after.

These rules are holding when diffs stay small, speculative layers do not appear, and questions come before the wrong implementation.

## Git history

Author and committer are the repository git identity only. No agent, Cursor, or generated-by trailer. Commit subjects, commit bodies, and pull-request text that will land in history describe the change, not the tool that wrote it. Code comments do not say an agent wrote them.

## Rules

- Implement behavior the requirements mark in scope. An unresolved item is a question to the user, not a silent default.
- A finished Export is offline-complete: every in-scope Note, Page link, and Attachment resolves inside the Vault with no Confluence session.
- Credentials never appear in the Vault or in committed files.
- `pytest` runs against checked-in synthetic storage fixtures and does not need a token. Do not commit a Vault or a recording from a real Site. A live Export against a Site is a separate command.
- Entrypoint: `uv run confluence-to-md` (`python -m confluence_to_md`). Do not copy flags or path rules up here; those live in the requirements and the tool's help.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for tincubus/confluence-to-md. See `docs/agents/issue-tracker.md`.

### Triage labels

Five default roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` and `docs/adr/`. See `docs/agents/domain.md`.

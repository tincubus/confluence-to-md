# Requirements

Contract for the Export. Terms are defined in [CONTEXT.md](../CONTEXT.md). Do not rename them here.

An unresolved item blocks only that behavior. Ship the in-scope contract without inventing an answer for the unresolved list.

## Purpose

An Operator exports Confluence into a Vault so the knowledge can still be read after the Site is gone. Notes link to each other, Attachments sit on disk, and Obsidian is the reference reader. The same tree must stay readable in any CommonMark reader.

While an Export runs, Confluence is the source. After that, the Vault is the reference. It is not a live mirror.

## In scope

- A local command an Operator runs against their own Site. The Atlassian account email and API token come from the environment, never from command arguments. The Site URL and the Selection may be arguments. None of the three appear in the Vault, the repo, or command output.
- A list command that prints non-archived Spaces the token can see, one per line, Space key then name. Archived Spaces and Personal Spaces are omitted. A Space that is not a Personal Space stays on the list, including collaboration and knowledge-base Spaces. No interactive prompt, no flag to include Personal Spaces, and no count of the ones omitted. A Site whose only Spaces are Personal Spaces prints no lines and exits success.
- An export command that takes a directory argument and a Selection. That directory is the Vault root. If it already exists, Re-export rules apply. The Selection is either one or more Space keys, or one Page id and that Page's descendants. One run does not take both.
- One Note per Page, Hierarchy as folders, Page links rewritten to relative markdown links.
- Every Attachment on an exported Page downloaded beside that Note, and every in-body reference rewritten to the local file.
- Opening the Vault root in Obsidian yields notes, rendered images, openable files, and a graph of Page links, with no plugin and no network.
- Re-export into the same Vault updates Notes in place by Page id.

## Out of scope

- Writing back to Confluence.
- Blog posts, whiteboards, databases, comments, inline comments, and page history.
- Mirroring Confluence permissions inside the Vault.
- Creating Notes for users, Jira issues, or Spaces that were not exported as Pages.
- Live sync or watch mode.
- Rendering a diagram Attachment into a new image. Existing files, including a preview image Confluence already stored, are downloaded as Attachments.
- Selection by CQL or by Label alone.

## Decisions

These are the working contract. Overturning one changes every Vault.

- **Relative markdown links, not wikilinks.** Obsidian graphs relative links, and the tree stays valid outside Obsidian. Wikilinks would lock the Vault to one app.
- **Folder per Page, Note is `{title}.md` inside that folder.** Hierarchy is visible on disk, and a move of the folder keeps the Note and its Attachments together. The filename is the title, not `index.md`: Obsidian names a note from the filename, with no plugin, so every note would otherwise appear as `index`.
- **Include-style macros become Page links, not copied bodies.** One Page, one Note. Inlining would duplicate content and drift on Re-export.
- **Re-export replaces exporter-owned Note content and does not delete Notes that left the Selection.** Silent deletion would destroy a knowledge base the operator may still be reading. Absence is reported, not erased.
- **Confluence Cloud only.** Data Center and Server use a different API and auth.
- **Page body is read as storage format, not rendered HTML.** The Note is still markdown. Storage keeps Page link targets and Attachment filenames, so the Vault stays offline-complete. Rendered HTML usually leaves absolute Site URLs.
- **A table that cannot be GFM stays as HTML in the Note.** Dropping the cells would lose content. Agent readability does not outweigh that.
- **List, then export by Space key.** The list command does not ask the Operator to pick, and it omits Personal Spaces. Export takes the key as an argument, including a Personal Space key, so a person or an agent can run either command without a prompt.
- **A Page and its descendants is a second Selection, not a substitute for a Space.** Attachments are downloaded for every exported Page either way. The difference is which Pages are written. One Export does not mix a Space key with a Page id.
- **Blog posts stay out.** The Vault must outlive the Site, and a blog post is still not a Page. Adding blogs later does not change Vault layout.
- **Same-Site links outside the Selection are reported, not pulled in.** An External link that still points at the Site dies when the Site is gone. The run names those links. The Export does not widen the Selection to fetch them.

## Vault layout

```
{Vault}/
  {Space name}/
    {Homepage title}/
      {Homepage title}.md
      attachments/
      {Child title}/
        {Child title}.md
        attachments/
        {Grandchild title}/
          {Grandchild title}.md
          attachments/
```

- Every Page, including the homepage, is a folder. The Note is `{title}.md` inside that folder. Children nest inside the parent folder. The Space folder itself is not a Note.
- A Page whose parent is outside the Selection lives directly under the Space folder. Frontmatter `parent_id` still records the Confluence parent.
- A Space with no readable homepage still gets a Space folder; its root Pages are folders under it. Do not invent a homepage body.
- Several Spaces in one Export are sibling folders in the same Vault.
- Folder name is the Page title, sanitized: trim, replace `\ / : * ? " < > |` with `-`, and keep the name case-insensitively unique among siblings. A collision or a name empty after sanitizing gets ` (Page id)` appended.
- Note body and Attachments are UTF-8 files. Filenames stay human-readable.

## Note shape

Frontmatter is the Note's identity. Obsidian shows it as properties.

```yaml
---
title: "Page title"
confluence_id: "123456"
space_key: "ENG"
source_url: "https://example.atlassian.net/wiki/spaces/ENG/pages/123456/Page+title"
parent_id: "123400"
updated_at: "2026-09-17T04:00:00Z"
labels:
  - runbook
---
```

- `confluence_id` is the Page id. `parent_id` is omitted when the Page has no parent.
- `labels` copies Labels. Omit the key when there are none.
- `updated_at` is the Page's last-updated time in UTC, ISO-8601.
- The body starts with a one-line source link to `source_url`, then the converted body.
- If the first heading text equals the Page title, omit that heading so Obsidian does not show the title twice.
- Exporter-owned sections, when present, sit after the body and are wrapped in HTML comments so Re-export can replace them without touching operator files outside the Note:

```markdown
<!-- confluence-to-md:children -->
## Child pages
- [Child title](Child%20title/Child%20title.md)
<!-- /confluence-to-md:children -->

<!-- confluence-to-md:attachments -->
## Attachments
- [sheet.xlsx](attachments/sheet.xlsx)
<!-- /confluence-to-md:attachments -->
```

- `Child pages` lists every child Page that is in the Selection, in Confluence sibling order, then by title. The section is omitted when there are no such children.
- `Attachments` lists Attachments not already referenced in the body. The section is omitted when every Attachment is referenced, or the Page has none.

## Page links

Rewrite every Confluence link whose target Page is in the Selection to a relative markdown link from the linking Note's directory to that Note's `{title}.md`. Encode spaces and reserved characters. Use `../` to climb. No wikilink syntax.

- A heading fragment is the heading text, percent-encoded, not a slug. Obsidian resolves heading links by heading text.
- A link to a Page outside the Selection stays an absolute Confluence URL (External link).
- An http(s) or mailto URL that is not a Confluence Page stays unchanged.
- A user mention becomes the display name as text. No user Note.
- An include, excerpt-include, or other macro that points at a Page becomes a Page link when that Page is in the Selection, otherwise an External link when a URL is known, otherwise a Placeholder. Do not inline the target body.
- A smart link or card follows the same rule: Page link, else External link, else Placeholder.

## Attachments

Download the latest version of every Attachment on each exported Page into that Note's `attachments/` directory.

- An image shown in the body becomes an Embed: `![alt](attachments/file%20name.png)`. Alt text falls back to the filename.
- A non-image file referenced in the body becomes a markdown link to the local file.
- An Attachment not referenced in the body is still downloaded and listed in the `Attachments` section.
- Sanitize attachment filenames with the same character rules as folder names. A name collision in one `attachments/` directory gets the attachment id appended.
- On Re-export, the same Attachment overwrites the same relative path.
- A failed download does not abort the Export. The Note is still written. The reference keeps its absolute Confluence URL, and the run reports the failure.
- Diagram sources (draw.io and similar) are downloaded as files. Do not render them. If Confluence already embeds a preview image, that image is an Embed of that Attachment.

## Conversion

Read each Page body as Confluence storage format. Write the Note as CommonMark, plus YAML frontmatter, GFM tables, fenced code, and task-list checkboxes. Obsidian callouts are the one flavor extension, and they degrade to blockquotes elsewhere.

- Headings, lists, tables, links, images, emphasis, and inline code convert to markdown.
- A Confluence code macro becomes a fenced block with its language when known.
- A task list becomes `- [ ]` / `- [x]`.
- Info, note, warning, tip, and success panels become Obsidian callouts (`> [!info]`, `> [!note]`, `> [!warning]`, `> [!tip]`, `> [!success]`).
- A simple table becomes a GFM table. A table that cannot be represented stays as an HTML table inside the Note so the content is not dropped.
- A macro with a plain-text body and no richer equivalent becomes that text.
- Any other construct becomes a Placeholder that names the macro or element. The rest of the Page still exports.

## Re-export

Match an existing Note by `confluence_id` in frontmatter, not by path.

- Title or parent change moves the folder to the new Hierarchy path, then writes the new Note. Page links are regenerated from Confluence, so they follow the move.
- Re-export replaces the Note body and the frontmatter this contract lists. It does not delete other files in the folder, and it does not delete or modify `.obsidian/`.
- A Page that is no longer in Confluence or no longer in the Selection is left on disk and named in the run report. The operator deletes it.
- Edits made inside an exported Note do not survive Re-export. Change the Page in Confluence if the change must persist. Files the operator added beside the Note are kept.

## Run outcome

- The process exit code is success when every Page in the Selection was written, including Pages whose Attachment downloads failed.
- The process exit code is failure when Confluence could not be authenticated, the Selection could not be listed, or a Page body could not be read. Pages already written in that run stay on disk.
- A Page the token cannot read is not given an empty Note. It is counted as a failure and omitted from its parent's `Child pages` list.
- The run prints counts of Notes written, Page links rewritten, Attachments downloaded, and each failure (Page id or attachment id, and reason). It also lists each External link that still points at the Site, with the source Page id. No token in that output. The Selection is not expanded to include those targets.
- Transient Confluence errors are retried before a download or Page is reported failed. The operator does not download Attachments by hand.

## Acceptance

The Export is done when all of these hold.

1. A Space with a homepage, two children, and one grandchild exports to the nested layout above. The homepage Note is `{Space}/{Homepage title}/{Homepage title}.md`. Each `Child pages` section links to the children that were exported. Obsidian's file explorer shows those titles, not `index`.
2. Page A links to Page B by title, and both are in the Selection. A's Note contains a relative markdown link to B's `{title}.md`. Following it opens B with no network.
3. Page A links to Page C, and C is not in the Selection. The link remains an absolute Confluence URL.
4. A Page embeds `diagram.png`, links `spec.pdf`, and also has unreferenced `sheet.xlsx`. All three files exist under that Note's `attachments/`. The image renders from the local path. The pdf link opens the local file. `sheet.xlsx` appears only in the `Attachments` section.
5. No relative link and no Embed targets a Confluence host. External links still may.
6. Re-export of the same Page id updates that Note in place and does not create a second Note for that id. A title change moves the folder; the old path is not left holding a copy of the Note.
7. Re-export does not delete a Note whose Page left the Selection, and does not modify `.obsidian/`.
8. The API token does not appear in any file under the Vault.
9. A Page whose body is only an unsupported macro still exports. The Note contains a Placeholder naming the macro, not an empty body and not a dropped file.
10. Opening the Vault root in Obsidian shows the Notes, renders an exported image, opens a non-image Attachment from its link, and connects two Page-linked Notes in the graph. No plugin install.
11. A storage body that links a Page in the Selection and embeds an Attachment image becomes a relative Page link and an Embed. Those two do not contain a Site URL.
12. A list of Spaces that includes an archived Space and a Personal Space prints only the non-archived, non-personal ones, each line showing the Space key and the name. It does not print the token or a count of omitted Personal Spaces. A Site whose only Spaces are Personal Spaces prints no lines and exits success. An Export given that Personal Space's Space key still writes the Space.
13. Page A links to a Page on the same Site that is not in the Selection. The Note keeps that absolute URL, and the run report names A's Page id and that URL. No extra Note is created for the missing Page.

# Confluence export

This context is the export of Confluence pages into a local markdown tree that remains readable after the Site is gone. It exists so source objects and vault objects are never called by the same name.

## Source

**Site**:
The Confluence Cloud host an Operator connects to. A Site contains Spaces.
_Avoid_: endpoint, server, base URL

**Space**:
A Confluence space that contains Pages. Not a Site.
_Avoid_: site, project, wiki

**Personal Space**:
A Space whose Confluence type is personal: one person's Space, not a team Space. The Space key often starts with `~`, but the type identifies it, not the prefix.
_Avoid_: user space, private space

**Space key**:
The stable short identifier of a Space, distinct from its name.
_Avoid_: space name, space id

**Page**:
A Confluence page. Not a blog post, whiteboard, database, attachment, comment, or historical version.
_Avoid_: document, article, note, blog post, comment

**Page id**:
The stable Confluence identifier of a Page. Survives a title change.
_Avoid_: slug, filename, url

**Label**:
A tag Confluence stores on a Page.
_Avoid_: tag, property

**Attachment**:
A file stored on a Page in Confluence, including images and non-image files.
_Avoid_: asset, media, embed

**Selection**:
The set of Pages one Export writes. Either one or more Spaces, or one Page and its descendants, not both in the same Export.
_Avoid_: query, filter, scope

## Vault

**Operator**:
The person who runs an Export against their own Site, supplying that Site's URL and their own token.
_Avoid_: user, owner, admin

**Export**:
One run that writes a Selection into a Vault.
_Avoid_: sync, backup, migration, scrape

**Vault**:
The directory tree an Export writes, opened as a knowledge base, and still readable after the Site is gone. Obsidian is the reference reader.
_Avoid_: knowledge base as a second output, dump, archive, mirror, output folder

**Note**:
The markdown file an Export writes for one Page. One Page, one Note.
_Avoid_: page, page file, document

**Hierarchy**:
The parent-child relation among Pages in a Selection, mirrored as nested folders in the Vault.
_Avoid_: structure, tree, outline

**Page link**:
A link from a Note to another Note in the same Vault, produced by rewriting a Confluence link whose target Page is in the Selection. Includes a same-note heading fragment.
_Avoid_: wikilink, hyperlink, backlink

**External link**:
A link whose target is not a Page in the Selection. The destination stays a URL.
_Avoid_: broken link, remote link

**Embed**:
An inline reference in a Note body to an Attachment, usually an image. The Attachment is still an Attachment.
_Avoid_: image, inline file

**Placeholder**:
Visible text an Export leaves where a Confluence construct has no markdown equivalent. The surrounding Page still becomes a Note.
_Avoid_: skip, omit, error

**Re-export**:
An Export into an existing Vault that updates Notes for the Selection in place, matched by Page id.
_Avoid_: sync, incremental, overwrite-all

# File Search (W3) — integration status

**This feature is wired in. Do not follow splice instructions here; there are
none left.** An earlier version of this file listed snippets for a maintainer
to paste into the shared file-manager UI. Those splices were superseded: the
integration that actually shipped takes a different and better shape, and
pasting the old snippets on top of it would render the results twice.

## What is wired, and where

| Piece | Lives in | Notes |
|---|---|---|
| Mode toggle | `file-manager/components/FileActionsBar.tsx` | Renders `SearchModeToggle`; defaults to `filename`. |
| Re-index button | same file | Shown only in content mode. |
| Search state | `file-manager/FileManagerPage.tsx` | `searchMode` state plus `contentActive`. |
| The query | same file | `useContentSearch`, fires only in content mode with a non-empty term. |
| Result rendering | same file | Hits are mapped to `FileRow` and rendered by the existing `FileGrid` / `FileList`. |
| Snippet + match highlight | `FileGrid.tsx`, `FileList.tsx` | `row.extra.snippet` through `SnippetHighlight`, with the live term passed down as `searchQuery`. |
| Failed-search banner | `FileManagerPage.tsx` | A search that does not return says so instead of drawing an empty result. |

Mapping hits onto `FileRow` rather than rendering a separate results list is
deliberate: selection, open, context menu, favourites and the preview pane all
work on search hits for free, because they are the same rows the grid already
knows how to drive.

Two consequences of that choice are handled explicitly in the two view
components, and are worth knowing before you touch them. A hit comes from the
search index, not from a directory listing, so it carries no size and no
modified date. The grid and the list both suppress those columns for a hit
rather than printing the placeholder zero, which would read as an empty file.

## `SearchResults.tsx` is not mounted

It is the standalone results list from the original design, kept because it is
the natural renderer if the search ever needs a surface of its own (a global
search palette, for instance). Today nothing imports it. If you are adding a
new search surface, start there; if you are editing the file manager, you want
`FileGrid` / `FileList`.

## Optional index maintenance, still open

Neither of these is wired, and both are cheap:

* Index on upload. Call `useIndexFile` in the upload mutation's `onSuccess`.
  Until then a freshly uploaded file is findable by name but not by content
  until someone presses re-index.
* Drop from the index on delete. Call `removeFromIndex` after a successful
  delete, so a deleted file stops appearing in content results.

## API

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| POST | `/api/v1/file-search/index/` | `file_search.index` | Index one file by id |
| GET | `/api/v1/file-search/` | `file_search.read` | Run a search |
| POST | `/api/v1/file-search/reindex/` | `file_search.index` | Re-OCR every file |
| DELETE | `/api/v1/file-search/{file_id}/` | `file_search.index` | Drop one row |

The migration is `backend/alembic/versions/v3061_file_search_tags.py`.

## Extraction dependencies

`pypdfium2` (PDF text and page rendering) and `opencv-python-headless` are base
dependencies, not extras: an `ImportError` on either means a broken install, not
a missing optional. Only `paddleocr` and `Pillow` sit behind the `cv` extra. Without them, image content
is not searchable but the file is still findable by name, and the endpoint
reports `ocr_engine = 'none'` rather than failing.

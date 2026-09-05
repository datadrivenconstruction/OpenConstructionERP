# Vendored ReDoc

`/api/redoc` serves this file from this install instead of fetching it from
`cdn.jsdelivr.net`, which is what FastAPI's stock ReDoc route does. Without it
the page arrives as a bare `<redoc>` element that never upgrades, so the
operator gets a white page with nothing in the console to search for, and an
air-gapped or egress-filtered VPS is a normal deployment for this platform
rather than an edge case.

| File | Purpose |
|---|---|
| `redoc.standalone.js` | The ReDoc application |
| `redoc.standalone.js.LICENSE.txt` | Licenses of the libraries inside the bundle |

Source: [redoc](https://www.npmjs.com/package/redoc), version **2.5.3**,
MIT. Taken unmodified from the published package.

Cost: 1,099,998 bytes on disk and 326,708 deflated. That is less than the
Swagger UI assets next door already cost, which is worth stating because the
note this replaces put the price at "roughly another megabyte" and declined the
fix on it. Both numbers were right about different things: a megabyte is the
disk figure, and the 100 MiB ceiling the published wheel is measured against
counts the deflated one. Nothing was added to `dependencies` for it.

There is no stylesheet to vendor. ReDoc carries its styles inside the bundle,
and the stock page's other two outbound requests are dropped rather than
replaced: the Google Fonts stylesheet is switched off at the call site
(`with_google_fonts=False`) so the page falls back to the system sans-serif,
and the favicon points at this install's own.

The file reaches the wheel through the ordinary `app` package walk, so it needs
no entry in the `force-include` map, and adding one would ship it twice and
have PyPI reject the upload:

```bash
uv build --wheel && python -m zipfile -l dist/*.whl | grep redoc
```

## Updating

Pin an exact version rather than the `@2` range the stock FastAPI template
uses, so a CDN-side release cannot change what this install serves:

```sh
V=2.5.3
for f in redoc.standalone.js redoc.standalone.js.LICENSE.txt; do
  curl -sS -o "backend/app/static/redoc/$f" \
    "https://cdn.jsdelivr.net/npm/redoc@$V/bundles/$f"
done
```

Then update the version above, and the one named in the comment beside
`_DOCS_ASSETS` in `app/main.py`.

`tests/unit/test_the_api_docs_page_does_not_need_the_internet.py` fetches every
URL the page names and checks the bytes, so a partial or failed download fails
the suite rather than shipping a blank reference page.

## What still leaves the machine

One request, and the page does not depend on it. ReDoc renders an `<img>` for
the Redocly mark at `https://cdn.redoc.ly/redoc/logo-mini.svg` and hides it
from its own `onError` handler, so offline the image 404s in the network log
and the page is otherwise complete. Removing it would mean writing the page's
HTML by hand instead of calling `get_redoc_html`, or editing the vendored
bundle, and neither is worth it for an image that already fails safe.

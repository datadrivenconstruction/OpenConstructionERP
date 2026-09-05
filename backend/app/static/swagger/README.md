# Vendored Swagger UI

`/api/docs` serves these two files from this install instead of fetching them
from `cdn.jsdelivr.net`, which is what FastAPI's stock docs route does. Without
them the page arrives as an empty shell on any machine with no outbound
internet, and an air-gapped or egress-filtered VPS is a normal deployment for
this platform rather than an edge case.

| File | Purpose |
|---|---|
| `swagger-ui-bundle.js` | The Swagger UI application |
| `swagger-ui.css` | Its stylesheet |
| `swagger-ui-bundle.js.LICENSE.txt` | Licenses of the libraries inside the bundle |

Source: [swagger-ui-dist](https://www.npmjs.com/package/swagger-ui-dist),
version **5.32.15**, Apache-2.0. Taken unmodified from the published package.

Cost: 1,737,993 bytes on disk and 452,877 deflated, read back out of a built
wheel rather than estimated. That is the whole price of the fix; nothing was
added to `dependencies` for it, because a package would have brought its own
release cadence and a great deal more than two files.

The files reach the wheel through the ordinary `app` package walk, so they need
no entry in the `force-include` map, and adding one would ship them twice and
have PyPI reject the upload. That the walk really carries them is worth
checking after any change to the ignore rules, because it is the walk that
silently dropped the twelve site photos:

```bash
uv build --wheel && python -m zipfile -l dist/*.whl | grep swagger
```

## Updating

Pin an exact version rather than the `@5` range the stock FastAPI template
uses, so a CDN-side release cannot change what this install serves:

```sh
V=5.32.15
for f in swagger-ui-bundle.js swagger-ui.css swagger-ui-bundle.js.LICENSE.txt; do
  curl -sS -o "backend/app/static/swagger/$f" \
    "https://cdn.jsdelivr.net/npm/swagger-ui-dist@$V/$f"
done
```

Then update the version above, and the one named in the comment beside
`_SWAGGER_DIR` in `app/main.py`.

`tests/unit/test_the_api_docs_page_does_not_need_the_internet.py` fetches every
URL the page names and checks the bytes, so a partial or failed download fails
the suite rather than shipping a blank docs page.

## Not covered

`/api/redoc` still uses FastAPI's stock route and still loads
`redoc.standalone.js` from the CDN, so it stays blank offline. Vendoring it
costs roughly another megabyte, and it is not the page the boot banner points
new operators at.

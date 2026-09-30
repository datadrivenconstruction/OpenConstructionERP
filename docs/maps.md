# Maps and basemaps

Every map in OpenConstructionERP fetches its basemap from your own server at
`/api/v1/geo-hub/`. Browsers never contact a tile host directly. This keeps
ad and privacy blockers from blanking the maps, and it means the Content
Security Policy needs no extra hosts.

## Street maps (default, no setup)

The 2D maps show streets with street names, in a dark variant when the app
uses the dark theme. These include the dashboard map, project maps, the geo
hub, and project card thumbnails. They use vector tiles from the public
[OpenFreeMap](https://openfreemap.org/) instance, which needs no key and sets
no request limit ([terms](https://openfreemap.org/tos/)). The map data is
© OpenStreetMap contributors under the ODbL, and every map shows that credit.

For an offline or high-volume install, run your own OpenFreeMap copy and
point the server at it:

```env
OE_BASEMAP_UPSTREAM=https://tiles.example.internal
```

That server must expose the same paths as the public instance: `/planet`,
`/fonts`, `/sprites` and `/natural_earth`.

## The 3D globe

The 3D globe can only draw raster tiles (images). The 2D maps use vector
tiles, and the globe cannot read them. No free public raster street service
allows use from an application: the OpenStreetMap Foundation tile servers
forbid it in their
[usage policy](https://operations.osmfoundation.org/policies/tiles/). So by
default the globe shows public-domain shaded relief from Natural Earth.

If you run a raster tile server yourself, or license one, the globe can show
streets instead:

```env
OE_GLOBE_STREET_TILES_URL=https://tiles.example.internal/osm/{z}/{x}/{y}.png
OE_GLOBE_STREET_TILES_ATTRIBUTION=© OpenStreetMap contributors
OE_GLOBE_STREET_TILES_MAX_ZOOM=19
```

- `OE_GLOBE_STREET_TILES_URL` is an XYZ template with `{z}`, `{x}` and `{y}`.
  It must use http or https.
- `OE_GLOBE_STREET_TILES_ATTRIBUTION` is the credit your tile licence
  requires. It is required. If it is missing, the setting is ignored and the
  globe stays on relief, because a map must not be shown without its credit.
  The server logs a warning when that happens.
- `OE_GLOBE_STREET_TILES_MAX_ZOOM` is the deepest zoom level your server has.
  The default is 19. Beyond it, the globe enlarges the last level instead of
  requesting empty tiles.

Tiles are proxied through `/api/v1/geo-hub/globe-streets/{z}/{x}/{y}.png`,
so your tile server does not need to be reachable from the browser. Any
answer that is not a PNG, JPEG or WebP image shows as an empty tile, so an
error page from your tile server never appears on the globe. Tiles are cached
for a day, so a change of provider reaches users without a cache purge.
Restart the server after changing these settings.

You are responsible for the terms of the tile server you configure. Do not
point this at `tile.openstreetmap.org` or any other service whose policy
forbids proxying or use from an application.

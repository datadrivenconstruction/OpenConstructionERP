// defineConfig comes from vitest/config, not vite, because the `test` block
// near the bottom of this file is part of the config object and vite's own
// UserConfig has no such property. Line 1 used to be
// /// <reference types="vitest" />, which is how vitest 0.x augmented vite's
// type; it stopped doing that in 1.0 and we are on 4.1.9, so the reference had
// been a declaration with no reader for a long time and the `test` block was
// unchecked. Runtime was never affected - vitest reads this file either way.
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { VitePWA } from 'vite-plugin-pwa';
import path from 'path';
import { cpSync, existsSync, readFileSync, readdirSync, createReadStream, statSync } from 'fs';
import type { Plugin } from 'vite';
import { STATIC_ASSETS_CACHE, isStaticAssetRequest } from './src/pwa/staticAssetRoute';

const cesiumSource = path.resolve(__dirname, 'node_modules/cesium/Build/Cesium');
const cesiumDirs = ['Workers', 'ThirdParty', 'Assets', 'Widgets'] as const;

// Cesium's runtime fetches Workers / Widgets / Assets / ThirdParty from
// ``window.CESIUM_BASE_URL`` (we set it to ``/cesium/`` in main.tsx). At build
// time ``writeBundle`` copies the files into ``dist/cesium/``. The dev server
// needs the same thing — without the middleware below, /cesium/Workers/*.js
// falls through to Vite's SPA index.html, the Cesium loader gets a 200 with
// "<!DOCTYPE html>" instead of JS, and the page wedges before the viewer
// initialises. Middleware streams directly out of node_modules so first paint
// is instant and HMR keeps working.
function cesiumAssets(): Plugin {
  return {
    name: 'cesium-assets',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? '';
        if (!url.startsWith('/cesium/')) {
          next();
          return;
        }
        const rel = decodeURIComponent(url.slice('/cesium/'.length).split('?')[0] ?? '');
        const file = path.join(cesiumSource, rel);
        if (!file.startsWith(cesiumSource) || !existsSync(file) || statSync(file).isDirectory()) {
          next();
          return;
        }
        const ext = path.extname(file).toLowerCase();
        const mime: Record<string, string> = {
          '.js': 'application/javascript',
          '.mjs': 'application/javascript',
          '.json': 'application/json',
          '.css': 'text/css',
          '.wasm': 'application/wasm',
          '.glb': 'model/gltf-binary',
          '.gltf': 'model/gltf+json',
          '.svg': 'image/svg+xml',
          '.png': 'image/png',
          '.jpg': 'image/jpeg',
          '.jpeg': 'image/jpeg',
          '.xml': 'application/xml',
          '.ktx2': 'image/ktx2',
        };
        if (mime[ext]) {
          res.setHeader('Content-Type', mime[ext]);
        }
        res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
        createReadStream(file).pipe(res);
      });
    },
    writeBundle(options) {
      const outDir = options.dir ?? path.resolve(__dirname, 'dist');
      if (!existsSync(cesiumSource)) return;
      for (const sub of cesiumDirs) {
        const src = path.join(cesiumSource, sub);
        const dest = path.join(outDir, 'cesium', sub);
        if (existsSync(src)) {
          cpSync(src, dest, { recursive: true });
        }
      }
    },
  };
}

const pdfjsRoot = path.resolve(__dirname, 'node_modules/pdfjs-dist');
// The two directories the PDF.js worker fetches from at runtime. ``wasm``
// holds the JBIG2 and JPEG 2000 decoders, a JavaScript fallback for each, and
// the colour-management module; ``iccs`` holds the CMYK profile. The
// ``quickjs-eval`` pair is skipped: it is the sandbox for JavaScript embedded
// in a PDF, which no viewer here loads, and it is the largest file there.
const pdfjsAssetDirs = ['wasm', 'iccs'] as const;

// PDF.js 5 moved the JBIG2 and JPEG 2000 decoders out of the worker into
// WebAssembly files it fetches on demand under the ``wasmUrl`` option, and
// without that option the image is simply not drawn, which for a scanned
// drawing is the whole page. src/shared/lib/pdfjs.ts passes ``wasmUrl`` and
// ``iccUrl`` to every getDocument call; this plugin is what makes those URLs
// answer. The files have fixed names and are addressed by directory, so they
// cannot go through Vite's hashed asset pipeline: the build emits them under
// ``assets/pdfjs/<version>/`` and the dev server streams the same paths out
// of node_modules. Under ``assets/`` because that is the one directory the
// backend mounts as files (everything else falls through to index.html), and
// with the version in the path because that mount answers with a year-long
// immutable cache header while the file names never change between PDF.js
// releases: without the segment a bump would pair a new worker with a cached
// old decoder. The runtime reads the same version from the library itself.
function pdfjsAssets(): Plugin {
  const pkgPath = path.join(pdfjsRoot, 'package.json');
  const version = existsSync(pkgPath)
    ? (JSON.parse(readFileSync(pkgPath, 'utf-8')).version as string)
    : '';
  const prefix = `/assets/pdfjs/${version}/`;
  const keep = (name: string) => !name.startsWith('quickjs-eval');
  return {
    name: 'pdfjs-assets',
    configureServer(server) {
      if (!version) return;
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? '';
        if (!url.startsWith(prefix)) {
          next();
          return;
        }
        const rel = decodeURIComponent(url.slice(prefix.length).split('?')[0] ?? '');
        const sub = rel.split('/')[0] ?? '';
        const file = path.join(pdfjsRoot, rel);
        if (
          !(pdfjsAssetDirs as readonly string[]).includes(sub) ||
          !keep(path.basename(file)) ||
          !file.startsWith(pdfjsRoot) ||
          !existsSync(file) ||
          statSync(file).isDirectory()
        ) {
          next();
          return;
        }
        const mime: Record<string, string> = {
          '.wasm': 'application/wasm',
          '.js': 'text/javascript',
          '.icc': 'application/vnd.iccprofile',
        };
        const type = mime[path.extname(file).toLowerCase()];
        if (type) res.setHeader('Content-Type', type);
        createReadStream(file).pipe(res);
      });
    },
    generateBundle() {
      if (!version) return;
      for (const sub of pdfjsAssetDirs) {
        const dir = path.join(pdfjsRoot, sub);
        if (!existsSync(dir)) continue;
        for (const name of readdirSync(dir)) {
          const file = path.join(dir, name);
          if (!keep(name) || statSync(file).isDirectory()) continue;
          this.emitFile({
            type: 'asset',
            fileName: `assets/pdfjs/${version}/${sub}/${name}`,
            source: readFileSync(file),
          });
        }
      }
    },
  };
}

// Read the version from package.json once at build time so the entire app
// (sidebar, About page, error reports, update checker) stays in sync.
const pkg = JSON.parse(readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'));

// The static JSON-LD block in index.html advertises ``softwareVersion`` to
// search engines. Rewrite it from package.json at serve/build time so the
// SEO metadata can never drift from the released version again (the literal
// sat at 0.2.4 while the app shipped 7.6.0). The literal in the source file
// stays as a fallback for tools that read the raw file.
function jsonLdSoftwareVersion(): Plugin {
  return {
    name: 'jsonld-software-version',
    transformIndexHtml(html) {
      return html.replace(
        /"softwareVersion":\s*"[^"]*"/,
        `"softwareVersion": "${pkg.version}"`,
      );
    },
  };
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [
    react(),
    process.env.ANALYZE === '1' && visualizer({
      filename: 'stats.html',
      gzipSize: true,
      brotliSize: true,
      open: false,
    }),
    cesiumAssets(),
    pdfjsAssets(),
    jsonLdSoftwareVersion(),
    // ── Mobile PWA — Slice 1 ────────────────────────────────────────────
    // Installable PWA with offline-app-shell + i18n bundle caching.
    //
    // * App-shell precaching is handled by workbox (generateSW), which
    //   automatically picks up the build outputs via the
    //   ``globPatterns``.  No additional pre-cache list is needed.
    // * Runtime caching is split into three deliberately-named lanes
    //   so each behaviour is independently verifiable in the SW unit
    //   tests:
    //     - "oce-static-assets-v2"  CacheFirst for same-origin fonts,
    //       images and /assets/ files, status 200 only.
    //     - "oce-i18n-locales"   StaleWhileRevalidate for the per-locale
    //       chunks under ``assets/i18n-*.js`` so a returning user gets
    //       an instant paint in their last language even when offline,
    //       while the background fetch keeps the chunk fresh.
    //     - "oce-api"            NetworkFirst for ``/api/v1/*`` GETs
    //       with a 30s timeout; cache used only as offline fallback for
    //       idempotent reads.  Mutations (POST/PUT/PATCH/DELETE) bypass
    //       the cache and surface a network error normally.
    //
    // * Navigation fallback points at ``/index.html`` so a refresh from
    //   any deep route while offline still gets the SPA shell back; the
    //   inner ``<Routes>`` then resolves whatever route is in the URL
    //   and the per-feature ``OfflineFallback`` renders if the route's
    //   own data hooks fail.
    //
    // * registerType=autoUpdate + injectRegister=auto: the SW silently
    //   takes over and starts updating in the background; ``skipWaiting``
    //   + ``clientsClaim`` mean the next navigation picks up the new
    //   bundle.  No "Update available" toast in this slice; deferred
    //   behind ``vite-plugin-pwa``'s ``registerSW`` helper for a future
    //   slice.
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      // Strip the SW + manifest from the dev server entirely; the dev
      // server is HMR-driven and a stale workbox precache would mask
      // edits during development.  ``npm run build`` still emits both.
      devOptions: { enabled: false },
      includeAssets: ['favicon.svg', 'pwa/*.svg'],
      manifest: {
        name: 'OpenConstructionERP',
        short_name: 'OCERP',
        description:
          'Open-source construction cost estimation, BIM takeoff, BOQ, tendering and field operations.',
        theme_color: '#0284c7',
        background_color: '#f7fbff',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        scope: '/',
        lang: 'en',
        icons: [
          { src: '/pwa/icon-192.svg', sizes: '192x192', type: 'image/svg+xml', purpose: 'any' },
          { src: '/pwa/icon-256.svg', sizes: '256x256', type: 'image/svg+xml', purpose: 'any' },
          { src: '/pwa/icon-384.svg', sizes: '384x384', type: 'image/svg+xml', purpose: 'any' },
          { src: '/pwa/icon-512.svg', sizes: '512x512', type: 'image/svg+xml', purpose: 'any' },
          { src: '/pwa/icon-maskable-512.svg', sizes: '512x512', type: 'image/svg+xml', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Precache index + JS/CSS/HTML + the static SVGs above.  Vite's
        // build output lands in ``dist/``; workbox-build resolves the
        // patterns relative to that.
        //
        // ``.mjs`` MUST be in the glob — pdf.worker.min-*.mjs is shipped
        // as an ESM module and is loaded via ``new Worker(url, {type:
        // 'module'})``. If it isn't precached, workbox falls through to
        // the CacheFirst runtime rule for /assets/, which has occasionally
        // returned cached responses without the correct ``Content-Type``
        // header in some browsers. The downstream symptom was a
        // "Setting up fake worker failed: error loading dynamically
        // imported module" on /takeoff. Including ``.mjs`` precaches the
        // worker with its real headers and removes the runtime-cache
        // intermediary altogether.
        globPatterns: ['**/*.{js,mjs,css,html,svg,woff2,ico}'],
        // Skip huge prerendered marketing assets (handled by the static
        // host) and stats.html (visualizer output).
        //
        // The locale chunks are excluded deliberately, and not because
        // they are merely large. Precaching them means every visitor
        // downloads all 43 languages to read one: the chunks run past
        // 5 MB each, so the manifest was asking for well over 200 MB
        // before anyone saw a screen. They already have their own
        // ``oce-i18n-locales`` StaleWhileRevalidate lane below, which
        // caches the one locale a reader actually loads and refreshes it
        // in the background, so precaching them was never doing work the
        // runtime lane does not already do better.
        //
        // Leaving them in is also what broke the build rather than merely
        // bloating it: workbox fails ``generateSW`` outright once a
        // precache entry exceeds the ceiling, so every locale that grew
        // past it took the desktop build down with it. Excluding them
        // takes the growing file out of the manifest entirely, which is
        // the fix that does not need revisiting the next time a
        // translation lands.
        //
        // splash.html is excluded because the web build has no use for it at
        // all. It is the desktop launcher's startup screen, loaded by the
        // Tauri window from the tauri:// origin before this bundle exists, and
        // nothing a browser can reach ever links to it. It only appears here
        // because it lives in ``public/``, which Vite copies verbatim. Left in,
        // every web visitor downloads it on first load to cache a page they
        // can never open, and it grows every time a language is added to it.
        //
        // The PDF.js runtime assets (see the pdfjs-assets plugin) are left to
        // the runtime lane too. The wasm files never matched the glob; the
        // JavaScript fallbacks next to them would, and they are 600 KB of
        // decoder that only a browser without WebAssembly ever asks for.
        globIgnores: ['stats.html', 'splash.html', '**/*.map', '**/i18n-*.js', 'assets/pdfjs/**'],
        // Allow large lazy-loaded chunks (vendor-three, vendor-maplibre)
        // to be precached on first visit. Workbox's own default is 2 MiB;
        // this raises it, it does not restate it.
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        navigateFallback: '/index.html',
        // Don't try to fall back to /index.html for API routes or for
        // file/asset routes the SW doesn't precache.
        navigateFallbackDenylist: [/^\/api\//, /^\/static\//, /^\/pwa\//],
        cleanupOutdatedCaches: true,
        skipWaiting: true,
        clientsClaim: true,
        runtimeCaching: [
          {
            // Same-origin static files: fonts, images and /assets/ chunks.
            //
            // SAME ORIGIN AND STATUS 200 ONLY. This lane used to take every
            // image, cross-origin included, and cache status 0. A
            // cross-origin <img> gets an opaque response, and an opaque 404
            // looks exactly like an opaque 200, so failures were cached and
            // served for 30 days: video covers stayed blank until a hard
            // reload bypassed the worker. Cross-origin images now go to the
            // browser's HTTP cache. The predicate and the reasoning live in
            // src/pwa/staticAssetRoute.ts, with tests; the cache was renamed
            // and main.tsx deletes the old one.
            //
            // Worker scripts (pdf.worker.min, cesium/Workers/*) are excluded
            // there too: a CacheFirst hit could serve a response whose
            // module/script disposition tripped ``new Worker(url, {type:
            // 'module'})`` into the "fake worker" fallback.
            urlPattern: isStaticAssetRequest,
            handler: 'CacheFirst',
            options: {
              cacheName: STATIC_ASSETS_CACHE,
              expiration: {
                maxEntries: 200,
                maxAgeSeconds: 30 * 24 * 60 * 60, // 30 days
              },
              cacheableResponse: { statuses: [200] },
            },
          },
          {
            // i18n locale chunks — names emitted by manualChunks above
            // are ``i18n-<code>``.  StaleWhileRevalidate keeps the
            // active locale instant-on while still pulling fresh keys
            // in the background.
            // Regional codes carry a hyphen and a country, so the code half
            // has to allow one or this lane silently skips en-US and the
            // four Spanish and Portuguese variants.
            urlPattern: ({ url }) => /\/assets\/i18n-[a-z]{2,3}(?:-[A-Z]{2})?-.*\.js$/.test(url.pathname),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'oce-i18n-locales',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 14 * 24 * 60 * 60, // 14 days
              },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // API reads — NetworkFirst with 30 s timeout, cache only
            // used as the offline fallback for idempotent GETs.  Other
            // verbs bypass the SW (no ``method`` match here means GET
            // by default).
            urlPattern: ({ url, request }) => {
              if (request.method !== 'GET') return false;
              // A bidder link's token is its credential; never keep it, or
              // the bill behind it, in a cache on a shared device.
              if (url.pathname.startsWith('/api/v1/tendering/bid-portal/')) return false;
              return url.pathname.startsWith('/api/v1/');
            },
            handler: 'NetworkFirst',
            options: {
              cacheName: 'oce-api',
              networkTimeoutSeconds: 30,
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 24 * 60 * 60, // 1 day
              },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    // Without dedupe, recharts can pull a second copy of react/react-dom through
    // its peer-dep optimize-deps pre-bundle in vite dev mode. The duplicate
    // instances make useContext return null inside ResponsiveContainer the moment
    // the Simulator tab mounts after a cold optimize flush — the page hits the
    // ErrorBoundary with "Cannot read properties of null (reading 'useContext')"
    // and the production bundle is unaffected (single chunk = single React).
    // Reported by qa/V3-propdev-pricing-engine.
    dedupe: ['react', 'react-dom'],
  },
  server: {
    host: '127.0.0.1',
    // Vite default — matches the README quickstart, default Playwright
    // config, and every "localhost:5173" link in locales/marketing. Was
    // hard-coded to 5180 historically; reverted to 5173 in the install
    // paper-cuts sweep (internal QA note FRESH_INSTALL_RESULTS Issue 4) so the
    // README's documented URL actually reaches the dev server.
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        // Local dev backend default :8000 — matches the README quickstart
        // (``uvicorn ... --port 8000``). The previous 9090 default came
        // from a v4.1.0 local-dev convention nobody else uses and caused
        // every API call to 502 on a fresh checkout until the user found
        // the ``VITE_API_TARGET`` override buried in this comment block.
        // Operators who run on a different port can still override via
        // ``VITE_API_TARGET=http://127.0.0.1:9090 npm run dev``.
        target:
          process.env.VITE_API_TARGET ??
          process.env.E2E_BACKEND ??
          'http://127.0.0.1:8000',
        changeOrigin: true,
        // 30 minutes. Catalogue v3 installs (`/costs/catalogues-v3/{id}/install`)
        // download a 200–500 MB snapshot from Hugging Face, stream it
        // multipart into Qdrant, then poll Qdrant for collection
        // registration. The full round-trip routinely runs 5–15 min on a
        // typical home link; the previous 5-min ceiling killed the
        // connection mid-install and the browser surfaced it as
        // "Failed to fetch", with no useful diagnostic. proxyTimeout
        // covers the upstream-response wait specifically; timeout covers
        // the socket as a whole — both need to be generous.
        timeout: 30 * 60 * 1000,
        proxyTimeout: 30 * 60 * 1000,
      },
    },
  },
  // Pre-bundle heavy deps that are imported lazily by route-level chunks.
  // Without this, Vite discovers them only when the chunk first loads and
  // triggers a "504 Outdated Optimize Dep" on the in-flight import — which
  // surfaces as "Failed to fetch dynamically imported module" on the takeoff
  // and BIM pages.  Including them up-front keeps the version hash stable
  // across the dev session.
  optimizeDeps: {
    // Single ``include`` array — previously this object had TWO ``include``
    // keys (cesium-only + everything-else) and esbuild's JS evaluator
    // silently dropped the first one, plus warned on every Vite boot with
    // ``Duplicate key "include" in object literal``. Merged into one list
    // in the install paper-cuts sweep (internal QA note FRESH_INSTALL_RESULTS
    // Issue 6).
    //
    // ``cesium`` ships a mix of ESM + CJS deps (mersenne-twister, urijs,
    // etc.). Without pre-bundling, Vite's dev server fails the dynamic
    // import with "does not provide an export named 'default'" the moment
    // Cesium pulls in a CJS interop. Including it here forces esbuild to
    // bundle cesium up front so CJS named-exports become real default
    // exports. The Rollup ``manualChunks`` rule still keeps it in its own
    // production chunk.
    //
    // The rest of the list — pdfjs-dist, three, ag-grid, etc. — are heavy
    // deps reached only via lazy route chunks. Without pre-bundling, Vite
    // discovers them mid-navigation and the in-flight import 504s with
    // "Failed to fetch dynamically imported module".
    include: [
      'cesium',
      'pdfjs-dist/legacy/build/pdf.mjs',
      'pdfjs-dist/legacy/build/pdf.worker.min.mjs',
      'three',
      'ag-grid-react',
      'ag-grid-community',
      'recharts',
      'jspdf',
      'jspdf-autotable',
      'maplibre-gl',
      'react-map-gl/maplibre',
      'exceljs',
      'yjs',
      'y-websocket',
      'y-webrtc',
      '@xyflow/react',
      '@dnd-kit/core',
      '@dnd-kit/sortable',
      '@dnd-kit/utilities',
    ],
  },
  build: {
    // Keep heavy, route-only vendor chunks out of the entry HTML's eager
    // <link rel="modulepreload"> set. They are reached only through lazy()
    // routes (geo hub globe, flow editor, 3D viewer, PDF/takeoff, Excel
    // export, realtime collab), so preloading them on the very first paint
    // makes every session pay for libraries most never open. They still
    // load on demand when their route mounts. Only the entry HTML preload
    // is trimmed; runtime dynamic-import preloads stay intact so navigating
    // to a heavy route still warms its chunks (V321-PERF-03).
    modulePreload: {
      resolveDependencies: (_url, deps, ctx) => {
        if (ctx.hostType !== 'html') return deps;
        const HEAVY = /vendor-(cesium|flow|three|pdf|pdf-export|exceljs|collab)/;
        return deps.filter((d) => !HEAVY.test(d));
      },
    },
    rollupOptions: {
      output: {
        manualChunks(id) {
          // i18n locales: each ``src/app/locales/<code>.ts`` is fetched
          // on demand via dynamic import in ``i18n.ts``. Vite emits one
          // chunk per locale automatically; pin a stable name so cache
          // keys survive minor unrelated edits.  Checked first because
          // these are source files, not node_modules (the guard below
          // would otherwise skip them).
          // The code is not always two letters.  Six catalogues are named
          // otherwise - en-US, es-MX, es-CL, es-CO, pt-BR, fil - and a
          // two-letter pattern left every one of them unnamed here.  They
          // still got a chunk each, because the dynamic import splits them
          // either way, so nothing about the build looked wrong.  What they
          // lost was the ``i18n-`` prefix, which is what ``globIgnores`` and
          // the runtime cache lane below both key on.  Measured on the
          // 15.0.0 build that put 15.6 MB of locale catalogues into the
          // precache manifest, which is precisely what the comment above
          // ``globIgnores`` says must never happen again.
          const localeMatch = id.match(/[\\/]src[\\/]app[\\/]locales[\\/]([a-z]{2,3}(?:-[A-Z]{2})?)\.ts$/);
          if (localeMatch) return `i18n-${localeMatch[1]}`;
          // Vite's module-preload helper (`__vitePreload`) is a virtual module
          // ("\0vite/preload-helper.js"). Left unassigned, Rollup folds it into
          // whichever vendor chunk shares its import signature (it landed in
          // vendor-maplibre), forcing the entry to statically import that ~1 MB
          // chunk just to get the ~1 KB helper every lazy() route uses. Pin it to
          // its own chunk. Checked before the node_modules guard because the
          // virtual id contains no "node_modules" (V321-PERF-04).
          if (id.includes('vite/preload-helper')) return 'vendor-preload';
          if (!id.includes('node_modules')) return;
          // A bare CSS side-effect import (e.g. maplibre-gl's stylesheet,
          // which the dashboard map widget imports eagerly so markers
          // position correctly on first paint) must not be grouped into a
          // heavy JS vendor chunk. Grouping the CSS with the JS forces the
          // entry to statically pull that vendor's ~1 MB JS just to fetch
          // the stylesheet. Returning undefined lets Vite co-locate the CSS
          // with its importing chunk, so the JS stays truly async behind its
          // dynamic import (V321-PERF-02).
          if (/\.css($|\?)/.test(id)) return;
          // DOMPurify is shared by the eager app shell (Markdown + the always
          // mounted floating chat panel, via isomorphic-dompurify), the lazy
          // Cesium globe, and the PDF export stack (jspdf). Unassigned, Rollup
          // bucketed it into vendor-cesium, so the entry statically imported the
          // 4.8 MB cesium chunk just to get the sanitizer (and vendor-pdf-export
          // dynamically imported cesium for the same reason). Pin DOMPurify to
          // its own tiny chunk; the entry imports that, and cesium / pdf-export
          // share it. node_modules/dompurify does not match the isomorphic
          // wrapper, so both are listed (V321-PERF-05).
          if (
            id.includes('node_modules/dompurify') ||
            id.includes('node_modules/isomorphic-dompurify')
          )
            return 'vendor-dompurify';
          // ── Heavy, route-only vendors → dedicated async chunks ───────
          // These libraries are only reached through `lazy()` route
          // chunks (BOQ editor, dashboard map, PDF/DWG takeoff, Excel
          // export, flow editor).  Pinning each to its own chunk keeps
          // them OUT of the initial `index` chunk and lets multiple
          // routes share a single cached copy instead of duplicating the
          // payload per route chunk (V320-PERF-01).  Order: most specific
          // first; map rule before any generic react rule so the
          // `react-map-gl` adapter rides with maplibre, not vendor-react.
          if (id.includes('node_modules/exceljs')) return 'vendor-exceljs';
          if (
            id.includes('node_modules/maplibre-gl') ||
            id.includes('node_modules/react-map-gl')
          )
            return 'vendor-maplibre';
          if (id.includes('node_modules/ag-grid-')) return 'vendor-ag-grid';
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-'))
            return 'vendor-recharts';
          if (id.includes('node_modules/@xyflow/')) return 'vendor-flow';
          if (id.includes('node_modules/@dnd-kit/')) return 'vendor-dnd';
          if (id.includes('node_modules/three')) return 'vendor-three';
          // CesiumJS — Geo Hub. Optional dep (~3 MB minified). Lives
          // in its own chunk so the main bundle never pays the cost
          // when the user never visits /geo.
          if (
            id.includes('node_modules/cesium') ||
            id.includes('node_modules/@cesium/')
          )
            return 'vendor-cesium';
          if (id.includes('node_modules/pdfjs-dist')) return 'vendor-pdf';
          // jsPDF + html2canvas (PDF report export) — distinct from the
          // recharts charting stack so a page that only charts doesn't
          // drag in the PDF generator and vice-versa.
          if (id.includes('node_modules/jspdf') || id.includes('node_modules/html2canvas'))
            return 'vendor-pdf-export';
          if (
            id.includes('node_modules/yjs') ||
            id.includes('node_modules/y-webrtc') ||
            id.includes('node_modules/y-websocket') ||
            id.includes('node_modules/y-protocols') ||
            id.includes('node_modules/lib0')
          )
            return 'vendor-collab';
          // ── Framework / always-loaded vendors ────────────────────────
          if (id.includes('node_modules/react-dom/')) return 'vendor-react';
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-router-dom/') || id.includes('node_modules/react-router/')) return 'vendor-react';
          if (id.includes('node_modules/@tanstack/react-query')) return 'vendor-query';
          if (id.includes('node_modules/i18next') || id.includes('node_modules/react-i18next') || id.includes('node_modules/i18next-browser-languagedetector') || id.includes('node_modules/i18next-http-backend')) return 'vendor-i18n';
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    css: false,
    // The default 5s per-test timeout is too tight for the few tests that
    // build a real xlsx/PDF artifact (the first one pays a one-time lazy
    // import of exceljs / pdf-lib). Under full-suite CI load the CPU is
    // saturated by ~290 parallel test files and that first build can exceed
    // 5s, flaking the run even though every test passes in isolation. 15s
    // gives headroom without hiding a genuine hang.
    testTimeout: 15000,
    // Public-asset imports (`import url from '/brand/x.webp'`) are resolved by
    // Vite against ``publicDir`` at runtime, but under vitest the public dir is
    // not served — ``vite:import-analysis`` fails with "Failed to resolve
    // import /brand/...", and a bare Node resolve throws "The argument
    // 'filename' must be a file URL object ...". Alias these binary image
    // assets to a tiny string-URL stub so resolution is deterministic and the
    // default export is a URL string, matching Vite's runtime contract.
    //
    // The regex matches the full leading-slash specifier (anchored on the
    // ``/brand/`` public path) because a bare extension-suffix alias is
    // applied too late to intercept the public-asset code path.
    alias: [
      {
        find: /^\/.*\.(webp|png|jpe?g|gif|avif|ico)$/,
        replacement: path.resolve(__dirname, './src/test/assetStub.ts'),
      },
    ],
  },
});

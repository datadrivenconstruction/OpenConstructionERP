/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { VitePWA } from 'vite-plugin-pwa';
import path from 'path';
import { cpSync, existsSync, readFileSync, createReadStream, statSync } from 'fs';
import type { Plugin } from 'vite';

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
        const rel = decodeURIComponent(url.slice('/cesium/'.length).split('?')[0]);
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

// Read the version from package.json once at build time so the entire app
// (sidebar, About page, error reports, update checker) stays in sync.
const pkg = JSON.parse(readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'));

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [
    react(),
    visualizer({
      filename: 'stats.html',
      gzipSize: true,
      brotliSize: true,
      open: false,
    }),
    cesiumAssets(),
    // ── Mobile PWA — Slice 1 ────────────────────────────────────────────
    // Installable PWA with offline-app-shell + i18n bundle caching.
    //
    // * App-shell precaching is handled by workbox (generateSW), which
    //   automatically picks up the build outputs via the
    //   ``globPatterns``.  No additional pre-cache list is needed.
    // * Runtime caching is split into three deliberately-named lanes
    //   so each behaviour is independently verifiable in the SW unit
    //   tests:
    //     - "oce-static-assets"  CacheFirst for fonts/images that are
    //       hash-fingerprinted at build time.
    //     - "oce-i18n-locales"   StaleWhileRevalidate for the per-locale
    //       chunks under ``assets/i18n-*.js`` so a returning user gets
    //       an instant paint in their last language even when offline,
    //       while the background fetch keeps the chunk fresh.
    //     - "oce-api"            NetworkFirst for ``/api/v1/*`` GETs
    //       with an 8s timeout; cache used only as offline fallback for
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
        globIgnores: ['stats.html', '**/*.map'],
        // Allow large lazy-loaded chunks (vendor-three, vendor-maplibre)
        // to be runtime-cached on first visit. 5 MB ceiling matches
        // workbox's default but is set explicitly for clarity.
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
            // Static assets (fonts, images shipped under /assets/) ─
            // hashed at build time so a CacheFirst lookup is safe.
            //
            // EXCLUDES ``request.destination === 'worker'``: dedicated
            // workers (pdf.worker.min, cesium/Workers/*) need the
            // browser's own fetch with the exact MIME the server sent.
            // A CacheFirst hit was occasionally serving a response whose
            // module/script disposition tripped ``new Worker(url, {type:
            // 'module'})`` into the "fake worker" fallback, which then
            // failed dynamic import. Workers are not user-perceived
            // chatty traffic — letting them bypass the SW costs nothing.
            urlPattern: ({ url, request }) => {
              if (url.pathname.startsWith('/api/')) return false;
              if (request.destination === 'worker') return false;
              return (
                request.destination === 'font' ||
                request.destination === 'image' ||
                /\/assets\//.test(url.pathname)
              );
            },
            handler: 'CacheFirst',
            options: {
              cacheName: 'oce-static-assets',
              expiration: {
                maxEntries: 200,
                maxAgeSeconds: 30 * 24 * 60 * 60, // 30 days
              },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // i18n locale chunks — names emitted by manualChunks above
            // are ``i18n-<code>``.  StaleWhileRevalidate keeps the
            // active locale instant-on while still pulling fresh keys
            // in the background.
            urlPattern: ({ url }) => /\/assets\/i18n-[a-z]{2}-.*\.js$/.test(url.pathname),
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
            // API reads — NetworkFirst with 8 s timeout, cache only
            // used as the offline fallback for idempotent GETs.  Other
            // verbs bypass the SW (no ``method`` match here means GET
            // by default).
            urlPattern: ({ url, request }) => {
              if (request.method !== 'GET') return false;
              return url.pathname.startsWith('/api/v1/');
            },
            handler: 'NetworkFirst',
            options: {
              cacheName: 'oce-api',
              networkTimeoutSeconds: 8,
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
    // paper-cuts sweep (docs/qa/FRESH_INSTALL_RESULTS.md Issue 4) so the
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
    // in the install paper-cuts sweep (docs/qa/FRESH_INSTALL_RESULTS.md
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
      'pdfjs-dist',
      'pdfjs-dist/build/pdf.worker.min.mjs',
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
    rollupOptions: {
      output: {
        manualChunks(id) {
          // i18n locales: each ``src/app/locales/<code>.ts`` is fetched
          // on demand via dynamic import in ``i18n.ts``. Vite emits one
          // chunk per locale automatically; pin a stable name so cache
          // keys survive minor unrelated edits.  Checked first because
          // these are source files, not node_modules (the guard below
          // would otherwise skip them).
          const localeMatch = id.match(/[\\/]src[\\/]app[\\/]locales[\\/]([a-z]{2})\.ts$/);
          if (localeMatch) return `i18n-${localeMatch[1]}`;
          if (!id.includes('node_modules')) return;
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
  },
});

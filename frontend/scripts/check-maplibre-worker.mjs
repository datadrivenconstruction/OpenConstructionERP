// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Small real-browser check of Vite dev optimization and production worker output.
// Run from frontend: node scripts/check-maplibre-worker.mjs
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, createServer, preview } from 'vite';
import { chromium } from '@playwright/test';

const frontend = fileURLToPath(new URL('../', import.meta.url));
const cache = path.join(frontend, 'node_modules/.cache');
await mkdir(cache, { recursive: true });
const root = await mkdtemp(path.join(cache, 'maplibre-worker-'));
const adapter = path.join(frontend, 'src/shared/lib/mapLibre.ts').replaceAll('\\', '/');
const thumbnailContainer = path.join(frontend, 'src/shared/ui/ProjectMap/streetThumbnailContainer.ts').replaceAll('\\', '/');
let browser;
let server;
try {
  await writeFile(path.join(root, 'index.html'), '<script type="module" src="/main.js"></script>');
  await writeFile(path.join(root, 'main.js'), `
    import { getWorkerUrl } from ${JSON.stringify(adapter)};
    import { createStreetThumbnailContainer } from ${JSON.stringify(thumbnailContainer)};
    window.checkThumbnailGeometry = (direction) => {
      document.documentElement.dir = direction;
      const {host, container} = createStreetThumbnailContainer(480, 112);
      const result = {width: container.clientWidth, height: container.clientHeight,
        scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth};
      host.remove();
      return result;
    };
    window.workerCheck = new Promise((resolve, reject) => {
      const url = getWorkerUrl();
      // Import the actual configured worker, including all its dependencies.
      // MapLibre registers self.worker only after the module executes.
      const blob = new Blob(['import ' + JSON.stringify(new URL(url, location.href).href) + '; postMessage(!!self.worker);'], {type: 'text/javascript'});
      const objectUrl = URL.createObjectURL(blob);
      const worker = new Worker(objectUrl, {type: 'module'});
      const timer = setTimeout(() => { worker.terminate(); reject(new Error('Worker timeout')); }, 15000);
      worker.onmessage = ({data}) => { clearTimeout(timer); worker.terminate(); URL.revokeObjectURL(objectUrl); resolve({ready: data, url}); };
      worker.onerror = (error) => { clearTimeout(timer); worker.terminate(); reject(new Error(error.message)); };
    });
  `);
  const config = {
    configFile: false, root, logLevel: 'warn', base: '/worker-test/',
    optimizeDeps: { include: ['maplibre-gl'], entries: ['index.html'] },
    server: { host: '127.0.0.1', port: 0, fs: { allow: [frontend] } },
    build: { outDir: path.join(root, 'dist'), minify: false },
  };
  browser = await chromium.launch({ headless: true });
  for (const mode of ['dev', 'production']) {
    if (mode === 'dev') {
      server = await createServer(config);
      await server.listen();
    } else {
      await build(config);
      server = await preview({ ...config, preview: { host: '127.0.0.1', port: 0 } });
    }
    const page = await browser.newPage();
    await page.setViewportSize({ width: 320, height: 640 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    await page.goto(server.resolvedUrls.local[0]);
    const result = await page.evaluate(() => window.workerCheck);
    assert.equal(result.ready, true, `${mode}: MapLibre worker did not initialize`);
    assert.deepEqual(errors, [], `${mode}: browser errors`);
    for (const direction of ['ltr', 'rtl']) {
      const geometry = await page.evaluate(direction => window.checkThumbnailGeometry(direction), direction);
      assert.equal(geometry.width, 480);
      assert.equal(geometry.height, 112);
      assert.equal(geometry.scrollWidth, geometry.viewport, `${mode}/${direction}: thumbnail expands viewport`);
    }
    if (mode === 'production') assert.match(result.url, /^\/worker-test\/assets\/maplibre-gl-worker-.*\.js$/);
    console.log(`${mode}: worker executes successfully (${result.url})`);
    await page.close();
    await server.close();
    server = undefined;
  }
} finally {
  await server?.close();
  await browser?.close();
  assert.ok(root.startsWith(cache + path.sep));
  await rm(root, { recursive: true, force: true });
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The contract between the PDF.js binding and the assets the build publishes.
 *
 * PDF.js only checks `wasmUrl` and `iccUrl` when a document is opened, and it
 * only fetches from them when a page carries a JBIG2 or JPEG 2000 image, so a
 * wrong URL passes every type check and every viewer test and shows up as a
 * blank scanned drawing on a user's machine. These tests pin the shape both
 * sides agree on: the directory is versioned, it lives under `/assets/`, and
 * every prefix ends in the slash PDF.js insists on.
 *
 * Nothing here is compared against a version typed into this file. The mock
 * used to declare `version: '6.1.200'` and every assertion compared the URLs
 * against that same string, so the whole file passed at any version of the
 * library, including one that ships no decoder directory at all - it only ever
 * proved that a literal equals itself. The version that matters is the one
 * `vite.config.ts` stamps into the published path, and the config reads it
 * from `node_modules/pdfjs-dist/package.json`, so the expectation is read from
 * there too. The mocked `version` is taken from the library build instead, so
 * the two sides are free to disagree: that drift is what `pdfjs.ts` claims
 * cannot happen and what nothing checked.
 *
 * The directories are measured the same way. The plugin copies `wasm` and
 * `iccs` out of the installed package and skips a directory that is not there
 * without a log or an error, so a release that moves the decoders would emit
 * nothing, build green, and blank every scanned drawing. Both halves of that -
 * the package no longer shipping the directory, and the build no longer
 * looking where the viewer asks - fail here instead.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const FRONTEND_ROOT = resolve(__dirname, '../../..');
/** Resolved exactly as `vite.config.ts` resolves it. */
const PDFJS_ROOT = join(FRONTEND_ROOT, 'node_modules', 'pdfjs-dist');
const PDFJS_PACKAGE = join(PDFJS_ROOT, 'package.json');

if (!existsSync(PDFJS_PACKAGE)) {
  throw new Error(
    `pdfjs-dist is not installed at ${PDFJS_ROOT}. The build plugin reads the version from that ` +
      'package and publishes the decoders out of it, so there is nothing to check against here.',
  );
}

/** The version the build stamps into the asset path, from the source the plugin reads. */
const PACKAGE_VERSION = (JSON.parse(readFileSync(PDFJS_PACKAGE, 'utf-8')) as { version: string })
  .version;
const ASSET_ROOT = `/assets/pdfjs/${PACKAGE_VERSION}/`;

// The three extensions the dev middleware serves out of node_modules. A
// directory holding only licences is a directory whose payload has moved.
const PAYLOAD_EXTENSIONS = ['.wasm', '.js', '.icc'];
/** The plugin's own skip: the JavaScript sandbox no viewer here loads. */
const keep = (name: string) => !name.startsWith('quickjs-eval');

const getDocument = vi.fn(() => ({ promise: Promise.resolve() }));

// The library is mocked because these tests read the arguments `getDocument`
// was handed rather than a parsed document, but `version` comes from the real
// module: it is the value `pdfjs.ts` builds the URL from, and inventing it here
// is what made the old assertions unfalsifiable.
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', async (importOriginal) => {
  const actual = await importOriginal<{ version: string }>();
  return {
    GlobalWorkerOptions: { workerSrc: '' },
    version: actual.version,
    getDocument: (...args: unknown[]) => getDocument(...(args as [])),
  };
});

type OpenParams = { data: ArrayBuffer; wasmUrl: string; iccUrl: string };

/** Open a document and hand back what the binding asked PDF.js for. */
async function paramsOfOneOpen(): Promise<OpenParams> {
  const { openPdf } = await import('./pdfjs');
  openPdf(new ArrayBuffer(8));
  expect(getDocument).toHaveBeenCalledTimes(1);
  const [params] = getDocument.mock.calls[0] as unknown as [OpenParams];
  return params;
}

/** The directory names the viewer actually asks the build for, not a restated list. */
function requestedDirs(params: OpenParams): string[] {
  return [params.wasmUrl, params.iccUrl].map((url) => {
    expect(url.startsWith(ASSET_ROOT)).toBe(true);
    return url.slice(ASSET_ROOT.length).replace(/\/$/, '');
  });
}

describe('pdfjs binding', () => {
  beforeEach(() => {
    getDocument.mockClear();
  });

  it('publishes the runtime assets under the version the build stamps into the path', async () => {
    const { PDFJS_ASSET_ROOT } = await import('./pdfjs');
    expect(PDFJS_ASSET_ROOT).toBe(ASSET_ROOT);
  });

  it('reads the same version the build reads, so the two cannot name different directories', async () => {
    const actual = await vi.importActual<{ version: string }>('pdfjs-dist/legacy/build/pdf.mjs');
    expect(actual.version).toBe(PACKAGE_VERSION);
  });

  it('points the worker at the bundled legacy worker, never a CDN', async () => {
    const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs');
    await import('./pdfjs');
    expect(pdfjs.GlobalWorkerOptions.workerSrc).toMatch(/pdf\.worker\.min\.mjs$/);
    expect(pdfjs.GlobalWorkerOptions.workerSrc).not.toMatch(/^https?:\/\/(cdn|unpkg|cdnjs)/);
  });

  it('opens every document with the wasm and ICC directories, each ending in a slash', async () => {
    const params = await paramsOfOneOpen();
    expect(params.data).toBeInstanceOf(ArrayBuffer);
    expect(params.wasmUrl).toBe(`${ASSET_ROOT}wasm/`);
    expect(params.iccUrl).toBe(`${ASSET_ROOT}iccs/`);
  });

  it('passes the caller its own buffer, which the worker then detaches', async () => {
    const { openPdf } = await import('./pdfjs');
    const bytes = new ArrayBuffer(8);
    openPdf(bytes);
    const [params] = getDocument.mock.calls[0] as unknown as [OpenParams];
    expect(params.data).toBe(bytes);
  });

  it('asks only for directories the installed pdfjs-dist still ships', async () => {
    const params = await paramsOfOneOpen();
    for (const dir of requestedDirs(params)) {
      const full = join(PDFJS_ROOT, dir);
      expect(
        existsSync(full),
        `pdfjs-dist ${PACKAGE_VERSION} ships no "${dir}" directory. The build plugin skips a ` +
          'missing directory without a log, so the assets would simply not be published and ' +
          'every scanned drawing would render blank.',
      ).toBe(true);
      const payload = readdirSync(full).filter(
        (name) =>
          keep(name) &&
          !statSync(join(full, name)).isDirectory() &&
          PAYLOAD_EXTENSIONS.includes(extname(name).toLowerCase()),
      );
      expect(
        payload.length,
        `"${dir}" in pdfjs-dist ${PACKAGE_VERSION} holds no ${PAYLOAD_EXTENSIONS.join('/')} file ` +
          'the plugin would copy. The decoders have moved, and the plugin copies files only from ' +
          'the top of the directory.',
      ).toBeGreaterThan(0);
    }
  });

  it('is published from exactly the directories it asks for', async () => {
    const params = await paramsOfOneOpen();
    const config = readFileSync(join(FRONTEND_ROOT, 'vite.config.ts'), 'utf-8');
    const declaration = config.match(/const pdfjsAssetDirs = \[([^\]]*)\]/);
    expect(
      declaration,
      'vite.config.ts no longer declares `pdfjsAssetDirs`. Whatever replaced it is what publishes ' +
        'the decoders, so point this assertion at that instead of deleting it.',
    ).not.toBeNull();
    const published = [...(declaration?.[1] ?? '').matchAll(/'([^']+)'/g)].map((m) => m[1]);
    expect(
      published.slice().sort(),
      'The build publishes different directories than the viewer requests. Either side alone is ' +
        'silent: the plugin skips a directory it cannot find, and PDF.js only fetches a decoder ' +
        'when a page happens to carry a JBIG2 or JPEG 2000 image.',
    ).toEqual(requestedDirs(params).slice().sort());
  });

  it('closes a document through its loading task and tolerates nothing loaded', async () => {
    const { closePdf } = await import('./pdfjs');
    const destroy = vi.fn(() => Promise.resolve());
    closePdf({ loadingTask: { destroy } } as unknown as Parameters<typeof closePdf>[0]);
    expect(destroy).toHaveBeenCalledTimes(1);
    expect(() => closePdf(null)).not.toThrow();
    expect(() => closePdf(undefined)).not.toThrow();
  });
});

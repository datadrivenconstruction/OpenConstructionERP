// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one place that binds PDF.js to this bundle.
 *
 * Every viewer (takeoff, plan room, punch pin board, markups, revision
 * compare) used to configure the worker on its own. Since PDF.js 5 the
 * library also needs two things served next to the bundle: the WebAssembly
 * decoders for JBIG2 and JPEG 2000 images, which the worker fetches on demand
 * under `wasmUrl`, and the ICC profile it uses for CMYK colour under `iccUrl`.
 * A scanned drawing is very often a JBIG2 or JPX image, so a viewer that
 * forgets either option renders a blank page for exactly the documents a
 * takeoff is most likely to receive. Routing every `getDocument` through
 * `openPdf` means no viewer can forget them.
 *
 * Build choice. This imports the `legacy` build on purpose. The default build
 * of PDF.js 6 is compiled for "the latest browsers" and relies on
 * `Map.prototype.getOrInsertComputed`, `Promise.withResolvers`, `Promise.try`
 * and `Float16Array` without polyfills. The legacy build carries the
 * polyfills and documents its floor (Chrome 125, Safari 18, Firefox ESR),
 * which is what the desktop WebView on an older macOS and the browsers in a
 * site office actually run. It costs about 100 KB across the two files.
 *
 * Asset layout. The wasm and ICC files are copied at build time by the
 * `pdfjs-assets` plugin in vite.config.ts into `assets/pdfjs/<version>/`, and
 * the dev server streams the same paths out of node_modules. The version
 * segment matters: the backend serves everything under `/assets` with a
 * year-long immutable cache header, and the file names inside the PDF.js
 * package never change between releases, so without the segment a bump would
 * leave browsers pairing a new worker with a cached old decoder. Both sides
 * read the version from the package, so they cannot drift apart.
 *
 * Teardown. PDF.js 6 removed `PDFDocumentProxy.destroy()`; the loading task
 * owns the worker transport now. `closePdf` is the one spelling of that, so a
 * viewer cannot keep calling a method that no longer exists behind optional
 * chaining and silently leak the parsed document for the life of the tab.
 */
import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist';

// Bundled locally: no CDN, so the desktop app and an on-prem install work
// offline. Vite turns the URL into a hashed asset next to the other chunks.
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/legacy/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

/**
 * Root of the PDF.js runtime assets the Vite plugin publishes. PDF.js appends
 * fixed file names to `wasmUrl` and `iccUrl`, so both must end in a slash; it
 * throws on a URL without one, but only at the moment a document is opened.
 */
export const PDFJS_ASSET_ROOT = `${import.meta.env.BASE_URL}assets/pdfjs/${pdfjsLib.version}/`;

/**
 * Open a PDF from its bytes with the runtime assets wired in.
 *
 * The buffer is transferred to the worker and is detached afterwards, exactly
 * as `getDocument` has always done; do not read it again after this call.
 */
export function openPdf(data: ArrayBuffer): PDFDocumentLoadingTask {
  return pdfjsLib.getDocument({
    data,
    wasmUrl: `${PDFJS_ASSET_ROOT}wasm/`,
    iccUrl: `${PDFJS_ASSET_ROOT}iccs/`,
  });
}

/** Release the worker-side document. Safe to call with nothing loaded. */
export function closePdf(doc: PDFDocumentProxy | null | undefined): void {
  void doc?.loadingTask.destroy();
}

export type { PageViewport, PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist';

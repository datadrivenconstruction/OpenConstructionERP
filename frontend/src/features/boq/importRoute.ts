// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which import route a file picked from the bill toolbar goes to.
 *
 * - `site`: a GAEB X31 measurement or X89 invoice, read against this bill in
 *   its own dialog rather than imported into it;
 * - `gaeb`: a GAEB DA bill named as one (`.x81`/`.x83`/`.x84`, or
 *   `.x8x.xml`/`.gaeb.xml`), for the dedicated GAEB parser;
 * - `auto`: a file only the content-detecting route reads. XPWE and BC3 have
 *   native readers the smart route refuses by extension; an estimating
 *   program's own `.dcf`/`.pwe` project file is refused there with what to do
 *   instead; and a plain `.xml` is told apart by its content, the way the
 *   import dialog does it, because an XPWE export is often saved as
 *   `computo.xml` and the smart route refuses `.xml` outright;
 * - `smart`: everything else (spreadsheets, PDF, images, CAD).
 */

export type ImportRoute = 'site' | 'gaeb' | 'auto' | 'smart';

const NATIVE_EXCHANGE = ['xpwe', 'bc3', 'dcf', 'pwe', 'xml'];

export function toolbarImportRoute(fileName: string): ImportRoute {
  if (/\.x(31|89)$/i.test(fileName)) return 'site';
  const ext = (fileName.split('.').pop() ?? '').toLowerCase();
  if (['x81', 'x83', 'x84'].includes(ext)) return 'gaeb';
  if (ext === 'xml' && /\.(x8[134]|gaeb)\.xml$/i.test(fileName)) return 'gaeb';
  if (NATIVE_EXCHANGE.includes(ext)) return 'auto';
  return 'smart';
}

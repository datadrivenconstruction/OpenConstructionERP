/** GAEB Langtext helpers: the importer stores the long text of a position in
 *  `metadata.gaeb_long_text` (line breaks preserved, up to ~2000 chars). */

/** Long text of a position, or null when absent/blank or equal to the short text. */
export function getGaebLongText(meta: unknown): string | null {
  if (!meta || typeof meta !== 'object') return null;
  const raw = (meta as { gaeb_long_text?: unknown }).gaeb_long_text;
  if (typeof raw !== 'string') return null;
  const text = raw.replace(/\r\n?/g, '\n').trim();
  return text.length > 0 ? text : null;
}

/** Row height of the expanded Langtext block for `text` (about 16px per
 *  wrapped line, estimated at 110 chars/line, clamped to 48..260). */
export function langtextBlockHeight(text: string): number {
  let lines = 0;
  for (const part of text.split('\n')) lines += Math.max(1, Math.ceil(part.length / 110));
  return Math.min(260, Math.max(48, lines * 16 + 20));
}

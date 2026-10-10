/**
 * Remembered column mappings for cost-file imports.
 *
 * A regional price list is published in the same layout every year, so once
 * an estimator has mapped its columns the next edition should open already
 * mapped. A mapping is remembered per header row: the same headers in the same
 * order (case, spacing and accents aside) bring the mapping back.
 *
 * It lives in this browser only. It is a convenience: losing it costs one
 * manual mapping, so every storage access tolerates a blocked or empty store.
 */

const STORAGE_KEY = 'oe_cost_import_column_profiles';
/** Oldest profiles are dropped past this many. */
const MAX_PROFILES = 50;

interface StoredProfile {
  map: Record<string, string>;
  savedAt: number;
}

function normaliseHeader(header: string): string {
  return header
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

/** The key a header row is remembered under. */
export function headerFingerprint(headers: readonly string[]): string {
  return headers.map(normaliseHeader).join('\u001f');
}

function readAll(): Record<string, StoredProfile> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, StoredProfile>) : {};
  } catch {
    return {};
  }
}

/**
 * The remembered mapping for this header row, keeping only fields whose header
 * is still in the file. ``null`` when nothing usable was remembered.
 */
export function loadColumnProfile(headers: readonly string[]): Record<string, string> | null {
  const profile = readAll()[headerFingerprint(headers)];
  if (!profile || typeof profile.map !== 'object' || profile.map === null) return null;
  const present = new Set(headers);
  const map: Record<string, string> = {};
  for (const [field, header] of Object.entries(profile.map)) {
    if (typeof header === 'string' && present.has(header)) map[field] = header;
  }
  return Object.keys(map).length > 0 ? map : null;
}

/** Remember the mapping used for this header row; unmapped fields are not stored. */
export function saveColumnProfile(headers: readonly string[], map: Record<string, string>): void {
  const cleaned: Record<string, string> = {};
  for (const [field, header] of Object.entries(map)) {
    if (header) cleaned[field] = header;
  }
  if (headers.length === 0 || Object.keys(cleaned).length === 0) return;
  const all = readAll();
  all[headerFingerprint(headers)] = { map: cleaned, savedAt: Date.now() };
  const kept = Object.entries(all)
    .sort(([, a], [, b]) => (b.savedAt ?? 0) - (a.savedAt ?? 0))
    .slice(0, MAX_PROFILES);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(kept)));
  } catch {
    // Storage blocked or full: the mapping is simply not remembered.
  }
}

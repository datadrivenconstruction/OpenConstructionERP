// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Pure helpers for the photo archive: URL state, filter query, slider maths, AI payload text.

export const PHOTO_VIEWS = ['grid', 'timeline', 'map', 'albums', 'compare'] as const;
export type PhotoView = (typeof PHOTO_VIEWS)[number];

export const SOURCE_MODULES = ['documents', 'daily_diary', 'punchlist', 'fieldreports', 'progress'] as const;

export const PHOTO_CATEGORIES = ['site', 'progress', 'defect', 'delivery', 'safety', 'aerial', 'other'] as const;
export type PhotoCategory = (typeof PHOTO_CATEGORIES)[number];

export interface PhotoFilters {
  q?: string;
  category?: string;
  tag?: string;
  album?: string;
  from?: string; // yyyy-mm-dd
  to?: string; // yyyy-mm-dd
  source?: string;
  hasGps?: boolean;
  targetKind?: string;
  targetId?: string;
}

export function parseView(value: string | null | undefined): PhotoView {
  return (PHOTO_VIEWS as readonly string[]).includes(value ?? '') ? (value as PhotoView) : 'grid';
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Read the filter bar state from the page URL, dropping anything malformed. */
export function filtersFromParams(params: URLSearchParams): PhotoFilters {
  const out: PhotoFilters = {};
  const q = params.get('q')?.trim();
  if (q) out.q = q;
  const tag = params.get('tag')?.trim();
  if (tag) out.tag = tag;
  const album = params.get('album');
  if (album) out.album = album;
  const from = params.get('from');
  if (from && DAY.test(from)) out.from = from;
  const to = params.get('to');
  if (to && DAY.test(to)) out.to = to;
  const category = params.get('category');
  if (category && (PHOTO_CATEGORIES as readonly string[]).includes(category)) out.category = category;
  const source = params.get('source');
  if (source && (SOURCE_MODULES as readonly string[]).includes(source)) out.source = source;
  if (params.get('gps') === '1') out.hasGps = true;
  const targetKind = params.get('target_kind');
  const targetId = params.get('target_id');
  if (targetKind && targetId) {
    out.targetKind = targetKind;
    out.targetId = targetId;
  }
  return out;
}

/** Write the filter state back into URL params, keeping unrelated params such as `view`. */
export function filtersToParams(filters: PhotoFilters, base: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(base);
  for (const k of ['q', 'category', 'tag', 'album', 'from', 'to', 'source', 'gps', 'target_kind', 'target_id']) next.delete(k);
  if (filters.q) next.set('q', filters.q);
  if (filters.category) next.set('category', filters.category);
  if (filters.tag) next.set('tag', filters.tag);
  if (filters.album) next.set('album', filters.album);
  if (filters.from) next.set('from', filters.from);
  if (filters.to) next.set('to', filters.to);
  if (filters.source) next.set('source', filters.source);
  if (filters.hasGps) next.set('gps', '1');
  if (filters.targetKind && filters.targetId) {
    next.set('target_kind', filters.targetKind);
    next.set('target_id', filters.targetId);
  }
  return next;
}

/**
 * The API query for a filter set. Day bounds become whole UTC days so a photo taken
 * late on the `to` day is still inside the window.
 */
export function filtersToQuery(filters: PhotoFilters): string {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.category) params.set('category', filters.category);
  if (filters.tag) params.set('tag', filters.tag);
  if (filters.album) params.set('album', filters.album);
  if (filters.from) params.set('from', `${filters.from}T00:00:00Z`);
  if (filters.to) params.set('to', `${filters.to}T23:59:59Z`);
  if (filters.source) params.set('source', filters.source);
  if (filters.hasGps) params.set('has_gps', 'true');
  if (filters.targetKind && filters.targetId) {
    params.set('target_kind', filters.targetKind);
    params.set('target_id', filters.targetId);
  }
  return params.toString();
}

export function activeFilterCount(filters: PhotoFilters): number {
  return ['q', 'category', 'tag', 'album', 'from', 'to', 'source', 'hasGps'].filter((k) => Boolean(filters[k as keyof PhotoFilters]))
    .length;
}

/** Slider position in percent from a pointer x inside a box; always within 0..100. */
export function sliderPercent(clientX: number, left: number, width: number): number {
  if (!(width > 0)) return 50;
  const pct = ((clientX - left) / width) * 100;
  return Math.min(100, Math.max(0, Math.round(pct * 10) / 10));
}

/** Keyboard step for the slider: arrows move 2 %, Page keys 10 %, Home/End jump to the edges. */
export function sliderKeyStep(key: string, current: number): number | null {
  const step: Record<string, number> = { ArrowLeft: -2, ArrowRight: 2, PageDown: -10, PageUp: 10 };
  if (key === 'Home') return 0;
  if (key === 'End') return 100;
  if (!(key in step)) return null;
  return Math.min(100, Math.max(0, current + step[key]!));
}

/** The text a reviewer sees for a suggestion, editable before accepting. */
export function suggestionText(kind: string, payload: Record<string, unknown>): string {
  if (kind === 'caption') return typeof payload.text === 'string' ? payload.text : '';
  if (kind === 'tags') return Array.isArray(payload.tags) ? payload.tags.filter((x) => typeof x === 'string').join(', ') : '';
  if (kind === 'hazard') return typeof payload.hazard === 'string' ? payload.hazard : '';
  if (kind === 'progress') {
    const pct = typeof payload.percent_observed === 'number' ? payload.percent_observed : null;
    return pct === null ? '' : String(pct);
  }
  return '';
}

/** Turn the reviewer's edited text back into the payload shape the API accepts. */
export function editedPayload(
  kind: string,
  original: Record<string, unknown>,
  text: string,
): Record<string, unknown> | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  if (kind === 'caption') return { text: trimmed };
  if (kind === 'tags') {
    const tags = [...new Set(trimmed.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean))];
    return tags.length ? { tags } : null;
  }
  if (kind === 'hazard') return { ...original, hazard: trimmed };
  if (kind === 'progress') {
    const pct = Number(trimmed.replace(',', '.'));
    if (!Number.isFinite(pct) || pct < 0 || pct > 100) return null;
    return { ...original, percent_observed: pct };
  }
  return null;
}

/** Hazard box as CSS percentages; bbox is [x, y, w, h] fractions of the image. */
export function bboxStyle(bbox: unknown): { left: string; top: string; width: string; height: string } | null {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null;
  const [x, y, w, h] = bbox.map(Number);
  if (![x, y, w, h].every((n) => Number.isFinite(n) && n! >= 0 && n! <= 1)) return null;
  return { left: `${x! * 100}%`, top: `${y! * 100}%`, width: `${w! * 100}%`, height: `${h! * 100}%` };
}

/** The register a photo came from, as a route the user can open. */
export function sourceRoute(source: string): string | null {
  const routes: Record<string, string> = {
    punchlist: '/punchlist',
    fieldreports: '/field-reports',
    daily_diary: '/daily-diary',
    progress: '/progress',
  };
  return routes[source] ?? null;
}

export type BulkAction =
  | { kind: 'category'; category: string }
  | { kind: 'addTags'; tags: string[] }
  | { kind: 'field'; on: boolean };

/** Split a typed tag list the way the old gallery did: comma separated, trimmed, no duplicates. */
export function parseTags(text: string): string[] {
  return [...new Set(text.split(',').map((t) => t.trim()).filter(Boolean))];
}

/**
 * The PATCH body one bulk action means for one photo, or null when the photo
 * already matches and no request is needed.
 */
export function bulkPatch(
  photo: { category: string; tags: string[] },
  action: BulkAction,
): { category?: string; tags?: string[] } | null {
  if (action.kind === 'category') return photo.category === action.category ? null : { category: action.category };
  const current = photo.tags ?? [];
  const lower = new Set(current.map((t) => t.toLowerCase()));
  if (action.kind === 'addTags') {
    const extra = action.tags.filter((t) => !lower.has(t.toLowerCase()));
    return extra.length ? { tags: [...current, ...extra] } : null;
  }
  const hasField = lower.has('field');
  if (action.on === hasField) return null;
  return { tags: action.on ? [...current, 'field'] : current.filter((t) => t.toLowerCase() !== 'field') };
}

/** A category suggestion the reviewer can apply, read from the photo record. */
export function categorySuggestion(
  photo: { category: string; category_suggestion?: Record<string, unknown> | null },
): { category: string; confidence: number | null; tags: string[] } | null {
  const raw = photo.category_suggestion;
  if (!raw) return null;
  const cat = raw.suggested_category;
  if (typeof cat !== 'string' || !(PHOTO_CATEGORIES as readonly string[]).includes(cat) || cat === photo.category) return null;
  const conf = typeof raw.confidence === 'number' && Number.isFinite(raw.confidence) ? raw.confidence : null;
  const tags = Array.isArray(raw.suggested_tags) ? raw.suggested_tags.filter((t): t is string => typeof t === 'string') : [];
  return { category: cat, confidence: conf, tags };
}

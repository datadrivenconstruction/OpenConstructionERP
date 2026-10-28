// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small, pure presentation helpers for the connectors feature. No IO, no
// network: they only shape a source's stored sync timestamps for display, so
// they are trivially testable and shared by the page, the summary strip and
// the source card.

import type { ConnectorSource } from './types';
import { getIntlLocale } from '@/shared/lib/formatters';

/** The narrow `t` shape these helpers need (defaultValue + interpolation). */
type Translate = (key: string, opts: { defaultValue: string } & Record<string, unknown>) => string;

/**
 * A compact, localized "time ago" for a sync timestamp. Returns null for a
 * missing or unparseable value so the caller can fall back to a "not synced"
 * label rather than rendering "Invalid Date". The unit letters (m / h / d) are
 * interpolated, never pluralized, so no plural-key lookup is involved.
 */
export function formatSyncAgo(iso: string | null | undefined, t: Translate): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 45) return t('connectors.rel_now', { defaultValue: 'just now' });
  const min = Math.round(sec / 60);
  if (min < 60) return t('connectors.rel_min', { defaultValue: '{{n}}m ago', n: min });
  const hr = Math.round(min / 60);
  if (hr < 24) return t('connectors.rel_hour', { defaultValue: '{{n}}h ago', n: hr });
  const day = Math.round(hr / 24);
  if (day < 30) return t('connectors.rel_day', { defaultValue: '{{n}}d ago', n: day });
  return new Date(then).toLocaleDateString(getIntlLocale());
}

/** A full, locale-formatted timestamp for tooltips; '' when unparseable. */
export function formatAbsolute(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(getIntlLocale());
}

/** The most recent last_synced_at across the sources (ISO), or null if none. */
export function mostRecentSync(sources: ConnectorSource[]): string | null {
  let bestMs: number | null = null;
  let bestIso: string | null = null;
  for (const source of sources) {
    const iso = source.last_synced_at;
    if (!iso) continue;
    const ms = Date.parse(iso);
    if (Number.isNaN(ms)) continue;
    if (bestMs === null || ms > bestMs) {
      bestMs = ms;
      bestIso = iso;
    }
  }
  return bestIso;
}

/** Whether a source matches a free-text query over its name and watched path. */
export function sourceMatchesQuery(source: ConnectorSource, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    source.name.toLowerCase().includes(q) || source.root_path.toLowerCase().includes(q)
  );
}

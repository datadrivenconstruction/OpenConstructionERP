// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PresenceTooltip -- click-activated popover showing details of one
 * online user: their name, current page, and idle status.
 *
 * Positioned below the avatar stack container via absolute placement.
 * Closes on click-outside or Escape -- the same pattern used by
 * BugReportMenu and HelpMenu in Header.tsx.
 */

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import type { GlobalPresenceUser } from '@/stores/useGlobalPresenceStore';
import { TITLE_I18N_MAP } from '@/app/layout/Header';

/* ── Helpers ───────────────────────────────────────────────────────── */

/**
 * Build a reverse map from route pathnames to English titles.
 *
 * `TITLE_I18N_MAP` maps English title strings to i18n keys. The WS
 * sends pathnames (e.g. `/boq`), so we need the reverse direction:
 * pathname -> best-effort English title -> i18n key. Since there is no
 * canonical pathname-to-title map on the client, we extract the last
 * meaningful segment of the pathname, title-case it, look it up in the
 * map, and fall back to the prettified segment.
 */
function prettifyPathSegment(segment: string): string {
  return segment
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Route slugs that don't match their TITLE_I18N_MAP key after simple
 * title-casing. Covers the common divergences; anything not listed here
 * falls back to the prettified segment, which is fine for routes where
 * the slug and the English title are close enough (e.g. "daily-diary"
 * -> "Daily Diary").
 */
const ROUTE_SLUG_TO_TITLE: Record<string, string> = {
  'boq': 'Bill of Quantities',
  'ai-estimate': 'AI Quick Estimate',
  'ai-estimator': 'AI Estimate Builder',
  'cad-takeoff': 'CAD/BIM Takeoff',
  'pdf-takeoff': 'PDF Takeoff',
  'dwg-takeoff': 'DWG Takeoff',
  'cost-database': 'Cost Database',
  'cost-explorer': 'Cost Explorer',
  'cost-match': 'Cost Match',
  'match-elements': 'Match Elements',
  'bim-viewer': 'BIM Viewer',
  'bim-federations': 'BIM Federations',
  'bim-rules': 'BIM Rules',
  'data-explorer': 'CAD-BIM BI Explorer',
  'schedule': '4D Schedule',
  'schedule-advanced': 'Advanced Schedule',
  '5d-cost-model': '5D Cost Model',
  'risk-register': 'Risk Register',
  'daily-diary': 'Daily Diary',
  'field-reports': 'Field Reports',
  'equipment': 'Equipment & Fleet',
  'resources': 'Resources & Crew',
  'ai-agents': 'AI Agents',
  'ai-advisor': 'AI Cost Advisor',
  'erp-chat': 'AI Chat',
  'gaeb-exchange': 'GAEB Exchange',
  'resource-catalog': 'Resource Catalog',
  'user-management': 'User Management',
  'audit-log': 'Audit Log',
  'project-controls': 'Project Controls',
  'bi-dashboards': 'BI Dashboards',
  'property-dev': 'Property Development',
  'payment-clock': 'Payment Clock',
  'cvr': 'Cost-Value Reconciliation',
  'evm': 'Earned Value',
  'carbon': 'Carbon & ESG',
};

/**
 * Resolve a route pathname to an i18n key via TITLE_I18N_MAP.
 *
 * Tries the last non-UUID segment of the path against a slug-to-title
 * lookup first (for slugs that diverge from their English title), then
 * falls back to title-casing the segment and checking the map directly.
 */
function routeToI18nKey(route: string): { key: string | null; fallback: string } {
  // Strip leading slash and split.
  const segments = route.replace(/^\//, '').split('/').filter(Boolean);
  // Walk segments from the end, skip anything that looks like a UUID.
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;
  for (let i = segments.length - 1; i >= 0; i--) {
    const seg = segments[i]!;
    if (UUID_RE.test(seg)) continue;
    // Try the explicit slug-to-title map first.
    const mappedTitle = ROUTE_SLUG_TO_TITLE[seg];
    if (mappedTitle) {
      const key = TITLE_I18N_MAP[mappedTitle] ?? null;
      return { key, fallback: mappedTitle };
    }
    // Fall back to title-casing the slug.
    const title = prettifyPathSegment(seg);
    const key = TITLE_I18N_MAP[title] ?? null;
    return { key, fallback: title };
  }
  return { key: 'nav.dashboard', fallback: 'Dashboard' };
}

/**
 * Human-readable relative time for the idle duration.
 *
 * Returns "Xm" for minutes, "Xh" for hours. Under 1 minute returns
 * the empty string (treated as "just now").
 */
function idleDuration(lastActive: string): string {
  const diff = Date.now() - new Date(lastActive).getTime();
  if (diff < 0 || !Number.isFinite(diff)) return '';
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return '';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h`;
}

/* ── Component ─────────────────────────────────────────────────────── */

export interface PresenceTooltipProps {
  user: GlobalPresenceUser;
  onClose: () => void;
}

export function PresenceTooltip({ user, onClose }: PresenceTooltipProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);

  // Close on click outside.
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  // Close on Escape.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const { key, fallback } = routeToI18nKey(user.route);
  const pageName = key
    ? t(key, { defaultValue: fallback })
    : fallback;

  const isIdle = user.status === 'idle';
  const idleTime = isIdle ? idleDuration(user.last_active) : '';
  const statusLabel = isIdle
    ? idleTime
      ? t('presence.idle_for', { defaultValue: 'Idle for {{time}}', time: idleTime })
      : t('presence.idle', { defaultValue: 'Idle' })
    : t('presence.active', { defaultValue: 'Active' });

  return (
    <div
      ref={ref}
      role="tooltip"
      className={clsx(
        'absolute top-full right-0 mt-2 z-50',
        'w-56 rounded-xl border border-border-light',
        'bg-surface-primary shadow-lg',
        'p-3 text-sm',
        'animate-fade-in',
      )}
    >
      {/* User name */}
      <p className="font-semibold text-content-primary truncate">
        {user.user_name}
      </p>

      {/* Current page */}
      <p className="mt-1 text-content-secondary truncate">
        {pageName}
      </p>

      {/* Status */}
      <p className={clsx(
        'mt-1.5 flex items-center gap-1.5 text-xs',
        isIdle ? 'text-content-quaternary' : 'text-emerald-600 dark:text-emerald-400',
      )}>
        <span
          className={clsx(
            'inline-block h-1.5 w-1.5 rounded-full',
            isIdle ? 'bg-content-quaternary' : 'bg-emerald-500',
          )}
        />
        {statusLabel}
      </p>
    </div>
  );
}

/**
 * UpdateNotification — Sidebar widget showing when a new version is available.
 *
 * Polls the GitHub Releases API for the upstream repository and shows a
 * compact card in the sidebar when the latest tag is newer than the
 * currently running version. The card surfaces grouped highlights and a
 * one-click jump to either the full in-app changelog or the GitHub release.
 *
 * Implementation notes:
 *
 * - **Caching.** The GitHub response is cached in localStorage with a 1-hour
 *   TTL keyed by URL. Multiple tabs / sessions reuse the cached payload so
 *   we don't hammer the unauthenticated GitHub API (which is rate-limited
 *   to 60 req/hour per IP).
 *
 * - **First check.** Runs ~2 seconds after mount so the user sees the card
 *   almost immediately on a fresh load if there is an update. Subsequent
 *   checks happen every hour.
 *
 * - **Dismiss.** Per-version dismiss state is stored in localStorage; once
 *   the user closes the card for v0.8.0 they will not see it again until
 *   v0.8.1 (or higher) appears.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Sparkles, X, ExternalLink, ChevronDown, ChevronUp, Download, Copy, Check,
  Plus, Wrench, Palette,
} from 'lucide-react';
import { APP_VERSION } from '@/shared/lib/version';

const CURRENT_VERSION = APP_VERSION;
const CHECK_INTERVAL_MS = 60 * 60 * 1000;       // 1 hour between polls
const FIRST_CHECK_DELAY_MS = 2_000;             // first check ~2s after mount
const CACHE_TTL_MS = 60 * 60 * 1000;            // 1 hour
const CACHE_KEY = 'oe_update_cache_v1';
const DISMISS_KEY = 'oe_update_dismissed_version';

const GITHUB_RELEASES_API =
  'https://api.github.com/repos/datadrivenconstruction/OpenConstructionERP/releases/latest';

interface ReleaseInfo {
  version: string;
  notes: string;
  url: string;
  publishedAt: string;
}

interface CachedRelease {
  fetched_at: number;
  data: ReleaseInfo;
}

interface GroupedHighlights {
  added: string[];
  fixed: string[];
  polished: string[];
  other: string[];
  totalCount: number;
}

/** Compare semver strings — returns true if `a` is strictly newer than `b`. */
function isNewer(a: string, b: string): boolean {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] ?? 0) > (pb[i] ?? 0)) return true;
    if ((pa[i] ?? 0) < (pb[i] ?? 0)) return false;
  }
  return false;
}

/**
 * Parse markdown release notes into grouped highlights.
 *
 * We classify each bullet by its leading prefix (New:/Fix:/Polish:/etc.)
 * which is the convention used by our own changelog. Lines that don't
 * match any prefix go into the "other" bucket. The total count includes
 * everything regardless of length filtering so the badge stays accurate.
 */
function groupHighlights(notes: string): GroupedHighlights {
  const lines = notes
    .split('\n')
    .map((l) => l.replace(/^[-*]\s*/, '').trim())
    .filter((l) => l.length > 5 && l.length < 240);

  const result: GroupedHighlights = {
    added: [],
    fixed: [],
    polished: [],
    other: [],
    totalCount: lines.length,
  };

  for (const line of lines) {
    const lower = line.toLowerCase();
    if (lower.startsWith('new:') || lower.startsWith('add')) {
      result.added.push(line.replace(/^(new|add(?:ed)?):\s*/i, ''));
    } else if (lower.startsWith('fix')) {
      result.fixed.push(line.replace(/^fix(?:ed)?:?\s*/i, ''));
    } else if (lower.startsWith('polish') || lower.startsWith('improve')) {
      result.polished.push(line.replace(/^(polish|improve(?:d)?):?\s*/i, ''));
    } else {
      result.other.push(line);
    }
  }

  return result;
}

/* ── Cache helpers ─────────────────────────────────────────────────── */

function readCache(): CachedRelease | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw) as CachedRelease;
    if (!cached?.fetched_at || !cached?.data) return null;
    if (Date.now() - cached.fetched_at > CACHE_TTL_MS) return null;
    return cached;
  } catch {
    return null;
  }
}

function writeCache(data: ReleaseInfo): void {
  try {
    const payload: CachedRelease = { fetched_at: Date.now(), data };
    localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
  } catch {
    /* localStorage quota or disabled — silent */
  }
}

/* ── Component ─────────────────────────────────────────────────────── */

export function UpdateNotification() {
  const { t } = useTranslation();
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showInstructions, setShowInstructions] = useState(false);

  const checkForUpdate = useCallback(async () => {
    // 1. Try cache first — avoids hitting GitHub API when multiple tabs are open.
    const cached = readCache();
    if (cached) {
      const dismissedVersion = localStorage.getItem(DISMISS_KEY);
      if (dismissedVersion !== cached.data.version && isNewer(cached.data.version, CURRENT_VERSION)) {
        setRelease(cached.data);
      }
      return;
    }

    // 2. Cache miss → fetch from GitHub.
    try {
      const resp = await fetch(GITHUB_RELEASES_API);
      if (!resp.ok) return;
      const data = await resp.json();
      const latest = (data.tag_name ?? '').replace(/^v/, '');
      if (!latest) return;

      const info: ReleaseInfo = {
        version: latest,
        notes: data.body ?? '',
        url:
          data.html_url ??
          'https://github.com/datadrivenconstruction/OpenConstructionERP/releases',
        publishedAt: data.published_at ?? '',
      };
      writeCache(info);

      if (!isNewer(latest, CURRENT_VERSION)) return;

      const dismissedVersion = localStorage.getItem(DISMISS_KEY);
      if (dismissedVersion === latest) return;

      setRelease(info);
    } catch {
      /* Network error — silent. The next polling tick will retry. */
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(checkForUpdate, FIRST_CHECK_DELAY_MS);
    const interval = setInterval(checkForUpdate, CHECK_INTERVAL_MS);
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [checkForUpdate]);

  const handleDismiss = useCallback(() => {
    setDismissed(true);
    if (release) {
      localStorage.setItem(DISMISS_KEY, release.version);
    }
  }, [release]);

  const grouped = useMemo<GroupedHighlights | null>(
    () => (release ? groupHighlights(release.notes) : null),
    [release],
  );

  if (!release || dismissed) return null;

  const relativeDate = release.publishedAt
    ? new Date(release.publishedAt).toLocaleDateString()
    : '';

  // Show up to 2 entries per category in the collapsed preview to keep
  // the card minimal in the sidebar.
  const previewLimit = 2;

  return (
    <>
      <div className="mx-2 mb-2 rounded-lg border border-emerald-300/50 dark:border-emerald-700/40 bg-gradient-to-br from-emerald-50/90 via-teal-50/80 to-cyan-50/70 dark:from-emerald-950/40 dark:via-teal-950/30 dark:to-cyan-950/20 overflow-hidden animate-card-in shadow-sm shadow-emerald-500/5">
        {/* ── Header (single tight row) ─────────────────────────── */}
        <div className="flex items-center gap-2 px-2.5 py-2">
          <div className="relative shrink-0">
            <span
              className="absolute inset-0 rounded-md bg-emerald-500/25 animate-ping"
              aria-hidden="true"
            />
            <div className="relative flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-emerald-400 to-teal-500 text-white shadow-sm">
              <Sparkles size={12} strokeWidth={2.5} />
            </div>
          </div>
          <div className="flex-1 min-w-0 leading-tight">
            <div className="flex items-baseline gap-1.5">
              <span className="text-xs font-bold text-emerald-800 dark:text-emerald-200 tabular-nums">
                v{release.version}
              </span>
              <span className="text-[9px] font-semibold uppercase tracking-wider text-emerald-600/70 dark:text-emerald-400/60">
                {t('update.new_available', { defaultValue: 'available' })}
              </span>
            </div>
            <div className="flex items-center gap-1 text-[9px] text-emerald-700/60 dark:text-emerald-300/50 tabular-nums">
              {relativeDate && <span>{relativeDate}</span>}
              {grouped && grouped.totalCount > 0 && (
                <>
                  {relativeDate && <span aria-hidden="true">·</span>}
                  <span>
                    {t('update.changes_count', {
                      defaultValue: '{{count}} changes',
                      count: grouped.totalCount,
                    })}
                  </span>
                </>
              )}
            </div>
          </div>
          <button
            onClick={handleDismiss}
            aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
            className="flex h-5 w-5 items-center justify-center rounded text-emerald-500/60 hover:text-emerald-700 hover:bg-emerald-500/10 dark:hover:bg-emerald-400/10 transition-colors"
          >
            <X size={11} />
          </button>
        </div>

        {/* ── Highlights toggle (collapsible) ─────────────────────── */}
        {grouped && grouped.totalCount > 0 && (
          <>
            <button
              onClick={() => setExpanded(!expanded)}
              className="w-full flex items-center justify-between gap-1.5 px-2.5 py-1 text-[10px] font-medium text-emerald-700/80 dark:text-emerald-300/70 hover:text-emerald-800 dark:hover:text-emerald-200 hover:bg-emerald-500/[0.04] transition-colors border-t border-emerald-200/40 dark:border-emerald-800/30"
              aria-expanded={expanded}
            >
              <span>{t('update.whats_new', { defaultValue: "What's new" })}</span>
              {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            </button>
            {expanded && (
              <div className="px-2.5 py-1.5 space-y-1.5 border-t border-emerald-200/40 dark:border-emerald-800/30">
                {grouped.added.length > 0 && (
                  <HighlightGroup
                    icon={<Plus size={8} />}
                    iconClass="text-emerald-600 dark:text-emerald-400 bg-emerald-500/15"
                    label={t('update.group_new', { defaultValue: 'New' })}
                    items={grouped.added.slice(0, previewLimit)}
                    hiddenCount={Math.max(0, grouped.added.length - previewLimit)}
                  />
                )}
                {grouped.fixed.length > 0 && (
                  <HighlightGroup
                    icon={<Wrench size={8} />}
                    iconClass="text-blue-600 dark:text-blue-400 bg-blue-500/15"
                    label={t('update.group_fixed', { defaultValue: 'Fixed' })}
                    items={grouped.fixed.slice(0, previewLimit)}
                    hiddenCount={Math.max(0, grouped.fixed.length - previewLimit)}
                  />
                )}
                {grouped.polished.length > 0 && (
                  <HighlightGroup
                    icon={<Palette size={8} />}
                    iconClass="text-violet-600 dark:text-violet-400 bg-violet-500/15"
                    label={t('update.group_polished', { defaultValue: 'Polished' })}
                    items={grouped.polished.slice(0, previewLimit)}
                    hiddenCount={Math.max(0, grouped.polished.length - previewLimit)}
                  />
                )}
                {grouped.other.length > 0 && grouped.added.length + grouped.fixed.length + grouped.polished.length === 0 && (
                  <ul className="space-y-0.5">
                    {grouped.other.slice(0, 4).map((line, i) => (
                      <li key={i} className="flex items-start gap-1 text-[10px] leading-snug text-emerald-700/80 dark:text-emerald-300/70">
                        <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-emerald-500/60" />
                        <span className="line-clamp-2">{line}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}

        {/* ── Single primary action: How to update ───────────────── */}
        <div className="px-2 pb-2 pt-1">
          <button
            onClick={() => setShowInstructions(true)}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-md bg-gradient-to-br from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 px-2.5 py-1.5 text-[11px] font-semibold text-white shadow-sm shadow-emerald-500/20 transition-all hover:shadow-emerald-500/30"
          >
            <Download size={11} strokeWidth={2.5} />
            {t('update.how_to_update', { defaultValue: 'How to update' })}
          </button>
        </div>
      </div>

      {showInstructions && (
        <UpdateInstructionsModal
          version={release.version}
          releaseUrl={release.url}
          onClose={() => setShowInstructions(false)}
        />
      )}
    </>
  );
}

/* ── Subcomponent: one labelled group of highlights ──────────────── */

function HighlightGroup({
  icon,
  iconClass,
  label,
  items,
  hiddenCount,
}: {
  icon: React.ReactNode;
  iconClass: string;
  label: string;
  items: string[];
  hiddenCount: number;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <div className="flex items-center gap-1 mb-0.5">
        <span className={`flex h-3 w-3 items-center justify-center rounded ${iconClass}`}>
          {icon}
        </span>
        <span className="text-[9px] font-semibold uppercase tracking-wider text-emerald-700/70 dark:text-emerald-300/60">
          {label}
        </span>
      </div>
      <ul className="space-y-0.5 ml-4">
        {items.map((line, i) => (
          <li
            key={i}
            className="text-[10px] leading-snug text-emerald-800/85 dark:text-emerald-200/80 line-clamp-2"
          >
            {line}
          </li>
        ))}
        {hiddenCount > 0 && (
          <li className="text-[10px] italic text-emerald-600/60 dark:text-emerald-400/50">
            {t('update.more_count', {
              defaultValue: '+ {{count}} more',
              count: hiddenCount,
            })}
          </li>
        )}
      </ul>
    </div>
  );
}

/* ── Subcomponent: install-instructions modal ────────────────────── */

/**
 * Modal that shows the user *exactly* what to do to upgrade. We can't
 * auto-update a self-hosted FastAPI process from inside the SPA, so the
 * next-best UX is a single click → copyable commands for every supported
 * install method (Docker, pip, source). One-click copy on every command.
 */
function UpdateInstructionsModal({
  version,
  releaseUrl,
  onClose,
}: {
  version: string;
  releaseUrl: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const copy = useCallback(async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1500);
    } catch {
      /* clipboard blocked — silent */
    }
  }, []);

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const methods: Array<{ key: string; title: string; subtitle: string; cmd: string }> = [
    {
      key: 'pip',
      title: t('update.method_pip', { defaultValue: 'pip / PyPI' }),
      subtitle: t('update.method_pip_sub', { defaultValue: 'Recommended for Python installs' }),
      cmd: 'pip install --upgrade openconstructionerp',
    },
    {
      key: 'docker',
      title: t('update.method_docker', { defaultValue: 'Docker' }),
      subtitle: t('update.method_docker_sub', {
        defaultValue: 'Pull the new image and restart the container',
      }),
      cmd: `docker pull ghcr.io/datadrivenconstruction/openconstructionerp:${version}\ndocker compose up -d`,
    },
    {
      key: 'source',
      title: t('update.method_source', { defaultValue: 'Source (git)' }),
      subtitle: t('update.method_source_sub', {
        defaultValue: 'For self-hosted installs from source',
      }),
      cmd: 'git pull && cd frontend && npm ci && npm run build && cd ../backend && pip install -e .',
    },
  ];

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-card-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="update-modal-title"
    >
      <div
        className="relative w-full max-w-lg rounded-2xl bg-surface-elevated border border-border shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="relative px-5 py-4 bg-gradient-to-br from-emerald-50 via-teal-50 to-cyan-50 dark:from-emerald-950/40 dark:via-teal-950/30 dark:to-cyan-950/20 border-b border-border">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500 text-white shadow-md shadow-emerald-500/30">
              <Download size={18} strokeWidth={2.5} />
            </div>
            <div className="flex-1 min-w-0">
              <h2
                id="update-modal-title"
                className="text-base font-bold text-content-primary"
              >
                {t('update.modal_title', {
                  defaultValue: 'Update to v{{version}}',
                  version,
                })}
              </h2>
              <p className="text-xs text-content-secondary mt-0.5">
                {t('update.modal_subtitle', {
                  defaultValue: 'Pick the install method you used. Copy the command and run it in your terminal.',
                })}
              </p>
            </div>
            <button
              onClick={onClose}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Methods */}
        <div className="px-5 py-4 space-y-3 max-h-[60vh] overflow-y-auto">
          {methods.map((m) => (
            <div
              key={m.key}
              className="rounded-xl border border-border bg-surface-base overflow-hidden"
            >
              <div className="flex items-center justify-between px-3 py-2 border-b border-border/60">
                <div>
                  <div className="text-sm font-semibold text-content-primary">{m.title}</div>
                  <div className="text-2xs text-content-tertiary">{m.subtitle}</div>
                </div>
                <button
                  onClick={() => copy(m.key, m.cmd)}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-2xs font-medium text-content-secondary hover:text-content-primary hover:bg-surface-secondary transition-colors"
                  aria-label={t('common.copy', { defaultValue: 'Copy' })}
                >
                  {copiedKey === m.key ? (
                    <>
                      <Check size={11} className="text-emerald-500" />
                      {t('common.copied', { defaultValue: 'Copied' })}
                    </>
                  ) : (
                    <>
                      <Copy size={11} />
                      {t('common.copy', { defaultValue: 'Copy' })}
                    </>
                  )}
                </button>
              </div>
              <pre className="px-3 py-2.5 text-[11px] leading-relaxed font-mono text-content-primary bg-surface-secondary/40 overflow-x-auto whitespace-pre">
                {m.cmd}
              </pre>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-surface-secondary/40 border-t border-border flex items-center justify-between gap-3">
          <p className="text-2xs text-content-tertiary">
            {t('update.modal_help', {
              defaultValue: 'After running the command, restart the service to load the new version.',
            })}
          </p>
          <a
            href={releaseUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-2xs font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300 whitespace-nowrap"
          >
            {t('update.release_notes', { defaultValue: 'Release notes' })}
            <ExternalLink size={10} />
          </a>
        </div>
      </div>
    </div>
  );
}

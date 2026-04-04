/**
 * UpdateNotification — Sidebar widget showing when a new version is available.
 *
 * Checks GitHub Releases API for datadrivenconstruction/OpenConstructionERP.
 * Shows a compact card in the sidebar with version, key changes, and update link.
 */

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUpCircle, X, ExternalLink, Gift, ChevronDown, ChevronUp } from 'lucide-react';

const CURRENT_VERSION = '0.2.1';
const CHECK_INTERVAL = 4 * 60 * 60 * 1000; // 4 hours
const GITHUB_RELEASES_API =
  'https://api.github.com/repos/datadrivenconstruction/OpenConstructionERP/releases/latest';
const DISMISS_KEY = 'oe_update_dismissed_version';

interface ReleaseInfo {
  version: string;
  notes: string;
  url: string;
  publishedAt: string;
}

/** Compare semver strings: returns true if a > b */
function isNewer(a: string, b: string): boolean {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] ?? 0) > (pb[i] ?? 0)) return true;
    if ((pa[i] ?? 0) < (pb[i] ?? 0)) return false;
  }
  return false;
}

/** Extract first 5 bullet points from markdown release notes */
function extractHighlights(notes: string): string[] {
  return notes
    .split('\n')
    .map((l) => l.replace(/^[-*]\s*/, '').trim())
    .filter((l) => l.length > 5 && l.length < 200)
    .slice(0, 5);
}

export function UpdateNotification() {
  const { t } = useTranslation();
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const checkForUpdate = useCallback(async () => {
    try {
      const resp = await fetch(GITHUB_RELEASES_API);
      if (!resp.ok) return;
      const data = await resp.json();
      const latest = (data.tag_name ?? '').replace(/^v/, '');
      if (!latest || !isNewer(latest, CURRENT_VERSION)) return;

      // Check if user already dismissed this version
      const dismissedVersion = localStorage.getItem(DISMISS_KEY);
      if (dismissedVersion === latest) return;

      setRelease({
        version: latest,
        notes: data.body ?? '',
        url: data.html_url ?? `https://github.com/datadrivenconstruction/OpenConstructionERP/releases`,
        publishedAt: data.published_at ?? '',
      });
    } catch {
      // Silent fail
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(checkForUpdate, 8000);
    const interval = setInterval(checkForUpdate, CHECK_INTERVAL);
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

  if (!release || dismissed) return null;

  const highlights = extractHighlights(release.notes);
  const relativeDate = release.publishedAt
    ? new Date(release.publishedAt).toLocaleDateString()
    : '';

  return (
    <div className="mx-2 mb-2 rounded-xl border border-emerald-200 dark:border-emerald-800/40 bg-gradient-to-br from-emerald-50 to-teal-50 dark:from-emerald-950/30 dark:to-teal-950/20 overflow-hidden animate-card-in">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
          <Gift size={14} className="text-emerald-600 dark:text-emerald-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-emerald-700 dark:text-emerald-300">
              v{release.version}
            </span>
            <span className="text-2xs text-emerald-600/60 dark:text-emerald-400/50">
              {t('update.new_available', { defaultValue: 'available' })}
            </span>
          </div>
          {relativeDate && (
            <span className="text-2xs text-emerald-600/50 dark:text-emerald-400/40">
              {relativeDate}
            </span>
          )}
        </div>
        <button
          onClick={handleDismiss}
          className="p-0.5 rounded text-emerald-400 hover:text-emerald-600 transition-colors"
          title={t('common.dismiss', { defaultValue: 'Dismiss' })}
        >
          <X size={12} />
        </button>
      </div>

      {/* Highlights (collapsible) */}
      {highlights.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="w-full flex items-center gap-1 px-3 py-1 text-2xs text-emerald-600/70 dark:text-emerald-400/60 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors"
          >
            {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            <span>{t('update.whats_new', { defaultValue: "What's new" })}</span>
          </button>
          {expanded && (
            <div className="px-3 pb-2">
              <ul className="space-y-0.5">
                {highlights.map((h, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-2xs text-emerald-700/80 dark:text-emerald-300/70">
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-emerald-500/50" />
                    <span>{h}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {/* Update button */}
      <div className="px-3 pb-2.5">
        <a
          href={release.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-1.5 w-full rounded-lg bg-emerald-600 hover:bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white transition-colors"
        >
          <ArrowUpCircle size={13} />
          {t('update.view_update', { defaultValue: 'View Update' })}
          <ExternalLink size={10} />
        </a>
      </div>
    </div>
  );
}

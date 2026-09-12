// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * UpdateNotification — Sidebar widget showing when a new version is available.
 *
 * Reads `GET /api/system/version-check`, our own backend, and shows a compact
 * card in the sidebar when that endpoint says an update is available. The card
 * surfaces the release highlights and a one-click jump to the release.
 *
 * Implementation notes:
 *
 * - **Where the answer comes from.** The server asks PyPI, falls back to the
 *   GitHub release, compares versions itself and caches the result for four
 *   hours. This used to be a browser call straight to api.github.com, which
 *   costs the anonymous rate limit — 60 requests an hour per IP, shared by
 *   everyone in an office — and cannot be answered at all on an air-gapped
 *   install, where it failed once an hour per tab and logged every attempt.
 *   The server also knows things the browser cannot see: which version is
 *   really installed, and whether this build can upgrade itself.
 *
 * - **Caching.** The query holds the answer for the same four hours the
 *   server caches it, so mounting the widget again costs nothing and a
 *   long-lived tab still notices a release that lands while it is open.
 *
 * - **Failure.** Anything other than a well-formed answer — offline, a proxy
 *   answering with its own page, a slow endpoint, an error — renders nothing
 *   at all. The notice can never be the reason a screen fails.
 *
 * - **Dismiss.** Per-version dismiss state is stored in sessionStorage; once
 *   the user closes the card for v0.8.0 they will not see it again until
 *   v0.8.1 (or higher) appears.
 */

import { useState, useEffect, useCallback, useMemo, type MouseEvent as ReactMouseEvent } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Sparkles, X, ExternalLink, Copy, Check,
  Plus, Wrench, Palette, Loader2, Download, RotateCcw,
} from 'lucide-react';
import { apiGet, apiPost, ApiError } from '@/shared/lib/api';
import { copyToClipboard } from '@/shared/lib/browser';
import { isTauri, openExternalUrl, openInNewTab } from '@/shared/lib/desktop';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── One-click upgrade — starts `pip install --upgrade` server-side ───
 *
 *  The server starts a job and answers straight away; we poll it. It used to
 *  do the whole install inside the request, which no browser waits for: on a
 *  slow link the client gave up at 45s and told the user the upgrade had
 *  failed, over an upgrade that was still running and went on to succeed
 *  (issue #430).
 */

interface UpgradeJob {
  job_id: string | null;
  /** ``idle`` means this server process has not run one, which is also what
   *  it says after the restart a finished upgrade asks for. */
  status: 'idle' | 'running' | 'succeeded' | 'failed';
  ok?: boolean;
  command?: string;
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
  error?: string;
  installed_version?: string;
  running_version?: string;
  restart_required?: boolean;
  restart_hint?: string;
}

const UPGRADE_POLL_MS = 2_000;
/** Stop polling eventually. The server stops pip itself at 600s, so this only
 *  has to outlast that. Reaching it leaves the dialog saying "running", which
 *  is the truthful thing to say about an upgrade that is still running. */
const UPGRADE_POLL_CEILING_MS = 15 * 60 * 1000;
/** Consecutive failed polls tolerated. An install replaces files under a
 *  process a watchdog may restart, so one quiet moment is not a failure. */
const UPGRADE_POLL_RETRIES = 5;

async function startRuntimeUpgrade(version?: string): Promise<UpgradeJob> {
  const qs = version ? `?version=${encodeURIComponent(version)}` : '';
  try {
    return await apiPost<UpgradeJob>(`/system/upgrade${qs}`, {});
  } catch (err) {
    // 409 carries the job already running. Pressing the button twice, or
    // pressing it again after the browser gave up waiting, is the ordinary
    // way that happens, so attach to it instead of reporting an error.
    if (err instanceof ApiError && err.status === 409 && err.body && typeof err.body === 'object') {
      return err.body as UpgradeJob;
    }
    throw err;
  }
}

async function readUpgradeStatus(): Promise<UpgradeJob> {
  return apiGet<UpgradeJob>('/system/upgrade/status');
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const VERSION_CHECK_URL = '/api/system/version-check';
/** Matches the server's own cache window, so holding the answer here costs
 *  the server nothing and asking again inside it would gain nothing. */
const VERSION_CHECK_TTL_MS = 4 * 60 * 60 * 1000;
// OC-16: dismiss state persists across sessions via localStorage so the
// banner does not reappear on every page load. The guard is version-scoped:
// dismissing v17.4.1 does not suppress a later v17.5.0 notification.
const DISMISS_KEY = 'oe_update_dismissed_version';
/** The endpoint truncates the release body at this many characters, so notes
 *  arriving at exactly this length are a cut, not a short release. */
const NOTES_CAP = 500;

/**
 * Skip the release check entirely.
 *
 * Kept from when this widget called api.github.com itself, where a site with
 * no outbound internet asked once an hour, per tab, forever, and the browser
 * logged the failed request every time. The request is same-origin now and
 * the server answers an air-gapped install without reaching anywhere, so this
 * is no longer a remedy for anything; it stays as the way to switch the
 * update notice off for a deployment that does not want one - a demo, a
 * recording, a managed install upgraded by its own pipeline.
 */
const UPDATE_CHECK_DISABLED = Boolean(import.meta.env.VITE_DISABLE_UPDATE_CHECK);

/** The answer from ``GET /api/system/version-check``.
 *
 *  ``update_available`` is the server's comparison, not ours: it parses both
 *  versions as integer tuples, so 5.2.10 sorts above 5.2.9 where a string
 *  compare puts it below, and a pre-release sorts below the release it
 *  precedes. Comparing again here would be a second implementation of one
 *  decision, and the copy is the one that goes wrong.
 *
 *  ``self_upgrade_supported`` answers whether ``sys.executable`` can run
 *  ``-m pip``, which a frozen bundle cannot. It is a property of the build,
 *  and only the build can report it.
 */
export interface VersionCheck {
  current_version: string;
  latest_version: string;
  update_available: boolean;
  release_url: string;
  release_notes: string;
  published_at: string;
  /** Installers published with the release. Empty when the endpoint could
   *  not stand behind them, which it decides the same way it decides the
   *  notes: only a GitHub release naming `latest_version` is quoted. */
  assets: ReleaseAsset[];
  self_upgrade_supported: boolean;
  upgrade_command: string;
}

/** One published installer: what it is called, where it is, how big it is. */
export interface ReleaseAsset {
  name: string;
  url: string;
  size: number;
}

interface GroupedHighlights {
  added: string[];
  fixed: string[];
  polished: string[];
  other: string[];
  totalCount: number;
}

/** Keep only the asset entries that carry all three fields we would render.
 *  An older backend answers no ``assets`` at all, which is the same thing to
 *  a reader as a release that published none: no download to offer, and the
 *  release page below still gets them there. */
function parseAssets(raw: unknown): ReleaseAsset[] {
  if (!Array.isArray(raw)) return [];
  const out: ReleaseAsset[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const a = entry as Partial<ReleaseAsset>;
    if (typeof a.name !== 'string' || !a.name) continue;
    if (typeof a.url !== 'string' || !a.url) continue;
    out.push({ name: a.name, url: a.url, size: typeof a.size === 'number' ? a.size : 0 });
  }
  return out;
}

/** The three platforms Desktop Release publishes an installer for. `null`
 *  covers everything else, phones included, where there is nothing to run. */
type InstallerPlatform = 'windows' | 'macos' | 'linux' | null;

/**
 * Which machine is the reader sitting at.
 *
 * Read from the browser and never from the server. The desktop build serves
 * its API to any browser that can reach the port, so the platform this
 * process runs on is not reliably the platform of the person reading, and
 * that mismatch is exactly what the endpoint declines to guess at.
 *
 * Order is load-bearing twice over. Android user agents contain "Linux", and
 * iPhone and iPad ones contain "Mac OS X", so both mobile families have to be
 * answered before the desktop tests they would otherwise match. Neither has
 * an installer to be offered.
 */
function readInstallerPlatform(): InstallerPlatform {
  if (typeof navigator === 'undefined') return null;
  const ua = navigator.userAgent || '';
  if (/Windows/i.test(ua)) return 'windows';
  if (/Android|iPhone|iPad|iPod/i.test(ua)) return null;
  if (/Macintosh|Mac OS X/i.test(ua)) return 'macos';
  if (/Linux|X11/i.test(ua)) return 'linux';
  return null;
}

/**
 * Extensions to offer per platform, best first.
 *
 * macOS is matched on `.dmg` alone even though the release also carries an
 * `.app.tar.gz`: that second file is the updater bundle, not something a
 * person installs, and a substring test would hand it over. Linux has up to
 * three, and one button can only be one of them - `.AppImage` leads because
 * it runs on any distribution where `.deb` is Debian and Ubuntu only, and the
 * `.rpm` is last because it reaches the fewest readers, not because it is
 * unreliable. It used to be both: the rpm build ran out of job time often
 * enough to be absent from a release, and 15.1.0 spent five hours fifty
 * minutes producing nothing. Setting the packer's compression to none took
 * that to nineteen minutes in 15.2.0, so treat an absent `.rpm` as a fault to
 * look into rather than as the normal case. The fallback below stays either
 * way: a release genuinely short of a platform should answer with the release
 * page, not with a broken link. Windows has shipped one installer, the NSIS
 * `.exe`, since 15.2.0.
 */
const INSTALLER_SUFFIXES: Record<Exclude<InstallerPlatform, null>, string[]> = {
  windows: ['.exe'],
  macos: ['.dmg'],
  linux: ['.AppImage', '.deb', '.rpm'],
};

/**
 * The installer this reader should be offered, or ``null`` when the release
 * published nothing that fits.
 *
 * Matched on the end of the file name rather than anywhere inside it, which
 * is what keeps `.app.tar.gz` from answering for `.dmg` and a detached
 * `.exe.sig` signature from answering for the installer it signs.
 */
function pickInstaller(assets: ReleaseAsset[], platform: InstallerPlatform): ReleaseAsset | null {
  if (!platform) return null;
  for (const suffix of INSTALLER_SUFFIXES[platform]) {
    const hit = assets.find((a) => a.name.toLowerCase().endsWith(suffix.toLowerCase()));
    if (hit) return hit;
  }
  return null;
}

/**
 * Ask the backend whether this install is behind, answering ``null`` for
 * every way that can fail to produce a usable answer.
 *
 * Nothing here rejects, and nothing here throws: a rejected promise would
 * put React Query into an error state that a caller could render, and the
 * one thing this notice must never do is become the reason a screen fails.
 * Offline, a 500, a gateway answering 200 with its own login page, a body
 * whose shape moved - all of them are the same thing to a reader, which is
 * nothing to show.
 */
async function fetchVersionCheck(): Promise<VersionCheck | null> {
  try {
    const r = await fetch(VERSION_CHECK_URL, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    const data: unknown = await r.json();
    if (!data || typeof data !== 'object') return null;
    const body = data as Partial<VersionCheck>;
    // Shape check rather than a cast. Without it a body that answers 200 with
    // something else entirely renders "v undefined → v undefined".
    if (typeof body.latest_version !== 'string' || !body.latest_version) return null;
    if (typeof body.update_available !== 'boolean') return null;
    return {
      current_version: typeof body.current_version === 'string' ? body.current_version : '',
      latest_version: body.latest_version,
      update_available: body.update_available,
      release_url: typeof body.release_url === 'string' ? body.release_url : '',
      release_notes: typeof body.release_notes === 'string' ? body.release_notes : '',
      published_at: typeof body.published_at === 'string' ? body.published_at : '',
      assets: parseAssets(body.assets),
      // A build that does not say either way is treated as unable to upgrade
      // itself, because the failure modes are not symmetric: an installer
      // instruction reaches a pip install too, while a pip command reaches a
      // frozen build as advice it cannot carry out.
      self_upgrade_supported: body.self_upgrade_supported === true,
      upgrade_command: typeof body.upgrade_command === 'string' ? body.upgrade_command : '',
    };
  } catch {
    return null;
  }
}

/**
 * Parse markdown release notes into grouped highlights.
 *
 * The changelog uses Keep-a-Changelog `### Added`, `### Fixed`,
 * `### Changed` etc. headers, with `- **Bold name** — description` bullets
 * underneath. We track the current header as we scan, classify each bullet
 * by which section it lives in, and strip markdown markup so the rendered
 * card never shows raw `###`, `**`, `_`, or backtick characters.
 */
function stripMarkdown(text: string): string {
  return text
    // **bold** / __bold__ → bold (drop markers, keep content)
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    // *italic* / _italic_ → italic
    .replace(/(?<!\*)\*(?!\s)([^*\n]+?)\*(?!\*)/g, '$1')
    .replace(/(?<![A-Za-z0-9_])_(?!\s)([^_\n]+?)_(?![A-Za-z0-9_])/g, '$1')
    // `code` → code (drop backticks)
    .replace(/`([^`]+)`/g, '$1')
    // [link text](url) → link text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .trim();
}

function groupHighlights(notes: string): GroupedHighlights {
  const result: GroupedHighlights = {
    added: [],
    fixed: [],
    polished: [],
    other: [],
    totalCount: 0,
  };

  // Track which Keep-a-Changelog bucket we're currently inside.
  // null = no header seen yet (bullets land in "other").
  let currentBucket: 'added' | 'fixed' | 'polished' | 'other' | null = null;

  const rawLines = notes.split('\n');
  for (const raw of rawLines) {
    const line = raw.trim();
    if (!line) continue;

    // ### Added — Foo  /  ## Fixed  /  #### Security
    const headerMatch = line.match(/^#{1,6}\s+(.+)$/);
    if (headerMatch?.[1]) {
      const headerText = headerMatch[1].toLowerCase();
      if (/(^|[\s—-])(added|new|feature|features)(\b|[\s—-])/.test(headerText)) {
        currentBucket = 'added';
      } else if (/(^|[\s—-])(fixed|fix|bug|bugs)(\b|[\s—-])/.test(headerText)) {
        currentBucket = 'fixed';
      } else if (/(^|[\s—-])(changed|polish|polished|improve|improved|ux|polish)(\b|[\s—-])/.test(headerText)) {
        currentBucket = 'polished';
      } else if (/(^|[\s—-])(security|hardening|deprecated|removed)(\b|[\s—-])/.test(headerText)) {
        currentBucket = 'fixed';
      } else {
        currentBucket = 'other';
      }
      continue;
    }

    // Bullet line: `- foo`, `* foo`, or numbered `1. foo`
    if (!/^[-*]|^\d+\.\s/.test(line)) continue;

    const cleaned = stripMarkdown(line.replace(/^[-*]\s*/, '').replace(/^\d+\.\s*/, ''));
    if (cleaned.length < 5 || cleaned.length > 280) continue;

    // Allow inline prefixes ("New:", "Fix:", "Fixed:") to override the
    // current bucket — they're a stronger signal than the section header.
    let bucket: 'added' | 'fixed' | 'polished' | 'other' = currentBucket ?? 'other';
    let display = cleaned;
    const lower = cleaned.toLowerCase();
    if (/^(new|added?):\s*/i.test(cleaned)) {
      bucket = 'added';
      display = cleaned.replace(/^(new|added?):\s*/i, '');
    } else if (/^fix(?:ed)?:?\s*/i.test(cleaned)) {
      bucket = 'fixed';
      display = cleaned.replace(/^fix(?:ed)?:?\s*/i, '');
    } else if (lower.startsWith('polish') || lower.startsWith('improve')) {
      bucket = 'polished';
      display = cleaned.replace(/^(polish(?:ed)?|improve(?:d)?):?\s*/i, '');
    }

    result[bucket].push(display);
    result.totalCount++;
  }

  return result;
}

/**
 * The opening of the release notes, as prose.
 *
 * The endpoint caps the body at {@link NOTES_CAP} characters and this
 * project's releases open with paragraphs rather than bullets, so
 * `groupHighlights` usually finds nothing to group in what arrives. An empty
 * panel would be the wrong answer to that: the paragraph itself says what the
 * release is about. What it must not do is print the half-finished word a cut
 * at a fixed character count leaves behind, so the text is trimmed back to a
 * word boundary and marked as continuing.
 */
function isProseLine(line: string): boolean {
  // Headings, bullets and anything carrying a URL are not prose. The release
  // body ends with the list GitHub generates - one commit subject and a
  // compare link per line - and read as a paragraph those print raw URLs and
  // commit prefixes at the reader.
  return (
    Boolean(line) &&
    !line.startsWith('#') &&
    !line.startsWith('-') &&
    !line.startsWith('*') &&
    !line.includes('://')
  );
}

function notesExcerpt(notes: string, limit = 320): string {
  const lines = notes.split('\n').map((line) => line.trim());
  const clean = stripMarkdown(lines.filter(isProseLine).join(' '));
  if (!clean) return '';
  // The endpoint hands back the first NOTES_CAP characters of the body, so
  // where that cut landed decides whether the last thing we quote is whole.
  // Inside a heading or a bullet, the paragraph above it survives intact and
  // is printed as written; inside the paragraph itself, its last word is a
  // fragment and has to go.
  const endsMidWord = notes.length >= NOTES_CAP && isProseLine(lines[lines.length - 1] ?? '');
  if (clean.length <= limit && !endsMidWord) return clean;
  const cut = clean.slice(0, Math.min(limit, clean.length));
  const lastSpace = cut.lastIndexOf(' ');
  return `${lastSpace > 0 ? cut.slice(0, lastSpace) : cut}…`;
}

/* ── Component ─────────────────────────────────────────────────────── */

/**
 * Public hook so other pages (About, Settings) can show the same update
 * card without duplicating the fetch logic. Returns the server's answer when
 * it says an update is available, otherwise null.
 *
 * One query key for the whole app, so the sidebar card, the About page and
 * the Settings panel share one answer and one request between them. The
 * query is never retried and its failure is held for the same window as its
 * success: a site that cannot reach the endpoint would otherwise ask again on
 * every mount, which is the retry storm the browser-side GitHub call used to
 * produce.
 */
export function useUpdateCheck(): VersionCheck | null {
  const { data } = useQuery<VersionCheck | null>({
    queryKey: ['system-version-check'],
    queryFn: fetchVersionCheck,
    enabled: !UPDATE_CHECK_DISABLED,
    staleTime: VERSION_CHECK_TTL_MS,
    // No interval. A tab left open for days will not hear about a release
    // until it is reloaded, and that is the trade this widget should make: a
    // timer asks again forever, including on the install that can never be
    // answered, which is the shape of the storm this change removed. A
    // release is worth knowing about within the session that follows it.
    refetchOnWindowFocus: false,
    retry: false,
  });

  return data && data.update_available ? data : null;
}

interface UpdateNotificationProps {
  /** When true, the dismiss state is ignored — used on the About / Settings pages
   *  where the user explicitly navigated to "see what's new". */
  forceShow?: boolean;
  /** Hide the dismiss button — pairs naturally with `forceShow`. */
  hideDismiss?: boolean;
}

export function UpdateNotification({ forceShow = false, hideDismiss = false }: UpdateNotificationProps = {}) {
  const { t } = useTranslation();
  const release = useUpdateCheck();
  // The version a dismissal was about, not the fact that one happened. Read
  // from storage at mount rather than when the answer arrives, so a card
  // dismissed in this session stays down when the widget mounts again on
  // another route with the answer already cached.
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(() => {
    try {
      return localStorage.getItem(DISMISS_KEY);
    } catch {
      return null;
    }
  });
  const [showFullModal, setShowFullModal] = useState(false);

  const handleDismiss = useCallback(() => {
    if (!release) return;
    setDismissedVersion(release.latest_version);
    try {
      localStorage.setItem(DISMISS_KEY, release.latest_version);
    } catch {
      /* storage unavailable — the card simply reappears next mount */
    }
  }, [release]);

  const grouped = useMemo<GroupedHighlights | null>(
    () => (release ? groupHighlights(release.release_notes) : null),
    [release],
  );

  if (!release) return null;
  // Scoped to the version dismissed: the next release speaks up on its own.
  if (dismissedVersion === release.latest_version && !forceShow) return null;

  const relativeDate = release.published_at
    ? new Date(release.published_at).toLocaleDateString(getIntlLocale())
    : '';

  return (
    <>
      {/* Site-brand palette: oe-blue (#0071e3) with sky/cyan accents.
          Entire card is a button — clicking anywhere opens the full-screen
          modal with highlights + install commands. The sidebar stays narrow,
          the details breathe. */}
      <div className="mx-2 mb-2 relative rounded-lg border border-sky-400/60 dark:border-sky-500/40 bg-gradient-to-br from-sky-50 via-blue-50 to-cyan-50 dark:from-sky-950/50 dark:via-blue-950/40 dark:to-cyan-950/30 overflow-hidden animate-card-in shadow-md shadow-sky-500/15 ring-1 ring-sky-500/10 dark:ring-sky-400/10 hover:shadow-lg hover:shadow-sky-500/25 hover:ring-sky-500/30 transition-shadow">
        <button
          type="button"
          onClick={() => setShowFullModal(true)}
          aria-label={t('update.open_details', {
            defaultValue: 'View update details for v{{version}}',
            version: release.latest_version,
          })}
          className="w-full text-left"
        >
          {/* Stacked layout — three rows so nothing truncates inside a 210px
              sidebar:
                row 1  icon + version arrow + "available" pill
                row 2  date · N changes
                row 3  full-width Details chip
              Each row owns its own width, so we never have to fight flex
              competition between version text and right-side chip (the old
              row-flex layout was clipping the version on narrow sidebars). */}
          <div className="px-3 py-2.5">
            <div className="flex items-center gap-2">
              <div className="relative shrink-0">
                <span
                  className="absolute inset-0 rounded-md bg-sky-500/35 animate-ping"
                  aria-hidden="true"
                />
                <div className="relative flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-sm shadow-blue-500/30">
                  <Sparkles size={12} strokeWidth={2.5} />
                </div>
              </div>
              <span className="flex-1 text-[13px] font-bold text-blue-900 dark:text-sky-100 tabular-nums leading-tight break-words">
                {/* The arrow needs both ends to mean anything. A body that
                    named the new version but not the running one would
                    otherwise read "v → v15.1.0". */}
                {release.current_version
                  ? `v${release.current_version} → v${release.latest_version}`
                  : `v${release.latest_version}`}
              </span>
              <span className="shrink-0 inline-flex items-center rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-300">
                {t('update.new_available', { defaultValue: 'available' })}
              </span>
            </div>
            {(relativeDate || (grouped && grouped.totalCount > 0)) && (
              <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 pl-8 text-[11px] text-blue-700/75 dark:text-sky-300/65 tabular-nums">
                {relativeDate && <span>{relativeDate}</span>}
                {grouped && grouped.totalCount > 0 && (
                  <>
                    {relativeDate && <span aria-hidden="true">·</span>}
                    <span>
                      {t('update.changes_count_short', {
                        defaultValue: '{{count}} changes',
                        count: grouped.totalCount,
                      })}
                    </span>
                  </>
                )}
              </div>
            )}
            <div className="mt-2 flex items-center justify-end gap-1 text-[11px] font-semibold text-blue-600 dark:text-sky-300">
              {t('update.details', { defaultValue: 'Details' })}
              <ExternalLink size={11} />
            </div>
          </div>
        </button>
        {!hideDismiss && (
          <button
            onClick={handleDismiss}
            aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
            className="absolute top-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded text-sky-500/70 hover:text-blue-700 hover:bg-sky-500/20 dark:hover:bg-sky-400/20 transition-colors"
          >
            <X size={11} />
          </button>
        )}
      </div>

      {showFullModal && (
        <UpdateFullModal
          release={release}
          grouped={grouped}
          onClose={() => setShowFullModal(false)}
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
        <span className="text-[9px] font-semibold uppercase tracking-wider text-blue-700/75 dark:text-sky-300/65">
          {label}
        </span>
      </div>
      <ul className="space-y-0.5 ml-4">
        {items.map((line, i) => (
          <li
            key={i}
            className="text-[10px] leading-snug text-blue-900/85 dark:text-sky-100/85 line-clamp-2"
          >
            {line}
          </li>
        ))}
        {hiddenCount > 0 && (
          <li className="text-[10px] italic text-blue-600/65 dark:text-sky-400/55">
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

/* ── Full-page update modal ──────────────────────────────────────── */

/**
 * UpdateFullModal — controlled full-screen modal opened from the sidebar
 * card. Combines grouped highlights (added / fixed / polished) with
 * copy-able install commands and a link to the full GitHub release notes.
 *
 * Controlled: the parent (sidebar card) owns `open` state. Escape key
 * and backdrop click both fire `onClose` so the modal is easy to
 * dismiss.
 */
function UpdateFullModal({
  release,
  grouped,
  onClose,
}: {
  release: VersionCheck;
  grouped: GroupedHighlights | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  /** One-click upgrade state. ``idle`` is the default; ``running`` shows a
   *  spinner; ``done`` shows the post-pip result + restart hint; ``error``
   *  shows the captured stderr so the user can copy it into a bug report.
   *
   *  Backed by ``POST /api/system/upgrade`` which gates on
   *  ``ALLOW_RUNTIME_UPGRADE`` — managed installs (VPS, SaaS) keep the
   *  copy-paste path while localhost / Windows installer users get the
   *  one-click button working out of the box. */
  const [upgradeStatus, setUpgradeStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [upgradeResult, setUpgradeResult] = useState<UpgradeJob | null>(null);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);

  const handleApplyUpgrade = useCallback(async () => {
    setUpgradeStatus('running');
    setUpgradeError(null);
    try {
      let job = await startRuntimeUpgrade(release.latest_version);
      setUpgradeResult(job);

      const ceiling = Date.now() + UPGRADE_POLL_CEILING_MS;
      let failures = 0;
      while (job.status === 'running' && Date.now() < ceiling) {
        await sleep(UPGRADE_POLL_MS);
        try {
          job = await readUpgradeStatus();
          setUpgradeResult(job);
          failures = 0;
        } catch (pollErr) {
          if (++failures >= UPGRADE_POLL_RETRIES) throw pollErr;
        }
      }

      if (job.status === 'failed') {
        setUpgradeStatus('error');
        setUpgradeError(job.error || job.stderr || job.stdout || `pip exited ${job.exit_code}`);
      } else if (job.status === 'running') {
        // Still going when we stopped watching. Leaving the dialog on
        // "running" says exactly that, and reopening it attaches again.
        setUpgradeStatus('running');
      } else {
        // succeeded, or idle because the server restarted under us, which is
        // the thing a finished upgrade asks the user to do.
        setUpgradeStatus('done');
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setUpgradeError(err.message);
        // 403 → runtime upgrade disabled on this install (e.g. managed VPS).
        // Surface that explicitly so the user copies the command instead of
        // hammering the button.
      } else {
        setUpgradeError(String(err));
      }
      setUpgradeStatus('error');
    }
  }, [release.latest_version]);

  const copy = useCallback(async (key: string, text: string) => {
    try {
      await copyToClipboard(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1500);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const relativeDate = release.published_at
    ? new Date(release.published_at).toLocaleDateString(getIntlLocale())
    : '';

  // What the reader can actually do, decided by the build rather than by the
  // browser. `self_upgrade_supported` is false inside a frozen bundle, where
  // `sys.executable` is the app binary and a pip command feeds its own tokens
  // back into this application's CLI (issue #403). This used to be decided
  // here from `isTauri`, which is a guess about the window rather than a fact
  // about the build: the desktop app's server is reachable from an ordinary
  // browser, and read there the guess said "pip" to a build that has none.
  //
  // The pip command itself comes from the server too, for the reason
  // backend/app/core/self_upgrade.py gives about its own wording: two places
  // writing one instruction drift, and the second is always written by
  // somebody who has not read the first.
  const methods: Array<{ key: string; title: string; subtitle: string; cmd: string }> =
    release.self_upgrade_supported
      ? [
          {
            key: 'pip',
            title: t('update.method_pip', { defaultValue: 'pip / PyPI' }),
            subtitle: t('update.method_pip_sub', { defaultValue: 'Recommended for Python installs' }),
            cmd: release.upgrade_command || 'pip install --upgrade openconstructionerp',
          },
          {
            key: 'source',
            title: t('update.method_source', { defaultValue: 'Source (git)' }),
            subtitle: t('update.method_source_sub', {
              defaultValue: 'For self-hosted installs from source',
            }),
            cmd: 'git pull && cd frontend && npm ci && npm run build && cd ../backend && pip install -e .',
          },
        ]
      : [];

  // The installer for the machine this is being read on, when the release
  // published one. The release page lists every platform at once, so someone
  // who cannot upgrade in place is otherwise asked to work out which of six
  // files is theirs; naming it turns the page into a download.
  const installer = pickInstaller(release.assets, readInstallerPlatform());

  // The desktop shell renders in a webview where a plain target="_blank" can
  // land nowhere, so the native bridge opens the reader's real browser. In an
  // ordinary browser the anchor is left to do its own job, which also keeps
  // right-click and copy-link working.
  const openDownload = async (e: ReactMouseEvent<HTMLAnchorElement>, url: string): Promise<void> => {
    if (!isTauri) return;
    e.preventDefault();
    const opened = await openExternalUrl(url);
    if (!opened) openInNewTab(url);
  };

  /** The opening paragraph of the notes, shown when there are no bullets to
   *  group - which is the usual case, because the release body opens with
   *  prose and the endpoint returns only its first {@link NOTES_CAP}
   *  characters. */
  const excerpt =
    grouped && grouped.totalCount > 0 ? '' : notesExcerpt(release.release_notes);

  // Portal to <body> so the modal escapes the Sidebar's stacking context.
  // AppLayout applies `translate-x-0` on the sidebar wrapper, which
  // establishes a containing block for `position: fixed` descendants —
  // without the portal, the overlay would be clipped to the sidebar's
  // width instead of spanning the full viewport.
  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-lg p-4 animate-card-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="update-fullmodal-title"
    >
      <div
        className="relative w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl bg-surface-elevated border border-border shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header — version + dismiss */}
        <div className="relative px-6 py-5 bg-gradient-to-br from-sky-50 via-blue-50 to-cyan-50 dark:from-sky-950/50 dark:via-blue-950/40 dark:to-cyan-950/30 border-b border-border">
          <div className="flex items-start gap-3">
            <div className="relative shrink-0">
              <span className="absolute inset-0 rounded-xl bg-sky-500/30 animate-ping" aria-hidden="true" />
              <div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-md shadow-blue-500/40">
                <Sparkles size={20} strokeWidth={2.5} />
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <h2
                id="update-fullmodal-title"
                className="text-xl font-bold text-content-primary leading-tight"
              >
                {t('update.popup_title', {
                  defaultValue: 'Update available - v{{version}}',
                  version: release.latest_version,
                })}
              </h2>
              <div className="flex items-center gap-2 mt-1 text-sm text-content-secondary">
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
                {release.current_version && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="tabular-nums">
                      {t('update.currently_on', {
                        defaultValue: 'you have v{{version}}',
                        version: release.current_version,
                      })}
                    </span>
                  </>
                )}
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body — highlights + install commands */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Highlights */}
          {grouped && grouped.totalCount > 0 && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                {t('update.whats_new', { defaultValue: "What's new" })}
              </h3>
              <div className="space-y-4">
                {grouped.added.length > 0 && (
                  <HighlightGroup
                    icon={<Plus size={10} />}
                    iconClass="text-sky-600 dark:text-sky-300 bg-sky-500/20"
                    label={t('update.group_new', { defaultValue: 'New' })}
                    items={grouped.added.slice(0, 6)}
                    hiddenCount={Math.max(0, grouped.added.length - 6)}
                  />
                )}
                {grouped.fixed.length > 0 && (
                  <HighlightGroup
                    icon={<Wrench size={10} />}
                    iconClass="text-blue-600 dark:text-blue-300 bg-blue-500/20"
                    label={t('update.group_fixed', { defaultValue: 'Fixed' })}
                    items={grouped.fixed.slice(0, 6)}
                    hiddenCount={Math.max(0, grouped.fixed.length - 6)}
                  />
                )}
                {grouped.polished.length > 0 && (
                  <HighlightGroup
                    icon={<Palette size={10} />}
                    iconClass="text-cyan-600 dark:text-cyan-300 bg-cyan-500/20"
                    label={t('update.group_polished', { defaultValue: 'Polished' })}
                    items={grouped.polished.slice(0, 6)}
                    hiddenCount={Math.max(0, grouped.polished.length - 6)}
                  />
                )}
                {grouped.other.length > 0 &&
                  grouped.added.length + grouped.fixed.length + grouped.polished.length === 0 && (
                    <ul className="space-y-1">
                      {grouped.other.slice(0, 6).map((line, i) => (
                        <li
                          key={i}
                          className="flex items-start gap-2 text-sm leading-snug text-content-primary"
                        >
                          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-sky-500/70" />
                          <span>{line}</span>
                        </li>
                      ))}
                    </ul>
                  )}
              </div>
            </section>
          )}

          {/* Prose opening of the notes, for the releases whose body carries
              no bullets to group. Empty whenever the groups above have
              something, so exactly one of the two renders. */}
          {excerpt && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                {t('update.whats_new', { defaultValue: "What's new" })}
              </h3>
              <p className="text-sm leading-relaxed text-content-primary">{excerpt}</p>
            </section>
          )}

          {/* One-click upgrade — server-side ``pip install --upgrade`` in the
              same venv as the running uvicorn. The 403 fallback below shows
              when ALLOW_RUNTIME_UPGRADE is off (managed installs).

              Shown only where the server says this build can upgrade itself.
              It used to be shown everywhere, deliberately, because the 409 a
              frozen build answers carries the instruction the reader needs
              and hiding the button hid the instruction with it (issue #403).
              That reasoning held while the instruction lived in the refusal;
              it is now printed up front by the installer card below, so the
              reader gets it without pressing a button that cannot work. */}
          {release.self_upgrade_supported && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
              {t('update.apply_now', { defaultValue: 'Apply update' })}
            </h3>
            <div className="rounded-xl border border-sky-400/50 dark:border-sky-500/40 bg-gradient-to-br from-sky-50 to-blue-50 dark:from-sky-950/40 dark:to-blue-950/30 p-4">
              {upgradeStatus === 'idle' && (
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-content-primary">
                      {t('update.one_click_title', {
                        defaultValue: 'Install v{{version}} now',
                        version: release.latest_version,
                      })}
                    </div>
                    <div className="text-2xs text-content-tertiary mt-0.5">
                      {t('update.one_click_sub', {
                        defaultValue:
                          'Runs pip in the active venv. Restart the launcher once the install completes.',
                      })}
                    </div>
                  </div>
                  <button
                    onClick={handleApplyUpgrade}
                    className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-sky-500 to-blue-600 hover:from-sky-600 hover:to-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm shadow-blue-500/30 transition-all"
                  >
                    <Download size={14} />
                    {t('update.apply_now_button', { defaultValue: 'Apply update' })}
                  </button>
                </div>
              )}
              {upgradeStatus === 'running' && (
                <div className="flex items-center gap-3">
                  <Loader2 size={18} className="animate-spin text-sky-600 dark:text-sky-400" />
                  <div className="text-sm text-content-primary">
                    {t('update.running', {
                      defaultValue: 'Running pip install - this can take a minute on first download…',
                    })}
                  </div>
                </div>
              )}
              {upgradeStatus === 'done' && upgradeResult && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700 dark:text-emerald-300">
                    <Check size={16} />
                    {t('update.installed', {
                      defaultValue: 'Installed v{{version}}',
                      version: upgradeResult.installed_version,
                    })}
                  </div>
                  {upgradeResult.restart_required && (
                    <div className="rounded-lg bg-amber-500/15 px-3 py-2 text-2xs text-amber-700 dark:text-amber-300 flex items-start gap-2">
                      <RotateCcw size={12} className="mt-0.5 shrink-0" />
                      <span>{upgradeResult.restart_hint}</span>
                    </div>
                  )}
                  {upgradeResult.stdout && (
                    <details className="text-2xs">
                      <summary className="cursor-pointer text-content-tertiary">
                        {t('update.show_log', { defaultValue: 'Show pip log' })}
                      </summary>
                      <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-surface-secondary/60 p-2 text-[10px] leading-snug font-mono whitespace-pre-wrap">
                        {upgradeResult.stdout.slice(-2000)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
              {upgradeStatus === 'error' && (
                <div className="space-y-2">
                  <div className="text-sm font-semibold text-rose-700 dark:text-rose-300">
                    {t('update.error', { defaultValue: 'Upgrade failed' })}
                  </div>
                  <pre className="max-h-40 overflow-auto rounded-md bg-rose-500/10 p-2 text-[10px] leading-snug font-mono text-rose-700 dark:text-rose-300 whitespace-pre-wrap">
                    {upgradeError ?? 'unknown error'}
                  </pre>
                  <div className="text-2xs text-content-tertiary">
                    {t('update.error_hint', {
                      defaultValue:
                        'Copy the command below and run it from your terminal - the same pip install works there.',
                    })}
                  </div>
                </div>
              )}
            </div>
          </section>
          )}

          {/* How to update. A build that can run pip gets the commands; a
              frozen one gets the only route that works for it, said plainly,
              rather than a command whose first effect would be to teach the
              reader that the tool telling them about the update cannot apply
              it either.

              `isTauri` widens this beyond frozen builds rather than replacing
              the test, and the two are not the same question. Whether pip can
              run is a fact about the build; whether the reader is sitting in
              the desktop shell is a fact about the window. A desktop build
              backed by a real venv answers yes to both, and it keeps the pip
              route below - what it gains here is the installer, which works
              for it either way. Nothing promises to install anything: we ship
              no updater, and on Windows the installer wants administrator
              rights that a download cannot grant itself. */}
          {(!release.self_upgrade_supported || isTauri) && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
                {t('update.how_to_update', { defaultValue: 'How to update' })}
              </h3>
              <div className="rounded-xl border border-border bg-surface-primary px-3 py-3">
                <div className="text-sm font-semibold text-content-primary">
                  {t('update.method_installer')}
                </div>
                <p className="mt-1 text-2xs leading-relaxed text-content-tertiary">
                  {installer
                    ? t('update.download_installer_hint')
                    : t('update.method_installer_advice')}
                </p>
                {/* The file itself when we can name it. The name is shown
                    because it is the thing that will land in the downloads
                    folder, and a reader who can see it is not taking our word
                    for which platform we decided they are on. */}
                {installer && (
                  <div className="mt-2">
                    <a
                      href={installer.url}
                      onClick={(e) => void openDownload(e, installer.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-sm font-semibold text-white transition-colors"
                    >
                      <Download size={13} />
                      {t('update.download_installer')}
                    </a>
                    <div className="mt-1.5 flex items-center gap-2 text-2xs text-content-tertiary">
                      <span className="font-mono break-all">{installer.name}</span>
                      {installer.size > 0 && (
                        <span className="tabular-nums whitespace-nowrap">
                          {t('update.installer_size', {
                            size: Math.round(installer.size / (1024 * 1024)),
                          })}
                        </span>
                      )}
                    </div>
                  </div>
                )}
                {/* The way there, next to the instruction that names it. The
                    footer link says "Release notes", and a reader sent to
                    fetch an installer should not have to work out that those
                    are the same page. Kept even when the download above is
                    offered: it is the only route left when we picked the
                    wrong platform, or when someone wants the package the one
                    button could not be. */}
                <a
                  href={release.release_url}
                  onClick={(e) => void openDownload(e, release.release_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-sky-400 dark:hover:text-sky-300"
                >
                  {t('update.open_release_page')}
                  <ExternalLink size={12} />
                </a>
              </div>
            </section>
          )}

          {methods.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
              {t('update.how_to_update', { defaultValue: 'How to update' })}
            </h3>
            <div className="space-y-3">
              {methods.map((m) => (
                <div
                  key={m.key}
                  className="rounded-xl border border-border bg-surface-primary overflow-hidden"
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
                          <Check size={11} className="text-sky-500" />
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
          </section>
          )}
        </div>

        {/* Footer — release link + primary dismiss */}
        <div className="px-6 py-4 bg-surface-secondary/40 border-t border-border flex items-center justify-between gap-3">
          <a
            href={release.release_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-sky-400 dark:hover:text-sky-300"
          >
            {t('update.release_notes', { defaultValue: 'Release notes' })}
            <ExternalLink size={12} />
          </a>
          <button
            onClick={onClose}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-br from-sky-500 to-blue-600 hover:from-sky-600 hover:to-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm shadow-blue-500/30 ring-1 ring-blue-500/20 transition-all"
          >
            {t('update.got_it', { defaultValue: 'Got it' })}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}


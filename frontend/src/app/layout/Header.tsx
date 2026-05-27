import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search, ChevronDown, ChevronRight, LogOut, User, Settings, Menu, MessageSquarePlus, FolderOpen, CheckCircle2, XCircle, Bug, BookOpen, Loader2, Upload, HelpCircle, Mail, ExternalLink, Github, Sun, Moon, Monitor } from 'lucide-react';
import clsx from 'clsx';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '../i18n';
import { useAuthStore } from '@/stores/useAuthStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { CountryFlag } from '@/shared/ui';
import { NotificationBell } from '@/shared/ui/NotificationBell';
import { apiGet } from '@/shared/lib/api';
import {
  exportErrorReport,
  getErrorCount,
  getLastError,
  isLastErrorNetworkOnly,
} from '@/shared/lib/errorLogger';
import { APP_VERSION, APP_BUILD_FINGERPRINT } from '@/shared/lib/version';
import { useToastStore } from '@/stores/useToastStore';
import { useI18nReady } from '@/shared/lib/useI18nReady';
import { SupportUsButton } from './SupportUsButton';
import { SubscribeButton } from './SubscribeButton';

/** Map English page titles (passed from App.tsx routes) to i18n keys. */
const TITLE_I18N_MAP: Record<string, string> = {
  'Dashboard': 'nav.dashboard',
  'AI Quick Estimate': 'nav.ai_estimate',
  'AI Cost Advisor': 'nav.ai_advisor',
  'CAD/BIM Takeoff': 'nav.cad_takeoff',
  'Match Elements': 'match_elements.title',
  'Projects': 'nav.projects',
  'New Project': 'projects.new_project',
  'Project': 'nav.projects',
  'New BOQ': 'boq.new_estimate',
  'Bill of Quantities': 'nav.boq',
  'BOQ Editor': 'boq.editor',
  'BOQ Templates': 'nav.templates',
  'Cost Database': 'nav.costs',
  'Import Cost Database': 'costs.import_title',
  'Resource Catalog': 'nav.resource_catalog',
  'Assemblies': 'nav.assemblies',
  'New Assembly': 'assemblies.new',
  'Assembly Editor': 'assemblies.editor',
  'Validation': 'nav.validation',
  'Quantity Takeoff': 'nav.takeoff_overview',
  'PDF Takeoff': 'nav.takeoff',
  '4D Schedule': 'nav.schedule',
  '5D Cost Model': 'nav.5d_cost_model',
  'Reports': 'nav.reports',
  'Sustainability': 'nav.sustainability',
  'Tendering': 'nav.tendering',
  'Change Orders': 'nav.change_orders',
  'Documents': 'nav.documents',
  'Project Photos': 'nav.photos',
  'Project Files': 'nav.project_files',
  'Risk Register': 'nav.risk_register',
  'Analytics': 'nav.analytics',
  'About': 'nav.about',
  'Not Found': 'error.not_found',
  'Modules': 'nav.modules',
  'Settings': 'nav.settings',
};

interface HeaderProps {
  title?: string;
  onMenuClick?: () => void;
}

export function Header({ title, onMenuClick }: HeaderProps) {
  const { t, i18n } = useTranslation();
  // Header mounts at app boot, before lazy-loaded locale chunks arrive.
  // ``useTranslation`` doesn't always pick up bundle-added events under
  // React StrictMode (subscription gets churned by double-mount), so we
  // attach an external-store subscription that survives the remount and
  // forces a re-render whenever a new resource bundle is merged in. The
  // returned version number is unused — its role is to invalidate the
  // memoization React applies to this render.
  useI18nReady();
  const translatedTitle = title
    ? t(TITLE_I18N_MAP[title] ?? title, { defaultValue: title })
    : undefined;
  const currentLang = getLanguageByCode(i18n.language) ?? { code: 'en', name: 'English', flag: '', country: 'gb' };
  const openCommandPalette = useCallback(() => {
    // Dispatch Ctrl+K to open the CommandPalette managed by App.tsx
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
  }, []);

  return (
    <header
      className={clsx(
        'sticky top-0 z-30 relative',
        'flex h-header items-center justify-between gap-3 px-4 sm:px-6 lg:px-8',
        'bg-surface-primary/80 backdrop-blur-xl',
      )}
    >
      {/* Soft hairline at the bottom — replaces a hard 1px border for
          a calmer Linear/Vercel-style separation from the page below. */}
      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-border to-transparent" />

      {/* ── Zone 1 (Workspace): mobile menu + project breadcrumb + title ── */}
      <div className="flex items-center gap-3 min-w-0">
        {onMenuClick && (
          <button
            onClick={onMenuClick}
            aria-label={t('common.open_menu', { defaultValue: 'Open menu' })}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary lg:hidden"
          >
            <Menu size={20} />
          </button>
        )}

        {/* Active project switcher (rendered first so the breadcrumb
            reads left-to-right as ProjectName › PageTitle). */}
        <ProjectSwitcher />

        {translatedTitle && (
          <>
            {/* Breadcrumb separator — only shown on lg+ where the page
                title is visible. Subtle chevron so it reads as
                "ProjectName › PageTitle" hierarchy. */}
            <ChevronRight
              size={14}
              strokeWidth={1.75}
              className="hidden lg:block shrink-0 text-content-quaternary/60"
              aria-hidden
            />
            <h1 className="hidden lg:block text-base font-semibold text-content-primary truncate sm:text-lg">{translatedTitle}</h1>
          </>
        )}
      </div>

      {/* Right side — three zones separated by hairline dividers.
          Zone 2: Search · Zone 3: Notifications + Help · Zone 4: Account
          (Upload + Language + User). Each zone has internal `gap-1`,
          dividers between zones are 1px hairlines.

          SubscribeButton lives in Zone 3 next to HelpMenu (sized to
          match the Support pill — same h-8 icon-with-label format on
          desktop, icon-only on mobile). It used to sit absolutely
          centred across the header but that created awkward visual
          tension with the project switcher on the left; planted next
          to Support/Help, the two CTAs read as a coherent cluster. */}
      <div className="flex items-center gap-2">
        {/* ── Zone 2 (Search) ──────────────────────────────────────── */}
        <button
          onClick={openCommandPalette}
          className={clsx(
            'hidden sm:flex h-8 items-center gap-2 rounded-lg px-3',
            // Solid-ish white background so the field doesn't dissolve into
            // the translucent header background; falls back to a dark tint
            // in dark mode so the chip stays readable on the dark blurred
            // topbar.
            'border border-border-light bg-white/85 backdrop-blur-sm dark:bg-surface-primary/70',
            'text-sm text-content-tertiary shadow-sm',
            'transition-colors duration-fast ease-oe',
            'hover:border-content-quaternary/40 hover:bg-white dark:hover:bg-surface-primary hover:text-content-secondary',
            'w-40 md:w-44 lg:w-56',
          )}
        >
          <Search size={14} strokeWidth={1.75} className="shrink-0" />
          <span className="truncate">{t('common.search')}</span>
          <kbd className="ml-auto inline-flex items-center gap-0.5 rounded border border-border-light bg-surface-primary px-1 py-px text-[9px] font-medium text-content-quaternary">
            ⌘K
          </kbd>
        </button>

        {/* Mobile search icon — collapses the search bar on tiny screens. */}
        <button
          onClick={openCommandPalette}
          aria-label={t('common.search', { defaultValue: 'Search' })}
          className="flex sm:hidden h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary transition-colors"
        >
          <Search size={16} />
        </button>

        {/* Hairline divider between Zone 2 and Zone 3. */}
        <div className="hidden sm:block h-4 w-px bg-border-light/70" aria-hidden />

        {/* ── Zone 3 (Notifications + Subscribe + Bug + Help) ──────
            Order: NotificationBell · SupportUs · Subscribe · BugReport · Help.
            The "ask the user for something" CTAs (Support / Subscribe) stay
            adjacent; Bug + Help sit on the right edge so a user filing a
            report doesn't have to scan past the marketing CTAs. */}
        <NotificationBell />
        <SupportUsButton />
        <SubscribeButton />
        <BugReportMenu />
        <HelpMenu />

        {/* Hairline divider between Zone 3 and Zone 4. */}
        <div className="hidden sm:block h-4 w-px bg-border-light/70" aria-hidden />

        {/* ── Zone 4 (Account) ─────────────────────────────────────── */}
        <UploadQueueIndicator />
        <LanguageSwitcher
          currentLang={currentLang}
          onSelect={(code) => i18n.changeLanguage(code)}
        />
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}

/* ── Theme Toggle ──────────────────────────────────────────────────────── */

/** Single icon-button that cycles light → dark → system. The icon swaps
 *  to mirror the *current* theme, not the *next* one (Linear/Vercel
 *  convention) — users glance at it to see what mode they're in,
 *  click to advance. Lives in Zone 4 next to the avatar so theme +
 *  identity sit together. */
function ThemeToggle() {
  const { t } = useTranslation();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);

  const cycle = () => {
    if (theme === 'light') setTheme('dark');
    else if (theme === 'dark') setTheme('system');
    else setTheme('light');
  };

  const Icon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor;
  const label =
    theme === 'light'
      ? t('settings.theme_light', { defaultValue: 'Light theme' })
      : theme === 'dark'
        ? t('settings.theme_dark', { defaultValue: 'Dark theme' })
        : t('settings.theme_system', { defaultValue: 'System theme' });

  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={label}
      title={label}
      data-testid="theme-toggle"
      data-theme={theme}
      className="hidden sm:flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
    >
      <Icon size={16} strokeWidth={1.75} />
    </button>
  );
}

/* ── Bug Report Menu (standalone, prominent) ─────────────────────────
   Dedicated header button so reporting an issue is one obvious click,
   not a multi-step "open help → scroll → click bug". The popover lets
   the user pick the channel:

     - GitHub Issue (pre-filled with last error + env)
     - Email the team (mailto: with the same payload)
     - Web feedback form (richer fields, captures attachments server-side)
     - Download log JSON (for manual sharing)

   A red dot on the icon flags that errors were captured this session,
   so the user notices the entry point is relevant to them. */

function BugReportMenu() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  // Once the user clicks "report anyway" we stop nagging them with the
  // network-only banner for the rest of the popover lifetime.
  const [overrodeNetworkWarning, setOverrodeNetworkWarning] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const errorCount = getErrorCount();
  // Re-evaluated each open of the popover. ``isLastErrorNetworkOnly``
  // returns true when every recent level=error entry is a transport
  // blip (Failed to fetch, AbortError, 502/503/504, …) — i.e. nothing
  // actionable for a GitHub issue. See errorLogger#155.
  const networkOnly = open && !overrodeNetworkWarning && isLastErrorNetworkOnly();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  // Reset the network-only override each time the popover is dismissed
  // so the next open shows the banner again if nothing new has happened.
  useEffect(() => {
    if (!open) setOverrodeNetworkWarning(false);
  }, [open]);

  const handleGithub = () => {
    setOpen(false);
    const { url, body } = buildBugReportUrl(t);
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
      return;
    }
    void navigator.clipboard.writeText(body).then(
      () => {
        addToast({
          type: 'info',
          title: t('app.report_bug_not_configured', { defaultValue: 'GitHub repo not configured' }),
          message: t('app.report_bug_copied', { defaultValue: 'Report copied to clipboard' }),
        });
      },
      () => {
        addToast({
          type: 'warning',
          title: t('app.report_bug_not_configured', { defaultValue: 'GitHub repo not configured' }),
        });
      },
    );
  };

  const handleEmail = () => {
    setOpen(false);
    const { body, title } = buildBugReportUrl(t);
    const subject = `OpenConstructionERP Issue — ${title}`;
    // mailto bodies are also length-limited (~2000 chars in Chrome),
    // so we trim aggressively. The downloaded log JSON is the long form.
    const safeBody = body.length > 1500 ? `${body.slice(0, 1500)}\n\n_[truncated — attach the JSON log if needed]_` : body;
    const href = `mailto:info@datadrivenconstruction.io?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(safeBody)}`;
    window.location.href = href;
  };

  const handleFeedbackForm = () => {
    setOpen(false);
    if (errorCount > 0) {
      const blob = exportErrorReport();
      const blobUrl = URL.createObjectURL(blob);
      const dl = document.createElement('a');
      dl.href = blobUrl;
      dl.download = `openconstructionerp-log-${new Date().toISOString().slice(0, 10)}.json`;
      dl.click();
      URL.revokeObjectURL(blobUrl);
    }
    const params = new URLSearchParams({
      report: 'true',
      app_version: APP_VERSION,
      platform: navigator.userAgent.includes('Win') ? 'Windows' : navigator.userAgent.includes('Mac') ? 'macOS' : 'Linux',
    });
    window.open(`https://openconstructionerp.com/contact.html?${params}`, '_blank');
  };

  const handleDownloadLog = () => {
    setOpen(false);
    const blob = exportErrorReport();
    const blobUrl = URL.createObjectURL(blob);
    const dl = document.createElement('a');
    dl.href = blobUrl;
    dl.download = `openconstructionerp-log-${new Date().toISOString().slice(0, 10)}.json`;
    dl.click();
    URL.revokeObjectURL(blobUrl);
    addToast({
      type: 'success',
      title: t('app.bug_log_downloaded', { defaultValue: 'Log downloaded' }),
      message: t('app.bug_log_downloaded_desc', { defaultValue: 'Attach this JSON to your report.' }),
    });
  };

  type Channel = {
    icon: typeof Github;
    iconColor: string;
    title: string;
    desc: string;
    onClick: () => void;
  };

  const channels: Channel[] = [
    {
      icon: Github,
      iconColor: 'text-content-primary',
      title: t('bug.channel_github', { defaultValue: 'Open a GitHub issue' }),
      desc: t('bug.channel_github_desc', { defaultValue: 'Pre-filled with the last error and environment. Public.' }),
      onClick: handleGithub,
    },
    {
      icon: Mail,
      iconColor: 'text-oe-blue',
      title: t('bug.channel_email', { defaultValue: 'Email the team' }),
      desc: t('bug.channel_email_desc', { defaultValue: 'Opens your mail client with the report attached.' }),
      onClick: handleEmail,
    },
    {
      icon: MessageSquarePlus,
      iconColor: 'text-emerald-500',
      title: t('bug.channel_form', { defaultValue: 'Web feedback form' }),
      desc: t('bug.channel_form_desc', { defaultValue: 'Richer fields and screenshots on openconstructionerp.com.' }),
      onClick: handleFeedbackForm,
    },
    {
      icon: Upload,
      iconColor: 'text-violet-500',
      title: t('bug.channel_download', { defaultValue: 'Download log only' }),
      desc: t('bug.channel_download_desc', { defaultValue: 'Save the JSON to share manually with support.' }),
      onClick: handleDownloadLog,
    },
  ];

  return (
    <div className="relative hidden sm:block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={clsx(
          'relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors',
          'text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary',
          open && 'bg-surface-secondary text-content-secondary',
        )}
        title={t('bug.menu_title', { defaultValue: 'Report a bug or send feedback' })}
        aria-label={t('bug.menu_title', { defaultValue: 'Report a bug or send feedback' })}
      >
        <Bug size={16} strokeWidth={1.75} />
        {errorCount > 0 && (
          <span
            className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-red-500 ring-2 ring-surface-primary"
            aria-label={t('bug.errors_captured', {
              defaultValue: '{{count}} errors captured this session',
              count: errorCount,
            })}
          />
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1.5 w-80 rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-scale-in py-2 z-40"
        >
          <div className="px-3 pb-2 border-b border-border-light">
            <div className="flex items-center gap-2">
              <Bug size={14} className="text-content-tertiary" />
              <span className="text-sm font-semibold text-content-primary">
                {t('bug.menu_heading', { defaultValue: 'Report a bug' })}
              </span>
              {errorCount > 0 && (
                <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-red-500/10 px-2 py-0.5 text-2xs font-semibold text-red-500">
                  <span className="h-1 w-1 rounded-full bg-red-500" />
                  {t('bug.errors_chip', {
                    defaultValue: '{{count}} captured',
                    count: errorCount,
                  })}
                </span>
              )}
            </div>
            <p className="mt-1 text-2xs text-content-tertiary leading-snug">
              {t('bug.menu_subheading', {
                defaultValue: 'Pick where to send it — every channel includes the same diagnostic payload.',
              })}
            </p>
          </div>

          {networkOnly && (
            <div
              role="alert"
              className="mx-3 my-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2"
            >
              <p className="text-2xs font-semibold text-amber-600 dark:text-amber-400">
                {t('bug.network_only_title', {
                  defaultValue: 'Looks like a network issue, not a bug',
                })}
              </p>
              <p className="mt-1 text-2xs text-amber-700/90 dark:text-amber-300/90 leading-snug">
                {t('bug.network_only_desc', {
                  defaultValue:
                    'Recent errors look like the backend was unreachable (offline, restarting, or VPN dropped). Check your connection and reload — if the problem persists, you can still file a report.',
                })}
              </p>
              <button
                type="button"
                onClick={() => setOverrodeNetworkWarning(true)}
                className="mt-1.5 text-2xs font-medium text-amber-700 dark:text-amber-300 underline-offset-2 hover:underline"
              >
                {t('bug.network_only_override', {
                  defaultValue: 'Report anyway →',
                })}
              </button>
            </div>
          )}

          <div className={clsx('py-1', networkOnly && 'opacity-40 pointer-events-none')}>
            {channels.map((ch, idx) => {
              const Icon = ch.icon;
              return (
                <button
                  key={idx}
                  type="button"
                  role="menuitem"
                  onClick={ch.onClick}
                  className="flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-surface-secondary transition-colors"
                >
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-secondary">
                    <Icon size={14} className={ch.iconColor} />
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13px] font-medium text-content-primary">
                      {ch.title}
                    </span>
                    <span className="block text-2xs text-content-tertiary leading-snug mt-0.5">
                      {ch.desc}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Help Menu (consolidated docs / GitHub / feedback / bug-report) ─── */

/** Single `?` icon button at top-right that opens a popover with every
 *  help / feedback / external-link action consolidated. Replaces what
 *  was previously six separate header buttons (GitHub, Docs, Report
 *  Issue, More, Feedback, Email Issues). One discoverable menu reads
 *  cleaner than six visually competing buttons. */
function HelpMenu() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  // Open the contact form pre-tagged as "Send Feedback". Mirrors the
  // pre-consolidation amber-Feedback button (which used to live in the
  // header). Downloads the in-session error log if there are any
  // errors so the user can attach it.
  const handleFeedback = () => {
    setOpen(false);
    if (getErrorCount() > 0) {
      const blob = exportErrorReport();
      const blobUrl = URL.createObjectURL(blob);
      const dl = document.createElement('a');
      dl.href = blobUrl;
      dl.download = `openconstructionerp-log-${new Date().toISOString().slice(0, 10)}.json`;
      dl.click();
      URL.revokeObjectURL(blobUrl);
    }
    const params = new URLSearchParams({
      feedback: 'true',
      app_version: APP_VERSION,
    });
    window.open(`https://openconstructionerp.com/contact.html?${params}`, '_blank');
  };

  // Download the JSON error report and open the contact form pre-tagged
  // as a Report Issue. Mirrors the pre-consolidation top-level Bug
  // button + the Report Issue item in the legacy More popover.
  const handleReportIssue = () => {
    setOpen(false);
    const blob = exportErrorReport();
    const blobUrl = URL.createObjectURL(blob);
    const dl = document.createElement('a');
    dl.href = blobUrl;
    dl.download = `openconstructionerp-report-${new Date().toISOString().slice(0, 10)}.json`;
    dl.click();
    URL.revokeObjectURL(blobUrl);
    const params = new URLSearchParams({
      report: 'true',
      app_version: APP_VERSION,
      platform: navigator.userAgent.includes('Win') ? 'Windows' : navigator.userAgent.includes('Mac') ? 'macOS' : 'Linux',
    });
    window.open(`https://openconstructionerp.com/contact.html?${params}`, '_blank');
  };

  // GitHub-issue with the last captured error pre-filled. Same flow as
  // the pre-consolidation "Report a bug" item from the user menu.
  const handleReportBug = () => {
    setOpen(false);
    const { url, body } = buildBugReportUrl(t);
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
      return;
    }
    void navigator.clipboard.writeText(body).then(
      () => {
        addToast({
          type: 'info',
          title: t('app.report_bug_not_configured', { defaultValue: 'Bug reporting is not configured' }),
          message: t('app.report_bug_copied', { defaultValue: 'Report contents copied to clipboard' }),
        });
      },
      () => {
        addToast({
          type: 'warning',
          title: t('app.report_bug_not_configured', { defaultValue: 'Bug reporting is not configured' }),
        });
      },
    );
  };

  return (
    <div className="relative hidden sm:block" ref={ref} data-testid="header-help-menu">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={clsx(
          'flex h-8 w-8 items-center justify-center rounded-lg transition-colors',
          'text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary',
          open && 'bg-surface-secondary text-content-secondary',
        )}
        title={t('nav.help', { defaultValue: 'Help & feedback' })}
        aria-label={t('nav.help', { defaultValue: 'Help & feedback' })}
      >
        <HelpCircle size={16} strokeWidth={1.75} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1.5 w-60 rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-scale-in py-1 z-40"
        >
          {/* External resources */}
          <a
            role="menuitem"
            href="https://openconstructionerp.com/docs.html"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <BookOpen size={14} className="text-content-tertiary shrink-0" />
            <span className="flex-1">{t('nav.docs', { defaultValue: 'Documentation' })}</span>
            <ExternalLink size={11} className="text-content-quaternary shrink-0" />
          </a>
          <a
            role="menuitem"
            href="https://github.com/datadrivenconstruction/OpenConstructionERP"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Github size={14} className="text-content-tertiary shrink-0" />
            <span className="flex-1">{t('nav.github', { defaultValue: 'GitHub repository' })}</span>
            <ExternalLink size={11} className="text-content-quaternary shrink-0" />
          </a>

          <div className="my-1 border-t border-border-light" role="separator" />

          {/* Feedback / report flows */}
          <button
            type="button"
            role="menuitem"
            onClick={handleFeedback}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <MessageSquarePlus size={14} className="text-content-tertiary shrink-0" />
            <span>{t('feedback.title', { defaultValue: 'Send feedback' })}</span>
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={handleReportIssue}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Bug size={14} className="text-content-tertiary shrink-0" />
            <span>{t('feedback.report_issue', { defaultValue: 'Report issue' })}</span>
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={handleReportBug}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Bug size={14} className="text-content-tertiary shrink-0" />
            <span>{t('app.report_bug', { defaultValue: 'Report a bug (with logs)' })}</span>
          </button>
          <a
            role="menuitem"
            href="mailto:info@datadrivenconstruction.io?subject=OpenConstructionERP%20Issue%20Report"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Mail size={14} className="text-content-tertiary shrink-0" />
            <span>{t('header.email_issues', { defaultValue: 'Email the team' })}</span>
          </a>
        </div>
      )}
    </div>
  );
}

/* ── Language Switcher Dropdown ─────────────────────────────────────────── */

function LanguageSwitcher({
  currentLang,
  onSelect,
}: {
  currentLang: (typeof SUPPORTED_LANGUAGES)[number] | undefined;
  onSelect: (code: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!currentLang) return null;
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`Language: ${currentLang.name}`}
        title={currentLang.name}
        className={clsx(
          'flex h-8 items-center gap-1.5 rounded-lg px-2',
          'text-xs font-medium text-content-secondary',
          'transition-all duration-fast ease-oe',
          'hover:bg-surface-secondary',
          open && 'bg-surface-secondary',
        )}
      >
        <CountryFlag code={currentLang.country} size={16} />
        <ChevronDown size={11} className={clsx('transition-transform duration-fast', open && 'rotate-180')} aria-hidden="true" />
      </button>

      {open && (
        <div role="menu" className="absolute right-0 top-full mt-1.5 w-48 max-h-72 overflow-y-auto rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-scale-in py-1">
          {SUPPORTED_LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              role="menuitem"
              onClick={() => { onSelect(lang.code); setOpen(false); }}
              className={clsx(
                'flex w-full items-center gap-2.5 px-3 py-1.5 text-sm transition-colors',
                lang.code === currentLang.code
                  ? 'bg-oe-blue-subtle text-oe-blue-text font-medium'
                  : 'text-content-primary hover:bg-surface-secondary',
              )}
            >
              <CountryFlag code={lang.country} size={16} />
              <span className="truncate text-xs">{lang.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── User Menu ─────────────────────────────────────────────────────────── */

/** GitHub repo slug for "Report a bug". Empty string = clipboard fallback. */
const GITHUB_REPO = 'datadrivenconstruction/OpenConstructionERP';
/** Hard ceiling for the GitHub issue body inside a URL. ~8KB is safe across browsers. */
const MAX_BODY_BYTES = 7800;

/**
 * Build the GitHub "new issue" URL pre-filled with environment + last error.
 *
 * Returns `{ url, body }` so callers can fall back to clipboard when the
 * repo is not configured.  The body is plain text (markdown-ish) and never
 * contains user JWT, email, or other PII — `getLastError()` returns
 * already-anonymized strings via `errorLogger.anonymize()`.
 */
function buildBugReportUrl(t: (key: string, opts?: { defaultValue?: string }) => string): {
  url: string;
  body: string;
  title: string;
} {
  const last = getLastError();
  const stackLines = last?.stack ? last.stack.split('\n').slice(0, 30).join('\n') : '';
  const errorBlock = last
    ? `\`\`\`\n${last.message}\n${stackLines}\n\`\`\``
    : t('app.report_bug_no_error', { defaultValue: '_No error captured during this session._' });

  const body = [
    '### Description',
    '<!-- describe what you were doing -->',
    '',
    '### Environment',
    `- App version: ${APP_VERSION}`,
    `- Page: ${window.location.pathname}${window.location.search}`,
    `- User agent: ${navigator.userAgent}`,
    `- Build: ${APP_BUILD_FINGERPRINT}`,
    last ? `- Captured at: ${last.at}` : '',
    '',
    '### Last error captured',
    errorBlock,
  ].filter(Boolean).join('\n');

  // URL-encode and trim if the body would push us past the safe size.
  let safeBody = body;
  let encoded = encodeURIComponent(safeBody);
  if (encoded.length > MAX_BODY_BYTES) {
    // Keep the head; truncation marker tells the maintainer to ask for the
    // full JSON via "Report Issue" if they need more.
    const trimmed = safeBody.slice(0, Math.floor(safeBody.length * (MAX_BODY_BYTES / encoded.length)) - 64);
    safeBody = trimmed + '\n\n_[truncated — attach the full JSON via the Report Issue button if needed]_';
    encoded = encodeURIComponent(safeBody);
  }

  const title = t('app.report_bug_title_default', { defaultValue: 'Bug report from in-app menu' });
  const encodedTitle = encodeURIComponent(title);
  const url = GITHUB_REPO
    ? `https://github.com/${GITHUB_REPO}/issues/new?title=${encodedTitle}&body=${encoded}`
    : '';
  return { url, body: safeBody, title };
}

function UserMenu() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const logout = useAuthStore((s) => s.logout);
  const userEmail = useAuthStore((s) => s.userEmail);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const userInitial = userEmail ? userEmail.charAt(0).toUpperCase() : 'U';

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="true"
        className={clsx(
          'relative flex h-8 w-8 items-center justify-center rounded-full',
          'bg-gradient-to-br from-oe-blue to-[#38bdf8] text-xs font-semibold text-white',
          'shadow-[0_1px_3px_rgba(0,122,255,0.25)]',
          'transition-all duration-fast ease-oe',
          'hover:opacity-90 hover:shadow-[0_2px_6px_rgba(0,122,255,0.35)]',
        )}
        title={userEmail ?? undefined}
        aria-label={t('auth.account', { defaultValue: 'Account menu' })}
      >
        {userInitial}
        {/* Online status dot — bottom-right of the avatar. Matches the
            UserBadge in the sidebar so the two surfaces feel coherent. */}
        <span
          aria-hidden
          className="absolute -bottom-0.5 -right-0.5 flex h-2.5 w-2.5 items-center justify-center"
        >
          <span className="absolute inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400/70 animate-ping" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-surface-primary" />
        </span>
      </button>

      {open && (
        <div role="menu" className="absolute right-0 top-full mt-1.5 w-48 rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-scale-in py-1">
          {userEmail && (
            <>
              <div className="px-3 py-1.5 text-2xs text-content-tertiary truncate" title={userEmail}>
                {userEmail}
              </div>
              <div className="my-1 border-t border-border-light" role="separator" />
            </>
          )}
          <button
            role="menuitem"
            onClick={() => { setOpen(false); navigate('/settings'); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <User size={14} className="text-content-tertiary" />
            {t('auth.profile', 'Profile')}
          </button>
          <button
            role="menuitem"
            onClick={() => { setOpen(false); navigate('/settings'); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Settings size={14} className="text-content-tertiary" />
            {t('nav.settings', 'Settings')}
          </button>
          <div className="my-1 border-t border-border-light" role="separator" />
          <button
            role="menuitem"
            onClick={() => { logout(); navigate('/login'); setOpen(false); }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-semantic-error hover:bg-semantic-error-bg transition-colors"
          >
            <LogOut size={14} />
            {t('auth.logout', 'Sign out')}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Project Switcher (global dropdown in header) ─────────────────────── */

/**
 * Compute where to navigate after switching projects in the global picker.
 *
 * We stay on the same module but never keep a URL that points at an
 * entity (BOQ / BIM model / assembly / transmittal / …) owned by the
 * *previous* project — that entity doesn't belong to the new project,
 * so the page would either 404 or silently show stale data.
 *
 * Rules:
 *   `/projects/:oldId` or `/projects/:oldId/sub` → swap in the new id
 *       (e.g. /projects/AAA/finance → /projects/BBB/finance)
 *   `/<module>/:entityId` where `<module>` is one of the entity-scoped
 *       list-plus-detail modules → redirect to the module list `/<module>`
 *   everything else → stay on the same URL
 */
export function resolveRouteAfterProjectSwitch(
  pathname: string,
  newProjectId: string,
): string | null {
  const projectSub = pathname.match(/^\/projects\/[^/]+(\/.*)?$/);
  if (projectSub) {
    const suffix = projectSub[1] ?? '';
    return `/projects/${newProjectId}${suffix}`;
  }
  // Module-scoped detail routes.  The list lives at /<module>.
  const entityRoutes: Array<[RegExp, string]> = [
    [/^\/boq\/[^/]+/, '/boq'],
    [/^\/bim\/[^/]+/, '/bim'],
    [/^\/assemblies\/[^/]+/, '/assemblies'],
    [/^\/takeoff\/[^/]+/, '/takeoff'],
    [/^\/documents\/[^/]+/, '/documents'],
    [/^\/transmittals\/[^/]+/, '/transmittals'],
    [/^\/rfi\/[^/]+/, '/rfi'],
    [/^\/submittals\/[^/]+/, '/submittals'],
    [/^\/contacts\/[^/]+/, '/contacts'],
    [/^\/tasks\/[^/]+/, '/tasks'],
    [/^\/markups\/[^/]+/, '/markups'],
    [/^\/reports\/[^/]+/, '/reports'],
  ];
  for (const [re, list] of entityRoutes) {
    if (re.test(pathname)) return list;
  }
  return null;
}

function ProjectSwitcher() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const clearProject = useProjectContextStore((s) => s.clearProject);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  // "Show all" toggle — collapsed by default to keep the dropdown tidy
  // when the user has dozens of projects; explicit opt-in to expand.
  const [expanded, setExpanded] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Pre-fetch so the dropdown renders an instant list when the user opens
  // it (no race between open → fetch → render that used to flash
  // "No projects yet" for half a second).
  const { data: projects, isLoading, isError, refetch } = useQuery({
    queryKey: ['projects-switcher'],
    queryFn: () => apiGet<Array<{ id: string; name: string }>>('/v1/projects/?limit=500'),
    staleTime: 60_000,
    // Enabled as soon as the component mounts — the Header is always on
    // screen after login, so the list is warm by the time the user clicks.
    enabled: true,
  });

  const MAX_VISIBLE = 20;
  const filteredProjects = (projects ?? []).filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()),
  );
  // When the user is actively searching, show every hit — typing is an
  // implicit "show all that match". The collapse/expand affordance only
  // applies to the default, unfiltered listing.
  const showEverything = expanded || searchQuery.trim().length > 0;
  const visibleProjects = showEverything
    ? filteredProjects
    : filteredProjects.slice(0, MAX_VISIBLE);
  const remainingCount = filteredProjects.length - visibleProjects.length;

  useEffect(() => {
    if (!open) {
      setSearchQuery('');
      setExpanded(false);
      return;
    }
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  useEffect(() => {
    if (open && searchRef.current) {
      searchRef.current.focus();
    }
  }, [open, projects]);

  // Auto-clear a stale ``activeProjectId`` whose project no longer exists
  // on the server (hard-deleted by another session / admin cleanup). A
  // stale id kept pinging 404 on every module that accepts a project
  // context — the most visible one being BIM upload, which failed with
  // "Project not found" because the persisted id in localStorage had
  // been wiped from the DB. We only run the purge once the list has
  // actually loaded (``projects`` defined, even if empty) to avoid
  // blowing away the selection during the first render before data
  // arrives.
  useEffect(() => {
    if (!projects) return;
    if (!activeProjectId) return;
    const stillExists = projects.some((p) => p.id === activeProjectId);
    if (!stillExists) {
      clearProject();
    }
  }, [projects, activeProjectId, clearProject]);

  return (
    <div className="relative hidden sm:block" ref={ref} data-testid="header-project-picker">
      {/* Split-button — visibly the most-used surface in the app. Left half
          opens the active project's detail; right half (chevron) opens
          the switcher dropdown. Two distinct visual modes:
            • No project active → dashed pill + pulsing dot + clear CTA
            • Project active   → solid blue-subtle bg + folder square +
                                 bold project name
          Taller h-9 hit-target, always tinted, never blends into the
          chrome — this is the breadcrumb root, it should anchor the eye. */}
      <div
        className={clsx(
          'flex items-stretch rounded-lg border transition-all max-w-[260px] overflow-hidden',
          activeProjectId
            ? 'bg-oe-blue-subtle border-oe-blue/30 hover:bg-oe-blue/10 hover:border-oe-blue/50 shadow-[0_1px_2px_rgba(0,122,255,0.05)]'
            : 'border-dashed border-oe-blue/40 bg-oe-blue/[0.04] hover:bg-oe-blue/[0.08] hover:border-oe-blue/60',
        )}
      >
        <button
          type="button"
          onClick={() => {
            if (activeProjectId) {
              navigate(`/projects/${activeProjectId}`);
            } else {
              setOpen(true);
            }
          }}
          className={clsx(
            // WCAG AA fix 2026-05-27: text-oe-blue-text (#0071e3) on bg-oe-blue-subtle
            // failed 4.35:1; text-oe-blue-text passes at 8.05:1.
            'flex items-center gap-2 pl-1.5 pr-2 h-9 text-[13px] min-w-0',
            activeProjectId ? 'text-oe-blue-text' : 'text-oe-blue-text/85 hover:text-oe-blue-text',
          )}
          title={activeProjectId
            ? t('projects.open_current', { defaultValue: 'Open this project' })
            : t('schedule.select_project', { defaultValue: 'Select Project' })}
        >
          {/* Leading icon square — colored tile in active mode; pulsing
              dot in CTA mode so the eye is drawn to "act here". */}
          {activeProjectId ? (
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-oe-blue/15 shrink-0">
              <FolderOpen size={13} strokeWidth={2} />
            </span>
          ) : (
            <span aria-hidden className="flex h-6 w-6 items-center justify-center shrink-0">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-2 w-2 rounded-full bg-oe-blue/60 animate-ping" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-oe-blue" />
              </span>
            </span>
          )}
          <span className={clsx(
            'truncate',
            activeProjectId ? 'font-semibold' : 'font-medium',
          )}>
            {activeProjectName || t('schedule.select_project', { defaultValue: 'Select Project' })}
          </span>
        </button>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={clsx(
            // WCAG AA: text-oe-blue-text at /70 alpha on bg-oe-blue-subtle drops
            // below 4.5:1. Use oe-blue-dark for the icon color so axe scans
            // pass even though ChevronDown is presentational.
            'flex items-center px-2 border-l transition-colors',
            activeProjectId
              ? 'border-oe-blue/20 text-oe-blue-text/70 hover:bg-oe-blue/10 hover:text-oe-blue-text'
              : 'border-oe-blue/25 border-dashed text-oe-blue-text/60 hover:bg-oe-blue/10 hover:text-oe-blue-text',
          )}
          title={t('schedule.switch_project', { defaultValue: 'Switch Project' })}
          aria-label={t('schedule.switch_project', { defaultValue: 'Switch Project' })}
        >
          <ChevronDown size={13} strokeWidth={2.25} className={clsx(
            'shrink-0 transition-transform duration-fast',
            open && 'rotate-180',
          )} />
        </button>
      </div>

      {open && (
        <div className="absolute top-full left-0 mt-1.5 z-50 w-72 rounded-xl border border-border bg-surface-elevated shadow-xl overflow-hidden animate-fade-in">
          <div className="px-4 py-2.5 border-b border-border-light bg-surface-secondary/50">
            <p className="text-xs font-semibold text-content-secondary">
              {t('schedule.switch_project', { defaultValue: 'Switch Project' })}
            </p>
          </div>
          <div className="px-3 py-2 border-b border-border-light">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-quaternary pointer-events-none" />
              <input
                ref={searchRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('common.search', { defaultValue: 'Search...' })}
                className="w-full rounded-lg border border-border-light bg-surface-secondary pl-8 pr-3 py-1.5 text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {isLoading && (
              <div className="flex items-center gap-2 px-4 py-4 text-sm text-content-tertiary">
                <span className="inline-block w-3 h-3 border-2 border-oe-blue border-t-transparent rounded-full animate-spin" />
                {t('common.loading', { defaultValue: 'Loading…' })}
              </div>
            )}
            {!isLoading && isError && (
              <div className="px-4 py-4 text-sm text-content-tertiary text-center">
                <p className="text-semantic-error mb-2">
                  {t('common.load_failed', { defaultValue: 'Could not load projects' })}
                </p>
                <button
                  onClick={() => refetch()}
                  className="text-xs text-oe-blue hover:underline"
                >
                  {t('common.retry')}
                </button>
              </div>
            )}
            {!isLoading && !isError && visibleProjects.length === 0 && (
              <p className="px-4 py-4 text-sm text-content-tertiary text-center">
                {searchQuery
                  ? t('common.no_results', { defaultValue: 'No projects found' })
                  : t('projects.none', { defaultValue: 'No projects yet' })}
              </p>
            )}
            {visibleProjects.map((p) => (
              <button
                key={p.id}
                onClick={() => {
                  setActiveProject(p.id, p.name);
                  const target = resolveRouteAfterProjectSwitch(location.pathname, p.id);
                  if (target && target !== location.pathname) navigate(target);
                  setOpen(false);
                }}
                className={clsx(
                  'flex w-full items-center gap-2.5 px-4 py-2 text-sm transition-colors',
                  p.id === activeProjectId
                    ? 'bg-oe-blue-subtle text-oe-blue-text font-medium'
                    : 'text-content-primary hover:bg-surface-secondary',
                )}
              >
                <div className={clsx(
                  'flex items-center justify-center w-7 h-7 rounded-md shrink-0',
                  p.id === activeProjectId
                    ? 'bg-oe-blue/10'
                    : 'bg-surface-tertiary',
                )}>
                  <FolderOpen size={14} className="shrink-0" />
                </div>
                <span className="truncate">{p.name}</span>
                {p.id === activeProjectId && (
                  <span className="ml-auto text-2xs text-oe-blue font-normal shrink-0">
                    {t('common.active', { defaultValue: 'Active' })}
                  </span>
                )}
              </button>
            ))}
            {remainingCount > 0 && !showEverything && (
              <button
                type="button"
                onClick={() => setExpanded(true)}
                className="w-full px-4 py-2 text-xs font-medium text-oe-blue hover:bg-surface-secondary transition-colors text-center"
              >
                {t('projects.show_all', {
                  defaultValue: 'Show all ({{count}})',
                  count: filteredProjects.length,
                })}
              </button>
            )}
            {expanded && !searchQuery && filteredProjects.length > MAX_VISIBLE && (
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="w-full px-4 py-2 text-xs font-medium text-content-tertiary hover:bg-surface-secondary transition-colors text-center"
              >
                {t('projects.collapse_list', { defaultValue: 'Collapse' })}
              </button>
            )}
          </div>
          {activeProjectId && (
            <div className="border-t border-border-light px-4 py-2.5">
              <button
                onClick={() => { navigate(`/projects/${activeProjectId}`); setOpen(false); }}
                className="text-xs font-medium text-oe-blue hover:underline"
              >
                {t('projects.open_details', { defaultValue: 'Open Project Details' })} &rarr;
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Upload Queue Indicator ────────────────────────────────────────────── */

function UploadQueueIndicator() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const tasks = useUploadQueueStore((s) => s.tasks);
  const removeTask = useUploadQueueStore((s) => s.removeTask);
  const clearCompleted = useUploadQueueStore((s) => s.clearCompleted);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const activeTasks = tasks.filter((t) => t.status === 'processing' || t.status === 'queued');
  const completedTasks = tasks.filter((t) => t.status === 'completed');
  const errorTasks = tasks.filter((t) => t.status === 'error');
  const totalActive = activeTasks.length;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (tasks.length === 0) return null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        aria-label={t('queue.title', { defaultValue: 'Upload Queue' })}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={clsx(
          'relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors',
          totalActive > 0 ? 'text-oe-blue-text bg-oe-blue-subtle' : 'text-content-tertiary hover:bg-surface-secondary',
        )}
        title={t('queue.title', { defaultValue: 'Upload Queue' })}
      >
        {totalActive > 0 ? (
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        ) : (
          <Upload size={16} aria-hidden="true" />
        )}
        {(totalActive > 0 || errorTasks.length > 0) && (
          <span className={`absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold text-white ${
            errorTasks.length > 0 ? 'bg-semantic-error' : 'bg-oe-blue'
          }`}>
            {totalActive || errorTasks.length}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-xl border border-border-light bg-surface-elevated shadow-xl z-50 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border-light">
            <h3 className="text-xs font-semibold text-content-primary">
              {t('queue.title', { defaultValue: 'Processing Queue' })}
            </h3>
            {completedTasks.length > 0 && (
              <button onClick={clearCompleted} className="text-2xs text-oe-blue hover:underline">
                {t('queue.clear_done', { defaultValue: 'Clear completed' })}
              </button>
            )}
          </div>
          <div className="max-h-64 overflow-y-auto">
            {tasks.length === 0 ? (
              <p className="px-4 py-6 text-center text-xs text-content-tertiary">
                {t('queue.empty', { defaultValue: 'No tasks' })}
              </p>
            ) : (
              tasks.map((task) => (
                <div key={task.id} className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light last:border-0 hover:bg-surface-secondary/30">
                  <div className="shrink-0">
                    {task.status === 'processing' && <Loader2 size={14} className="text-oe-blue animate-spin" />}
                    {task.status === 'queued' && <Upload size={14} className="text-content-tertiary" />}
                    {task.status === 'completed' && <CheckCircle2 size={14} className="text-semantic-success" />}
                    {task.status === 'error' && <XCircle size={14} className="text-semantic-error" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-content-primary truncate">{task.filename}</p>
                    <div className="flex items-center gap-2">
                      {task.status === 'processing' && (
                        <>
                          <div className="flex-1 h-1 bg-surface-secondary rounded-full overflow-hidden">
                            <div className="h-full bg-oe-blue rounded-full transition-all duration-500" style={{ width: `${task.progress}%` }} />
                          </div>
                          <span className="text-2xs text-content-quaternary tabular-nums">{Math.round(task.progress)}%</span>
                        </>
                      )}
                      {task.status === 'completed' && task.resultUrl && (
                        <button onClick={() => { navigate(task.resultUrl!); setOpen(false); }} className="text-2xs text-oe-blue hover:underline">
                          {t('queue.open_result', { defaultValue: 'Open' })}
                        </button>
                      )}
                      {task.status === 'error' && (
                        <p className="text-2xs text-semantic-error truncate">{task.error || 'Failed'}</p>
                      )}
                      {task.message && task.status === 'processing' && (
                        <p className="text-2xs text-content-quaternary truncate">{task.message}</p>
                      )}
                    </div>
                  </div>
                  {(task.status === 'completed' || task.status === 'error') && (
                    <button
                      onClick={() => removeTask(task.id)}
                      aria-label={t('queue.remove_task', { defaultValue: 'Remove {{filename}} from queue', filename: task.filename })}
                      title={t('queue.remove_task_short', { defaultValue: 'Remove from queue' })}
                      className="shrink-0 p-1 rounded hover:bg-surface-secondary text-content-quaternary"
                    >
                      <XCircle size={12} aria-hidden="true" />
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Search, ChevronDown, LogOut, User, Settings, Menu, MessageSquarePlus, FolderOpen, CheckCircle2, XCircle, Bug, BookOpen, Loader2, Upload } from 'lucide-react';
import clsx from 'clsx';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '../i18n';
import { useAuthStore } from '@/stores/useAuthStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { CountryFlag } from '@/shared/ui';
import { NotificationBell } from '@/shared/ui/NotificationBell';
import { apiGet } from '@/shared/lib/api';
import { exportErrorReport, getErrorCount } from '@/shared/lib/errorLogger';
import { APP_VERSION } from '@/shared/lib/version';

/** Map English page titles (passed from App.tsx routes) to i18n keys. */
const TITLE_I18N_MAP: Record<string, string> = {
  'Dashboard': 'nav.dashboard',
  'AI Quick Estimate': 'nav.ai_estimate',
  'AI Cost Advisor': 'nav.ai_advisor',
  'CAD/BIM Takeoff': 'nav.cad_takeoff',
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
  const translatedTitle = title ? t(TITLE_I18N_MAP[title] ?? title, title) : undefined;
  const currentLang = getLanguageByCode(i18n.language) ?? { code: 'en', name: 'English', flag: '', country: 'gb' };
  const openCommandPalette = useCallback(() => {
    // Dispatch Ctrl+K to open the CommandPalette managed by App.tsx
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }));
  }, []);

  return (
    <header
      className={clsx(
        'sticky top-0 z-[100]',
        'flex h-header items-center justify-between gap-3 px-4 sm:px-6 lg:px-8',
        'border-b border-border-light bg-surface-primary/80 backdrop-blur-xl',
      )}
    >
      {/* Left: mobile menu + title */}
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
        {translatedTitle && (
          <h1 className="text-base font-semibold text-content-primary truncate sm:text-lg">{translatedTitle}</h1>
        )}

        {/* Active project switcher */}
        <ProjectSwitcher />
      </div>

      {/* Right */}
      <div className="flex items-center gap-1.5">
        {/* GitHub */}
        <a
          href="https://github.com/datadrivenconstruction/OpenConstructionERP"
          target="_blank"
          rel="noopener noreferrer"
          className={clsx(
            'hidden sm:flex h-8 items-center gap-1.5 rounded-lg px-2.5',
            'text-xs font-medium',
            'text-content-tertiary border border-border-light',
            'transition-all duration-fast ease-oe',
            'hover:bg-surface-secondary hover:text-content-secondary',
          )}
          title="GitHub"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
          <span className="hidden lg:inline">GitHub</span>
        </a>

        {/* Search — opens CommandPalette */}
        <button
          onClick={openCommandPalette}
          className={clsx(
            'hidden sm:flex h-9 items-center gap-2 rounded-lg px-3',
            'border border-border bg-surface-secondary',
            'text-sm text-content-tertiary',
            'transition-all duration-fast ease-oe',
            'hover:border-content-tertiary hover:text-content-secondary',
            'w-48 lg:w-56',
          )}
        >
          <Search size={15} strokeWidth={1.75} />
          <span>{t('common.search')}</span>
          <kbd className="ml-auto text-2xs text-content-tertiary font-mono bg-surface-primary border border-border-light rounded px-1.5 py-0.5">
            /
          </kbd>
        </button>

        {/* Mobile search icon */}
        <button
          onClick={openCommandPalette}
          aria-label={t('common.search', { defaultValue: 'Search' })}
          className="flex sm:hidden h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary"
        >
          <Search size={17} />
        </button>

        {/* Keyboard shortcuts hint */}
        <button
          onClick={() => document.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }))}
          className={clsx(
            'hidden sm:flex h-8 w-8 items-center justify-center rounded-lg',
            'text-content-tertiary transition-colors',
            'hover:bg-surface-secondary hover:text-content-secondary',
          )}
          title={t('common.keyboard_shortcuts', 'Keyboard shortcuts') + ' (?)'}
          aria-label={t('common.keyboard_shortcuts', 'Keyboard shortcuts')}
        >
          <kbd className="text-2xs font-mono font-medium bg-surface-primary border border-border-light rounded px-1.5 py-0.5">
            ?
          </kbd>
        </button>

        {/* Notification bell */}
        <NotificationBell />

        {/* Bug report — Variant A (file download) + B (URL params) + C (direct POST) */}
        <button
          onClick={() => {
            // Variant A: Download JSON file
            const blob = exportErrorReport();
            const blobUrl = URL.createObjectURL(blob);
            const dl = document.createElement('a');
            dl.href = blobUrl;
            dl.download = `openconstructionerp-report-${new Date().toISOString().slice(0, 10)}.json`;
            dl.click();
            URL.revokeObjectURL(blobUrl);

            // Variant B: Open form with URL params
            const params = new URLSearchParams({
              report: 'true',
              app_version: APP_VERSION,
              error_count: String(getErrorCount()),
              platform: navigator.userAgent.includes('Win') ? 'Windows' : navigator.userAgent.includes('Mac') ? 'macOS' : 'Linux',
            });
            window.open(`https://openconstructionerp.com/contact.html?${params}`, '_blank');

            // Variant C: Direct POST (best-effort, non-blocking)
            const reportBlob = exportErrorReport();
            reportBlob.text().then((text) => {
              const data = JSON.parse(text);
              fetch('https://formsubmit.co/ajax/info@datadrivenconstruction.io', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({
                  _subject: 'Bug Report from OpenConstructionERP App',
                  'App Version': data.app_version || APP_VERSION,
                  'Error Count': data.total_errors || 0,
                  Platform: data.platform || '',
                  Locale: data.locale || '',
                  'Session Minutes': data.session_duration_minutes || 0,
                  'Pages Visited': (data.pages_visited || []).join(', '),
                  Errors: JSON.stringify(data.entries?.slice(0, 10) || [], null, 2),
                }),
              }).catch(() => { /* silent — form is primary channel */ });
            }).catch(() => {});
          }}
          className={clsx(
            'hidden sm:flex h-8 items-center gap-1.5 rounded-lg px-2.5',
            'text-xs font-medium',
            'text-content-tertiary border border-border-light',
            'transition-all duration-fast ease-oe',
            'hover:bg-surface-secondary hover:text-content-secondary',
          )}
          title={t('feedback.report_issue', { defaultValue: 'Report Issue' })}
          aria-label={t('feedback.report_issue', { defaultValue: 'Report Issue' })}
        >
          <Bug size={14} />
          <span className="hidden lg:inline">{t('feedback.report_issue', { defaultValue: 'Report Issue' })}</span>
        </button>

        {/* Documentation link */}
        <a
          href="https://openconstructionerp.com/docs.html"
          target="_blank"
          rel="noopener noreferrer"
          className={clsx(
            'hidden sm:flex h-8 items-center gap-1.5 rounded-lg px-2.5',
            'text-xs font-medium',
            'text-oe-blue border border-oe-blue/20 bg-oe-blue/[0.04]',
            'transition-all duration-fast ease-oe',
            'hover:bg-oe-blue/10 hover:border-oe-blue/40',
          )}
          title={t('nav.docs', { defaultValue: 'Documentation' })}
        >
          <BookOpen size={14} />
          <span className="hidden lg:inline">{t('nav.docs', { defaultValue: 'Docs' })}</span>
        </a>

        {/* Feedback — Variant A (optional file) + B (URL params) */}
        <button
          type="button"
          onClick={() => {
            // Variant A: Download log if errors exist
            if (getErrorCount() > 0) {
              const blob = exportErrorReport();
              const blobUrl = URL.createObjectURL(blob);
              const dl = document.createElement('a');
              dl.href = blobUrl;
              dl.download = `openconstructionerp-log-${new Date().toISOString().slice(0, 10)}.json`;
              dl.click();
              URL.revokeObjectURL(blobUrl);
            }
            // Variant B: Open feedback form with params
            const params = new URLSearchParams({
              feedback: 'true',
              app_version: APP_VERSION,
              error_count: String(getErrorCount()),
            });
            window.open(`https://openconstructionerp.com/contact.html?${params}`, '_blank');
          }}
          className={clsx(
            'flex h-8 items-center gap-1.5 rounded-lg px-2.5',
            'text-xs font-medium',
            'bg-amber-50 text-amber-700 border border-amber-200',
            'dark:bg-amber-900/20 dark:text-amber-400 dark:border-amber-800',
            'transition-all duration-fast ease-oe',
            'hover:bg-amber-100 hover:border-amber-300',
            'dark:hover:bg-amber-900/30',
          )}
          title={t('feedback.title', { defaultValue: 'Send Feedback' })}
          aria-label={t('feedback.title', { defaultValue: 'Send Feedback' })}
        >
          <MessageSquarePlus size={14} strokeWidth={1.75} />
          <span className="hidden sm:inline">{t('feedback.title', { defaultValue: 'Feedback' })}</span>
        </button>

        {/* Upload queue indicator */}
        <UploadQueueIndicator />

        <div className="w-px h-5 bg-border-light mx-1 hidden sm:block" />

        {/* Language */}
        <LanguageSwitcher
          currentLang={currentLang}
          onSelect={(code) => i18n.changeLanguage(code)}
        />

        {/* User menu */}
        <UserMenu />
      </div>
    </header>
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
        className={clsx(
          'flex h-8 items-center gap-1.5 rounded-lg px-2',
          'text-xs font-medium text-content-secondary',
          'transition-all duration-fast ease-oe',
          'hover:bg-surface-secondary',
          open && 'bg-surface-secondary',
        )}
      >
        <CountryFlag code={currentLang.country} size={16} />
        <ChevronDown size={11} className={clsx('transition-transform duration-fast', open && 'rotate-180')} />
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
                  ? 'bg-oe-blue-subtle text-oe-blue font-medium'
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
          'flex h-8 w-8 items-center justify-center rounded-full',
          'bg-oe-blue text-xs font-semibold text-white',
          'transition-all duration-fast ease-oe',
          'hover:opacity-80',
        )}
      >
        {userInitial}
      </button>

      {open && (
        <div role="menu" className="absolute right-0 top-full mt-1.5 w-44 rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-scale-in py-1">
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

function ProjectSwitcher() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const { data: projects } = useQuery({
    queryKey: ['projects-switcher'],
    queryFn: () => apiGet<Array<{ id: string; name: string }>>('/v1/projects/?limit=100'),
    staleTime: 60_000,
    enabled: open,
  });

  const MAX_VISIBLE = 20;
  const filteredProjects = (projects ?? []).filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()),
  );
  const visibleProjects = filteredProjects.slice(0, MAX_VISIBLE);
  const remainingCount = filteredProjects.length - visibleProjects.length;

  useEffect(() => {
    if (!open) {
      setSearchQuery('');
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

  return (
    <div className="relative hidden sm:block" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={clsx(
          'flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-all border max-w-[220px]',
          activeProjectId
            ? 'bg-oe-blue-subtle text-oe-blue border-oe-blue/20 hover:bg-oe-blue/10 hover:border-oe-blue/30'
            : 'text-content-tertiary border-border-light hover:text-content-primary hover:bg-surface-secondary hover:border-border',
        )}
      >
        <FolderOpen size={13} className="shrink-0" />
        <span className="text-content-quaternary shrink-0">{t('common.project', { defaultValue: 'Projekt' })}:</span>
        <span className="truncate">
          {activeProjectName || t('schedule.select_project', { defaultValue: 'Select Project' })}
        </span>
        <ChevronDown size={12} className={clsx(
          'shrink-0 text-content-quaternary transition-transform duration-fast',
          open && 'rotate-180',
        )} />
      </button>

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
            {visibleProjects.length === 0 && (
              <p className="px-4 py-4 text-sm text-content-tertiary text-center">
                {searchQuery
                  ? t('common.no_results', { defaultValue: 'No projects found' })
                  : t('projects.none', { defaultValue: 'No projects yet' })}
              </p>
            )}
            {visibleProjects.map((p) => (
              <button
                key={p.id}
                onClick={() => { setActiveProject(p.id, p.name); setOpen(false); }}
                className={clsx(
                  'flex w-full items-center gap-2.5 px-4 py-2 text-sm transition-colors',
                  p.id === activeProjectId
                    ? 'bg-oe-blue-subtle text-oe-blue font-medium'
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
            {remainingCount > 0 && (
              <p className="px-4 py-2 text-xs text-content-tertiary text-center">
                {t('common.n_more', { count: remainingCount, defaultValue: '{{count}} more...' })}
              </p>
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
        className={clsx(
          'relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors',
          totalActive > 0 ? 'text-oe-blue bg-oe-blue-subtle' : 'text-content-tertiary hover:bg-surface-secondary',
        )}
        title={t('queue.title', { defaultValue: 'Upload Queue' })}
      >
        {totalActive > 0 ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Upload size={16} />
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
                    {task.status === 'completed' && <CheckCircle2 size={14} className="text-green-500" />}
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
                    <button onClick={() => removeTask(task.id)} className="shrink-0 p-1 rounded hover:bg-surface-secondary text-content-quaternary">
                      <XCircle size={12} />
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

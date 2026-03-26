import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Search, ChevronDown, LogOut, User, Settings, Menu, MessageSquarePlus, FolderOpen } from 'lucide-react';
import clsx from 'clsx';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '../i18n';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { CountryFlag } from '@/shared/ui';

/** Map English page titles (passed from App.tsx routes) to i18n keys. */
const TITLE_I18N_MAP: Record<string, string> = {
  'Dashboard': 'nav.dashboard',
  'AI Quick Estimate': 'nav.ai_estimate',
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
  'PDF Takeoff': 'nav.takeoff',
  '4D Schedule': 'nav.schedule',
  '5D Cost Model': 'nav.5d_cost_model',
  'Reports': 'nav.reports',
  'Sustainability': 'nav.sustainability',
  'Tendering': 'nav.tendering',
  'Modules': 'nav.modules',
  'Settings': 'nav.settings',
};

interface HeaderProps {
  title?: string;
  onMenuClick?: () => void;
  onFeedbackClick?: () => void;
}

export function Header({ title, onMenuClick, onFeedbackClick }: HeaderProps) {
  const { t, i18n } = useTranslation();
  const translatedTitle = title ? t(TITLE_I18N_MAP[title] ?? title, title) : undefined;
  const navigate = useNavigate();
  const currentLang = getLanguageByCode(i18n.language);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  // Keyboard shortcut: press / to open search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && !searchOpen && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault();
        setSearchOpen(true);
      }
      if (e.key === 'Escape' && searchOpen) {
        setSearchOpen(false);
        setSearchQuery('');
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [searchOpen]);

  useEffect(() => {
    if (searchOpen && searchRef.current) {
      searchRef.current.focus();
    }
  }, [searchOpen]);

  const handleSearch = useCallback((q: string) => {
    setSearchQuery(q);
    // Navigate to cost database with search query
    if (q.trim().length >= 2) {
      navigate(`/costs?q=${encodeURIComponent(q.trim())}`);
      setSearchOpen(false);
      setSearchQuery('');
    }
  }, [navigate]);

  return (
    <header
      className={clsx(
        'sticky top-0 z-20',
        'flex h-header items-center justify-between gap-3 px-4 sm:px-6 lg:px-8',
        'border-b border-border-light bg-surface-primary/80 backdrop-blur-xl',
      )}
    >
      {/* Left: mobile menu + title */}
      <div className="flex items-center gap-3 min-w-0">
        {onMenuClick && (
          <button
            onClick={onMenuClick}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary lg:hidden"
          >
            <Menu size={20} />
          </button>
        )}
        {translatedTitle && (
          <h1 className="text-base font-semibold text-content-primary truncate sm:text-lg">{translatedTitle}</h1>
        )}

        {/* Active project indicator */}
        {activeProjectId && (
          <button
            onClick={() => navigate(`/projects/${activeProjectId}`)}
            className={clsx(
              'hidden sm:flex items-center gap-1.5 rounded-lg px-2.5 py-1',
              'bg-oe-blue-subtle text-oe-blue',
              'text-xs font-medium',
              'transition-all duration-fast ease-oe',
              'hover:bg-oe-blue/10',
              'max-w-[180px]',
            )}
            title={activeProjectName}
          >
            <FolderOpen size={13} className="shrink-0" />
            <span className="truncate">{activeProjectName || t('projects.title', 'Project')}</span>
          </button>
        )}
      </div>

      {/* Right */}
      <div className="flex items-center gap-1.5">
        {/* Search — overlay style so it doesn't push layout */}
        {searchOpen && (
          <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh]">
            <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={() => { setSearchOpen(false); setSearchQuery(''); }} />
            <div className="relative z-10 w-full max-w-md mx-4 rounded-xl border border-border-light bg-surface-elevated shadow-xl overflow-hidden">
              <div className="flex items-center gap-3 px-4">
                <Search size={18} className="shrink-0 text-content-tertiary" />
                <input
                  ref={searchRef}
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSearch(searchQuery);
                    if (e.key === 'Escape') { setSearchOpen(false); setSearchQuery(''); }
                  }}
                  placeholder={t('common.search_placeholder', { defaultValue: 'Search costs, projects...' })}
                  className="flex-1 h-12 bg-transparent text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none"
                  autoComplete="off"
                />
                <kbd className="text-2xs text-content-tertiary font-mono bg-surface-secondary border border-border-light rounded px-1.5 py-0.5">Esc</kbd>
              </div>
              {searchQuery.trim().length >= 2 && (
                <div className="border-t border-border-light px-4 py-3 text-sm text-content-secondary">
                  {t('common.search_hint', { defaultValue: 'Press Enter to search in Cost Database' })}
                </div>
              )}
            </div>
          </div>
        )}
        {!searchOpen && (
          <button
            onClick={() => setSearchOpen(true)}
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
        )}

        {/* Mobile search icon */}
        {!searchOpen && (
          <button
            onClick={() => setSearchOpen(true)}
            className="flex sm:hidden h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary"
          >
            <Search size={17} />
          </button>
        )}

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

        {/* Feedback */}
        {onFeedbackClick && (
          <button
            onClick={onFeedbackClick}
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
        )}

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
  currentLang: (typeof SUPPORTED_LANGUAGES)[number];
  onSelect: (code: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

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

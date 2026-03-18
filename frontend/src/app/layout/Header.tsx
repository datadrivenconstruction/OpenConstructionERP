import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Search, Bell, ChevronDown, LogOut, User, Settings } from 'lucide-react';
import clsx from 'clsx';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '../i18n';
import { useAuthStore } from '@/stores/useAuthStore';

interface HeaderProps {
  title?: string;
}

export function Header({ title }: HeaderProps) {
  const { t, i18n } = useTranslation();
  const currentLang = getLanguageByCode(i18n.language);

  return (
    <header
      className={clsx(
        'sticky top-0 z-20',
        'flex h-header items-center justify-between gap-4 px-6',
        'border-b border-border-light bg-surface-primary/80 backdrop-blur-xl',
      )}
    >
      <div className="min-w-0">
        {title && (
          <h1 className="text-lg font-semibold text-content-primary truncate">{title}</h1>
        )}
      </div>

      <div className="flex items-center gap-1">
        {/* Search */}
        <button
          className={clsx(
            'flex h-9 items-center gap-2 rounded-lg px-3',
            'border border-border bg-surface-secondary',
            'text-sm text-content-tertiary',
            'transition-all duration-fast ease-oe',
            'hover:border-content-tertiary hover:text-content-secondary',
            'w-56',
          )}
        >
          <Search size={15} strokeWidth={1.75} />
          <span>{t('common.search')}</span>
          <kbd className="ml-auto text-2xs text-content-tertiary font-mono bg-surface-primary border border-border-light rounded px-1.5 py-0.5">
            /
          </kbd>
        </button>

        <div className="w-px h-5 bg-border-light mx-2" />

        {/* Language switcher */}
        <LanguageSwitcher
          currentLang={currentLang}
          onSelect={(code) => i18n.changeLanguage(code)}
        />

        {/* Notifications */}
        <button
          className={clsx(
            'relative flex h-8 w-8 items-center justify-center rounded-lg',
            'text-content-secondary transition-all duration-fast ease-oe',
            'hover:bg-surface-secondary',
          )}
          aria-label="Notifications"
        >
          <Bell size={17} strokeWidth={1.75} />
        </button>

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
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={clsx(
          'flex h-8 items-center gap-1.5 rounded-lg px-2.5',
          'text-xs font-medium text-content-secondary',
          'transition-all duration-fast ease-oe',
          'hover:bg-surface-secondary',
          open && 'bg-surface-secondary',
        )}
      >
        <span className="text-base leading-none">{currentLang.flag}</span>
        <span className="hidden sm:inline">{currentLang.code.toUpperCase()}</span>
        <ChevronDown
          size={12}
          className={clsx('transition-transform duration-fast', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div
          className={clsx(
            'absolute right-0 top-full mt-1.5',
            'w-52 max-h-80 overflow-y-auto',
            'rounded-xl border border-border-light bg-surface-elevated',
            'shadow-lg animate-scale-in',
            'py-1.5',
          )}
        >
          {SUPPORTED_LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              onClick={() => {
                onSelect(lang.code);
                setOpen(false);
              }}
              className={clsx(
                'flex w-full items-center gap-3 px-3 py-2',
                'text-sm transition-colors',
                lang.code === currentLang.code
                  ? 'bg-oe-blue-subtle text-oe-blue font-medium'
                  : 'text-content-primary hover:bg-surface-secondary',
              )}
            >
              <span className="text-base leading-none shrink-0">{lang.flag}</span>
              <span className="truncate">{lang.name}</span>
              <span className="ml-auto text-2xs text-content-tertiary uppercase">
                {lang.code}
              </span>
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
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className={clsx(
          'flex h-8 w-8 items-center justify-center rounded-full',
          'bg-oe-blue text-xs font-semibold text-white',
          'transition-all duration-fast ease-oe',
          'hover:opacity-80 ring-2 ring-transparent hover:ring-oe-blue-subtle',
        )}
      >
        A
      </button>

      {open && (
        <div
          className={clsx(
            'absolute right-0 top-full mt-1.5',
            'w-48 rounded-xl border border-border-light bg-surface-elevated',
            'shadow-lg animate-scale-in',
            'py-1.5',
          )}
        >
          <button
            onClick={() => { setOpen(false); navigate('/settings'); }}
            className="flex w-full items-center gap-3 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <User size={15} className="text-content-tertiary" />
            {t('auth.profile', 'Profile')}
          </button>
          <button
            onClick={() => { setOpen(false); navigate('/settings'); }}
            className="flex w-full items-center gap-3 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <Settings size={15} className="text-content-tertiary" />
            {t('nav.settings', 'Settings')}
          </button>
          <div className="my-1.5 border-t border-border-light" />
          <button
            onClick={() => { logout(); navigate('/login'); setOpen(false); }}
            className="flex w-full items-center gap-3 px-3 py-2 text-sm text-semantic-error hover:bg-semantic-error-bg transition-colors"
          >
            <LogOut size={15} />
            {t('auth.logout', 'Sign out')}
          </button>
        </div>
      )}
    </div>
  );
}

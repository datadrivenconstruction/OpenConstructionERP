import { useTranslation } from 'react-i18next';
import { Search, Bell, Globe } from 'lucide-react';
import clsx from 'clsx';
import { SUPPORTED_LANGUAGES } from '../i18n';

interface HeaderProps {
  title?: string;
}

export function Header({ title }: HeaderProps) {
  const { t, i18n } = useTranslation();

  return (
    <header
      className={clsx(
        'sticky top-0 z-20',
        'flex h-header items-center justify-between gap-4 px-6',
        'border-b border-border-light bg-surface-primary/80 backdrop-blur-xl',
      )}
    >
      {/* Left: Page title or breadcrumb */}
      <div className="min-w-0">
        {title && (
          <h1 className="text-lg font-semibold text-content-primary truncate">{title}</h1>
        )}
      </div>

      {/* Right: Search, language, notifications, avatar */}
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
        <div className="relative">
          <select
            value={i18n.language}
            onChange={(e) => i18n.changeLanguage(e.target.value)}
            className={clsx(
              'h-8 appearance-none rounded-lg pl-8 pr-3',
              'border border-transparent bg-transparent',
              'text-xs font-medium text-content-secondary',
              'transition-all duration-fast ease-oe',
              'hover:bg-surface-secondary cursor-pointer',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue',
            )}
          >
            {SUPPORTED_LANGUAGES.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.name}
              </option>
            ))}
          </select>
          <Globe
            size={14}
            strokeWidth={1.75}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
        </div>

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

        {/* User avatar */}
        <button
          className={clsx(
            'flex h-8 w-8 items-center justify-center rounded-full',
            'bg-oe-blue text-xs font-semibold text-white',
            'transition-all duration-fast ease-oe',
            'hover:opacity-80 ring-2 ring-transparent hover:ring-oe-blue-subtle',
          )}
        >
          A
        </button>
      </div>
    </header>
  );
}

/**
 * "Top bar" card in Settings > General: a show/hide switch for each optional
 * item of the header, with a live preview strip. Everything is shown by
 * default; preferences stay on this device (`shared/lib/topBarPrefs.ts`).
 * Notifications, Help and the account menu are always shown, and the command
 * palette keeps working on Ctrl/Cmd+K when the search box is hidden.
 */
import { useTranslation } from 'react-i18next';
import {
  Bug,
  Compass,
  Gift,
  Globe2,
  Heart,
  Languages,
  Newspaper,
  Puzzle,
  Search,
  Sparkles,
  SunMoon,
  type LucideIcon,
} from 'lucide-react';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { useTopBarPrefs, writeTopBarPrefs, type TopBarItem } from '@/shared/lib/topBarPrefs';

interface Row {
  id: TopBarItem;
  icon: LucideIcon;
  label: string;
}

export function TopBarCard() {
  const { t } = useTranslation();
  const prefs = useTopBarPrefs();

  const rows: Row[] = [
    { id: 'pack', icon: Globe2, label: t('settings.topbar_pack', { defaultValue: 'Regional pack badge' }) },
    { id: 'journey', icon: Compass, label: t('settings.topbar_journey', { defaultValue: 'Project journey' }) },
    { id: 'search', icon: Search, label: t('settings.topbar_search', { defaultValue: 'Search' }) },
    { id: 'askAi', icon: Sparkles, label: t('settings.topbar_ask_ai', { defaultValue: 'Ask AI' }) },
    { id: 'news', icon: Newspaper, label: t('settings.topbar_news', { defaultValue: "What's new" }) },
    { id: 'moduleBuilder', icon: Puzzle, label: t('settings.topbar_module_builder', { defaultValue: 'Module builder' }) },
    { id: 'supportUs', icon: Heart, label: t('settings.topbar_support', { defaultValue: 'Support the project' }) },
    { id: 'subscribe', icon: Gift, label: t('settings.topbar_subscribe', { defaultValue: 'Subscribe' }) },
    { id: 'bugReport', icon: Bug, label: t('settings.topbar_bug', { defaultValue: 'Report a problem' }) },
    { id: 'language', icon: Languages, label: t('settings.topbar_language', { defaultValue: 'Language' }) },
    { id: 'theme', icon: SunMoon, label: t('settings.topbar_theme', { defaultValue: 'Theme' }) },
  ];

  return (
    <Card>
      <CardHeader
        title={t('settings.topbar_title', { defaultValue: 'Top bar' })}
        subtitle={t('settings.topbar_subtitle', {
          defaultValue: 'Choose which items appear in the bar at the top of every page.',
        })}
      />
      <CardContent>
        <div
          data-testid="topbar-preview"
          aria-label={t('settings.topbar_preview', { defaultValue: 'Preview' })}
          role="group"
          className="mb-3 flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border border-border-light bg-surface-secondary/60 px-3 py-2"
        >
          {rows
            .filter((r) => !prefs[r.id])
            .map((r) => (
              <span
                key={r.id}
                data-testid={`topbar-preview-${r.id}`}
                title={r.label}
                className="flex h-7 w-7 items-center justify-center rounded-md bg-surface-primary text-content-secondary shadow-xs"
              >
                <r.icon size={14} strokeWidth={1.75} aria-hidden />
              </span>
            ))}
        </div>
        <ul className="flex flex-col divide-y divide-border-light">
          {rows.map((row) => {
            const shown = !prefs[row.id];
            return (
              <li key={row.id} className="flex items-center justify-between gap-3 py-2">
                <span className="flex items-center gap-2 text-sm text-content-primary">
                  <row.icon size={14} strokeWidth={1.75} aria-hidden className="text-content-tertiary" />
                  {row.label}
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={shown}
                  aria-label={t('settings.topbar_show', {
                    defaultValue: 'Show {{label}} in the top bar',
                    label: row.label,
                  })}
                  data-testid={`topbar-switch-${row.id}`}
                  onClick={() => writeTopBarPrefs({ ...prefs, [row.id]: !prefs[row.id] })}
                  className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-normal ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/40 ${
                    shown ? 'bg-oe-blue' : 'bg-surface-tertiary'
                  }`}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform duration-normal ease-oe ${
                      shown ? 'translate-x-5' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-xs text-content-tertiary">
          {t('settings.topbar_note', {
            defaultValue:
              'Notifications, Help and your account menu are always shown. Search stays available with Ctrl+K (Cmd+K).',
          })}
        </p>
      </CardContent>
    </Card>
  );
}

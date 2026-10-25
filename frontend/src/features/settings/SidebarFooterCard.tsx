// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Sidebar footer" card in Settings > General: a show/hide switch for each
 * button at the foot of the left menu. Everything is shown by default.
 *
 * Settings, Users and About are menu routes, so they use the same per-user
 * hidden list as the "Edit menu" editor; Edit menu, GitHub and Community are
 * kept on this device (`shared/lib/footerPrefs.ts`). Settings can never be
 * lost: the profile menu in the header always links to it.
 */
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { useHiddenModules } from '@/shared/hooks/useHiddenModules';
import { useFooterPrefs, writeFooterPrefs, type FooterItem } from '@/shared/lib/footerPrefs';

interface FooterRow {
  id: string;
  route?: string;
  pref?: FooterItem;
  labelKey: string;
  fallback: string;
}

const ROWS: FooterRow[] = [
  { id: 'settings', route: '/settings', labelKey: 'sidebar.admin_grid.settings', fallback: 'Settings' },
  { id: 'users', route: '/users', labelKey: 'sidebar.admin_grid.users', fallback: 'Users' },
  { id: 'editMenu', pref: 'editMenu', labelKey: 'sidebar.edit_menu', fallback: 'Edit menu' },
  { id: 'about', route: '/about', labelKey: 'sidebar.admin_grid.about', fallback: 'About' },
  { id: 'github', pref: 'github', labelKey: '', fallback: 'GitHub' },
  { id: 'community', pref: 'community', labelKey: 'sidebar.community_title', fallback: 'Community' },
];

export function SidebarFooterCard() {
  const { t } = useTranslation();
  const prefs = useFooterPrefs();
  const { hiddenModules, setHiddenModules } = useHiddenModules();

  const isShown = (row: FooterRow) =>
    row.route ? !hiddenModules.includes(row.route) : !prefs[row.pref!];

  const toggle = (row: FooterRow) => {
    if (row.route) {
      setHiddenModules(
        hiddenModules.includes(row.route)
          ? hiddenModules.filter((r) => r !== row.route)
          : [...hiddenModules, row.route],
      );
      return;
    }
    writeFooterPrefs({ ...prefs, [row.pref!]: !prefs[row.pref!] });
  };

  return (
    <Card>
      <CardHeader
        title={t('settings.footer_title', { defaultValue: 'Sidebar footer' })}
        subtitle={t('settings.footer_subtitle', {
          defaultValue: 'Choose which buttons appear at the bottom of the left menu.',
        })}
      />
      <CardContent>
        <ul className="flex flex-col divide-y divide-border-light">
          {ROWS.map((row) => {
            const shown = isShown(row);
            const label = row.labelKey ? t(row.labelKey, { defaultValue: row.fallback }) : row.fallback;
            return (
              <li key={row.id} className="flex items-center justify-between gap-3 py-2">
                <span className="text-sm text-content-primary">{label}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={shown}
                  aria-label={t('settings.footer_show', {
                    defaultValue: 'Show {{label}} in the sidebar footer',
                    label,
                  })}
                  onClick={() => toggle(row)}
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
          {t('settings.footer_note', {
            defaultValue: 'Settings stays available from the profile menu at the top right, even when its button is hidden.',
          })}
        </p>
      </CardContent>
    </Card>
  );
}

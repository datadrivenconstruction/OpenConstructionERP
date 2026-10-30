// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A pack's modules grouped by work area, each with its one-line description.
 * With `onShow` every row gets a one-click "Show" button: that is the picker
 * for modules the focus hid.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, Loader2 } from 'lucide-react';
import { moduleDisplayNameKey } from '@/features/modules/moduleDisplayName';
import { groupModules } from './focus';

export function FocusModuleList({
  modules,
  onShow,
  testId,
}: {
  modules: readonly string[];
  onShow?: (module: string) => Promise<void> | void;
  testId?: string;
}) {
  const { t } = useTranslation();
  const groups = useMemo(() => groupModules(modules), [modules]);
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const name = (key: string) => t(moduleDisplayNameKey(key), { defaultValue: key.replace(/_/g, ' ') });
  const q = query.trim().toLowerCase();

  return (
    <div data-testid={testId} className="space-y-4">
      {onShow && modules.length > 8 && (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('packs.focus_search', { defaultValue: 'Find a module' })}
          aria-label={t('packs.focus_search', { defaultValue: 'Find a module' })}
          className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm"
        />
      )}
      {groups.map((group) => {
        const rows = group.modules.filter((m) => !q || name(m.key).toLowerCase().includes(q));
        if (!rows.length) return null;
        return (
          <section key={group.id}>
            <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t(group.labelKey, { defaultValue: group.id.replace(/_/g, ' ') })}
            </h4>
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {rows.map((m) => (
                <li key={m.key} className="flex items-center gap-3 px-3 py-2" data-testid={`focus-module-${m.key}`}>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-content-primary">{name(m.key)}</p>
                    {m.descriptionKey && (
                      <p className="line-clamp-1 text-xs text-content-tertiary">{t(m.descriptionKey, { defaultValue: '' })}</p>
                    )}
                  </div>
                  {onShow && (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={async () => {
                        setBusy(m.key);
                        try {
                          await onShow(m.key);
                        } finally {
                          setBusy(null);
                        }
                      }}
                      className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-2.5 text-xs font-medium text-content-primary hover:bg-surface-secondary disabled:opacity-60"
                      data-testid={`focus-show-${m.key}`}
                    >
                      {busy === m.key ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} aria-hidden />}
                      {t('packs.focus_show', { defaultValue: 'Show' })}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > Packages & modules: the installed packages, "Add package", and
 * every module with its own switch. Switching a module off that others need
 * asks first and names them. Nothing here deletes data; a module switched
 * back on shows the same records again.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus } from 'lucide-react';
import { moduleDisplayNameKey } from '@/features/modules/moduleDisplayName';
import { ApiError } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { PACKAGES_QUERY_KEY, removePackage, setModuleEnabled, useSolutionPackages } from './api';
import { PackageCard, PackagePicker } from './PackagePicker';
import { directDependents, enabledModules } from './logic';
import { fmtList } from '@/shared/lib/formatters';

export function PackagesSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isLoading } = useSolutionPackages();
  const [adding, setAdding] = useState(false);
  const [pending, setPending] = useState<{ module: string; dependents: string[] } | null>(null);
  const [filter, setFilter] = useState('');
  const [removing, setRemoving] = useState<{ id: string; hidden: string[] } | null>(null);

  async function previewRemove(id: string) {
    const res = await removePackage(id, false);
    setRemoving({ id, hidden: res.hidden });
  }

  async function confirmRemove() {
    if (!removing) return;
    await removePackage(removing.id, true);
    setRemoving(null);
    await queryClient.invalidateQueries({ queryKey: PACKAGES_QUERY_KEY });
  }

  const enabled = useMemo(() => enabledModules(data?.state), [data]);
  const name = (m: string) => t(moduleDisplayNameKey(m), { defaultValue: m.replace(/_/g, ' ') });

  async function toggle(module: string, on: boolean, force = false) {
    try {
      await setModuleEnabled(module, on, force);
      setPending(null);
      await queryClient.invalidateQueries({ queryKey: PACKAGES_QUERY_KEY });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as { detail?: { dependents?: string[] } } | undefined;
        setPending({ module, dependents: body?.detail?.dependents ?? [] });
      }
    }
  }

  if (isLoading || !data) return <Loader2 className="animate-spin text-oe-blue" aria-label={t('packages.loading')} />;

  const installed = data.packages.filter((p) => data.state.installed.includes(p.id));
  const isOn = (m: string) => (data.state.packaged ? data.state.modules[m] !== false : true);
  const shown = data.modules.filter((m) => !filter || name(m.key).toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-6" data-testid="packages-settings">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-content-primary">{t('packages.installed_title')}</h3>
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-semibold text-oe-blue hover:bg-oe-blue/10"
          >
            <Plus size={14} aria-hidden /> {t('packages.add_package')}
          </button>
        </div>
        {installed.length === 0 && <p className="text-sm text-content-secondary">{t('packages.none_installed')}</p>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {installed.map((p) => (
            <div key={p.id} className="flex flex-col gap-1">
              <PackageCard pkg={p} selected installed onToggle={() => undefined} />
              <button
                type="button"
                data-testid={`package-remove-${p.id}`}
                onClick={() => void previewRemove(p.id)}
                className="self-end text-xs font-semibold text-content-secondary hover:text-semantic-error"
              >
                {t('packages.remove')}
              </button>
            </div>
          ))}
        </div>
        {removing && (
          <div role="alert" className="rounded-lg border border-semantic-warning/50 bg-semantic-warning/10 p-3 text-sm">
            <p>
              {removing.hidden.length
                ? t('packages.remove_warning', {
                    name: t(`packages.${removing.id}.name`),
                    modules: fmtList(removing.hidden.map(name)),
                  })
                : t('packages.remove_none', { name: t(`packages.${removing.id}.name`) })}
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className="rounded-lg bg-oe-blue px-2.5 py-1 text-xs font-semibold text-white"
                onClick={() => void confirmRemove()}
              >
                {t('packages.remove_confirm')}
              </button>
              <button type="button" className="text-xs" onClick={() => setRemoving(null)}>
                {t('packages.cancel')}
              </button>
            </div>
          </div>
        )}
        {adding && (
          <PackagePicker
            packages={data.packages}
            installed={data.state.installed}
            onInstalled={() => setAdding(false)}
            submitLabel={t('packages.add_selected')}
          />
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-base font-semibold text-content-primary">{t('packages.modules_title')}</h3>
        <p className="text-xs text-content-secondary">{t('packages.modules_hint')}</p>
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={t('packages.modules_filter')}
          className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-sm"
        />
        {pending && (
          <div role="alert" className="rounded-lg border border-semantic-warning/50 bg-semantic-warning/10 p-3 text-sm">
            <p>
              {t('packages.dependency_warning', {
                module: name(pending.module),
                dependents: fmtList(pending.dependents.map(name)),
              })}
            </p>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className="rounded-lg bg-oe-blue px-2.5 py-1 text-xs font-semibold text-white"
                onClick={() => void toggle(pending.module, false, true)}
              >
                {t('packages.switch_off_all')}
              </button>
              <button type="button" className="text-xs" onClick={() => setPending(null)}>
                {t('packages.cancel')}
              </button>
            </div>
          </div>
        )}
        <ul className="divide-y divide-border-light rounded-xl border border-border-light">
          {shown.map((m) => {
            const on = isOn(m.key);
            const needs = directDependents(m.key, data.modules, enabled);
            return (
              <li key={m.key} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <div className="text-sm text-content-primary">{name(m.key)}</div>
                  {needs.length > 0 && (
                    <div className="text-2xs text-content-tertiary">
                      {t('packages.needed_by', { modules: fmtList(needs.map(name)) })}
                    </div>
                  )}
                </div>
                <input
                  type="checkbox"
                  role="switch"
                  aria-label={name(m.key)}
                  checked={on}
                  onChange={(e) => void toggle(m.key, e.target.checked)}
                />
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The package grid: one card per package with its drawing, a one-line value
 * and the modules it brings as chips. Multi-select, a summary of what will be
 * installed, then an install view that reports each step as it lands.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Check, Loader2, AlertTriangle } from 'lucide-react';
import { moduleDisplayNameKey } from '@/features/modules/moduleDisplayName';
import {
  installPackages,
  seedPackageDemo,
  PACKAGES_QUERY_KEY,
  type InstallResult,
  type SolutionPackage,
} from './api';
import { applyPackageLayout } from './applyLayout';
import { PackageIllustration } from './PackageIllustration';
import { selectionModules, withPackageDependencies } from './logic';

type StepStatus = 'pending' | 'running' | 'done' | 'error';
interface InstallStep {
  id: string;
  label: string;
  status: StepStatus;
}

function humanise(key: string): string {
  return key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

export function ModuleChip({ module }: { module: string }) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center rounded-md border border-border-light bg-surface-primary px-1.5 py-0.5 text-2xs font-medium text-content-secondary">
      {t(moduleDisplayNameKey(module), { defaultValue: humanise(module) })}
    </span>
  );
}

export function PackageCard({
  pkg,
  selected,
  installed,
  onToggle,
}: {
  pkg: SolutionPackage;
  selected: boolean;
  installed: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={installed}
      aria-pressed={selected || installed}
      data-testid={`package-card-${pkg.id}`}
      className={clsx(
        'group flex h-full flex-col gap-2 rounded-xl border p-3 text-start transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        selected || installed
          ? 'border-oe-blue bg-oe-blue-subtle/60'
          : 'border-border-light bg-surface-elevated hover:border-oe-blue/50',
        installed && 'cursor-default opacity-80',
      )}
    >
      <div className="relative">
        <PackageIllustration id={pkg.id} className="h-20 w-full text-content-primary" />
        {(selected || installed) && (
          <span className="absolute end-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white">
            <Check size={12} aria-hidden />
          </span>
        )}
      </div>
      <div className="text-sm font-semibold text-content-primary">{t(pkg.name_key)}</div>
      <div className="text-xs text-content-secondary">{t(pkg.value_key)}</div>
      <div className="text-2xs text-content-tertiary">{t(pkg.audience_key)}</div>
      <div className="mt-auto flex flex-wrap gap-1 pt-1">
        {pkg.required.map((m) => (
          <ModuleChip key={m} module={m} />
        ))}
      </div>
      {installed && (
        <div className="text-2xs font-semibold text-oe-blue">{t('packages.installed_badge')}</div>
      )}
    </button>
  );
}

export function PackagePicker({
  packages,
  installed = [],
  seedDemos = true,
  onInstalled,
  submitLabel,
}: {
  packages: SolutionPackage[];
  installed?: string[];
  seedDemos?: boolean;
  onInstalled?: (result: InstallResult) => void;
  submitLabel?: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [withDemo, setWithDemo] = useState(seedDemos);
  const [steps, setSteps] = useState<InstallStep[] | null>(null);

  const closure = useMemo(() => withPackageDependencies(packages, selected), [packages, selected]);
  const modules = useMemo(() => selectionModules(packages, selected), [packages, selected]);
  const busy = steps?.some((s) => s.status === 'running') ?? false;

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));

  const mark = (id: string, status: StepStatus) =>
    setSteps((prev) => prev?.map((s) => (s.id === id ? { ...s, status } : s)) ?? prev);

  async function run() {
    const demoPkgs = withDemo
      ? packages.filter((p) => closure.includes(p.id) && !installed.includes(p.id) && p.demo_id)
      : [];
    setSteps([
      { id: 'modules', label: t('packages.progress_modules', { count: modules.length }), status: 'running' },
      ...demoPkgs.map((p) => ({
        id: `demo:${p.id}`,
        label: t('packages.progress_demo', { name: t(p.name_key) }),
        status: 'pending' as StepStatus,
      })),
      { id: 'layout', label: t('packages.progress_layout'), status: 'pending' },
    ]);
    let result: InstallResult;
    try {
      result = await installPackages(selected);
      mark('modules', 'done');
    } catch {
      mark('modules', 'error');
      return;
    }
    for (const p of demoPkgs) {
      mark(`demo:${p.id}`, 'running');
      try {
        await seedPackageDemo(p.id);
        mark(`demo:${p.id}`, 'done');
      } catch {
        mark(`demo:${p.id}`, 'error');
      }
    }
    mark('layout', 'running');
    applyPackageLayout(packages, result.installed);
    mark('layout', 'done');
    await queryClient.invalidateQueries({ queryKey: PACKAGES_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: ['module-preferences'] });
    onInstalled?.(result);
  }

  if (steps) {
    return (
      <ol className="space-y-2" aria-live="polite" data-testid="package-install-progress">
        {steps.map((s) => (
          <li key={s.id} className="flex items-center gap-2 text-sm text-content-primary">
            {s.status === 'running' && <Loader2 size={16} className="animate-spin text-oe-blue" aria-hidden />}
            {s.status === 'done' && <Check size={16} className="text-semantic-success" aria-hidden />}
            {s.status === 'error' && <AlertTriangle size={16} className="text-semantic-error" aria-hidden />}
            {s.status === 'pending' && <span className="h-4 w-4 rounded-full border border-border-light" aria-hidden />}
            <span>{s.label}</span>
          </li>
        ))}
        {steps.some((s) => s.status === 'error') && !busy && (
          <li>
            <button
              type="button"
              className="text-xs font-semibold text-oe-blue"
              onClick={() => setSteps(null)}
            >
              {t('packages.retry')}
            </button>
          </li>
        )}
      </ol>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {packages.map((p) => (
          <PackageCard
            key={p.id}
            pkg={p}
            selected={closure.includes(p.id)}
            installed={installed.includes(p.id)}
            onToggle={() => toggle(p.id)}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border-light bg-surface-elevated/70 p-3">
        <div className="min-w-0 flex-1 text-sm text-content-secondary" data-testid="package-summary">
          {selected.length === 0
            ? t('packages.summary_empty')
            : t('packages.summary', { packages: closure.length, modules: modules.length })}
        </div>
        <label className="flex items-center gap-1.5 text-xs text-content-secondary">
          <input type="checkbox" checked={withDemo} onChange={(e) => setWithDemo(e.target.checked)} />
          {t('packages.with_demo')}
        </label>
        <button
          type="button"
          disabled={selected.length === 0}
          onClick={() => void run()}
          className="rounded-lg bg-oe-blue px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {submitLabel ?? t('packages.install')}
        </button>
      </div>
    </div>
  );
}

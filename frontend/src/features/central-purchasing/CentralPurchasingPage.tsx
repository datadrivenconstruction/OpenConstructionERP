// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Central purchasing register. The central buyer sees every bundle of the company; anyone
 * else sees only the active project's share of the bundles it takes part in.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AlertTriangle, Boxes, FileSignature, Plus, Wallet } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  KpiBand,
  ModuleGuideButton,
  PageHeader,
  SkeletonTable,
  WideModal,
} from '@/shared/ui';
import type { KpiBandItem } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { cpbApi, cpbKeys, type BundleKind, type BundleMode } from './api';
import { centralPurchasingGuide } from './guide';
import { MySharesView } from './MySharesView';
import { KIND_DEFAULTS, MODE_DEFAULTS, STATUS_DEFAULTS, statusVariant } from './status';
import { fromUnits, toUnits } from './shareMath';
import { WorkedExample } from './WorkedExample';

type View = 'bundles' | 'mine';

export function CentralPurchasingPage() {
  const { t } = useTranslation();
  const isBuyer = useHasPermission('central_purchasing.manage');
  const projectId = useActiveProjectId();
  const [view, setView] = useState<View>('bundles');
  const showBundles = isBuyer && view === 'bundles';

  const crumbs = [
    { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
    { label: t('central_purchasing.title', { defaultValue: 'Central purchasing' }) },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={crumbs} />
      <PageHeader
        srTitle={t('central_purchasing.title', { defaultValue: 'Central purchasing' })}
        subtitle={t('central_purchasing.subtitle', {
          defaultValue: 'One tender for several projects: the volume price for the group, a contract and a budget check for each project.',
        })}
        actions={<ModuleGuideButton content={centralPurchasingGuide} />}
      />
      {isBuyer && (
        <div className="flex flex-wrap gap-2" role="group">
          {(['bundles', 'mine'] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                view === v
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-light text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              {v === 'bundles'
                ? t('central_purchasing.view.bundles', { defaultValue: 'All bundles' })
                : t('central_purchasing.view.mine', { defaultValue: "This project's share" })}
            </button>
          ))}
        </div>
      )}
      {showBundles ? <BundleRegister /> : <MySharesView projectId={projectId} />}
    </div>
  );
}

function BundleRegister() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const query = useQuery({ queryKey: cpbKeys.list(), queryFn: cpbApi.list });
  const rows = useMemo(() => query.data ?? [], [query.data]);

  const kpis: KpiBandItem[] = useMemo(() => {
    const open = rows.filter((r) => r.status === 'draft' || r.status === 'published');
    const awarded = rows.filter((r) => r.status === 'awarded');
    const blocked = rows.filter((r) => r.errors > 0 && r.status !== 'awarded').length;
    const currencies = new Set(awarded.map((r) => r.currency));
    const awardedNet = currencies.size === 1 ? fromUnits(awarded.reduce((s, r) => s + (toUnits(r.net) ?? 0n), 0n)) : null;
    return [
      { key: 'open', label: t('central_purchasing.kpi.open', { defaultValue: 'Open bundles' }), value: open.length, icon: Boxes },
      {
        key: 'awarded',
        label: t('central_purchasing.kpi.awarded', { defaultValue: 'Awarded' }),
        value: awarded.length,
        icon: FileSignature,
      },
      {
        key: 'net',
        label: t('central_purchasing.kpi.awarded_value', { defaultValue: 'Awarded value' }),
        value: awardedNet != null ? <MoneyDisplay amount={awardedNet} currency={[...currencies][0]} compact /> : '-',
        icon: Wallet,
      },
      {
        key: 'blocked',
        label: t('central_purchasing.kpi.blocked', { defaultValue: 'Need attention' }),
        value: blocked,
        icon: AlertTriangle,
        tone: blocked ? 'warning' : undefined,
      },
    ];
  }, [rows, t]);

  return (
    <>
      <DismissibleInfo
        storageKey="central_purchasing.how"
        title={t('central_purchasing.intro_title', { defaultValue: 'Buy once for the group, book it per project' })}
      >
        <WorkedExample />
      </DismissibleInfo>
      <KpiBand items={kpis} />
      <div className="flex justify-end">
        <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
          {t('central_purchasing.new_bundle', { defaultValue: 'New bundle' })}
        </Button>
      </div>
      <Card padding="none">
        {query.isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : query.isError ? (
          <ErrorState
            title={t('central_purchasing.error.load', { defaultValue: 'Central purchasing could not be loaded.' })}
            onRetry={() => query.refetch()}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Boxes size={28} />}
            title={t('central_purchasing.empty.bundles', { defaultValue: 'No bundles yet.' })}
            description={t('central_purchasing.empty.bundles_hint', {
              defaultValue: 'Start a bundle for one trade or material, add the projects that need it, then type each project\'s quantities.',
            })}
            action={
              <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
                {t('central_purchasing.new_bundle', { defaultValue: 'New bundle' })}
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-xs text-content-tertiary">
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.bundle', { defaultValue: 'Bundle' })}</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.mode', { defaultValue: 'Award as' })}</th>
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.projects', { defaultValue: 'Projects' })}</th>
                  <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.net', { defaultValue: 'Net' })}</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.checks', { defaultValue: 'Checks' })}</th>
                  <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.status', { defaultValue: 'Status' })}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    tabIndex={0}
                    onClick={() => navigate(`/central-purchasing/${r.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') navigate(`/central-purchasing/${r.id}`);
                    }}
                    className="cursor-pointer border-b border-border-light last:border-0 hover:bg-surface-secondary focus-visible:bg-surface-secondary focus-visible:outline-none"
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-content-primary">{r.title}</div>
                      <div className="text-xs text-content-tertiary">
                        <bdi>{r.code}</bdi> · {t(`central_purchasing.kind.${r.kind}`, { defaultValue: KIND_DEFAULTS[r.kind] ?? r.kind })}
                        {r.vendor_name ? ` · ${r.vendor_name}` : ''}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-content-secondary">
                      {t(`central_purchasing.mode.${r.mode}`, { defaultValue: MODE_DEFAULTS[r.mode] ?? r.mode })}
                    </td>
                    <td className="px-4 py-2.5 text-end tabular-nums">{r.project_count}</td>
                    <td className="px-4 py-2.5 text-end tabular-nums">
                      <MoneyDisplay amount={r.net} currency={r.currency} compact />
                    </td>
                    <td className="px-4 py-2.5">
                      {r.errors > 0 ? (
                        <Badge variant="error" size="sm">
                          {t('central_purchasing.errors_n', { defaultValue: 'Errors: {{n}}', n: r.errors })}
                        </Badge>
                      ) : r.warnings > 0 ? (
                        <Badge variant="warning" size="sm">
                          {t('central_purchasing.warnings_n', { defaultValue: 'Warnings: {{n}}', n: r.warnings })}
                        </Badge>
                      ) : (
                        <Badge variant="success" size="sm">{t('central_purchasing.checks_ok', { defaultValue: 'OK' })}</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge variant={statusVariant(r.status)} size="sm">
                        {t(`central_purchasing.status.${r.status}`, { defaultValue: STATUS_DEFAULTS[r.status] ?? r.status })}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {creating && (
        <CreateBundleModal onClose={() => setCreating(false)} onCreated={(id) => navigate(`/central-purchasing/${id}`)} />
      )}
    </>
  );
}

function CreateBundleModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState<BundleKind>('subcontract');
  const [mode, setMode] = useState<BundleMode>('per_project_contracts');
  const [currency, setCurrency] = useState('');
  const create = useMutation({
    mutationFn: () => cpbApi.create({ title: title.trim(), kind, mode, currency: currency.trim() || undefined }),
    onSuccess: (b) => onCreated(b.id),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      size="md"
      title={t('central_purchasing.new_bundle', { defaultValue: 'New bundle' })}
      busy={create.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" disabled={!title.trim()} loading={create.isPending} onClick={() => create.mutate()}>
            {t('central_purchasing.create', { defaultValue: 'Create bundle' })}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="oe-label">{t('central_purchasing.field.title', { defaultValue: 'What is bought' })}</span>
          <input
            className="oe-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('central_purchasing.field.title_hint', { defaultValue: 'Drywall 2027, three houses' })}
            autoFocus
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="oe-label">{t('central_purchasing.field.kind', { defaultValue: 'Kind' })}</span>
          <select className="oe-input" value={kind} onChange={(e) => setKind(e.target.value as BundleKind)}>
            {(['subcontract', 'supply'] as const).map((k) => (
              <option key={k} value={k}>{t(`central_purchasing.kind.${k}`, { defaultValue: KIND_DEFAULTS[k] })}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="oe-label">{t('central_purchasing.field.currency', { defaultValue: 'Currency' })}</span>
          <input
            className="oe-input uppercase"
            maxLength={3}
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            placeholder={t('central_purchasing.field.currency_hint', { defaultValue: 'From the first project' })}
          />
        </label>
        <fieldset className="flex flex-col gap-2 sm:col-span-2">
          <legend className="oe-label mb-1">{t('central_purchasing.field.mode', { defaultValue: 'Award as' })}</legend>
          {(['per_project_contracts', 'framework_call_off'] as const).map((m) => (
            <label key={m} className="flex items-start gap-2 text-sm">
              <input type="radio" name="cpb-mode" checked={mode === m} onChange={() => setMode(m)} className="mt-1" />
              <span>
                <span className="font-medium text-content-primary">
                  {t(`central_purchasing.mode.${m}`, { defaultValue: MODE_DEFAULTS[m] })}
                </span>
                <span className="block text-xs text-content-tertiary">
                  {m === 'per_project_contracts'
                    ? t('central_purchasing.mode_hint.per_project_contracts', {
                        defaultValue: 'Each project gets its own contract or order for its share. The usual choice.',
                      })
                    : t('central_purchasing.mode_hint.framework_call_off', {
                        defaultValue: 'One agreement per company of the group; projects order against it as work starts.',
                      })}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      </div>
    </WideModal>
  );
}

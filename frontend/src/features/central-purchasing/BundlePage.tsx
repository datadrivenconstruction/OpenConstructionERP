// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One bundle for the central buyer: projects and budgets, the line by project share matrix,
 * the live award split and the award itself. Every amount comes from the server.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Boxes, Building2, CheckCircle2, ListPlus, Plus, Send, Trash2, Wallet } from 'lucide-react';
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
} from '@/shared/ui';
import type { KpiBandItem } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi } from '@/features/projects/api';
import { cpbApi, cpbKeys, type BundleDetail, type CallOffResult, type Finding, type Terms } from './api';
import { centralPurchasingGuide } from './guide';
import { documentPath } from './MySharesView';
import { checkShares, evenShares } from './shareMath';
import { MODE_DEFAULTS, STATUS_DEFAULTS, statusVariant } from './status';
import { WorkedExample } from './WorkedExample';

type Method = 'discount' | 'lump_sum';

export function BundlePage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isBuyer = useHasPermission('central_purchasing.manage');
  const query = useQuery({ queryKey: cpbKeys.detail(id), queryFn: () => cpbApi.get(id), enabled: Boolean(id && isBuyer) });

  const crumbs = [
    { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
    { label: t('central_purchasing.title', { defaultValue: 'Central purchasing' }), to: '/central-purchasing' },
    { label: query.data?.code ?? '' },
  ];

  if (!isBuyer) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb items={crumbs.slice(0, 2)} />
        <Card>
          <EmptyState
            icon={<Boxes size={28} />}
            title={t('central_purchasing.buyer_only', { defaultValue: 'Only the central buyer opens a bundle.' })}
            description={t('central_purchasing.buyer_only_hint', {
              defaultValue: "Your project's share, budget and contract are on the central purchasing page.",
            })}
            action={
              <Button variant="primary" onClick={() => navigate('/central-purchasing')}>
                {t('central_purchasing.view.mine', { defaultValue: "This project's share" })}
              </Button>
            }
          />
        </Card>
      </div>
    );
  }
  if (query.isLoading) return <SkeletonTable rows={6} columns={6} />;
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title={t('central_purchasing.error.load', { defaultValue: 'Central purchasing could not be loaded.' })}
        onRetry={() => query.refetch()}
      />
    );
  }
  return <BundleView bundle={query.data} crumbs={crumbs} />;
}

function BundleView({ bundle, crumbs }: { bundle: BundleDetail; crumbs: { label: string; to?: string }[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const editable = bundle.status === 'draft' || bundle.status === 'published';
  const setDetail = (d: BundleDetail) => {
    qc.setQueryData(cpbKeys.detail(bundle.id), d);
    qc.invalidateQueries({ queryKey: cpbKeys.list() });
  };
  const onError = (err: unknown) => {
    addToast({ type: 'error', title: getErrorMessage(err) });
    qc.invalidateQueries({ queryKey: cpbKeys.detail(bundle.id) });
  };
  const publish = useMutation({ mutationFn: () => cpbApi.publish(bundle.id), onSuccess: setDetail, onError });
  const errors = bundle.findings.filter((f) => f.severity === 'error').length;

  const kpis: KpiBandItem[] = [
    { key: 'projects', label: t('central_purchasing.col.projects', { defaultValue: 'Projects' }), value: bundle.projects.length, icon: Building2 },
    { key: 'lines', label: t('central_purchasing.kpi.lines', { defaultValue: 'Lines' }), value: bundle.lines.length, icon: ListPlus },
    {
      key: 'net',
      label: t('central_purchasing.col.net', { defaultValue: 'Net' }),
      value: <MoneyDisplay amount={bundle.split.net} currency={bundle.currency} compact />,
      icon: Wallet,
    },
    {
      key: 'checks',
      label: t('central_purchasing.col.checks', { defaultValue: 'Checks' }),
      value: errors,
      sub: t('central_purchasing.kpi.errors_sub', { defaultValue: 'errors blocking the award' }),
      icon: errors ? AlertTriangle : CheckCircle2,
      tone: errors ? 'danger' : 'success',
    },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={crumbs} />
      <PageHeader
        srTitle={bundle.title}
        subtitle={`${bundle.code} · ${t(`central_purchasing.mode.${bundle.mode}`, { defaultValue: MODE_DEFAULTS[bundle.mode] ?? bundle.mode })}`}
        actions={
          <>
            <Badge variant={statusVariant(bundle.status)}>
              {t(`central_purchasing.status.${bundle.status}`, { defaultValue: STATUS_DEFAULTS[bundle.status] ?? bundle.status })}
            </Badge>
            {bundle.status === 'draft' && (
              <Button
                variant="secondary"
                icon={<Send size={16} />}
                loading={publish.isPending}
                disabled={errors > 0}
                onClick={() => publish.mutate()}
              >
                {t('central_purchasing.publish', { defaultValue: 'Publish to projects' })}
              </Button>
            )}
            <ModuleGuideButton content={centralPurchasingGuide} />
          </>
        }
      />
      <DismissibleInfo
        storageKey="central_purchasing.bundle_how"
        title={t('central_purchasing.steps_title', { defaultValue: 'Four steps: projects, lines, terms, award' })}
      >
        <WorkedExample />
      </DismissibleInfo>
      <KpiBand items={kpis} />
      <FindingsCard findings={bundle.findings} />
      <ProjectsCard bundle={bundle} editable={editable} onDone={setDetail} onError={onError} />
      <LinesCard bundle={bundle} editable={editable} onDone={setDetail} onError={onError} />
      <AwardCard bundle={bundle} editable={editable} onDone={setDetail} onError={onError} />
      {bundle.mode === 'framework_call_off' && bundle.status === 'awarded' && <CallOffCard bundle={bundle} />}
    </div>
  );
}

interface CardProps {
  bundle: BundleDetail;
  editable: boolean;
  onDone: (d: BundleDetail) => void;
  onError: (err: unknown) => void;
}

function FindingsCard({ findings }: { findings: Finding[] }) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  return (
    <Card>
      <h2 className="mb-2 text-sm font-semibold text-content-primary">
        {t('central_purchasing.findings', { defaultValue: 'Checks' })}
      </h2>
      <ul className="space-y-2 text-sm">
        {findings.map((f, i) => (
          <li key={`${f.rule_id}-${i}`} className="flex items-start gap-2">
            <Badge variant={f.severity === 'error' ? 'error' : 'warning'} size="sm">
              {f.severity === 'error'
                ? t('central_purchasing.severity.error', { defaultValue: 'Error' })
                : t('central_purchasing.severity.warning', { defaultValue: 'Warning' })}
            </Badge>
            <span>
              <span className="text-content-primary">{f.message}</span>
              {f.suggestion && <span className="block text-xs text-content-tertiary">{f.suggestion}</span>}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ProjectsCard({ bundle, editable, onDone, onError }: CardProps) {
  const { t } = useTranslation();
  const [pick, setPick] = useState('');
  const projects = useQuery({ queryKey: ['projects', 'list'], queryFn: projectsApi.list, enabled: editable });
  const taken = new Set(bundle.projects.map((p) => p.project_id));
  const options = (projects.data ?? []).filter((p) => !taken.has(p.id));
  const add = useMutation({
    mutationFn: (projectId: string) => cpbApi.addProject(bundle.id, projectId),
    onSuccess: (d) => {
      setPick('');
      onDone(d);
    },
    onError,
  });
  const budget = useMutation({
    mutationFn: ({ bpId, value }: { bpId: string; value: string | null }) => cpbApi.updateProject(bundle.id, bpId, value),
    onSuccess: onDone,
    onError,
  });
  const remove = useMutation({ mutationFn: (bpId: string) => cpbApi.removeProject(bundle.id, bpId), onSuccess: onDone, onError });

  return (
    <Card padding="none">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light px-4 py-3">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('central_purchasing.step.projects', { defaultValue: '1. Projects and budgets' })}
        </h2>
        {editable && (
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="cpb-add-project">
              {t('central_purchasing.add_project', { defaultValue: 'Add project' })}
            </label>
            <select id="cpb-add-project" className="oe-input w-56 text-sm" value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">{t('central_purchasing.pick_project', { defaultValue: 'Choose a project' })}</option>
              {options.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <Button size="sm" icon={<Plus size={14} />} disabled={!pick} loading={add.isPending} onClick={() => add.mutate(pick)}>
              {t('central_purchasing.add_project', { defaultValue: 'Add project' })}
            </Button>
          </div>
        )}
      </div>
      {bundle.projects.length === 0 ? (
        <EmptyState
          icon={<Building2 size={28} />}
          title={t('central_purchasing.empty.projects', { defaultValue: 'No projects in this bundle yet.' })}
          description={t('central_purchasing.empty.projects_hint', {
            defaultValue: 'Choose the projects that need this trade. Each brings its company and its budget from its cost lines.',
          })}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-xs text-content-tertiary">
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.project', { defaultValue: 'Project' })}</th>
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.entity', { defaultValue: 'Buying company' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.budget', { defaultValue: 'Budget' })}</th>
                <th scope="col" className="w-10 px-2 py-2"><span className="sr-only">{t('common.actions', { defaultValue: 'Actions' })}</span></th>
              </tr>
            </thead>
            <tbody>
              {bundle.projects.map((p) => (
                <tr key={p.id} className="border-b border-border-light last:border-0">
                  <td className="px-4 py-2">
                    <div className="text-content-primary">{p.name}</div>
                    {p.project_code && <div className="text-xs text-content-tertiary"><bdi>{p.project_code}</bdi></div>}
                  </td>
                  <td className="px-4 py-2 text-content-secondary">
                    {p.legal_entity_name ?? (
                      <span className="text-content-tertiary">{t('central_purchasing.no_entity', { defaultValue: 'Not set on the project' })}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-end">
                    <input
                      key={`${p.id}-${p.budget_amount ?? ''}`}
                      aria-label={t('central_purchasing.col.budget', { defaultValue: 'Budget' })}
                      className="oe-input w-36 text-end tabular-nums"
                      inputMode="decimal"
                      disabled={!editable}
                      defaultValue={p.budget_amount ?? ''}
                      placeholder={p.budget_from_lines ?? t('central_purchasing.budget_none', { defaultValue: 'No budget' })}
                      onBlur={(e) => {
                        const value = e.target.value.trim();
                        if (value === (p.budget_amount ?? '')) return;
                        budget.mutate({ bpId: p.id, value: value || null });
                      }}
                    />
                    {p.budget_amount == null && p.budget_from_lines != null && (
                      <div className="text-xs text-content-tertiary">
                        {t('central_purchasing.budget_from_lines', { defaultValue: 'From the planned cost lines' })}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {editable && (
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Trash2 size={14} />}
                        aria-label={t('central_purchasing.remove_project', { defaultValue: 'Remove project' })}
                        onClick={() => remove.mutate(p.id)}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const EMPTY_LINE = { code: '', description: '', unit: '', quantity: '', unit_rate: '', cost_code: '' };

function LinesCard({ bundle, editable, onDone, onError }: CardProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(EMPTY_LINE);
  const add = useMutation({
    mutationFn: () =>
      cpbApi.addLine(bundle.id, {
        code: draft.code.trim(),
        description: draft.description.trim(),
        unit: draft.unit.trim(),
        quantity: draft.quantity.trim(),
        unit_rate: draft.unit_rate.trim() || null,
        cost_code: draft.cost_code.trim() || null,
      }),
    onSuccess: (d) => {
      setDraft(EMPTY_LINE);
      onDone(d);
    },
    onError,
  });
  const update = useMutation({
    mutationFn: ({ lineId, body }: { lineId: string; body: Parameters<typeof cpbApi.updateLine>[2] }) =>
      cpbApi.updateLine(bundle.id, lineId, body),
    onSuccess: onDone,
    onError,
  });
  const remove = useMutation({ mutationFn: (lineId: string) => cpbApi.removeLine(bundle.id, lineId), onSuccess: onDone, onError });
  const setShare = (lineId: string, bpId: string, quantity: string | null) =>
    update.mutate({ lineId, body: { shares: [{ bundle_project_id: bpId, quantity }] } });

  const field = (key: keyof typeof EMPTY_LINE, label: string, className: string) => (
    <input
      aria-label={label}
      placeholder={label}
      className={`oe-input text-sm ${className}`}
      value={draft[key]}
      inputMode={key === 'quantity' || key === 'unit_rate' ? 'decimal' : undefined}
      onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
    />
  );

  return (
    <Card padding="none">
      <div className="border-b border-border-light px-4 py-3">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('central_purchasing.step.lines', { defaultValue: '2. Lines and each project\'s share' })}
        </h2>
        <p className="text-xs text-content-tertiary">
          {t('central_purchasing.step.lines_hint', {
            defaultValue: 'Type each project\'s quantity under the line. A blank cell is not zero: type 0 when a project takes none.',
          })}
        </p>
      </div>
      {bundle.lines.length === 0 && (
        <EmptyState
          icon={<ListPlus size={28} />}
          title={t('central_purchasing.empty.lines', { defaultValue: 'No lines yet.' })}
          description={t('central_purchasing.empty.lines_hint', {
            defaultValue: 'Add the first line below: code, description, unit and the total quantity for all projects.',
          })}
        />
      )}
      {bundle.lines.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-xs text-content-tertiary">
                <th scope="col" className="px-3 py-2 text-start font-medium">{t('central_purchasing.col.line', { defaultValue: 'Line' })}</th>
                <th scope="col" className="px-3 py-2 text-end font-medium">{t('central_purchasing.col.quantity', { defaultValue: 'Quantity' })}</th>
                <th scope="col" className="px-3 py-2 text-end font-medium">{t('central_purchasing.col.rate', { defaultValue: 'Rate' })}</th>
                {bundle.projects.map((p) => (
                  <th key={p.id} scope="col" className="px-3 py-2 text-end font-medium">{p.name}</th>
                ))}
                <th scope="col" className="px-3 py-2 text-start font-medium">{t('central_purchasing.col.adds_up', { defaultValue: 'Adds up' })}</th>
                <th scope="col" className="w-10 px-2 py-2"><span className="sr-only">{t('common.actions', { defaultValue: 'Actions' })}</span></th>
              </tr>
            </thead>
            <tbody>
              {bundle.lines.map((ln) => {
                const byProject = new Map(ln.shares.map((s) => [s.bundle_project_id, s]));
                const check = checkShares(ln.quantity, bundle.projects.map((p) => byProject.get(p.id)?.quantity ?? null));
                return (
                  <tr key={ln.id} className="border-b border-border-light align-top last:border-0">
                    <td className="px-3 py-2">
                      <div className="text-content-primary"><bdi>{ln.code}</bdi> {ln.description}</div>
                      {ln.cost_code && (
                        <div className="text-xs text-content-tertiary">
                          {t('central_purchasing.cost_code', { defaultValue: 'Cost code {{code}}', code: ln.cost_code })}
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-end tabular-nums">{ln.quantity} {ln.unit}</td>
                    <td className="px-3 py-2 text-end">
                      <input
                        key={`${ln.id}-rate-${ln.unit_rate ?? ''}`}
                        aria-label={t('central_purchasing.col.rate', { defaultValue: 'Rate' })}
                        className="oe-input w-24 text-end tabular-nums"
                        inputMode="decimal"
                        disabled={!editable}
                        defaultValue={ln.unit_rate ?? ''}
                        onBlur={(e) => {
                          const value = e.target.value.trim();
                          if (value === (ln.unit_rate ?? '')) return;
                          update.mutate({ lineId: ln.id, body: value ? { unit_rate: value } : { clear_rate: true } });
                        }}
                      />
                    </td>
                    {bundle.projects.map((p) => {
                      const share = byProject.get(p.id);
                      return (
                        <td key={p.id} className="px-3 py-2 text-end">
                          <input
                            key={`${ln.id}-${p.id}-${share?.quantity ?? ''}`}
                            aria-label={`${ln.code} ${p.name}`}
                            className={`oe-input w-24 text-end tabular-nums ${share?.quantity == null ? 'border-semantic-warning' : ''}`}
                            inputMode="decimal"
                            disabled={!editable}
                            defaultValue={share?.quantity ?? ''}
                            onBlur={(e) => {
                              const value = e.target.value.trim();
                              if (value === (share?.quantity ?? '')) return;
                              setShare(ln.id, p.id, value || null);
                            }}
                          />
                          {share?.quantity != null && !share.cost_line_id && (
                            <div className="text-xs text-semantic-warning">
                              {t('central_purchasing.no_cost_line', { defaultValue: 'No cost line' })}
                            </div>
                          )}
                        </td>
                      );
                    })}
                    <td className="whitespace-nowrap px-3 py-2">
                      {check.ok ? (
                        <Badge variant="success" size="sm">{t('central_purchasing.checks_ok', { defaultValue: 'OK' })}</Badge>
                      ) : (
                        <div className="space-y-1">
                          <Badge variant="warning" size="sm">
                            {check.blanks > 0
                              ? t('central_purchasing.blanks', { defaultValue: 'Blank: {{n}}', n: check.blanks })
                              : t('central_purchasing.remaining', { defaultValue: 'Left: {{qty}}', qty: check.remaining })}
                          </Badge>
                          {editable && bundle.projects.length > 1 && (
                            <button
                              type="button"
                              className="block text-xs text-oe-blue hover:underline"
                              onClick={() => {
                                const parts = evenShares(ln.quantity, bundle.projects.length);
                                update.mutate({
                                  lineId: ln.id,
                                  body: { shares: bundle.projects.map((p, i) => ({ bundle_project_id: p.id, quantity: parts[i] ?? '0' })) },
                                });
                              }}
                            >
                              {t('central_purchasing.split_evenly', { defaultValue: 'Split evenly' })}
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {editable && (
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={14} />}
                          aria-label={t('central_purchasing.remove_line', { defaultValue: 'Remove line' })}
                          onClick={() => remove.mutate(ln.id)}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {editable && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border-light px-4 py-3">
          {field('code', t('central_purchasing.field.code', { defaultValue: 'Code' }), 'w-20')}
          {field('description', t('central_purchasing.field.description', { defaultValue: 'Description' }), 'w-56')}
          {field('unit', t('central_purchasing.field.unit', { defaultValue: 'Unit' }), 'w-16')}
          {field('quantity', t('central_purchasing.field.quantity', { defaultValue: 'Total quantity' }), 'w-28')}
          {field('unit_rate', t('central_purchasing.field.rate', { defaultValue: 'Rate (optional)' }), 'w-28')}
          {field('cost_code', t('central_purchasing.field.cost_code', { defaultValue: 'Cost code' }), 'w-28')}
          <Button
            size="sm"
            icon={<Plus size={14} />}
            disabled={!draft.quantity.trim() || (!draft.code.trim() && !draft.description.trim())}
            loading={add.isPending}
            onClick={() => add.mutate()}
          >
            {t('central_purchasing.add_line', { defaultValue: 'Add line' })}
          </Button>
        </div>
      )}
    </Card>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setOut(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return out;
}

function AwardCard({ bundle, editable, onDone, onError }: CardProps) {
  const { t } = useTranslation();
  const mayAward = useHasPermission('central_purchasing.award');
  const [vendor, setVendor] = useState(bundle.vendor_name);
  const [method, setMethod] = useState<Method>(bundle.lump_sum != null ? 'lump_sum' : 'discount');
  const [amount, setAmount] = useState(bundle.lump_sum ?? bundle.discount_pct ?? '');
  const terms: Terms = useMemo(() => {
    const value = amount.trim().replace(',', '.');
    const ok = /^\d+(\.\d+)?$/.test(value);
    return {
      discount_pct: method === 'discount' && ok ? value : null,
      lump_sum: method === 'lump_sum' && ok ? value : null,
    };
  }, [amount, method]);
  const debounced = useDebounced(terms, 400);
  const priced = bundle.lines.length > 0 && bundle.lines.every((l) => l.unit_rate != null);
  const preview = useQuery({
    queryKey: [...cpbKeys.preview(bundle.id, debounced), bundle.lines, bundle.projects],
    queryFn: () => cpbApi.preview(bundle.id, debounced),
    enabled: editable && priced && bundle.projects.length > 0,
  });
  const shown = editable ? (preview.data ?? bundle) : bundle;
  const blocking = shown.findings.filter((f) => f.severity === 'error').length;
  const award = useMutation({
    mutationFn: () => cpbApi.award(bundle.id, { vendor_name: vendor.trim(), ...terms }),
    onSuccess: onDone,
    onError,
  });
  const docWord =
    bundle.mode === 'framework_call_off'
      ? t('central_purchasing.award_docs.framework', { defaultValue: 'one framework agreement per company' })
      : bundle.kind === 'supply'
        ? t('central_purchasing.award_docs.po', { defaultValue: 'one draft purchase order per project' })
        : t('central_purchasing.award_docs.contract', { defaultValue: 'one draft contract per project' });

  return (
    <Card padding="none">
      <div className="border-b border-border-light px-4 py-3">
        <h2 className="text-sm font-semibold text-content-primary">
          {editable
            ? t('central_purchasing.step.award', { defaultValue: '3. Terms and award split' })
            : t('central_purchasing.step.awarded', { defaultValue: 'Award split and documents' })}
        </h2>
      </div>
      {editable && (
        <div className="flex flex-wrap items-end gap-3 px-4 py-3">
          <label className="flex flex-col gap-1">
            <span className="oe-label">{t('central_purchasing.field.vendor', { defaultValue: 'Awarded to' })}</span>
            <input className="oe-input w-64" value={vendor} onChange={(e) => setVendor(e.target.value)} />
          </label>
          <fieldset className="flex items-center gap-3">
            <legend className="sr-only">{t('central_purchasing.field.method', { defaultValue: 'Price terms' })}</legend>
            {(['discount', 'lump_sum'] as const).map((m) => (
              <label key={m} className="flex items-center gap-1 text-sm">
                <input type="radio" name="cpb-method" checked={method === m} onChange={() => setMethod(m)} />
                {m === 'discount'
                  ? t('central_purchasing.method.discount', { defaultValue: 'Discount, %' })
                  : t('central_purchasing.method.lump_sum', { defaultValue: 'Agreed lump sum' })}
              </label>
            ))}
          </fieldset>
          <label className="flex flex-col gap-1">
            <span className="sr-only">{t('central_purchasing.field.amount', { defaultValue: 'Value' })}</span>
            <input
              className="oe-input w-36 text-end tabular-nums"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={method === 'discount' ? '2' : '52000.00'}
            />
          </label>
        </div>
      )}
      {!priced || bundle.projects.length === 0 ? (
        <EmptyState
          icon={<Wallet size={28} />}
          title={t('central_purchasing.empty.split', { defaultValue: 'The split appears once every line has a rate.' })}
          description={t('central_purchasing.empty.split_hint', {
            defaultValue: 'Type the awarded rate on each line above; each project\'s amount and budget check show here as you type.',
          })}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-y border-border-light text-xs text-content-tertiary">
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.project', { defaultValue: 'Project' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.gross', { defaultValue: 'At rates' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.discount', { defaultValue: 'Discount' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.net', { defaultValue: 'Net' })}</th>
                <th scope="col" className="px-4 py-2 text-end font-medium">{t('central_purchasing.col.budget', { defaultValue: 'Budget' })}</th>
                <th scope="col" className="px-4 py-2 text-start font-medium">{t('central_purchasing.col.document', { defaultValue: 'Document' })}</th>
              </tr>
            </thead>
            <tbody>
              {shown.split.rows.map((r) => (
                <tr key={r.bundle_project_id} className="border-b border-border-light">
                  <td className="px-4 py-2">
                    <div className="text-content-primary">{r.project_name}</div>
                    {r.legal_entity_name && <div className="text-xs text-content-tertiary">{r.legal_entity_name}</div>}
                  </td>
                  <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={r.gross} currency={bundle.currency} /></td>
                  <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={r.discount} currency={bundle.currency} /></td>
                  <td className="px-4 py-2 text-end font-medium tabular-nums"><MoneyDisplay amount={r.net} currency={bundle.currency} /></td>
                  <td className="px-4 py-2 text-end tabular-nums">
                    {r.budget != null ? <MoneyDisplay amount={r.budget} currency={bundle.currency} /> : '-'}
                    {r.over_budget && r.budget_delta != null && (
                      <div className="text-xs text-semantic-warning">
                        {t('central_purchasing.over_by', { defaultValue: 'Over by' })}{' '}
                        <MoneyDisplay amount={r.budget_delta} currency={bundle.currency} />
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {r.document?.id ? (
                      <Link to={documentPath(r.document)} className="text-oe-blue hover:underline">
                        <bdi>{r.document.code || r.document.id}</bdi>
                      </Link>
                    ) : (
                      <span className="text-content-tertiary">-</span>
                    )}
                  </td>
                </tr>
              ))}
              <tr className="font-medium">
                <td className="px-4 py-2">{t('central_purchasing.total', { defaultValue: 'Total' })}</td>
                <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={shown.split.gross} currency={bundle.currency} /></td>
                <td className="px-4 py-2" />
                <td className="px-4 py-2 text-end tabular-nums"><MoneyDisplay amount={shown.split.net} currency={bundle.currency} /></td>
                <td className="px-4 py-2" colSpan={2}>
                  {shown.split.reconciles ? (
                    <Badge variant="success" size="sm">{t('central_purchasing.reconciles', { defaultValue: 'Adds up to the award' })}</Badge>
                  ) : (
                    <Badge variant="error" size="sm">{t('central_purchasing.unreconciled', { defaultValue: 'Does not add up' })}</Badge>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {editable && mayAward && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-light px-4 py-3">
          <p className="text-xs text-content-tertiary">
            {t('central_purchasing.award_note', {
              defaultValue: 'Award drafts {{docs}}. Nothing is signed until each draft is approved.',
              docs: docWord,
            })}
          </p>
          <Button
            variant="primary"
            disabled={!priced || !vendor.trim() || blocking > 0 || bundle.projects.length === 0}
            loading={award.isPending}
            onClick={() => award.mutate()}
          >
            {t('central_purchasing.award', { defaultValue: 'Award' })}
          </Button>
        </div>
      )}
      {!editable && bundle.agreements.length > 0 && (
        <div className="border-t border-border-light px-4 py-3 text-sm">
          <span className="text-content-tertiary">{t('central_purchasing.agreements', { defaultValue: 'Framework agreements' })}: </span>
          {bundle.agreements.map((a) => (
            <Link key={a.id ?? a.code} to={documentPath(a)} className="me-3 text-oe-blue hover:underline">
              <bdi>{a.code}</bdi>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

function CallOffCard({ bundle }: { bundle: BundleDetail }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [projectId, setProjectId] = useState(bundle.projects[0]?.project_id ?? '');
  const [qty, setQty] = useState<Record<string, string>>({});
  const [result, setResult] = useState<CallOffResult | null>(null);
  const lines = bundle.lines.filter((l) => (qty[l.id] ?? '').trim()).map((l) => ({ line_id: l.id, quantity: qty[l.id]!.trim() }));
  const callOff = useMutation({
    mutationFn: () => cpbApi.callOff(bundle.id, { project_id: projectId, lines }),
    onSuccess: (r) => {
      setResult(r);
      setQty({});
      qc.invalidateQueries({ queryKey: cpbKeys.all });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <Card>
      <h2 className="text-sm font-semibold text-content-primary">
        {t('central_purchasing.step.call_off', { defaultValue: '4. Call off for a project' })}
      </h2>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('central_purchasing.call_off_hint', {
          defaultValue: 'A call-off orders part of a project\'s share at the agreed rates and is booked on that project only.',
        })}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="oe-label">{t('central_purchasing.col.project', { defaultValue: 'Project' })}</span>
          <select className="oe-input w-56" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            {bundle.projects.map((p) => (
              <option key={p.id} value={p.project_id}>{p.name}</option>
            ))}
          </select>
        </label>
        {bundle.lines.map((l) => (
          <label key={l.id} className="flex flex-col gap-1">
            <span className="oe-label"><bdi>{l.code}</bdi> ({l.unit})</span>
            <input
              className="oe-input w-28 text-end tabular-nums"
              inputMode="decimal"
              value={qty[l.id] ?? ''}
              onChange={(e) => setQty((q) => ({ ...q, [l.id]: e.target.value }))}
            />
          </label>
        ))}
        <Button variant="primary" disabled={!projectId || lines.length === 0} loading={callOff.isPending} onClick={() => callOff.mutate()}>
          {t('central_purchasing.call_off', { defaultValue: 'Create call-off' })}
        </Button>
      </div>
      {result && (
        <div className="mt-3 space-y-2 text-sm">
          <p>
            {t('central_purchasing.call_off_done', { defaultValue: 'Draft created:' })}{' '}
            <Link to={documentPath(result.document)} className="text-oe-blue hover:underline"><bdi>{result.document.code}</bdi></Link>{' '}
            <MoneyDisplay amount={result.total} currency={bundle.currency} />
          </p>
          <FindingsCard findings={result.findings} />
        </div>
      )}
    </Card>
  );
}

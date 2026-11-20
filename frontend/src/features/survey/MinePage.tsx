// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Mine survey (/survey/mine): one period, one line per mining unit. The actual
 * is the cut of a Volumes calculation and is never typed; only a confirmed
 * actual can be added to the progress claim (survey.confirm).
 */

import { Fragment, Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, FileDown, Gauge, Layers, Mountain, Pickaxe, Plus, Scale, Send, Truck, Upload } from 'lucide-react';
import { Badge, Breadcrumb, Button, Card, CollapsibleSection, DismissibleInfo, EmptyState, ErrorState, KpiBand, Skeleton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui/ModuleGuideButton';
import { downloadWithAuth, getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useToastStore } from '@/stores/useToastStore';
import { getProjectCrs } from './api';
import { crsChipText } from './crsPicker';
import { useOpenSurveyDemo } from './useOpenSurveyDemo';
import { formatM3 } from './volumesApi';
import { AddToClaimDialog, AddUnitDialog, ComputeActualDialog, NewPeriodDialog, TruckLoadsDialog } from './MineDialogs';
import { mineGuide } from './mineGuide';
import {
  confirmActual,
  deleteEntry,
  formatPct,
  formatSigned,
  formatTonnes,
  getPeriod,
  listPeriods,
  outsideBand,
  parseNumber,
  periodReportUrl,
  periodTitle,
  updateEntry,
  type MineEntry,
} from './mineApi';
import { ViewOnlyNote, useSurveyAccess } from './useSurveyAccess';
import { MineBlastCard } from './MineBlastCard';
import { MineEntryDepth } from './MineEntryDepth';

const MinePlanView = lazy(() => import('@/features/survey-plan/screens/MinePlanView'));
function AdvanceCell({ entry, lang, onSave }: { entry: MineEntry; lang: string; onSave: (v: number | null) => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState(entry.actual_advance_m == null ? '' : String(entry.actual_advance_m));
  useEffect(() => setValue(entry.actual_advance_m == null ? '' : String(entry.actual_advance_m)), [entry.actual_advance_m]);
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs" data-testid="mine-advance">
      <span>
        {t('mine.field.plan_advance', { defaultValue: 'Plan advance (m)' })}: <bdi dir="ltr">{formatM3(entry.plan_advance_m, lang)}</bdi>
      </span>
      <label className="inline-flex items-center gap-1">
        {t('mine.field.actual_advance', { defaultValue: 'Actual advance (m)' })}
        <input
          className="oe-input w-24"
          inputMode="decimal"
          value={value}
          disabled={entry.claim_entry_id != null}
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => {
            const n = value.trim() ? parseNumber(value) : null;
            if (n !== entry.actual_advance_m && (value.trim() === '' || n != null)) onSave(n);
          }}
        />
      </label>
      {entry.advance_pct != null && <bdi dir="ltr">{formatPct(entry.advance_pct, lang)}</bdi>}
    </div>
  );
}

export default function MinePage() {
  const { t, i18n } = useTranslation();
  const { canWrite } = useSurveyAccess();
  const lang = i18n.language;
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const demo = useOpenSurveyDemo('/survey/mine');
  const [periodId, setPeriodId] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [unitOpen, setUnitOpen] = useState(false);
  const [computeFor, setComputeFor] = useState<MineEntry | null>(null);
  const [trucksFor, setTrucksFor] = useState<MineEntry | null>(null);
  const [claimFor, setClaimFor] = useState<MineEntry | null>(null);

  const enabled = !!projectId;
  const crs = useQuery({ queryKey: ['survey', 'crs', projectId], queryFn: () => getProjectCrs(projectId!), enabled });
  const periods = useQuery({ queryKey: ['mine', 'periods', projectId], queryFn: () => listPeriods(projectId!), enabled });
  const list = periods.data ?? [];
  const activeId = useMemo(() => (list.some((p) => p.id === periodId) ? periodId : (list[0]?.id ?? null)), [list, periodId]);
  const detail = useQuery({
    queryKey: ['mine', 'period', activeId, lang],
    queryFn: () => getPeriod(activeId!, lang),
    enabled: !!activeId,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['mine'] });
    qc.invalidateQueries({ queryKey: ['volumes'] });
  };
  const fail = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const confirm = useMutation({ mutationFn: (e: MineEntry) => confirmActual(e.id, [], lang), onSuccess: refresh, onError: fail });
  const remove = useMutation({ mutationFn: (id: string) => deleteEntry(id), onSuccess: refresh, onError: fail });
  const advance = useMutation({
    mutationFn: ({ e, v }: { e: MineEntry; v: number | null }) => updateEntry(e.id, { actual_advance_m: v }, lang),
    onSuccess: refresh,
    onError: fail,
  });

  const title = t('mine.page.title', { defaultValue: 'Mine survey' });
  const chip = crsChipText(crs.data?.crs ?? null, t('survey.crs.local', { defaultValue: 'Local grid' }));

  if (!projectId) {
    return (
      <div className="space-y-4">
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<Pickaxe size={24} />}
          title={t('mine.no_project', { defaultValue: 'Open a project to reconcile its mine survey.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => void demo.open() }}
        />
      </div>
    );
  }

  const d = detail.data;
  const totals = d?.totals;
  const band = d && d.band_lo_pct != null && d.band_hi_pct != null ? `${d.band_lo_pct}-${d.band_hi_pct} %` : null;
  const tonnes = (v: number | null | undefined) => <bdi dir="ltr">{formatTonnes(v, lang)}</bdi>;
  const kpis = [
    { key: 'plan', label: t('mine.kpi.plan', { defaultValue: 'Plan' }), value: <bdi dir="ltr">{formatM3(totals?.plan_m3, lang)} m³</bdi>, icon: Scale },
    {
      key: 'actual',
      label: t('mine.kpi.actual', { defaultValue: 'Actual' }),
      value: <bdi dir="ltr">{totals?.actual_m3 == null ? '-' : `${formatM3(totals.actual_m3, lang)} m³`}</bdi>,
      icon: Mountain,
    },
    {
      key: 'compliance',
      label: t('mine.kpi.compliance', { defaultValue: 'Compliance' }),
      value: <bdi dir="ltr">{formatPct(totals?.compliance_pct, lang)}</bdi>,
      icon: Gauge,
    },
    { key: 'truck', label: t('mine.kpi.truck', { defaultValue: 'Truck factor' }), value: <bdi dir="ltr">{formatSigned(totals?.truck_factor_pct, lang)}</bdi>, icon: Truck },
  ];

  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      {list.length > 0 && (
        <select
          className="oe-input"
          aria-label={t('mine.field.period', { defaultValue: 'Month' })}
          value={activeId ?? ''}
          onChange={(e) => setPeriodId(e.target.value)}
          data-testid="mine-period-select"
        >
          {list.map((p) => (
            <option key={p.id} value={p.id}>{periodTitle(p.label, lang)}</option>
          ))}
        </select>
      )}
      <Button variant="primary" icon={<Plus size={16} />} onClick={() => setNewOpen(true)} data-testid="mine-new-period" disabled={!canWrite}>
        {t('mine.action.new_period', { defaultValue: 'New period' })}
      </Button>
      <Button variant="secondary" icon={<Layers size={16} />} disabled={!d} onClick={() => setUnitOpen(true)} data-testid="mine-add-unit">
        {t('mine.action.add_unit', { defaultValue: 'Add unit' })}
      </Button>
      <Button
        variant="secondary"
        icon={<FileDown size={16} />}
        disabled={!d}
        onClick={() => d && void downloadWithAuth(periodReportUrl(d.id, lang), `mine-period-${d.label}.pdf`)}
        data-testid="mine-print"
      >
        {t('mine.action.print_report', { defaultValue: 'Print period report' })}
      </Button>
      <ModuleGuideButton content={mineGuide} />
    </div>
  );

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }) }, { label: title }]} />
      <PageHeader srTitle={title} subtitle={chip ? <bdi dir="ltr" className="text-xs">{chip}</bdi> : undefined} actions={actions} />
      <ViewOnlyNote />
      <DismissibleInfo storageKey="mine.info" title={t('survey.register.info_title', { defaultValue: 'What is this' })}>
        {t('mine.info', {
          defaultValue:
            'Each month, the surveyed volume of every pit, bench or drive is compared with its plan. The surveyed volume comes from two surfaces, and the truck count is a cross-check.',
        })}
      </DismissibleInfo>
      <CollapsibleSection storageKey="mine.how" title={t('guide.button', { defaultValue: 'How it works' })} defaultCollapsed>
        <p className="text-sm">{t('mine.hint.actual', { defaultValue: 'The actual is the cut between the two surfaces. It is never typed; confirm it before it goes on a claim.' })}</p>
      </CollapsibleSection>

      <KpiBand items={kpis} columns={4} size="sm" />

      {d && (
        <p className="text-xs text-content-secondary" data-testid="mine-profile">
          {band
            ? `${t('mine.kpi.compliance', { defaultValue: 'Compliance' })} ${band}${d.truck_tolerance_pct != null ? ` · ${t('mine.field.truck_check', { defaultValue: 'Truck check (%)' })} ${d.truck_tolerance_pct}` : ''}${d.profile_label ? ` · ${d.profile_label}` : ''}`
            : t('mine.profile.none', { defaultValue: 'No profile, set one' })}
        </p>
      )}

      {periods.isLoading || detail.isLoading ? (
        <Skeleton className="h-40" />
      ) : periods.isError || detail.isError ? (
        <ErrorState title={getErrorMessage(periods.error ?? detail.error)} onRetry={() => { void periods.refetch(); void detail.refetch(); }} />
      ) : list.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Pickaxe size={24} />}
            title={t('mine.empty', { defaultValue: 'No period yet. Open a month and add the units you plan to mine.' })}
            action={
              <div className="flex justify-center gap-2">
                <Button variant="primary" onClick={() => setNewOpen(true)}>
                  {t('mine.action.new_period', { defaultValue: 'New period' })}
                </Button>
                <Button variant="secondary" loading={demo.busy} onClick={() => void demo.open()} data-testid="mine-open-demo">
                  {t('survey.action.open_demo', { defaultValue: 'Open demo project' })}
                </Button>
              </div>
            }
          />
        </Card>
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="oe-table w-full text-sm" data-testid="mine-table">
            <thead>
              <tr>
                <th>{t('mine.col.unit', { defaultValue: 'Unit' })}</th>
                <th className="text-end">{t('mine.col.plan_m3', { defaultValue: 'Plan m³' })}</th>
                <th className="text-end">{t('mine.col.actual_m3', { defaultValue: 'Actual m³' })}</th>
                <th className="text-end">{t('mine.col.compliance', { defaultValue: 'Compliance' })}</th>
                <th className="text-end">{t('mine.col.plan_t', { defaultValue: 'Plan t' })}</th>
                <th className="text-end">{t('mine.col.survey_t', { defaultValue: 'Survey t' })}</th>
                <th className="text-end">{t('mine.col.truck_t', { defaultValue: 'Truck t' })}</th>
                <th>{t('common.status', { defaultValue: 'Status' })}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(d?.entries ?? []).map((e) => {
                const out = outsideBand(e.compliance_pct, d?.band_lo_pct ?? null, d?.band_hi_pct ?? null);
                const claimed = e.claim_entry_id != null;
                return (
                  <Fragment key={e.id}>
                    <tr data-testid={`mine-row-${e.unit_code}`}>
                      <td>
                        <p className="font-medium">{e.unit_name}</p>
                        <p className="text-xs text-content-secondary">
                          <bdi dir="ltr" className="font-mono">{e.unit_code}</bdi> {t(`mine.type.${e.unit_type}`, { defaultValue: e.unit_type })}
                        </p>
                      </td>
                      <td className="text-end" data-testid="mine-plan"><bdi dir="ltr">{formatM3(e.plan_m3, lang)}</bdi></td>
                      <td className="text-end" data-testid="mine-actual"><bdi dir="ltr">{formatM3(e.actual_m3, lang)}</bdi></td>
                      <td className="text-end" data-testid="mine-compliance">
                        <Badge variant={out == null ? 'neutral' : out ? 'warning' : 'success'}>
                          <bdi dir="ltr">{formatPct(e.compliance_pct, lang)}</bdi>
                        </Badge>
                      </td>
                      <td className="text-end"><bdi dir="ltr">{formatTonnes(e.plan_t, lang)}</bdi></td>
                      <td className="text-end" data-testid="mine-survey-t">{tonnes(e.survey_t)}</td>
                      <td className="text-end" data-testid="mine-truck-t">
                        {tonnes(e.truck_t)}
                        {e.truck_factor_pct != null && (
                          <p className="text-xs text-content-secondary" data-testid="mine-truck-factor">
                            <bdi dir="ltr">{formatSigned(e.truck_factor_pct, lang)}</bdi>
                          </p>
                        )}
                      </td>
                      <td>
                        {e.actual && (
                          <Badge variant={e.actual.status === 'draft' ? 'neutral' : 'blue'}>
                            {t(`volumes.status.${e.actual.status}`, { defaultValue: e.actual.status })}
                          </Badge>
                        )}
                        {claimed && (
                          <p className="mt-1 flex items-center gap-1 text-xs" data-testid="mine-claimed">
                            <CheckCircle2 size={12} aria-hidden />
                            {t('mine.claimed', { defaultValue: 'On claim: {{qty}} m³', qty: formatM3(e.claimed_m3, lang) })}
                          </p>
                        )}
                      </td>
                      <td>
                        <div className="flex flex-wrap justify-end gap-1">
                          {!claimed && (!e.actual || e.actual.status === 'draft') && (
                            <Button size="sm" variant="secondary" icon={<Layers size={14} />} onClick={() => setComputeFor(e)} data-testid="mine-compute">
                              {t('mine.action.compute_actual', { defaultValue: 'Compute actual' })}
                            </Button>
                          )}
                          {e.actual?.status === 'draft' && (
                            <Button size="sm" variant="primary" icon={<CheckCircle2 size={14} />} loading={confirm.isPending} onClick={() => confirm.mutate(e)} data-testid="mine-confirm">
                              {t('volumes.action.confirm', { defaultValue: 'Confirm result' })}
                            </Button>
                          )}
                          {!claimed && e.actual != null && (
                            <Button size="sm" variant="secondary" icon={<Upload size={14} />} onClick={() => setTrucksFor(e)} data-testid="mine-trucks">
                              {t('mine.action.import_trucks', { defaultValue: 'Import truck loads' })}
                            </Button>
                          )}
                          {!claimed && e.actual && e.actual.status !== 'draft' && (
                            <Button size="sm" variant="primary" icon={<Send size={14} />} onClick={() => setClaimFor(e)} data-testid="mine-claim">
                              {t('mine.action.add_to_claim', { defaultValue: 'Add to claim' })}
                            </Button>
                          )}
                          {!claimed && (
                            <Button size="sm" variant="ghost" onClick={() => remove.mutate(e.id)}>
                              {t('common.delete', { defaultValue: 'Delete' })}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {(e.findings.length > 0 || (isAdvanced && e.underground)) && (
                      <tr>
                        <td colSpan={9} className="bg-surface-secondary/40">
                          {e.findings.length > 0 && (
                            <ul className="space-y-1" data-testid="mine-findings">
                              {e.findings.map((f) => (
                                <li key={f.rule_id} className="flex items-start gap-2">
                                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-semantic-warning" aria-hidden />
                                  <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span>
                                  <span className="flex-1">
                                    {f.message}
                                    {f.suggestion && <span className="text-content-secondary"> {f.suggestion}</span>}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          )}
                          <MineEntryDepth entry={e} canWrite={canWrite} />
                          {isAdvanced && e.underground && <AdvanceCell entry={e} lang={lang} onSave={(v) => advance.mutate({ e, v })} />}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      <MineBlastCard projectId={projectId} canWrite={canWrite} />

      <Suspense fallback={<Skeleton className="h-[480px]" />}>
        <MinePlanView projectId={projectId} />
      </Suspense>

      <NewPeriodDialog open={newOpen} projectId={projectId} onClose={() => setNewOpen(false)} onCreated={(p) => setPeriodId(p.id)} />
      <AddUnitDialog open={unitOpen} period={d ?? null} onClose={() => setUnitOpen(false)} />
      <ComputeActualDialog open={!!computeFor} projectId={projectId} entry={computeFor} onClose={() => setComputeFor(null)} />
      <TruckLoadsDialog open={!!trucksFor} entry={trucksFor} onClose={() => setTrucksFor(null)} />
      <AddToClaimDialog
        open={!!claimFor}
        projectId={projectId}
        entry={claimFor}
        onClose={() => setClaimFor(null)}
        onClaimed={(r) => addToast({ type: 'success', title: t('volumes.progress.done', { defaultValue: 'Progress recorded: {{m3}} m3 ({{pct}} %) for {{period}}', m3: r.quantity_m3, pct: r.percent_complete, period: r.period_label }) })}
      />
    </div>
  );
}

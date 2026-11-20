// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Volumes (/survey/volumes): surfaces, cut and fill between two of them, the
 * Confirm step, and the trail from a confirmed volume to a BOQ line and a
 * progress entry. The computer suggests with a confidence score; a person with
 * survey.confirm confirms.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownToLine, ArrowUpFromLine, CheckCircle2, Copy, FileDown, Layers, Mountain, Plus, Scale, Send, TrendingUp } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  ConfidenceBadge,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  KpiBand,
  SideDrawer,
  Skeleton,
  TabBar,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui/ModuleGuideButton';
import { downloadWithAuth, getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useToastStore } from '@/stores/useToastStore';
import { getProjectCrs } from './api';
import { crsChipText } from './crsPicker';
import { StagedPanel } from './StagedPanel';
import { SurveyPlan } from './SurveyPlan';
import { NewSurfaceDialog, NewVolumeDialog, SendToBoqDialog } from './VolumeDialogs';
import { CertifyDialog } from './CertifyDialog';
import { HauledVsExcavatedPanel } from './HauledVsExcavatedPanel';
import { useOpenSurveyDemo } from './useOpenSurveyDemo';
import { volumesGuide } from './volumesGuide';
import {
  certifyVolume,
  certifyVolumePreview,
  confirmVolume,
  deleteSurface,
  duplicateVolume,
  formatM3,
  getVolumeSummary,
  getVolumesPlan,
  listSurfaces,
  listVolumes,
  netSide,
  recordProgress,
  volumeHistory,
  volumeReportUrl,
  type SendResult,
  type Volume,
} from './volumesApi';
import { fmtFixed } from '@/shared/lib/formatters';
import { ViewOnlyNote, useSurveyAccess } from './useSurveyAccess';

type Tab = 'calculations' | 'surfaces' | 'staged' | 'plan';

function StatusBadge({ status }: { status: Volume['status'] }) {
  const { t } = useTranslation();
  if (status === 'confirmed') return <Badge variant="success">{t('volumes.status.confirmed', { defaultValue: 'Confirmed' })}</Badge>;
  if (status === 'sent') return <Badge variant="blue">{t('volumes.status.sent', { defaultValue: 'Sent' })}</Badge>;
  return <Badge variant="neutral">{t('volumes.status.draft', { defaultValue: 'Draft' })}</Badge>;
}

export default function VolumesPage() {
  const { t, i18n } = useTranslation();
  const { canWrite } = useSurveyAccess();
  const lang = i18n.language;
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const demo = useOpenSurveyDemo('/survey/volumes');
  const [tab, setTab] = useState<Tab>('calculations');
  const [surfaceOpen, setSurfaceOpen] = useState(false);
  const [volumeOpen, setVolumeOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [certifyOpen, setCertifyOpen] = useState(false);
  const [sent, setSent] = useState<SendResult | null>(null);
  const [acks, setAcks] = useState<string[]>([]);

  const enabled = !!projectId;
  const crs = useQuery({ queryKey: ['survey', 'crs', projectId], queryFn: () => getProjectCrs(projectId!), enabled });
  const summary = useQuery({ queryKey: ['volumes', 'summary', projectId], queryFn: () => getVolumeSummary(projectId!), enabled });
  const volumes = useQuery({ queryKey: ['volumes', 'list', projectId, lang], queryFn: () => listVolumes(projectId!, lang), enabled });
  const surfaces = useQuery({ queryKey: ['volumes', 'surfaces', projectId], queryFn: () => listSurfaces(projectId!), enabled });
  const selected = useMemo(() => (volumes.data ?? []).find((v) => v.id === selectedId) ?? null, [volumes.data, selectedId]);
  const plan = useQuery({
    queryKey: ['volumes', 'plan', projectId, selectedId],
    queryFn: () => getVolumesPlan(projectId!, selectedId),
    enabled: enabled && (tab === 'plan' || !!selectedId),
  });
  const history = useQuery({
    queryKey: ['volumes', 'history', selectedId],
    queryFn: () => volumeHistory(selectedId!),
    enabled: !!selectedId,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ['volumes'] });
  const fail = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const confirm = useMutation({ mutationFn: (v: Volume) => confirmVolume(v.id, acks, lang), onSuccess: refresh, onError: fail });
  const duplicate = useMutation({
    mutationFn: (v: Volume) => duplicateVolume(v.id, {}),
    onSuccess: (v) => {
      refresh();
      setSelectedId(v.id);
    },
    onError: fail,
  });
  const removeSurface = useMutation({ mutationFn: (id: string) => deleteSurface(id), onSuccess: refresh, onError: fail });

  const title = t('volumes.page.title', { defaultValue: 'Volumes' });
  const chip = crsChipText(crs.data?.crs ?? null, t('survey.crs.local', { defaultValue: 'Local grid' }));

  if (!projectId) {
    return (
      <div className="space-y-4">
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<Mountain size={24} />}
          title={t('volumes.no_project', { defaultValue: 'Open a project to compute its earthwork volumes.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => void demo.open() }}
        />
      </div>
    );
  }

  const s = summary.data;
  const side = netSide(s?.net_m3 ?? 0);
  const m3 = (v: number | null | undefined) => `${formatM3(v, lang)} m³`;
  const kpis = [
    { key: 'cut', label: t('volumes.field.cut', { defaultValue: 'Cut' }), value: <bdi dir="ltr">{m3(s?.cut_m3)}</bdi>, icon: ArrowUpFromLine },
    { key: 'fill', label: t('volumes.field.fill', { defaultValue: 'Fill' }), value: <bdi dir="ltr">{m3(s?.fill_m3)}</bdi>, icon: ArrowDownToLine },
    {
      key: 'net',
      label: t('volumes.field.net', { defaultValue: 'Net' }),
      value: <bdi dir="ltr">{m3(Math.abs(s?.net_m3 ?? 0))}</bdi>,
      sub: side === 'balanced' ? t('volumes.net.balanced', { defaultValue: 'balanced' }) : t(`volumes.net.${side}`, { defaultValue: side }),
      icon: Scale,
    },
    {
      key: 'coverage',
      label: t('volumes.field.coverage', { defaultValue: 'Coverage' }),
      value: s?.coverage_pct == null ? '-' : `${Math.round(s.coverage_pct)} %`,
      icon: Layers,
    },
    {
      key: 'confirmed',
      label: t('volumes.kpi.confirmed', { defaultValue: 'Confirmed' }),
      value: `${s?.confirmed ?? 0}/${s?.calculations ?? 0}`,
      icon: CheckCircle2,
    },
  ];

  const actions = (
    <div className="flex flex-wrap gap-2">
      <Button
        variant="primary"
        icon={<Plus size={16} />}
        onClick={() => setVolumeOpen(true)}
        disabled={!canWrite || (surfaces.data ?? []).length < 2}
        data-testid="volumes-new"
      >
        {t('volumes.action.new_volume', { defaultValue: 'New volume' })}
      </Button>
      <Button variant="secondary" icon={<Layers size={16} />} onClick={() => setSurfaceOpen(true)} data-testid="volumes-new-surface" disabled={!canWrite}>
        {t('volumes.action.new_surface', { defaultValue: 'New surface' })}
      </Button>
      <ModuleGuideButton content={volumesGuide} />
    </div>
  );

  const list = volumes.data ?? [];
  const errors = selected?.findings.filter((f) => f.severity === 'error') ?? [];
  const warnings = selected?.findings.filter((f) => f.severity === 'warning') ?? [];
  const canConfirm = !!selected && selected.status === 'draft' && errors.length === 0 && warnings.every((w) => acks.includes(w.rule_id));

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }) }, { label: title }]} />
      <PageHeader srTitle={title} subtitle={chip ? <bdi dir="ltr" className="text-xs">{chip}</bdi> : undefined} actions={actions} />
      <ViewOnlyNote />
      <DismissibleInfo storageKey="volumes.info" title={t('survey.register.info_title', { defaultValue: 'What is this' })}>
        {t('volumes.info', {
          defaultValue:
            'Earth to dig out (cut) and to bring in (fill) between two ground surfaces, for example the existing ground and the design. A surveyor confirms the result before it feeds the BOQ.',
        })}
      </DismissibleInfo>
      <CollapsibleSection storageKey="volumes.how" title={t('guide.button', { defaultValue: 'How it works' })} defaultCollapsed>
        <ol className="list-decimal ps-5 space-y-1 text-sm">
          <li>{t('volumes.how_1', { defaultValue: 'Make two surfaces: one from the survey points, one from the design (LandXML).' })}</li>
          <li>{t('volumes.how_2', { defaultValue: 'New volume: pick the base (earlier) and the compare (later) surface and a name.' })}</li>
          <li>{t('volumes.how_3', { defaultValue: 'Check coverage and findings, then Confirm result. Only then send it to the BOQ or record progress.' })}</li>
        </ol>
      </CollapsibleSection>

      <KpiBand items={kpis} columns={5} size="sm" />

      <TabBar<Tab>
        ariaLabel={title}
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: 'calculations', label: t('volumes.tab.calculations', { defaultValue: 'Calculations' }) },
          { id: 'surfaces', label: t('volumes.tab.surfaces', { defaultValue: 'Surfaces' }) },
          { id: 'staged', label: t('volumes.tab.staged', { defaultValue: 'Stages' }) },
          { id: 'plan', label: t('survey.tab.plan', { defaultValue: 'Plan' }) },
        ]}
      />

      {tab === 'calculations' && (
        <Card className="p-0 overflow-hidden">
          {volumes.isLoading ? (
            <Skeleton className="h-48 m-3" />
          ) : volumes.isError ? (
            <ErrorState title={getErrorMessage(volumes.error)} onRetry={() => volumes.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState
              icon={<Mountain size={24} />}
              title={t('volumes.empty', { defaultValue: 'No volumes yet. Make two surfaces, then compute the cut and fill between them.' })}
              action={
                <div className="flex justify-center gap-2">
                  <Button variant="primary" onClick={() => setSurfaceOpen(true)}>
                    {t('volumes.action.new_surface', { defaultValue: 'New surface' })}
                  </Button>
                  <Button variant="secondary" loading={demo.busy} onClick={() => void demo.open()} data-testid="volumes-open-demo">
                    {t('survey.action.open_demo', { defaultValue: 'Open demo project' })}
                  </Button>
                </div>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="oe-table w-full text-sm" data-testid="volumes-table">
                <thead>
                  <tr>
                    <th>{t('volumes.field.id', { defaultValue: 'ID' })}</th>
                    <th>{t('common.name', { defaultValue: 'Name' })}</th>
                    <th>{t('volumes.field.base_compare', { defaultValue: 'Base -> Compare' })}</th>
                    <th>{t('volumes.field.method', { defaultValue: 'Method' })}</th>
                    <th className="text-right" title={t('volumes.unit.bank_m3', { defaultValue: 'Bank cubic metres' })}>{t('volumes.field.cut', { defaultValue: 'Cut' })} (m³)</th>
                    <th className="text-right" title={t('volumes.unit.bank_m3', { defaultValue: 'Bank cubic metres' })}>{t('volumes.field.fill', { defaultValue: 'Fill' })} (m³)</th>
                    <th className="text-right">{t('volumes.field.net', { defaultValue: 'Net' })} (m³)</th>
                    <th className="text-right" title={t('volumes.field.coverage_tip', { defaultValue: 'Share of the area where both surfaces have data' })}>
                      {t('volumes.field.coverage_short', { defaultValue: 'Cov' })}
                    </th>
                    <th>{t('volumes.field.status', { defaultValue: 'Status' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((v) => (
                    <tr key={v.id} className="cursor-pointer hover:bg-surface-secondary" onClick={() => { setAcks([]); setSelectedId(v.id); }}>
                      <td><bdi dir="ltr" className="font-mono">{v.code}</bdi></td>
                      <td>{v.name}</td>
                      <td className="text-content-secondary">{v.base_name} {'->'} {v.compare_name}</td>
                      <td>
                        {t(`volumes.method.${v.method}`, { defaultValue: v.method })}
                        {v.cell_size_m ? <bdi dir="ltr"> {v.cell_size_m} m</bdi> : null}
                      </td>
                      <td className="text-right"><bdi dir="ltr">{formatM3(v.cut_m3, lang)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr">{formatM3(v.fill_m3, lang)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr">{formatM3(v.net_m3, lang)}</bdi></td>
                      <td className="text-right">{Math.round(v.coverage_pct)} %</td>
                      <td><StatusBadge status={v.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === 'surfaces' && (
        <Card className="p-0 overflow-hidden">
          {(surfaces.data ?? []).length === 0 ? (
            <EmptyState
              icon={<Layers size={24} />}
              title={t('volumes.surface.empty', { defaultValue: 'No surfaces yet. Build one from a point set or import a LandXML file.' })}
              action={{ label: t('volumes.action.new_surface', { defaultValue: 'New surface' }), onClick: () => setSurfaceOpen(true) }}
            />
          ) : (
            <table className="oe-table w-full text-sm" data-testid="surfaces-table">
              <thead>
                <tr>
                  <th>{t('volumes.field.id', { defaultValue: 'ID' })}</th>
                  <th>{t('common.name', { defaultValue: 'Name' })}</th>
                  <th>{t('volumes.surface.source', { defaultValue: 'Source' })}</th>
                  <th className="text-right">{t('survey.kpi.points', { defaultValue: 'Points' })}</th>
                  <th className="text-right" title={t('volumes.unit.m2', { defaultValue: 'square metres' })}>{t('volumes.surface.area', { defaultValue: 'Area (m²)' })}</th>
                  <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('volumes.surface.z_range', { defaultValue: 'Z min - max (m)' })}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(surfaces.data ?? []).map((sf) => (
                  <tr key={sf.id}>
                    <td><bdi dir="ltr" className="font-mono">{sf.code}</bdi></td>
                    <td>{sf.name}</td>
                    <td className="text-content-secondary">
                      {t(`volumes.surface.source_${sf.source}`, { defaultValue: sf.source })} {sf.source_filename}
                    </td>
                    <td className="text-right">{sf.point_count}</td>
                    <td className="text-right"><bdi dir="ltr">{formatM3(sf.area_m2, lang)}</bdi></td>
                    <td className="text-right">
                      <bdi dir="ltr">{sf.z_min != null ? fmtFixed(sf.z_min, 3) : ''} - {sf.z_max != null ? fmtFixed(sf.z_max, 3) : ''}</bdi>
                    </td>
                    <td className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={sf.in_use > 0}
                        title={sf.in_use > 0 ? t('volumes.surface.in_use', { defaultValue: 'Used by a calculation' }) : undefined}
                        onClick={() => removeSurface.mutate(sf.id)}
                      >
                        {t('common.delete', { defaultValue: 'Delete' })}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'staged' && <StagedPanel projectId={projectId} surfaces={surfaces.data ?? []} />}

      {tab === 'plan' && <SurveyPlan plan={plan.data} isLoading={plan.isLoading} error={plan.error} onRetry={() => plan.refetch()} showLegend />}

      <SideDrawer
        open={!!selected}
        onClose={() => setSelectedId(null)}
        title={selected ? `${selected.code} ${selected.name}` : ''}
        subtitle={selected ? <StatusBadge status={selected.status} /> : undefined}
        widthClass="max-w-2xl"
        busy={confirm.isPending || duplicate.isPending}
      >
        {selected && (
          <div className="space-y-4 text-sm" data-testid="volume-drawer">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
              <dt className="text-content-secondary">{t('volumes.field.cut', { defaultValue: 'Cut' })}</dt>
              <dd data-testid="volume-cut"><bdi dir="ltr">{m3(selected.cut_m3)}</bdi></dd>
              <dt className="text-content-secondary">{t('volumes.field.fill', { defaultValue: 'Fill' })}</dt>
              <dd><bdi dir="ltr">{m3(selected.fill_m3)}</bdi></dd>
              <dt className="text-content-secondary">{t('volumes.field.net', { defaultValue: 'Net' })}</dt>
              <dd>
                <bdi dir="ltr">{m3(Math.abs(selected.net_m3))}</bdi> {t(`volumes.net.${netSide(selected.net_m3)}`, { defaultValue: netSide(selected.net_m3) })}
              </dd>
              {selected.swell_factor !== 1 && (
                <>
                  <dt className="text-content-secondary" title={t('volumes.field.swell_tip', { defaultValue: 'Loose volume divided by bank volume, for example 1.25 for clay.' })}>
                    {t('volumes.quantity.loose_cut', { defaultValue: 'Loose cut' })} (x {selected.swell_factor})
                  </dt>
                  <dd data-testid="volume-loose"><bdi dir="ltr">{m3(selected.loose_cut_m3)}</bdi></dd>
                </>
              )}
              <dt className="text-content-secondary">{t('volumes.field.coverage', { defaultValue: 'Coverage' })}</dt>
              <dd>{fmtFixed(selected.coverage_pct, 1)} %</dd>
              <dt className="text-content-secondary">{t('volumes.field.confidence', { defaultValue: 'Confidence' })}</dt>
              <dd><ConfidenceBadge score={selected.confidence ?? 0} showScore size="sm" /></dd>
              <dt className="text-content-secondary">{t('volumes.field.method', { defaultValue: 'Method' })}</dt>
              <dd>
                {t(`volumes.method.${selected.method}`, { defaultValue: selected.method })}
                {selected.cell_size_m ? <bdi dir="ltr"> {selected.cell_size_m} m{selected.cell_auto ? ` (${t('volumes.field.auto', { defaultValue: 'auto' })})` : ''}</bdi> : null}
              </dd>
              <dt className="text-content-secondary">{t('survey.set.crs', { defaultValue: 'Coordinate system' })}</dt>
              <dd><bdi dir="ltr">{selected.crs_epsg ? `EPSG ${selected.crs_epsg}` : '-'}</bdi></dd>
              {selected.confirmed_by_name && (
                <>
                  <dt className="text-content-secondary">{t('volumes.field.confirmed_by', { defaultValue: 'Confirmed by' })}</dt>
                  <dd>{selected.confirmed_by_name}</dd>
                </>
              )}
            </dl>

            {selected.findings.length > 0 && (
              <ul className="space-y-1" data-testid="volume-findings">
                {selected.findings.map((f) => (
                  <li key={f.rule_id} className="flex items-start gap-2">
                    <span
                      className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${f.severity === 'error' ? 'bg-semantic-error' : f.severity === 'warning' ? 'bg-semantic-warning' : 'bg-content-tertiary'}`}
                      aria-hidden
                    />
                    <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span>
                    <span className="flex-1">
                      {f.message}
                      {f.suggestion && <span className="text-content-secondary"> {f.suggestion}</span>}
                    </span>
                    {f.severity === 'warning' && selected.status === 'draft' && (
                      <label className="inline-flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={acks.includes(f.rule_id)}
                          onChange={(e) => setAcks((a) => (e.target.checked ? [...a, f.rule_id] : a.filter((x) => x !== f.rule_id)))}
                        />
                        {t('volumes.action.acknowledge', { defaultValue: 'Acknowledge' })}
                      </label>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <div className="flex flex-wrap gap-2">
              {selected.status === 'draft' && (
                <Button
                  variant="primary"
                  icon={<CheckCircle2 size={16} />}
                  disabled={!canConfirm}
                  loading={confirm.isPending}
                  onClick={() => confirm.mutate(selected)}
                  data-testid="volume-confirm"
                >
                  {t('volumes.action.confirm', { defaultValue: 'Confirm result' })}
                </Button>
              )}
              <Button
                variant="secondary"
                icon={<Send size={16} />}
                disabled={selected.status === 'draft'}
                onClick={() => setSendOpen(true)}
                data-testid="volume-send"
              >
                {t('volumes.action.send_to_boq', { defaultValue: 'Send to BOQ' })}
              </Button>
              <Button
                variant="secondary"
                icon={<TrendingUp size={16} />}
                disabled={selected.status === 'draft'}
                onClick={() => setCertifyOpen(true)}
                data-testid="volume-progress"
              >
                {t('certify.action', { defaultValue: 'Add to certificate' })}
              </Button>
              <Button
                variant="secondary"
                icon={<FileDown size={16} />}
                onClick={() => void downloadWithAuth(volumeReportUrl(selected.id, lang), `${selected.code}.pdf`).then(() => history.refetch())}
              >
                {t('volumes.action.print_report', { defaultValue: 'Print report' })}
              </Button>
              {isAdvanced && (
                <Button variant="ghost" icon={<Copy size={16} />} loading={duplicate.isPending} onClick={() => duplicate.mutate(selected)}>
                  {t('volumes.action.duplicate', { defaultValue: 'Duplicate' })}
                </Button>
              )}
            </div>
            {selected.status === 'draft' && (
              <p className="text-xs text-content-tertiary">
                {t('volumes.confirm_hint', { defaultValue: 'A confirmed result is locked. To change it, duplicate it and confirm the copy.' })}
              </p>
            )}

            {sent && sent.position_id === selected.boq_position_id && (
              <Card className="p-3" data-testid="volume-sent">
                <p>
                  {sent.ordinal} {sent.description}: <bdi dir="ltr" className="font-mono">{sent.quantity} {sent.unit}</bdi>
                </p>
                <span className="mt-1 inline-flex rounded-full border border-border-light px-2 py-0.5 font-mono text-xs">{sent.formula}</span>
              </Card>
            )}

            <div>
              <SurveyPlan plan={plan.data} isLoading={plan.isLoading} error={plan.error} onRetry={() => plan.refetch()} showLegend />
            </div>

            {selected.status !== 'draft' && <HauledVsExcavatedPanel projectId={projectId} volumeId={selected.id} />}

            <div>
              <h3 className="oe-card-title mb-1">{t('volumes.history', { defaultValue: 'History' })}</h3>
              <ul className="space-y-1 text-xs" data-testid="volume-history">
                {(history.data ?? []).map((h) => (
                  <li key={h.id} className="flex gap-2">
                    <span className="text-content-tertiary">{h.created_at ? new Date(h.created_at).toLocaleString(lang) : ''}</span>
                    <span>{h.user_name}</span>
                    <span>{t(`volumes.event.${h.action}`, { defaultValue: h.action })}</span>
                    {h.quantity != null && <bdi dir="ltr">{m3(h.quantity)}</bdi>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </SideDrawer>

      <NewSurfaceDialog open={surfaceOpen} projectId={projectId} onClose={() => setSurfaceOpen(false)} />
      <NewVolumeDialog
        open={volumeOpen}
        projectId={projectId}
        surfaces={surfaces.data ?? []}
        isAdvanced={isAdvanced}
        onClose={() => setVolumeOpen(false)}
        onCreated={(v) => {
          setAcks([]);
          setSelectedId(v.id);
        }}
      />
      {selected && certifyOpen && (
        <CertifyDialog
          open
          projectId={projectId}
          source={selected.code}
          amounts={{ cut: selected.cut_m3, fill: selected.fill_m3, net: selected.net_m3, loose_cut: selected.loose_cut_m3 }}
          initialPositionId={selected.boq_position_id}
          preview={(b) => certifyVolumePreview(selected.id, b)}
          commit={(b) => certifyVolume(selected.id, b)}
          progressOnly={(b) => recordProgress(selected.id, b)}
          onClose={() => setCertifyOpen(false)}
        />
      )}
      {selected && (
        <SendToBoqDialog
          open={sendOpen}
          projectId={projectId}
          volume={selected}
          onClose={() => setSendOpen(false)}
          onSent={(r) => {
            setSent(r);
            addToast({
              type: 'success',
              title: t('volumes.send.done', { defaultValue: '{{qty}} {{unit}} sent to {{ordinal}}', qty: r.quantity, unit: r.unit, ordinal: r.ordinal }),
            });
          }}
        />
      )}
    </div>
  );
}

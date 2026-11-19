// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Survey register (/survey/points): the project CRS, control and topo points, the
 * files they came from, and the SRV findings on them.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Crosshair, Database, FileUp, Grid3x3, ListChecks, MapPin, Route } from 'lucide-react';
import {
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  KpiBand,
  Skeleton,
  TabBar,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui/ModuleGuideButton';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  POINT_KINDS,
  bulkPoints,
  deletePointSet,
  getProjectCrs,
  getSummary,
  listPointSets,
  listPoints,
  validateRegister,
  type BulkAction,
  type PointSet,
} from './api';
import { ControlTab } from './ControlTab';
import { PointDrawer } from './PointDrawer';
import { PointExportControl } from './PointExportControl';
import { crsChipText } from './crsPicker';
import { CrsDialog } from './CrsDialog';
import { GridGroundChip, LocalGridDialog } from './GeodesyPanel';
import { SurveyExportMenu } from './SurveyExportMenu';
import { SurveyImportDialog } from './SurveyImportDialog';
import { surveyGuide } from './surveyGuide';
import { SurveyPlan } from './SurveyPlan';
import { TraverseDrawer, VerdictBadge, ratioText } from './TraverseDrawer';
import { useOpenSurveyDemo } from './useOpenSurveyDemo';
import { ViewOnlyNote, useSurveyAccess } from './useSurveyAccess';
import { deleteTraverse, getRegisterPlan, listTraverses, type Traverse } from './volumesApi';
import { fmtFixed } from '@/shared/lib/formatters';

type Tab = 'points' | 'control' | 'sets' | 'traverses' | 'plan';
const coord = (v: number | null | undefined) => (v == null ? '' : fmtFixed(v, 3));

export default function SurveyRegisterPage() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const [tab, setTab] = useState<Tab>('points');
  const [crsOpen, setCrsOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [localOpen, setLocalOpen] = useState(false);
  const [kind, setKind] = useState('');
  const [setFilter, setSetFilter] = useState('');
  const [q, setQ] = useState('');
  const [traverseOpen, setTraverseOpen] = useState(false);
  const [shownTraverse, setShownTraverse] = useState<Traverse | null>(null);
  const [openPoint, setOpenPoint] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState<BulkAction>('set_code');
  const [bulkValue, setBulkValue] = useState('');
  const demo = useOpenSurveyDemo('/survey/points');
  const { canWrite } = useSurveyAccess();

  const enabled = !!projectId;
  const crs = useQuery({ queryKey: ['survey', 'crs', projectId], queryFn: () => getProjectCrs(projectId!), enabled });
  const summary = useQuery({ queryKey: ['survey', 'summary', projectId], queryFn: () => getSummary(projectId!), enabled });
  const sets = useQuery({ queryKey: ['survey', 'sets', projectId], queryFn: () => listPointSets(projectId!), enabled });
  const points = useQuery({
    queryKey: ['survey', 'points', projectId, kind, setFilter, q],
    queryFn: () => listPoints(projectId!, { kind, set_id: setFilter, q }),
    enabled,
  });
  const findings = useQuery({
    queryKey: ['survey', 'findings', projectId, i18n.language],
    queryFn: () => validateRegister(projectId!, i18n.language),
    enabled,
  });

  const traverses = useQuery({
    queryKey: ['survey', 'traverses', projectId],
    queryFn: () => listTraverses(projectId!),
    enabled: enabled && tab === 'traverses',
  });
  const plan = useQuery({
    queryKey: ['survey', 'plan', projectId],
    queryFn: () => getRegisterPlan(projectId!),
    enabled: enabled && tab === 'plan',
  });
  const removeTraverse = useMutation({
    mutationFn: (tr: Traverse) => deleteTraverse(tr.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['survey'] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const noCrs = crs.isSuccess && !crs.data.crs;
  // Offer the CRS once per project and session; the chip and the SRV finding reopen it.
  useEffect(() => {
    if (!noCrs || !projectId) return;
    const key = `survey.crs.offered.${projectId}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, '1');
    } catch {
      // storage blocked: still offer it, closing works either way
    }
    setCrsOpen(true);
  }, [noCrs, projectId]);

  const remove = useMutation({
    mutationFn: (s: PointSet) => deletePointSet(s.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['survey'] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const bulk = useMutation({
    mutationFn: () =>
      bulkPoints(projectId!, {
        ids: [...selected],
        action: bulkAction,
        value: bulkAction === 'set_code' || bulkAction === 'set_kind' ? bulkValue : undefined,
        target_set_id: bulkAction === 'move_to_set' ? bulkValue : undefined,
      }),
    onSuccess: (r) => {
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: ['survey'] });
      addToast({
        type: r.skipped_locked ? 'warning' : 'success',
        title: t('survey.bulk.done', { defaultValue: '{{count}} points changed', count: r.affected }),
        message: r.skipped_locked
          ? t('survey.bulk.skipped_locked', { defaultValue: '{{count}} locked points were left as they are.', count: r.skipped_locked })
          : undefined,
      });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const runBulk = () => {
    if (bulkAction === 'delete') {
      const ok = window.confirm(
        t('survey.bulk.delete_confirm', { defaultValue: 'Delete {{count}} points? This cannot be undone.', count: selected.size }),
      );
      if (!ok) return;
    }
    bulk.mutate();
  };
  const visibleIds = (points.data?.items ?? []).map((p) => p.id);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const bulkReady = bulkAction === 'delete' || bulkValue.trim() !== '';

  const setNames = useMemo(() => new Map((sets.data ?? []).map((s) => [s.id, s.name])), [sets.data]);
  const chip = crsChipText(crs.data?.crs ?? null, t('survey.crs.local', { defaultValue: 'Local grid' }));
  const title = t('survey.page.register', { defaultValue: 'Survey register' });

  if (!projectId) {
    return (
      <div className="space-y-4">
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<Crosshair size={24} />}
          title={t('survey.no_project', { defaultValue: 'Open a project to see its survey points.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => void demo.open() }}
        />
      </div>
    );
  }

  const actions = (
    <div className="flex flex-wrap gap-2">
      {canWrite && (
      <>
      <Button variant="primary" icon={<FileUp size={16} />} onClick={() => setImportOpen(true)} data-testid="survey-import">
        {t('survey.action.import_points', { defaultValue: 'Import points' })}
      </Button>
      <Button
        variant="secondary"
        icon={<Route size={16} />}
        onClick={() => {
          setShownTraverse(null);
          setTraverseOpen(true);
        }}
        data-testid="survey-new-traverse"
      >
        {t('survey.action.new_traverse', { defaultValue: 'New traverse' })}
      </Button>
      <Button variant="secondary" icon={<Grid3x3 size={16} />} onClick={() => setLocalOpen(true)} data-testid="survey-local-grid-open">
        {t('survey.action.local_grid', { defaultValue: 'Local grid' })}
      </Button>
      </>
      )}
      <SurveyExportMenu
        target={{ kind: 'register', projectId: projectId!, pointKind: kind || undefined, setId: setFilter || undefined }}
        disabled={!summary.data?.points}
      />
      <PointExportControl projectId={projectId} ids={[...selected]} />
      <ModuleGuideButton content={surveyGuide} />
    </div>
  );

  const kpis = [
    { key: 'points', label: t('survey.kpi.points', { defaultValue: 'Points' }), value: summary.data?.points ?? 0, icon: MapPin },
    { key: 'control', label: t('survey.kpi.control', { defaultValue: 'Control' }), value: summary.data?.control ?? 0, icon: Crosshair },
    {
      key: 'findings',
      label: t('survey.kpi.findings', { defaultValue: 'Findings' }),
      value: findings.data ? findings.data.error_count + findings.data.warning_count : 0,
      icon: ListChecks,
    },
    {
      key: 'last',
      label: t('survey.kpi.last_import', { defaultValue: 'Last import' }),
      value: summary.data?.last_import ? new Date(summary.data.last_import).toLocaleDateString(i18n.language) : '-',
      icon: Database,
    },
  ];

  const empty = points.isSuccess && points.data.total === 0 && !kind && !setFilter && !q;

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }), to: '/survey' }, { label: title }]} />
      <PageHeader
        srTitle={title}
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="survey-crs-chip"
              onClick={() => setCrsOpen(true)}
              className="inline-flex items-center rounded-full border border-border-light px-2.5 py-0.5 text-xs hover:bg-surface-secondary"
              title={t('survey.crs.chip_tip', { defaultValue: 'Project coordinate system. Click to change.' })}
            >
              <bdi dir="ltr">{chip || t('survey.action.set_crs', { defaultValue: 'Set project CRS' })}</bdi>
            </button>
            {projectId && <GridGroundChip projectId={projectId} />}
          </span>
        }
        actions={actions}
      />
      <ViewOnlyNote />
      <DismissibleInfo storageKey="survey.register.info" title={t('survey.register.info_title', { defaultValue: 'What is this' })}>
        {t('survey.register.info', {
          defaultValue:
            'The points your surveyor measured, kept in one coordinate system for the whole project. Volumes, setting-out and parcels are worked out from them.',
        })}
      </DismissibleInfo>
      <CollapsibleSection storageKey="survey.register.how" title={t('guide.button', { defaultValue: 'How it works' })} defaultCollapsed>
        <ol className="list-decimal ps-5 space-y-1 text-sm">
          <li>{t('survey.register.how_1', { defaultValue: 'Set the project CRS once: the EPSG code your surveyor used.' })}</li>
          <li>{t('survey.register.how_2', { defaultValue: 'Import the control points first, then the topo points, each file as one point set.' })}</li>
          <li>{t('survey.register.how_3', { defaultValue: 'Fix the findings: a point ID used twice, or a file whose system is unknown.' })}</li>
        </ol>
      </CollapsibleSection>

      <KpiBand items={kpis} columns={4} size="sm" />

      {findings.data && findings.data.findings.length > 0 && (
        <Card className="p-3" data-testid="survey-findings">
          <ul className="space-y-1 text-sm">
            {findings.data.findings.map((f, i) => (
              <li key={i} className="flex items-start gap-2">
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${f.severity === 'error' ? 'bg-semantic-error' : f.severity === 'warning' ? 'bg-semantic-warning' : 'bg-content-tertiary'}`}
                  aria-hidden
                />
                <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span>
                <span className="flex-1">
                  {f.message}
                  {f.suggestion && <span className="text-content-secondary"> {f.suggestion}</span>}
                </span>
                {(f.rule_id === 'SRV-001' || f.rule_id === 'SRV-002') && (
                  <Button size="sm" variant="secondary" onClick={() => setCrsOpen(true)}>
                    {t('survey.action.set_crs', { defaultValue: 'Set project CRS' })}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <TabBar<Tab>
        ariaLabel={title}
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: 'points', label: t('survey.tab.points', { defaultValue: 'Points' }) },
          { id: 'control', label: t('survey.tab.control', { defaultValue: 'Control' }) },
          { id: 'sets', label: t('survey.tab.point_sets', { defaultValue: 'Point sets' }) },
          { id: 'traverses', label: t('survey.tab.traverses', { defaultValue: 'Traverses' }) },
          { id: 'plan', label: t('survey.tab.plan', { defaultValue: 'Plan' }) },
        ]}
      />

      {tab === 'points' && (
        <Card className="p-0 overflow-hidden">
          <div className="flex flex-wrap gap-2 p-3 border-b border-border-light">
            <select className="oe-input w-40" value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t('survey.field.kind', { defaultValue: 'Kind' })}>
              <option value="">{t('survey.filter.all_kinds', { defaultValue: 'All kinds' })}</option>
              {POINT_KINDS.map((k) => (
                <option key={k} value={k}>{t(`survey.kind.${k}`, { defaultValue: k })}</option>
              ))}
            </select>
            <select className="oe-input w-48" value={setFilter} onChange={(e) => setSetFilter(e.target.value)} aria-label={t('survey.field.set', { defaultValue: 'Set' })}>
              <option value="">{t('survey.filter.all_sets', { defaultValue: 'All point sets' })}</option>
              {(sets.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <input
              className="oe-input w-56"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('survey.filter.search', { defaultValue: 'Search ID or code' })}
              aria-label={t('survey.filter.search', { defaultValue: 'Search ID or code' })}
            />
          </div>
          {canWrite && selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b border-border-light bg-surface-secondary p-3 text-sm" data-testid="survey-bulk-bar">
              <span className="font-medium">{t('survey.bulk.selected', { defaultValue: '{{count}} selected', count: selected.size })}</span>
              <select
                className="oe-input w-44"
                value={bulkAction}
                onChange={(e) => {
                  setBulkAction(e.target.value as BulkAction);
                  setBulkValue('');
                }}
                aria-label={t('survey.bulk.action', { defaultValue: 'Action' })}
              >
                <option value="set_code">{t('survey.bulk.set_code', { defaultValue: 'Set code' })}</option>
                <option value="set_kind">{t('survey.bulk.set_kind', { defaultValue: 'Set kind' })}</option>
                <option value="move_to_set">{t('survey.bulk.move_to_set', { defaultValue: 'Move to point set (layer)' })}</option>
                <option value="delete">{t('survey.bulk.delete', { defaultValue: 'Delete' })}</option>
              </select>
              {bulkAction === 'set_code' && (
                <input className="oe-input w-32" value={bulkValue} onChange={(e) => setBulkValue(e.target.value)} placeholder={t('survey.field.code', { defaultValue: 'Code' })} />
              )}
              {bulkAction === 'set_kind' && (
                <select className="oe-input w-36" value={bulkValue} onChange={(e) => setBulkValue(e.target.value)}>
                  <option value="">-</option>
                  {POINT_KINDS.map((k) => (
                    <option key={k} value={k}>{t(`survey.kind.${k}`, { defaultValue: k })}</option>
                  ))}
                </select>
              )}
              {bulkAction === 'move_to_set' && (
                <select className="oe-input w-44" value={bulkValue} onChange={(e) => setBulkValue(e.target.value)}>
                  <option value="">-</option>
                  {(sets.data ?? []).map((st) => (
                    <option key={st.id} value={st.id}>{st.name}</option>
                  ))}
                </select>
              )}
              <Button size="sm" variant={bulkAction === 'delete' ? 'danger' : 'primary'} disabled={!bulkReady} loading={bulk.isPending} onClick={runBulk}>
                {t('survey.bulk.apply', { defaultValue: 'Apply' })}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                {t('survey.bulk.clear', { defaultValue: 'Clear selection' })}
              </Button>
            </div>
          )}
          {points.isLoading ? (
            <Skeleton className="h-48 m-3" />
          ) : points.isError ? (
            <ErrorState title={getErrorMessage(points.error)} onRetry={() => points.refetch()} />
          ) : empty ? (
            <EmptyState
              icon={<MapPin size={24} />}
              title={t('survey.empty', { defaultValue: 'No survey points yet. Import a CSV from your instrument.' })}
              action={
                <div className="flex gap-2 justify-center">
                  {canWrite && (
                    <Button variant="primary" onClick={() => setImportOpen(true)}>
                      {t('survey.action.import_points', { defaultValue: 'Import points' })}
                    </Button>
                  )}
                  <Button variant="secondary" loading={demo.busy} onClick={() => void demo.open()} data-testid="survey-open-demo">
                    {t('survey.action.open_demo', { defaultValue: 'Open demo project' })}
                  </Button>
                </div>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="oe-table w-full text-sm">
                <thead>
                  <tr>
                    <th className="w-8">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(visibleIds))}
                        aria-label={t('survey.bulk.select_all', { defaultValue: 'Select all shown points' })}
                      />
                    </th>
                    <th>{t('survey.field.point_id', { defaultValue: 'ID' })}</th>
                    <th>{t('survey.field.code', { defaultValue: 'Code' })}</th>
                    <th>{t('survey.field.kind', { defaultValue: 'Kind' })}</th>
                    <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.field.e', { defaultValue: 'E (m)' })}</th>
                    <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.field.n', { defaultValue: 'N (m)' })}</th>
                    <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.field.z', { defaultValue: 'Z (m)' })}</th>
                    <th>{t('survey.field.set', { defaultValue: 'Set' })}</th>
                    {isAdvanced && (
                      <th className="text-right" title={t('survey.field.sigma_tip', { defaultValue: 'Standard deviation of the position, metres' })}>
                        {t('survey.field.sigma', { defaultValue: 'Sigma (m)' })}
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {(points.data?.items ?? []).map((p) => (
                    <tr key={p.id} className={selected.has(p.id) ? 'bg-surface-secondary' : undefined}>
                      <td>
                        <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} aria-label={p.point_id} />
                      </td>
                      <td>
                        <button type="button" className="hover:underline" onClick={() => setOpenPoint(p.id)} data-testid="survey-point-open">
                          <bdi dir="ltr" className="font-mono">{p.point_id}</bdi>
                        </button>
                      </td>
                      <td>{p.code}</td>
                      <td>{t(`survey.kind.${p.kind}`, { defaultValue: p.kind })}</td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{coord(p.e)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{coord(p.n)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{coord(p.z)}</bdi></td>
                      <td className="text-content-secondary">{setNames.get(p.point_set_id) ?? ''}</td>
                      {isAdvanced && <td className="text-right"><bdi dir="ltr" className="font-mono">{coord(p.sigma)}</bdi></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === 'control' && (
        <ControlTab
          projectId={projectId}
          canWrite={canWrite}
          measuredOptions={(points.data?.items ?? [])
            .filter((p) => p.kind !== 'control')
            .map((p) => ({ id: p.id, label: p.code ? `${p.point_id} (${p.code})` : p.point_id }))}
        />
      )}

      {tab === 'sets' && (
        <Card className="p-0 overflow-hidden">
          {sets.isLoading ? (
            <Skeleton className="h-32 m-3" />
          ) : (sets.data ?? []).length === 0 ? (
            <EmptyState
              icon={<Database size={24} />}
              title={t('survey.empty', { defaultValue: 'No survey points yet. Import a CSV from your instrument.' })}
            />
          ) : (
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  <th>{t('common.name', { defaultValue: 'Name' })}</th>
                  <th>{t('survey.set.source', { defaultValue: 'Source file' })}</th>
                  <th>{t('survey.import.instrument', { defaultValue: 'Instrument' })}</th>
                  <th>{t('survey.import.date', { defaultValue: 'Survey date' })}</th>
                  <th>{t('survey.set.crs', { defaultValue: 'Coordinate system' })}</th>
                  <th className="text-right">{t('survey.kpi.points', { defaultValue: 'Points' })}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(sets.data ?? []).map((s) => (
                  <tr key={s.id}>
                    <td>{s.name}</td>
                    <td className="text-content-secondary">{s.source_filename}</td>
                    <td>{s.instrument}</td>
                    <td>{s.survey_date ?? ''}</td>
                    <td>
                      <bdi dir="ltr">{s.stored_epsg ? `EPSG ${s.stored_epsg}` : '-'}</bdi>
                      {s.transformed && s.source_epsg && (
                        <span className="text-xs text-content-tertiary">
                          {' '}
                          {t('survey.set.converted_from', { defaultValue: 'converted from EPSG {{code}}', code: s.source_epsg })}
                        </span>
                      )}
                    </td>
                    <td className="text-right">{s.point_count}</td>
                    <td className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={!canWrite}
                        onClick={() => {
                          if (window.confirm(t('survey.set.delete_confirm', { defaultValue: 'Delete this point set and its {{count}} points?', count: s.point_count }))) {
                            remove.mutate(s);
                          }
                        }}
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

      {tab === 'traverses' && (
        <Card className="p-0 overflow-hidden">
          {traverses.isLoading ? (
            <Skeleton className="h-32 m-3" />
          ) : (traverses.data ?? []).length === 0 ? (
            <EmptyState
              icon={<Route size={24} />}
              title={t('survey.traverse.empty', { defaultValue: 'No traverses yet. Paste the legs of a closed loop to check its misclosure.' })}
              action={canWrite ? { label: t('survey.action.new_traverse', { defaultValue: 'New traverse' }), onClick: () => setTraverseOpen(true) } : undefined}
            />
          ) : (
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  <th>{t('common.name', { defaultValue: 'Name' })}</th>
                  <th>{t('survey.traverse.kind', { defaultValue: 'Kind' })}</th>
                  <th className="text-right">{t('survey.traverse.ratio', { defaultValue: 'Ratio' })}</th>
                  <th>{t('survey.traverse.verdict', { defaultValue: 'Against the profile' })}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(traverses.data ?? []).map((tr) => (
                  <tr key={tr.id}>
                    <td>
                      <button
                        type="button"
                        className="text-start hover:underline"
                        onClick={() => {
                          setShownTraverse(tr);
                          setTraverseOpen(true);
                        }}
                      >
                        {tr.name}
                      </button>
                    </td>
                    <td>
                      {tr.kind === 'level'
                        ? t('survey.traverse.kind_level', { defaultValue: 'Level run' })
                        : t('survey.traverse.kind_traverse', { defaultValue: 'Closed traverse' })}
                    </td>
                    <td className="text-right">
                      <bdi dir="ltr">
                        {tr.kind === 'level'
                          ? `${tr.misclosure_mm ?? '-'} / ${tr.allowed_mm ?? '-'} mm`
                          : ratioText(tr.ratio, i18n.language)}
                      </bdi>
                    </td>
                    <td><VerdictBadge verdict={tr.verdict} /></td>
                    <td className="text-right">
                      <Button size="sm" variant="ghost" disabled={!canWrite} onClick={() => removeTraverse.mutate(tr)}>
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

      {tab === 'plan' && (
        <SurveyPlan
          plan={plan.data}
          isLoading={plan.isLoading}
          error={plan.error}
          onRetry={() => plan.refetch()}
          exportSlot={<PointExportControl projectId={projectId} />}
        />
      )}

      <PointDrawer pointId={openPoint} canWrite={canWrite} onClose={() => setOpenPoint(null)} />
      <TraverseDrawer
        open={traverseOpen}
        projectId={projectId}
        isAdvanced={isAdvanced}
        shown={shownTraverse}
        onClose={() => {
          setTraverseOpen(false);
          setShownTraverse(null);
        }}
      />
      {projectId && <LocalGridDialog open={localOpen} projectId={projectId} onClose={() => setLocalOpen(false)} />}
      <CrsDialog open={crsOpen} projectId={projectId} state={crs.data} onClose={() => setCrsOpen(false)} />
      <SurveyImportDialog
        open={importOpen}
        projectId={projectId}
        projectEpsg={crs.data?.crs?.horizontal_epsg ?? null}
        onClose={() => setImportOpen(false)}
      />
    </div>
  );
}

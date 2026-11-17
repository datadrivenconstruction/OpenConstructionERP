// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Survey register (/survey): the project CRS, control and topo points, the
 * files they came from, and the SRV findings on them.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Crosshair, Database, FileUp, ListChecks, MapPin } from 'lucide-react';
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
  deletePointSet,
  getProjectCrs,
  getSummary,
  listPointSets,
  listPoints,
  validateRegister,
  type PointSet,
} from './api';
import { crsChipText } from './crsPicker';
import { CrsDialog } from './CrsDialog';
import { SurveyImportDialog } from './SurveyImportDialog';
import { surveyGuide } from './surveyGuide';

type Tab = 'points' | 'sets';
const coord = (v: number | null | undefined) => (v == null ? '' : v.toFixed(3));

export default function SurveyRegisterPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const [tab, setTab] = useState<Tab>('points');
  const [crsOpen, setCrsOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [kind, setKind] = useState('');
  const [setFilter, setSetFilter] = useState('');
  const [q, setQ] = useState('');

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

  const noCrs = crs.isSuccess && !crs.data.crs;
  useEffect(() => {
    if (noCrs) setCrsOpen(true);
  }, [noCrs]);

  const remove = useMutation({
    mutationFn: (s: PointSet) => deletePointSet(s.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['survey'] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

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
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => navigate('/onboarding/demo') }}
        />
      </div>
    );
  }

  const actions = (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" icon={<FileUp size={16} />} onClick={() => setImportOpen(true)} data-testid="survey-import">
        {t('survey.action.import_points', { defaultValue: 'Import points' })}
      </Button>
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
    <div className="space-y-4">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }) }, { label: title }]} />
      <PageHeader
        srTitle={title}
        subtitle={
          <button
            type="button"
            data-testid="survey-crs-chip"
            onClick={() => setCrsOpen(true)}
            className="inline-flex items-center rounded-full border border-border-light px-2.5 py-0.5 text-xs hover:bg-surface-secondary"
            title={t('survey.crs.chip_tip', { defaultValue: 'Project coordinate system. Click to change.' })}
          >
            <bdi dir="ltr">{chip || t('survey.action.set_crs', { defaultValue: 'Set project CRS' })}</bdi>
          </button>
        }
        actions={actions}
      />
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
          { id: 'sets', label: t('survey.tab.point_sets', { defaultValue: 'Point sets' }) },
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
                  <Button variant="primary" onClick={() => setImportOpen(true)}>
                    {t('survey.action.import_points', { defaultValue: 'Import points' })}
                  </Button>
                  <Button variant="secondary" onClick={() => navigate('/onboarding/demo')}>
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
                    <tr key={p.id}>
                      <td><bdi dir="ltr" className="font-mono">{p.point_id}</bdi></td>
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

      <CrsDialog open={crsOpen} required={noCrs} projectId={projectId} state={crs.data} onClose={() => setCrsOpen(false)} />
      <SurveyImportDialog
        open={importOpen}
        projectId={projectId}
        projectEpsg={crs.data?.crs?.horizontal_epsg ?? null}
        onClose={() => setImportOpen(false)}
      />
    </div>
  );
}

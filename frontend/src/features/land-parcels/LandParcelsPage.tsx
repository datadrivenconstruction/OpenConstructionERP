// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Land & parcels (/survey/parcels): which land the works need, who holds
 * it, whether the project has it yet, and what it costs. Areas come from
 * the boundary points; findings PAR-001..006 come from the validation engine.
 */

import { Suspense, lazy, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Coins, FileDown, FileUp, LandPlot, Printer, Ruler } from 'lucide-react';
import {
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  KpiBand,
  Skeleton,
  StatusDot,
  TabBar,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui/ModuleGuideButton';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  PARTY_KINDS,
  createParty,
  deleteParty,
  downloadExport,
  downloadSchedule,
  getPlan,
  getProfile,
  getSummary,
  listParcels,
  listParties,
  listRights,
  type ImportTarget,
  type PartyKind,
} from './api';
import { ParcelDrawer } from './ParcelDrawer';
import { ParcelImportDialog } from './ParcelImportDialog';
import { STATUS_VARIANT, ruleIds } from './parcelFormat';
import { parcelsGuide } from './parcelsGuide';
import { fmtList } from '@/shared/lib/formatters';
import { useOpenSurveyDemo } from '@/features/survey/useOpenSurveyDemo';
import { ViewOnlyNote, useSurveyAccess } from '@/features/survey/useSurveyAccess';

const ParcelPlan = lazy(() => import('./ParcelPlan'));

type Tab = 'schedule' | 'plan' | 'rights';

export default function LandParcelsPage() {
  const { t, i18n } = useTranslation();
  const { canWrite } = useSurveyAccess();
  const openDemo = useOpenSurveyDemo('/survey/parcels');
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const [tab, setTab] = useState<Tab>('schedule');
  const [importTarget, setImportTarget] = useState<ImportTarget | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [planAsList, setPlanAsList] = useState(false);
  const [partyName, setPartyName] = useState('');
  const [partyKind, setPartyKind] = useState<PartyKind>('person');

  const enabled = !!projectId;
  const profile = useQuery({ queryKey: ['land-parcels', 'profile', projectId], queryFn: () => getProfile(projectId!), enabled });
  const summary = useQuery({ queryKey: ['land-parcels', 'summary', projectId], queryFn: () => getSummary(projectId!), enabled });
  const parcels = useQuery({
    queryKey: ['land-parcels', 'parcels', projectId, i18n.language],
    queryFn: () => listParcels(projectId!, i18n.language),
    enabled,
  });
  const plan = useQuery({ queryKey: ['land-parcels', 'plan', projectId], queryFn: () => getPlan(projectId!), enabled: enabled && tab === 'plan' });
  const parties = useQuery({ queryKey: ['land-parcels', 'parties', projectId], queryFn: () => listParties(projectId!), enabled: enabled && tab === 'rights' });
  const rights = useQuery({ queryKey: ['land-parcels', 'rights', projectId], queryFn: () => listRights(projectId!), enabled: enabled && tab === 'rights' });

  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const addParty = useMutation({
    mutationFn: () => createParty(projectId!, { name: partyName.trim(), kind: partyKind, reference: '', note: '' }),
    onSuccess: () => {
      setPartyName('');
      qc.invalidateQueries({ queryKey: ['land-parcels', 'parties'] });
    },
    onError,
  });
  const dropParty = useMutation({
    mutationFn: deleteParty,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['land-parcels'] }),
    onError,
  });

  const title = t('survey.parcels.title', { defaultValue: 'Land & parcels' });
  if (!projectId) {
    return (
      <div className="space-y-4">
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<LandPlot size={24} />}
          title={t('survey.parcels.no_project', { defaultValue: 'Open a project to see the land it needs.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => void openDemo.open() }}
        />
      </div>
    );
  }

  const idLabel = profile.data ? t(profile.data.id_label_key, { defaultValue: profile.data.id_label_default }) : t('survey.parcels.col.parcel_id', { defaultValue: 'Parcel ID' });
  const formats = profile.data?.export_formats ?? ['geojson', 'shapefile', 'dxf'];
  const s = summary.data;
  const statusLabel = (st: string) => t(`survey.parcels.status.${st}`, { defaultValue: st });
  const runDownload = (job: Promise<void>) => job.catch(onError);

  const actions = (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" icon={<FileUp size={16} />} onClick={() => setImportTarget('parcels')} data-testid="parcels-import" disabled={!canWrite}>
        {t('survey.parcels.btn.import', { defaultValue: 'Import parcels' })}
      </Button>
      <div className="relative">
        <Button
          variant="secondary"
          icon={<FileDown size={16} />}
          onClick={() => setExportOpen((v) => !v)}
          aria-expanded={exportOpen}
          data-testid="parcels-export"
          disabled={!s?.parcels}
        >
          {t('survey.parcels.btn.export', { defaultValue: 'Export' })}
        </Button>
        {exportOpen && (
          <ul role="menu" className="absolute end-0 z-20 mt-1 w-48 rounded-md border border-border-light bg-surface-primary py-1 shadow-lg">
            {formats.map((f) => (
              <li key={f}>
                <button
                  type="button"
                  role="menuitem"
                  className="w-full px-3 py-1.5 text-start text-sm hover:bg-surface-secondary"
                  onClick={() => {
                    setExportOpen(false);
                    void runDownload(downloadExport(projectId, f));
                  }}
                >
                  {t(`survey.parcels.format.${f}`, { defaultValue: f })}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button
        variant="secondary"
        icon={<Printer size={16} />}
        onClick={() => void runDownload(downloadSchedule(projectId, i18n.language))}
        data-testid="parcels-print"
        disabled={!s?.parcels}
      >
        {t('survey.parcels.btn.print', { defaultValue: 'Print schedule' })}
      </Button>
      <ModuleGuideButton content={parcelsGuide} />
    </div>
  );

  const kpis = [
    { key: 'parcels', label: t('survey.parcels.kpi.parcels', { defaultValue: 'Parcels' }), value: s?.parcels ?? 0, icon: LandPlot },
    {
      key: 'acquired',
      label: t('survey.parcels.kpi.acquired', { defaultValue: 'Acquired' }),
      value: t('survey.parcels.kpi.x_of_y', { defaultValue: '{{x}} of {{y}}', x: s?.acquired ?? 0, y: s?.parcels ?? 0 }),
      icon: CheckCircle2,
    },
    {
      key: 'area',
      label: t('survey.parcels.kpi.area', { defaultValue: 'Area' }),
      value: <QuantityDisplay value={s?.total_area ?? 0} unit="m²" precision={2} />,
      icon: Ruler,
    },
    {
      key: 'blocking',
      label: t('survey.parcels.kpi.blocking', { defaultValue: 'Blocking works' }),
      value: s?.blocking_works ?? 0,
      icon: AlertTriangle,
      tone: s?.blocking_works ? ('warning' as const) : undefined,
    },
    {
      key: 'cost',
      label: t('survey.parcels.kpi.cost', { defaultValue: 'Cost to acquire' }),
      value: <MoneyDisplay amount={s?.cost_to_acquire ?? '0'} currency={s?.currency} />,
      icon: Coins,
    },
  ];

  const rows = parcels.data ?? [];
  const empty = parcels.isSuccess && rows.length === 0;

  const scheduleTable = (
    <div className="overflow-x-auto">
      <table className="oe-table w-full text-sm" data-testid="parcels-table">
        <thead>
          <tr>
            <th>{idLabel}</th>
            {isAdvanced && <th>{t('survey.parcels.col.name', { defaultValue: 'Name' })}</th>}
            <th className="text-right" title={t('survey.parcels.tip.legal', { defaultValue: 'Area in the land register, m²' })}>
              {t('survey.parcels.col.legal', { defaultValue: 'Legal area' })}
            </th>
            <th className="text-right" title={t('survey.parcels.tip.computed', { defaultValue: 'Area worked out from the boundary points, m²' })}>
              {t('survey.parcels.col.computed', { defaultValue: 'Computed' })}
            </th>
            <th className="text-right" title={t('survey.parcels.tip.diff', { defaultValue: 'Difference between legal and computed area, m²' })}>
              {t('survey.parcels.col.diff', { defaultValue: 'Diff' })}
            </th>
            <th>{t('survey.parcels.col.status', { defaultValue: 'Status' })}</th>
            <th>{t('survey.parcels.col.rights', { defaultValue: 'Rights' })}</th>
            <th className="text-right">{t('survey.parcels.col.cost', { defaultValue: 'Cost' })}</th>
            <th>{t('survey.parcels.col.findings', { defaultValue: 'Findings' })}</th>
            {isAdvanced && <th>{t('survey.parcels.col.points', { defaultValue: 'Points' })}</th>}
            {isAdvanced && <th>EPSG</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id} className="cursor-pointer hover:bg-surface-secondary" onClick={() => setOpenId(p.id)} data-testid={`parcel-row-${p.parcel_ref}`}>
              <td>
                <bdi dir="ltr" className="font-mono">{p.parcel_ref}</bdi>
              </td>
              {isAdvanced && <td>{p.name}</td>}
              <td className="text-right">{p.legal_area ? <QuantityDisplay value={p.legal_area} unit="m²" precision={2} /> : '-'}</td>
              <td className="text-right">{p.computed_area ? <QuantityDisplay value={p.computed_area} unit="m²" precision={2} /> : '-'}</td>
              <td className="text-right">{p.area_diff ? <QuantityDisplay value={p.area_diff} unit="m²" precision={2} /> : '-'}</td>
              <td>
                <StatusDot variant={STATUS_VARIANT[p.status]} label={statusLabel(p.status)} />
                <span className="ms-2">{statusLabel(p.status)}</span>
              </td>
              <td>{fmtList(p.rights_kinds.map((k) => t(`survey.parcels.right.${k}`, { defaultValue: k })))}</td>
              <td className="text-right">{p.acquisition_cost ? <MoneyDisplay amount={p.acquisition_cost} currency={p.currency} /> : '-'}</td>
              <td>
                {ruleIds(p.findings).map((id) => (
                  <span
                    key={id}
                    className="me-1 inline-block rounded bg-semantic-warning/15 px-1.5 font-mono text-xs"
                    title={p.findings.filter((f) => f.rule_id === id).map((f) => f.message).join('\n')}
                  >
                    {id}
                  </span>
                ))}
              </td>
              {isAdvanced && <td>{p.point_count}</td>}
              {isAdvanced && <td>{p.epsg ?? ''}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }), to: '/survey' }, { label: title }]} />
      <PageHeader srTitle={title} actions={actions} />
      <ViewOnlyNote />
      <DismissibleInfo storageKey="survey.parcels.info" title={t('survey.register.info_title', { defaultValue: 'What is this' })}>
        {t('survey.parcels.info', {
          defaultValue:
            'Each parcel is a piece of land with a boundary, an area from its points, the area in the register, who holds rights on it, and whether the project has acquired it. Rights are kept as data, not legal advice.',
        })}
      </DismissibleInfo>

      <div data-testid="parcels-kpi">
        <KpiBand items={kpis} columns={5} size="sm" />
      </div>

      <TabBar<Tab>
        ariaLabel={title}
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: 'schedule', label: t('survey.parcels.tab.schedule', { defaultValue: 'Schedule' }) },
          { id: 'plan', label: t('survey.parcels.tab.plan', { defaultValue: 'Plan' }) },
          { id: 'rights', label: t('survey.parcels.tab.rights', { defaultValue: 'Parties & rights' }) },
        ]}
      />

      {tab === 'schedule' && (
        <Card className="p-0 overflow-hidden">
          {parcels.isLoading ? (
            <Skeleton className="h-48 m-3" />
          ) : parcels.isError ? (
            <ErrorState title={getErrorMessage(parcels.error)} onRetry={() => parcels.refetch()} />
          ) : empty ? (
            <EmptyState
              icon={<LandPlot size={24} />}
              title={t('survey.parcels.empty', { defaultValue: 'No parcels yet' })}
              description={t('survey.parcels.empty_hint', {
                defaultValue: 'Import the parcel boundaries as GeoJSON or a zipped Shapefile. The preview shows each area before anything is saved.',
              })}
              action={{ label: t('survey.parcels.btn.import', { defaultValue: 'Import parcels' }), onClick: () => setImportTarget('parcels') }}
            />
          ) : (
            <>
              {scheduleTable}
              <div className="border-t border-border-light p-3">
                <Button size="sm" variant="secondary" onClick={() => setImportTarget('work_zone')} data-testid="parcels-import-zone">
                  {t('survey.parcels.btn.import_zone', { defaultValue: 'Import work zone' })}
                </Button>
              </div>
            </>
          )}
        </Card>
      )}

      {tab === 'plan' && (
        <div className="space-y-2">
          <label className="inline-flex items-center gap-2 text-sm">
            <input type="checkbox" checked={planAsList} onChange={(e) => setPlanAsList(e.target.checked)} />
            {t('survey.parcels.plan_as_list', { defaultValue: 'List of features' })}
          </label>
          {plan.isLoading ? (
            <Skeleton className="h-[480px]" />
          ) : plan.isError ? (
            <ErrorState title={getErrorMessage(plan.error)} onRetry={() => plan.refetch()} />
          ) : planAsList || !plan.data || plan.data.local || plan.data.features.length === 0 ? (
            <Card className="p-3">
              {plan.data?.local && (
                <p className="mb-2 text-sm text-content-secondary">
                  {t('survey.parcels.plan_local', { defaultValue: 'The project uses a local grid, so the parcels cannot be placed on a world map.' })}
                </p>
              )}
              {scheduleTable}
            </Card>
          ) : (
            <Suspense fallback={<Skeleton className="h-[480px]" />}>
              <ParcelPlan plan={plan.data} />
            </Suspense>
          )}
          <p className="text-xs text-content-tertiary">
            {t('survey.parcels.plan_legend', {
              defaultValue: 'Green: Acquired. Amber: Negotiating. Grey: Needed. Red: Expropriation. Blue line: work zone. Dashed red edge: blocks the works.',
            })}
          </p>
        </div>
      )}

      {tab === 'rights' && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-3 space-y-2">
            <h3 className="font-medium">{t('survey.parcels.parties', { defaultValue: 'Parties' })}</h3>
            <ul className="space-y-1 text-sm">
              {(parties.data ?? []).map((x) => (
                <li key={x.id} className="flex items-center gap-2">
                  <span className="flex-1">{x.name}</span>
                  <span className="text-content-tertiary">{t(`survey.parcels.party.${x.kind}`, { defaultValue: x.kind })}</span>
                  <Button size="sm" variant="ghost" onClick={() => dropParty.mutate(x.id)}>
                    {t('common.delete', { defaultValue: 'Delete' })}
                  </Button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              <input
                className="oe-input flex-1"
                value={partyName}
                onChange={(e) => setPartyName(e.target.value)}
                placeholder={t('survey.parcels.party_name', { defaultValue: 'Owner, holder or authority' })}
              />
              <select className="oe-input w-40" value={partyKind} onChange={(e) => setPartyKind(e.target.value as PartyKind)}>
                {PARTY_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`survey.parcels.party.${k}`, { defaultValue: k })}
                  </option>
                ))}
              </select>
              <Button size="sm" variant="secondary" disabled={!partyName.trim()} onClick={() => addParty.mutate()}>
                {t('survey.parcels.btn.add_party', { defaultValue: 'Add party' })}
              </Button>
            </div>
          </Card>
          <Card className="p-3 space-y-2">
            <h3 className="font-medium">{t('survey.parcels.rights', { defaultValue: 'Rights and encumbrances' })}</h3>
            <p className="text-xs text-content-tertiary">
              {t('survey.parcels.rights_note', { defaultValue: 'Recorded as data from the register. This is not legal advice.' })}
            </p>
            <ul className="space-y-1 text-sm">
              {(rights.data ?? []).map((r) => (
                <li key={r.id}>
                  <bdi dir="ltr" className="font-mono">{rows.find((p) => p.id === r.parcel_id)?.parcel_ref ?? ''}</bdi>{' '}
                  <span className="font-medium">{t(`survey.parcels.right.${r.kind}`, { defaultValue: r.kind })}</span>{' '}
                  <span className="text-content-secondary">{[r.party_name, r.description].filter(Boolean).join(' · ')}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-content-tertiary">
              {t('survey.parcels.rights_add_hint', { defaultValue: 'Open a parcel on the Schedule tab to add a right to it.' })}
            </p>
          </Card>
        </div>
      )}

      {importTarget && (
        <ParcelImportDialog open projectId={projectId} initialTarget={importTarget} onClose={() => setImportTarget(null)} />
      )}
      <ParcelDrawer parcelId={openId} projectId={projectId} idLabel={idLabel} onClose={() => setOpenId(null)} />
    </div>
  );
}

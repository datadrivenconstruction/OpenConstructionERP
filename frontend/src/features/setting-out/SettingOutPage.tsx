// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Setting-out (/survey/setting-out): stakeout requests, their design stakes,
 * the measured values with an instant Pass/Fail, NCR drafts for fails, and the
 * printable setting-out sheet. On a phone each stake is one card.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, CircleDashed, FileUp, FileWarning, Plus, Printer, Target, XCircle } from 'lucide-react';
import {
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  InfoHint,
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
import { getProjectCrs } from '@/features/survey/api';
import { crsChipText } from '@/features/survey/crsPicker';
import { CrsDialog } from '@/features/survey/CrsDialog';
import { GridGroundChip } from '@/features/survey/GeodesyPanel';
import { SurveyExportMenu } from '@/features/survey/SurveyExportMenu';
import {
  acceptDeviation,
  createNcrDraft,
  createNcrDrafts,
  downloadSheet,
  getRequest,
  getSettings,
  getSummary,
  listProfiles,
  listRequests,
  putSettings,
  validateSettingOut,
  type SettingOutSettings,
} from './api';
import { SourceNote, splitReference } from './SourceNote';
import { DesignImportDialog } from './DesignImportDialog';
import { NewRequestDialog, profileLabel } from './NewRequestDialog';
import { StakeCard, VerdictBadge } from './StakeCard';
import { RoadStakePanel } from '@/features/survey-calc/RoadStakePanel';
import { settingOutGuide } from './settingOutGuide';
import { fmtCoord, fmtMm } from './verdict';
import { fmtFixed } from '@/shared/lib/formatters';
import { useOpenSurveyDemo } from '@/features/survey/useOpenSurveyDemo';
import { ViewOnlyNote, useSurveyAccess } from '@/features/survey/useSurveyAccess';

type View = 'table' | 'field';

function usePhone(): boolean {
  const query = '(max-width: 767px)';
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setPhone(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return phone;
}

export default function SettingOutPage() {
  const { t, i18n } = useTranslation();
  const { canWrite } = useSurveyAccess();
  const openDemo = useOpenSurveyDemo('/survey/setting-out');
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const phone = usePhone();
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<View>('table');
  const [newOpen, setNewOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [crsOpen, setCrsOpen] = useState(false);
  const [accepting, setAccepting] = useState<string | null>(null);
  const [acceptNote, setAcceptNote] = useState('');

  const enabled = !!projectId;
  const crs = useQuery({ queryKey: ['survey', 'crs', projectId], queryFn: () => getProjectCrs(projectId!), enabled });
  const profiles = useQuery({ queryKey: ['setting-out', 'profiles', projectId], queryFn: () => listProfiles(projectId!), enabled });
  const requests = useQuery({ queryKey: ['setting-out', 'requests', projectId], queryFn: () => listRequests(projectId!), enabled });
  const summary = useQuery({ queryKey: ['setting-out', 'summary', projectId], queryFn: () => getSummary(projectId!), enabled });
  const settings = useQuery({ queryKey: ['setting-out', 'settings', projectId], queryFn: () => getSettings(projectId!), enabled });
  const findings = useQuery({
    queryKey: ['setting-out', 'findings', projectId, i18n.language],
    queryFn: () => validateSettingOut(projectId!, i18n.language),
    enabled,
  });
  const activeId = selected ?? requests.data?.[0]?.id ?? null;
  const detail = useQuery({
    queryKey: ['setting-out', 'request', activeId],
    queryFn: () => getRequest(activeId!),
    enabled: !!activeId,
  });

  const ncr = useMutation({
    mutationFn: (recordId: string) => createNcrDraft(recordId, i18n.language),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['setting-out'] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const saveSettings = useMutation({
    mutationFn: (body: Partial<SettingOutSettings>) => putSettings(projectId!, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['setting-out', 'settings', projectId] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const bulkNcr = useMutation({
    mutationFn: () => createNcrDrafts(projectId!, i18n.language),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['setting-out'] });
      addToast({
        type: 'success',
        title: t('survey.setting_out.bulk_ncr_done', { defaultValue: 'NCR drafts created: {{n}}', n: r.created.length }),
      });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const accept = useMutation({
    mutationFn: ({ recordId, note }: { recordId: string; note: string }) => acceptDeviation(recordId, note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['setting-out'] });
      setAccepting(null);
      setAcceptNote('');
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const title = t('survey.page.setting_out', { defaultValue: 'Setting-out' });
  const chip = crsChipText(crs.data?.crs ?? null, t('survey.crs.local', { defaultValue: 'Local grid' }));
  const stakesByRef = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of detail.data?.stakes ?? []) if (s.latest) m.set(`${detail.data!.code}/${s.point_id}`, s.latest.id);
    return m;
  }, [detail.data]);

  if (!projectId) {
    return (
      <div className="space-y-4">
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<Target size={24} />}
          title={t('survey.setting_out.no_project', { defaultValue: 'Open a project to see its setting-out requests.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => void openDemo.open() }}
        />
      </div>
    );
  }

  const req = detail.data;
  const actions = (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" icon={<Plus size={16} />} onClick={() => setNewOpen(true)} data-testid="so-new-request" disabled={!canWrite}>
        {t('survey.setting_out.action.new_request', { defaultValue: 'New request' })}
      </Button>
      <Button variant="secondary" icon={<Printer size={16} />} disabled={!req}
        onClick={() => req && downloadSheet(req.id, req.code).catch((e) => addToast({ type: 'error', title: getErrorMessage(e) }))}
        data-testid="so-print-sheet">
        {t('survey.setting_out.action.print_sheet', { defaultValue: 'Print sheet' })}
      </Button>
      {req && projectId && (
        <SurveyExportMenu target={{ kind: 'stakes', projectId, requestId: req.id, code: req.code }} disabled={!req.stakes.length} />
      )}
      <ModuleGuideButton content={settingOutGuide} />
    </div>
  );

  const kpis = [
    { key: 'open', label: t('survey.setting_out.kpi.open', { defaultValue: 'Open' }), value: summary.data?.open ?? 0, icon: CircleDashed },
    { key: 'passed', label: t('survey.setting_out.kpi.passed', { defaultValue: 'Passed' }), value: summary.data?.passed ?? 0, icon: CheckCircle2 },
    { key: 'failed', label: t('survey.setting_out.kpi.failed', { defaultValue: 'Failed' }), value: summary.data?.failed ?? 0, icon: XCircle },
    { key: 'ncr', label: t('survey.setting_out.kpi.ncr_drafts', { defaultValue: 'NCR drafts' }), value: summary.data?.ncr_drafts ?? 0, icon: FileWarning },
  ];
  const showCards = phone || view === 'field';
  const defaultProfile = (profiles.data ?? []).find((p) => p.key === settings.data?.default_tolerance_key);
  const reqSource = splitReference(req?.tolerance_reference);
  const unresolved = (findings.data?.findings ?? []).filter((f) => f.rule_id === 'SET-003').length;
  const tolText = req
    ? req.tol_h_mm != null
      ? `${req.tolerance_label} ${fmtMm(req.tol_h_mm)} mm`.trim()
      : t('survey.setting_out.profile.none', { defaultValue: 'No profile, set one' })
    : '';

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }), to: '/survey' }, { label: title }]} />
      <PageHeader
        srTitle={title}
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => setCrsOpen(true)}
              className="inline-flex items-center rounded-full border border-border-light px-2.5 py-0.5 text-xs hover:bg-surface-secondary"
              title={t('survey.crs.chip_tip', { defaultValue: 'Project coordinate system. Click to change.' })}>
              <bdi dir="ltr">{chip || t('survey.action.set_crs', { defaultValue: 'Set project CRS' })}</bdi>
            </button>
            {projectId && <GridGroundChip projectId={projectId} />}
          </span>
        }
        actions={actions}
      />
      <ViewOnlyNote />
      <DismissibleInfo storageKey="survey.setting_out.info" title={t('survey.register.info_title', { defaultValue: 'What is this' })}>
        {t('survey.setting_out.what_is', {
          defaultValue:
            'Marking design positions on site and checking them. Type what the instrument measured and you see at once whether the stake is within tolerance.',
        })}
      </DismissibleInfo>
      <CollapsibleSection storageKey="survey.setting_out.how" title={t('guide.button', { defaultValue: 'How it works' })} defaultCollapsed>
        <ol className="list-decimal ps-5 space-y-1 text-sm">
          <li>{t('survey.setting_out.how_1', { defaultValue: 'Create a request and pick the tolerance profile, then import the design points or an alignment.' })}</li>
          <li>{t('survey.setting_out.how_2', { defaultValue: 'On site, type the measured E and N for each stake: Pass or Fail shows at once.' })}</li>
          <li>{t('survey.setting_out.how_3', { defaultValue: 'A failed stake opens an NCR draft in Quality with one button. Print the sheet for the file.' })}</li>
          <li>{t('survey.setting_out.how_4', { defaultValue: 'Every failed stake needs an NCR draft or an accepted deviation (SET-003). Turn on automatic NCR drafts for the project if you always raise one.' })}</li>
        </ol>
        <dl className="mt-3 grid gap-1 text-sm">
          {(['setting_out', 'tolerance', 'chainage'] as const).map((k) => (
            <div key={k}>
              <dt className="inline font-semibold">{t(`survey.glossary.${k}`, { defaultValue: k })}: </dt>
              <dd className="inline text-content-secondary">{t(`survey.glossary.${k}_def`, { defaultValue: '' })}</dd>
            </div>
          ))}
        </dl>
      </CollapsibleSection>

      <KpiBand items={kpis} columns={4} size="sm" />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" data-testid="so-settings">
        <label className="inline-flex flex-wrap items-center gap-2">
          <span className="font-semibold">{t('survey.setting_out.settings.default_profile', { defaultValue: 'Project tolerance profile' })}</span>
          <select className="oe-input" value={settings.data?.default_tolerance_key ?? ''} disabled={!canWrite || saveSettings.isPending}
            onChange={(e) => saveSettings.mutate({ default_tolerance_key: e.target.value })} data-testid="so-default-profile"
            title={t('survey.setting_out.settings.default_profile_tip', { defaultValue: 'Preselected for every new request. Country profiles show only for the markets of your company profile.' })}>
            <option value="">{t('survey.setting_out.profile.none', { defaultValue: 'No profile, set one' })}</option>
            {(profiles.data ?? []).map((p) => (
              <option key={p.key} value={p.key}>{profileLabel(p, t)}</option>
            ))}
          </select>
        </label>
        {defaultProfile && <SourceNote reference={defaultProfile.reference} />}
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={!!settings.data?.auto_ncr} disabled={!canWrite || saveSettings.isPending}
            onChange={(e) => saveSettings.mutate({ auto_ncr: e.target.checked })} data-testid="so-auto-ncr" />
          <span>{t('survey.setting_out.settings.auto_ncr', { defaultValue: 'Create an NCR draft automatically when a stake fails tolerance' })}</span>
        </label>
      </div>

      {findings.data && findings.data.findings.length > 0 && (
        <Card className="p-3" data-testid="so-findings">
          {unresolved > 0 && canWrite && (
            <div className="mb-2 flex justify-end">
              <Button size="sm" variant="secondary" icon={<FileWarning size={14} />} disabled={bulkNcr.isPending}
                onClick={() => bulkNcr.mutate()} data-testid="so-bulk-ncr">
                {t('survey.setting_out.action.bulk_ncr', { defaultValue: 'Create NCRs for all failures ({{n}})', n: unresolved })}
              </Button>
            </div>
          )}
          <ul className="space-y-1 text-sm">
            {findings.data.findings.map((f, i) => {
              const recordId = f.element_ref ? stakesByRef.get(f.element_ref) : undefined;
              const linked = recordId && detail.data?.stakes.find((s) => s.latest?.id === recordId)?.latest?.ncr_id;
              return (
                <li key={i} className="flex items-start gap-2">
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${f.severity === 'error' ? 'bg-semantic-error' : 'bg-semantic-warning'}`} aria-hidden />
                  <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span>
                  <span className="flex-1">
                    {f.message}
                    {f.suggestion && <span className="text-content-secondary"> {f.suggestion}</span>}
                  </span>
                  {f.rule_id === 'SET-003' && recordId && !linked && canWrite && (
                    <span className="flex flex-wrap gap-1">
                      <Button size="sm" variant="secondary" disabled={ncr.isPending} onClick={() => ncr.mutate(recordId)}>
                        {t('survey.setting_out.action.create_ncr', { defaultValue: 'Create NCR draft' })}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => { setAccepting(recordId); setAcceptNote(''); }}>
                        {t('survey.setting_out.action.accept_deviation', { defaultValue: 'Accept deviation' })}
                      </Button>
                    </span>
                  )}
                  {accepting && accepting === recordId && f.rule_id === 'SET-003' && (
                    <form className="flex w-full flex-wrap items-center gap-2 ps-4"
                      onSubmit={(e) => { e.preventDefault(); if (acceptNote.trim()) accept.mutate({ recordId: accepting, note: acceptNote.trim() }); }}>
                      <input className="oe-input flex-1" value={acceptNote} onChange={(e) => setAcceptNote(e.target.value)} autoFocus
                        aria-label={t('survey.setting_out.accept_reason', { defaultValue: 'Why is this deviation acceptable?' })}
                        placeholder={t('survey.setting_out.accept_reason', { defaultValue: 'Why is this deviation acceptable?' })} />
                      <Button size="sm" variant="primary" type="submit" disabled={!acceptNote.trim() || accept.isPending}>
                        {t('survey.setting_out.action.accept_deviation', { defaultValue: 'Accept deviation' })}
                      </Button>
                      <Button size="sm" variant="ghost" type="button" onClick={() => setAccepting(null)}>
                        {t('common.cancel', { defaultValue: 'Cancel' })}
                      </Button>
                    </form>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {requests.isLoading ? (
        <Skeleton className="h-40" />
      ) : requests.isError ? (
        <ErrorState title={getErrorMessage(requests.error)} onRetry={() => requests.refetch()} />
      ) : (requests.data ?? []).length === 0 ? (
        <EmptyState
          icon={<Target size={24} />}
          title={t('survey.setting_out.empty', { defaultValue: 'No setting-out requests yet. Create one, or try the course example.' })}
          action={
            <div className="flex flex-wrap gap-2 justify-center">
              <Button variant="primary" onClick={() => setNewOpen(true)}>
                {t('survey.setting_out.action.new_request', { defaultValue: 'New request' })}
              </Button>
              <Button variant="secondary" onClick={() => void openDemo.open()}>
                {t('survey.action.open_demo', { defaultValue: 'Open demo project' })}
              </Button>
            </div>
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap gap-2" role="list">
            {(requests.data ?? []).map((r) => (
              <button key={r.id} type="button" role="listitem" onClick={() => setSelected(r.id)}
                className={`rounded-lg border px-3 py-2 text-start text-sm ${r.id === activeId ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light hover:bg-surface-secondary'}`}>
                <div className="font-semibold">{r.name}</div>
                <div className="text-xs text-content-secondary">
                  <bdi dir="ltr">{r.code}</bdi> · {r.point_count} · {t('survey.setting_out.kpi.passed', { defaultValue: 'Passed' })} {r.pass_count} ·{' '}
                  {t('survey.setting_out.kpi.failed', { defaultValue: 'Failed' })} {r.fail_count}
                </div>
              </button>
            ))}
          </div>

          {detail.isLoading ? (
            <Skeleton className="h-48" />
          ) : req ? (
            <Card className="p-0 overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 p-3 border-b border-border-light">
                <div>
                  <div className="font-semibold" data-testid="so-request-title">
                    {t('survey.setting_out.request_label', { defaultValue: 'Request' })} "{req.name}"
                  </div>
                  <div className="text-sm text-content-secondary flex items-center gap-1" data-testid="so-request-tolerance">
                    {t('survey.setting_out.field.tolerance_short', { defaultValue: 'Tolerance' })}: {tolText}
                    <InfoHint inline text={t('survey.glossary.tolerance_def', { defaultValue: 'The allowed difference between the design and the staked position.' })} />
                    {reqSource.text && <SourceNote reference={reqSource.text} status={reqSource.status} testId="so-request-source" />}
                    {req.alignment && (
                      <span>
                        {' · '}
                        {t('survey.setting_out.alignment_found', {
                          defaultValue: 'Alignment {{name}}, {{length}} m',
                          name: req.alignment.name,
                          length: fmtFixed(req.alignment.length, 3),
                        })}
                      </span>
                    )}
                  </div>
                  {isAdvanced && (req.element_ref_label || req.instrument) && (
                    <div className="text-xs text-content-tertiary">
                      {req.element_ref_type.toUpperCase()} {req.element_ref_label} · {req.instrument} · {req.control_ref}
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" icon={<FileUp size={14} />} onClick={() => setImportOpen(true)}>
                    {t('survey.setting_out.action.import_design', { defaultValue: 'Import design' })}
                  </Button>
                </div>
              </div>
              {!phone && (
                <div className="px-3 pt-2">
                  <TabBar<View>
                    ariaLabel={req.name}
                    activeId={view}
                    onChange={setView}
                    tabs={[
                      { id: 'table', label: t('survey.setting_out.view.table', { defaultValue: 'Table' }) },
                      { id: 'field', label: t('survey.setting_out.view.field', { defaultValue: 'Field cards' }) },
                    ]}
                  />
                </div>
              )}
              {req.stakes.length === 0 ? (
                <EmptyState
                  icon={<Target size={24} />}
                  title={t('survey.setting_out.no_stakes', { defaultValue: 'No design points yet. Import a CSV or LandXML file.' })}
                  action={{ label: t('survey.setting_out.action.import_design', { defaultValue: 'Import design' }), onClick: () => setImportOpen(true) }}
                />
              ) : showCards ? (
                <div className="grid gap-3 p-3 sm:grid-cols-2 lg:grid-cols-3">
                  {req.stakes.map((s) => (
                    <StakeCard key={s.id} stake={s} tolH={req.tol_h_mm} tolV={req.tol_v_mm} instrument={req.instrument} controlRef={req.control_ref} canWrite={canWrite} />
                  ))}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="oe-table w-full text-sm">
                    <thead>
                      <tr>
                        <th>{t('survey.setting_out.col.point', { defaultValue: 'Point' })}</th>
                        <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.setting_out.col.design_e', { defaultValue: 'Design E' })}</th>
                        <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.setting_out.col.design_n', { defaultValue: 'Design N' })}</th>
                        {isAdvanced && <th className="text-right">{t('survey.setting_out.col.chainage', { defaultValue: 'Chainage (m)' })}</th>}
                        {isAdvanced && <th className="text-right">{t('survey.setting_out.col.offset', { defaultValue: 'Offset (m)' })}</th>}
                        <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.setting_out.col.measured_e', { defaultValue: 'Measured E' })}</th>
                        <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.setting_out.col.measured_n', { defaultValue: 'Measured N' })}</th>
                        <th className="text-right" title={t('survey.setting_out.tip.d', { defaultValue: 'd (mm): horizontal distance between design and measured position, sqrt(dE² + dN²).' })}>{t('survey.setting_out.col.d', { defaultValue: 'd (mm)' })}</th>
                        <th className="text-right" title={t('survey.setting_out.tip.dz', { defaultValue: 'dZ (mm): measured height minus design height.' })}>{t('survey.setting_out.col.dz', { defaultValue: 'dZ' })}</th>
                        <th>{t('survey.setting_out.col.verdict', { defaultValue: 'Verdict' })}</th>
                        <th>{t('survey.setting_out.col.by', { defaultValue: 'By' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {req.stakes.map((s) => (
                        <tr key={s.id} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setView('field')}>
                          <td><bdi dir="ltr" className="font-mono">{s.point_id}</bdi></td>
                          <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(s.design_e)}</bdi></td>
                          <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(s.design_n)}</bdi></td>
                          {isAdvanced && <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(s.chainage)}</bdi></td>}
                          {isAdvanced && <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(s.offset_m)}</bdi></td>}
                          <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(s.latest?.measured_e)}</bdi></td>
                          <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(s.latest?.measured_n)}</bdi></td>
                          <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtMm(s.latest?.d_mm)}</bdi></td>
                          <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtMm(s.latest?.dz_mm)}</bdi></td>
                          <td><VerdictBadge state={s.verdict} /></td>
                          <td className="text-content-secondary">{s.latest?.measured_by ?? ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ) : null}
        </>
      )}

      {projectId && (
        <CollapsibleSection storageKey="survey.setting_out.road" title={t('survey.road.title', { defaultValue: 'Road and rail stake list' })} defaultCollapsed>
          <RoadStakePanel />
        </CollapsibleSection>
      )}

      <NewRequestDialog open={newOpen} projectId={projectId} profiles={profiles.data ?? []} defaultKey={settings.data?.default_tolerance_key ?? ''} onClose={() => setNewOpen(false)} onCreated={(r) => setSelected(r.id)} />
      {activeId && <DesignImportDialog open={importOpen} requestId={activeId} onClose={() => setImportOpen(false)} />}
      <CrsDialog open={crsOpen} projectId={projectId} state={crs.data} onClose={() => setCrsOpen(false)} />
    </div>
  );
}

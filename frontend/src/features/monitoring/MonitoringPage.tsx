// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Monitoring (/survey/monitoring): the points under watch, their level against
 * the active threshold profile, readings import, Acknowledge and the alarm report.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, AlertOctagon, AlertTriangle, BellRing, CalendarClock, Printer, Upload } from 'lucide-react';
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
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui/ModuleGuideButton';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  downloadReport,
  getSettings,
  getSummary,
  listPoints,
  listProfiles,
  loadDemo,
  setProfile,
  validateMonitoring,
} from './api';
import { ImportReadingsDialog } from './ImportReadingsDialog';
import { LevelBadge, PointDrawer } from './PointDrawer';
import { fmtMm, fmtRate } from './levels';
import { monitoringGuide } from './monitoringGuide';

export default function MonitoringPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const [selected, setSelected] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const enabled = !!projectId;
  const points = useQuery({ queryKey: ['monitoring', 'points', projectId], queryFn: () => listPoints(projectId!), enabled });
  const summary = useQuery({ queryKey: ['monitoring', 'summary', projectId], queryFn: () => getSummary(projectId!), enabled });
  const settings = useQuery({ queryKey: ['monitoring', 'settings', projectId], queryFn: () => getSettings(projectId!), enabled });
  const profiles = useQuery({ queryKey: ['monitoring', 'profiles', projectId], queryFn: () => listProfiles(projectId!), enabled });
  const findings = useQuery({
    queryKey: ['monitoring', 'findings', projectId, i18n.language, summary.data?.last_epoch],
    queryFn: () => validateMonitoring(projectId!, i18n.language),
    enabled,
  });

  const demo = useMutation({
    mutationFn: () => loadDemo(projectId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['monitoring'] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const pick = useMutation({
    mutationFn: (key: string) => setProfile(projectId!, key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['monitoring'] }),
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const title = t('survey.page.monitoring', { defaultValue: 'Monitoring' });
  const rows = useMemo(() => points.data ?? [], [points.data]);

  if (!projectId) {
    return (
      <div className="space-y-4">
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<Activity size={24} />}
          title={t('survey.monitoring.no_project', { defaultValue: 'Open a project to see its monitoring points.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => navigate('/onboarding/demo') }}
        />
      </div>
    );
  }

  const s = summary.data;
  const kpis = [
    { key: 'points', label: t('survey.monitoring.kpi.points', { defaultValue: 'Points' }), value: s?.points ?? 0, icon: Activity },
    { key: 'alarm', label: t('survey.monitoring.kpi.alarm', { defaultValue: 'Alarm' }), value: s?.alarm ?? 0, icon: AlertOctagon },
    { key: 'action', label: t('survey.monitoring.kpi.action', { defaultValue: 'Action' }), value: s?.action ?? 0, icon: BellRing },
    { key: 'alert', label: t('survey.monitoring.kpi.alert', { defaultValue: 'Alert' }), value: s?.alert ?? 0, icon: AlertTriangle },
    {
      key: 'last',
      label: t('survey.monitoring.kpi.last_epoch', { defaultValue: 'Last epoch' }),
      value: s?.last_epoch ? new Date(s.last_epoch).toLocaleDateString(i18n.language) : '',
      icon: CalendarClock,
    },
  ];

  const actions = (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" icon={<Upload size={16} />} onClick={() => setImportOpen(true)} data-testid="mon-import">
        {t('survey.monitoring.action.import_readings', { defaultValue: 'Import readings' })}
      </Button>
      <Button
        variant="secondary"
        icon={<Printer size={16} />}
        disabled={rows.length === 0}
        onClick={() => downloadReport(projectId).catch((e) => addToast({ type: 'error', title: getErrorMessage(e) }))}
        data-testid="mon-report"
      >
        {t('survey.monitoring.action.print_report', { defaultValue: 'Print alarm report' })}
      </Button>
      <ModuleGuideButton content={monitoringGuide} />
    </div>
  );

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }), to: '/survey' }, { label: title }]} />
      <PageHeader srTitle={title} actions={actions} />
      <DismissibleInfo storageKey="survey.monitoring.info" title={t('survey.register.info_title', { defaultValue: 'What is this' })}>
        {t('survey.monitoring.what_is', {
          defaultValue:
            'Repeated surveys of the same points show how a structure or the ground moves. Each new epoch is compared with the limits of the profile.',
        })}
      </DismissibleInfo>
      <CollapsibleSection storageKey="survey.monitoring.how" title={t('guide.button', { defaultValue: 'How it works' })} defaultCollapsed>
        <ol className="list-decimal space-y-1 ps-5 text-sm">
          <li>{t('survey.monitoring.how_1', { defaultValue: 'Pick the limits (the profile) for this project.' })}</li>
          <li>{t('survey.monitoring.how_2', { defaultValue: 'Import each survey epoch as a CSV: point, date, Z.' })}</li>
          <li>{t('survey.monitoring.how_3', { defaultValue: 'When a limit is crossed you get a notification; Acknowledge it with a note.' })}</li>
        </ol>
        <dl className="mt-3 grid gap-1 text-sm">
          {(['epoch', 'displacement'] as const).map((k) => (
            <div key={k}>
              <dt className="inline font-semibold">{t(`survey.monitoring.glossary.${k}`, { defaultValue: k })}: </dt>
              <dd className="inline text-content-secondary">{t(`survey.monitoring.glossary.${k}_def`, { defaultValue: '' })}</dd>
            </div>
          ))}
        </dl>
      </CollapsibleSection>

      <KpiBand items={kpis} columns={5} size="sm" />

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="mon-profile" className="font-semibold">
          {t('survey.monitoring.profile.label', { defaultValue: 'Limits' })}
        </label>
        <select
          id="mon-profile"
          className="oe-input"
          value={settings.data?.profile_key ?? ''}
          disabled={pick.isPending}
          onChange={(e) => pick.mutate(e.target.value)}
          data-testid="mon-profile"
        >
          <option value="">{t('survey.monitoring.profile.none', { defaultValue: 'No profile, set one' })}</option>
          {(profiles.data ?? []).map((p) => (
            <option key={p.key} value={p.key}>
              {p.name}
            </option>
          ))}
        </select>
        {settings.data?.profile?.source === 'demo' && (
          <span className="text-xs text-content-tertiary">
            {t('survey.monitoring.profile.demo_note', { defaultValue: 'Demo values, not a standard' })}
          </span>
        )}
      </div>

      {findings.data && findings.data.findings.length > 0 && (
        <Card className="p-3" data-testid="mon-findings">
          <ul className="space-y-1 text-sm">
            {findings.data.findings.map((f, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${f.severity === 'error' ? 'bg-semantic-error' : 'bg-semantic-warning'}`} aria-hidden />
                <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span>
                <span className="flex-1">
                  {f.message}
                  {f.suggestion && <span className="text-content-secondary"> {f.suggestion}</span>}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {points.isLoading ? (
        <Skeleton className="h-40" />
      ) : points.isError ? (
        <ErrorState title={getErrorMessage(points.error)} onRetry={() => points.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Activity size={24} />}
          title={t('survey.monitoring.empty', { defaultValue: 'No monitoring points yet. Import readings, or try the course example.' })}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" onClick={() => setImportOpen(true)}>
                {t('survey.monitoring.action.import_readings', { defaultValue: 'Import readings' })}
              </Button>
              <Button variant="ghost" disabled={demo.isPending} onClick={() => demo.mutate()} data-testid="mon-load-demo">
                {t('survey.monitoring.action.load_example', { defaultValue: 'Load the course example' })}
              </Button>
            </div>
          }
        />
      ) : (
        <Card className="overflow-hidden p-0" data-testid="mon-points">
          <div className="overflow-x-auto">
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  <th>{t('survey.monitoring.col.point', { defaultValue: 'Point' })}</th>
                  <th>{t('survey.monitoring.col.type', { defaultValue: 'Type' })}</th>
                  <th className="text-right">{t('survey.monitoring.col.epochs', { defaultValue: 'Epochs' })}</th>
                  <th className="text-right">{t('survey.monitoring.col.displacement', { defaultValue: 'Displacement (mm)' })}</th>
                  <th className="text-right">{t('survey.monitoring.col.rate', { defaultValue: 'Rate (mm/day)' })}</th>
                  <th>{t('survey.monitoring.col.level', { defaultValue: 'Level' })}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} tabIndex={0} className="cursor-pointer" onClick={() => setSelected(p.id)} onKeyDown={(e) => e.key === 'Enter' && setSelected(p.id)}>
                    <td>
                      <bdi dir="ltr" className="font-mono">{p.code}</bdi>
                      {p.name && <span className="ms-2 text-content-secondary">{p.name}</span>}
                    </td>
                    <td className="text-content-secondary">{t(`survey.monitoring.type.${p.point_type}`, { defaultValue: p.point_type })}</td>
                    <td className="text-right">{p.epochs}</td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtMm(p.displacement_mm)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtRate(p.rate_mm_day)}</bdi></td>
                    <td>
                      <LevelBadge level={p.level} />
                      {p.ack_state === 'pending' && (
                        <span className="ms-2 text-xs text-semantic-warning">
                          {t('survey.monitoring.ack.open', { defaultValue: 'Not acknowledged yet' })}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <ImportReadingsDialog open={importOpen} projectId={projectId} onClose={() => setImportOpen(false)} />
      <PointDrawer pointId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

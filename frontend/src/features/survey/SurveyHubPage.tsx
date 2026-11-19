// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Survey overview (/survey): key numbers, the workflow strip from points to
 * results, the plan, and what needs attention. The point register itself lives
 * at /survey/points. While the survey family is off the same path shows the
 * setup card instead (SurveySetupPage).
 */

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, CheckCircle2, Crosshair, ListChecks, MapPin, Mountain } from 'lucide-react';
import { Breadcrumb, Button, Card, CardContent, CardHeader, EmptyState, KpiBand } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { fmtFixed } from '@/shared/lib/formatters';
import { getSummary, validateRegister } from './api';
import { SurveyPlan } from './SurveyPlan';
import { SURVEY_MODULES, SurveySetupCard } from './SurveySetupCard';
import { useOpenSurveyDemo } from './useOpenSurveyDemo';
import { ViewOnlyNote } from './useSurveyAccess';
import { getRegisterPlan, getVolumeSummary } from './volumesApi';

/** The workflow strip, in the order a survey job runs; rows of modules that are off drop out. */
const STEPS: { id: string; to: string }[] = [
  { id: 'survey_core', to: '/survey/points' },
  { id: 'surfaces_volumes', to: '/survey/volumes' },
  { id: 'stockpiles', to: '/survey/stockpiles' },
  { id: 'setting-out', to: '/survey/setting-out' },
  { id: 'monitoring', to: '/survey/monitoring' },
  { id: 'land-parcels', to: '/survey/parcels' },
  { id: 'mine_survey', to: '/survey/mine' },
];

/** /survey while the family is off: what it is, one click to switch it on, the demo. */
export function SurveySetupPage() {
  const { t } = useTranslation();
  const demo = useOpenSurveyDemo('/survey');
  const title = t('survey.page.overview', { defaultValue: 'Survey overview' });
  return (
    <div className="space-y-5">
      <PageHeader srTitle={title} />
      <SurveySetupCard />
      <div className="flex justify-end">
        <Button variant="secondary" loading={demo.busy} onClick={() => void demo.open()} data-testid="survey-open-demo">
          {t('survey.action.open_demo', { defaultValue: 'Open demo project' })}
        </Button>
      </div>
    </div>
  );
}

export default function SurveyHubPage() {
  const { t, i18n } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isModuleEnabled = useModuleStore((s) => s.isModuleEnabled);
  const demo = useOpenSurveyDemo('/survey');
  const title = t('survey.page.overview', { defaultValue: 'Survey overview' });
  const enabled = !!projectId;
  const volumesOn = isModuleEnabled('surfaces_volumes');

  const summary = useQuery({ queryKey: ['survey', 'summary', projectId], queryFn: () => getSummary(projectId!), enabled });
  const volumes = useQuery({
    queryKey: ['survey', 'volume-summary', projectId],
    queryFn: () => getVolumeSummary(projectId!),
    enabled: enabled && volumesOn,
  });
  const findings = useQuery({
    queryKey: ['survey', 'findings', projectId, i18n.language],
    queryFn: () => validateRegister(projectId!, i18n.language),
    enabled,
  });
  const plan = useQuery({ queryKey: ['survey', 'plan', projectId], queryFn: () => getRegisterPlan(projectId!), enabled });

  const breadcrumb = <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }) }, { label: title }]} />;
  if (!projectId) {
    return (
      <div className="space-y-5">
        {breadcrumb}
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<Crosshair size={24} />}
          title={t('survey.no_project', { defaultValue: 'Open a project to see its survey points.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => void demo.open() }}
        />
      </div>
    );
  }

  const issues = (findings.data?.findings ?? []).filter((f) => f.severity === 'error' || f.severity === 'warning');
  const kpis = [
    { key: 'points', label: t('survey.kpi.points', { defaultValue: 'Points' }), value: summary.data?.points ?? 0, icon: MapPin },
    { key: 'control', label: t('survey.kpi.control', { defaultValue: 'Control' }), value: summary.data?.control ?? 0, icon: Crosshair },
    ...(volumesOn
      ? [
          {
            key: 'net',
            label: t('survey.hub.kpi_net', { defaultValue: 'Net volume, m³' }),
            value: volumes.data ? fmtFixed(volumes.data.net_m3, 0) : '-',
            icon: Mountain,
          },
        ]
      : []),
    { key: 'findings', label: t('survey.kpi.findings', { defaultValue: 'Findings' }), value: issues.length, icon: ListChecks },
  ];
  const steps = STEPS.filter((s) => isModuleEnabled(s.id)).map((s) => ({ ...s, mod: SURVEY_MODULES.find((m) => m.id === s.id)! }));

  return (
    <div className="space-y-5">
      {breadcrumb}
      <PageHeader
        srTitle={title}
        actions={
          <Link to="/survey/points">
            <Button variant="primary" icon={<MapPin size={16} />} data-testid="survey-hub-points">
              {t('survey.hub.open_points', { defaultValue: 'Open the point register' })}
            </Button>
          </Link>
        }
      />
      <ViewOnlyNote />
      <KpiBand items={kpis} columns={4} size="sm" />

      <nav aria-label={t('survey.hub.workflow', { defaultValue: 'Survey workflow' })} data-testid="survey-hub-workflow">
        <ol className="flex flex-wrap items-center gap-2">
          {steps.map((s, i) => (
            <li key={s.id} className="flex items-center gap-2">
              <Link
                to={s.to}
                className="rounded-full border border-border-light bg-surface-primary px-3 py-1 text-sm text-content-primary hover:bg-surface-secondary"
              >
                {t(s.mod.labelKey, { defaultValue: s.mod.fallback })}
              </Link>
              {i < steps.length - 1 && <ArrowRight size={14} className="text-content-tertiary rtl:rotate-180" />}
            </li>
          ))}
        </ol>
      </nav>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <SurveyPlan plan={plan.data} isLoading={plan.isLoading} error={plan.error} onRetry={() => plan.refetch()} />
        </div>
        <Card>
          <CardHeader title={t('survey.hub.attention', { defaultValue: 'Needs attention' })} />
          <CardContent>
            {issues.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-content-secondary">
                <CheckCircle2 size={16} className="text-semantic-success" />
                {t('survey.hub.all_clear', { defaultValue: 'Nothing open on the register.' })}
              </p>
            ) : (
              <ul className="space-y-2" data-testid="survey-hub-issues">
                {issues.slice(0, 8).map((f, i) => (
                  <li key={`${f.rule_id}-${i}`} className="flex gap-2 text-sm">
                    <AlertTriangle
                      size={16}
                      className={f.severity === 'error' ? 'shrink-0 text-semantic-error' : 'shrink-0 text-semantic-warning'}
                    />
                    <span>
                      <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span> {f.message}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <Link to="/survey/points" className="mt-3 inline-block text-xs text-oe-blue hover:underline">
              {t('survey.hub.open_points', { defaultValue: 'Open the point register' })}
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

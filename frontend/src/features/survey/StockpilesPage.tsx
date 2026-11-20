// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Stockpiles (/survey/stockpiles): a card per pile with its last survey, and a
 * drawer with every survey, the findings and the adjustment. The computer
 * suggests a correction; nothing reaches the inventory until a person with
 * survey.confirm presses Confirm adjustment.
 */

import { Suspense, lazy, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BookOpen, CheckCircle2, FileDown, Package, Plus, Scale, Send, TrendingDown, Warehouse } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  KpiBand,
  SideDrawer,
  Skeleton,
} from '@/shared/ui';
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
import { AddSurveyDialog, NewStockpileDialog } from './StockpileDialogs';
import { stockpilesGuide } from './stockpilesGuide';
import {
  cancelAdjustment,
  confirmAdjustment,
  deleteSurvey,
  formatTonnes,
  formatVariance,
  getStockpile,
  getStockpileSummary,
  listStockpiles,
  proposeAdjustment,
  stockpileReportUrl,
  varianceTone,
  type PileSurvey,
  type Stockpile,
} from './stockpilesApi';
import { ViewOnlyNote, useSurveyAccess } from './useSurveyAccess';

function VarianceBadge({ survey, tolerance }: { survey: PileSurvey | null; tolerance: number | null }) {
  const { i18n } = useTranslation();
  if (!survey || survey.variance_pct == null) return null;
  return (
    <Badge variant={varianceTone(survey.variance_pct, tolerance)}>
      <bdi dir="ltr">{formatVariance(survey.variance_pct, i18n.language)}</bdi>
    </Badge>
  );
}

const StockpilePlanView = lazy(() => import('@/features/survey-plan/screens/StockpilePlanView'));

export default function StockpilesPage() {
  const { t, i18n } = useTranslation();
  const { canWrite } = useSurveyAccess();
  const lang = i18n.language;
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const demo = useOpenSurveyDemo('/survey/stockpiles');
  const [newOpen, setNewOpen] = useState(false);
  const [surveyFor, setSurveyFor] = useState<Stockpile | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const enabled = !!projectId;
  const crs = useQuery({ queryKey: ['survey', 'crs', projectId], queryFn: () => getProjectCrs(projectId!), enabled });
  const summary = useQuery({ queryKey: ['stockpiles', 'summary', projectId], queryFn: () => getStockpileSummary(projectId!), enabled });
  const piles = useQuery({ queryKey: ['stockpiles', 'list', projectId, lang], queryFn: () => listStockpiles(projectId!, lang), enabled });
  const detail = useQuery({
    queryKey: ['stockpiles', 'detail', selectedId, lang],
    queryFn: () => getStockpile(selectedId!, lang),
    enabled: !!selectedId,
  });
  const selected = useMemo(() => (piles.data ?? []).find((p) => p.id === selectedId) ?? null, [piles.data, selectedId]);

  const refresh = () => qc.invalidateQueries({ queryKey: ['stockpiles'] });
  const fail = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const propose = useMutation({ mutationFn: (surveyId: string) => proposeAdjustment(surveyId), onSuccess: refresh, onError: fail });
  const confirm = useMutation({ mutationFn: (adjustmentId: string) => confirmAdjustment(adjustmentId, lang), onSuccess: refresh, onError: fail });
  const withdraw = useMutation({ mutationFn: (adjustmentId: string) => cancelAdjustment(adjustmentId, lang), onSuccess: refresh, onError: fail });
  const remove = useMutation({ mutationFn: (surveyId: string) => deleteSurvey(surveyId), onSuccess: refresh, onError: fail });

  const title = t('stockpiles.page.title', { defaultValue: 'Stockpiles' });
  const chip = crsChipText(crs.data?.crs ?? null, t('survey.crs.local', { defaultValue: 'Local grid' }));

  if (!projectId) {
    return (
      <div className="space-y-4">
        <PageHeader srTitle={title} />
        <EmptyState
          icon={<Warehouse size={24} />}
          title={t('stockpiles.no_project', { defaultValue: 'Open a project to survey its stockpiles.' })}
          action={{ label: t('survey.action.open_demo', { defaultValue: 'Open demo project' }), onClick: () => void demo.open() }}
        />
      </div>
    );
  }

  const s = summary.data;
  const tonnes = (v: number | null | undefined) => `${formatTonnes(v, lang)} t`;
  const kpis = [
    { key: 'piles', label: t('stockpiles.kpi.stockpiles', { defaultValue: 'Stockpiles' }), value: String(s?.stockpiles ?? 0), icon: Warehouse },
    { key: 'surveyed', label: t('stockpiles.kpi.surveyed', { defaultValue: 'Surveyed tonnes' }), value: <bdi dir="ltr">{tonnes(s?.surveyed_tonnes)}</bdi>, icon: Scale },
    { key: 'book', label: t('stockpiles.kpi.book', { defaultValue: 'Book stock' }), value: <bdi dir="ltr">{tonnes(s?.book_tonnes)}</bdi>, icon: BookOpen },
    {
      key: 'variance',
      label: t('stockpiles.kpi.variance', { defaultValue: 'Variance' }),
      value: <bdi dir="ltr">{formatVariance(s?.variance_pct, lang)}</bdi>,
      icon: TrendingDown,
    },
  ];

  const actions = (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" icon={<Plus size={16} />} onClick={() => setNewOpen(true)} data-testid="stockpiles-new" disabled={!canWrite}>
        {t('stockpiles.action.new_stockpile', { defaultValue: 'New stockpile' })}
      </Button>
      <Button
        variant="secondary"
        icon={<Package size={16} />}
        disabled={(piles.data ?? []).length === 0}
        onClick={() => setSurveyFor((piles.data ?? [])[0] ?? null)}
        data-testid="stockpiles-add-survey"
      >
        {t('stockpiles.action.add_survey', { defaultValue: 'Add survey' })}
      </Button>
      <ModuleGuideButton content={stockpilesGuide} />
    </div>
  );

  const list = piles.data ?? [];
  const surveys = detail.data?.surveys ?? [];

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: t('sidebar.group.survey', { defaultValue: 'Survey & Land' }) }, { label: title }]} />
      <PageHeader srTitle={title} subtitle={chip ? <bdi dir="ltr" className="text-xs">{chip}</bdi> : undefined} actions={actions} />
      <ViewOnlyNote />
      <DismissibleInfo storageKey="stockpiles.info" title={t('survey.register.info_title', { defaultValue: 'What is this' })}>
        {t('stockpiles.info', {
          defaultValue:
            'Material heaped on site. Measure the pile above its base, turn the volume into tonnes with a density, and compare it with the book stock.',
        })}
      </DismissibleInfo>
      <CollapsibleSection storageKey="stockpiles.how" title={t('guide.button', { defaultValue: 'How it works' })} defaultCollapsed>
        <ol className="list-decimal ps-5 space-y-1 text-sm">
          <li>{t('stockpiles.how_1', { defaultValue: 'New stockpile: give a name, the ground file under the pile and the book stock in tonnes.' })}</li>
          <li>{t('stockpiles.how_2', { defaultValue: 'Add survey: pick the pile file, a surface or a typed volume, then the density and where it comes from.' })}</li>
          <li>{t('stockpiles.how_3', { defaultValue: 'Read the variance. If it is real, propose an adjustment; nothing is booked until someone confirms.' })}</li>
        </ol>
      </CollapsibleSection>

      <KpiBand items={kpis} columns={4} size="sm" />

      {piles.isLoading ? (
        <Skeleton className="h-40" />
      ) : piles.isError ? (
        <ErrorState title={getErrorMessage(piles.error)} onRetry={() => piles.refetch()} />
      ) : list.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Warehouse size={24} />}
            title={t('stockpiles.empty', { defaultValue: 'No stockpiles yet. Create one with its base surface and book stock.' })}
            action={
              <div className="flex justify-center gap-2">
                <Button variant="primary" onClick={() => setNewOpen(true)}>
                  {t('stockpiles.action.new_stockpile', { defaultValue: 'New stockpile' })}
                </Button>
                <Button variant="secondary" loading={demo.busy} onClick={() => void demo.open()} data-testid="stockpiles-open-demo">
                  {t('survey.action.open_demo', { defaultValue: 'Open demo project' })}
                </Button>
              </div>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="stockpile-cards">
          {list.map((p) => (
            <button
              key={p.id}
              type="button"
              className="text-start"
              onClick={() => setSelectedId(p.id)}
              data-testid={`stockpile-card-${p.code}`}
            >
              <Card className="h-full p-4 hover:bg-surface-secondary">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">{p.name}</p>
                    <p className="text-xs text-content-secondary">
                      <bdi dir="ltr" className="font-mono">{p.code}</bdi> {p.material}
                    </p>
                  </div>
                  <VarianceBadge survey={p.last_survey} tolerance={p.variance_tolerance_pct} />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  <dt className="text-content-secondary">{t('stockpiles.field.book', { defaultValue: 'Book stock (t)' })}</dt>
                  <dd><bdi dir="ltr">{formatTonnes(p.book_tonnes, lang)}</bdi></dd>
                  {p.last_survey ? (
                    <>
                      <dt className="text-content-secondary">{t('stockpiles.field.last_survey', { defaultValue: 'Last survey' })}</dt>
                      <dd><bdi dir="ltr">{p.last_survey.surveyed_on}</bdi></dd>
                      <dt className="text-content-secondary">{t('stockpiles.field.volume', { defaultValue: 'Volume (m³)' })}</dt>
                      <dd><bdi dir="ltr">{formatM3(p.last_survey.volume_m3, lang)}</bdi></dd>
                      <dt className="text-content-secondary">{t('stockpiles.field.tonnes', { defaultValue: 'Tonnes' })}</dt>
                      <dd><bdi dir="ltr">{formatTonnes(p.last_survey.tonnes, lang)}</bdi></dd>
                    </>
                  ) : (
                    <dd className="col-span-2 text-content-tertiary">{t('stockpiles.no_surveys', { defaultValue: 'No survey yet.' })}</dd>
                  )}
                </dl>
              </Card>
            </button>
          ))}
        </div>
      )}

      <SideDrawer
        open={!!selected}
        onClose={() => setSelectedId(null)}
        title={selected ? `${selected.code} ${selected.name}` : ''}
        widthClass="max-w-3xl"
        busy={propose.isPending || confirm.isPending || withdraw.isPending}
      >
        {selected && (
          <div className="space-y-4 text-sm" data-testid="stockpile-drawer">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
              <dt className="text-content-secondary">{t('stockpiles.field.book', { defaultValue: 'Book stock (t)' })}</dt>
              <dd data-testid="stockpile-book-value"><bdi dir="ltr">{formatTonnes(selected.book_tonnes, lang)}</bdi></dd>
              <dt className="text-content-secondary">{t('stockpiles.field.material', { defaultValue: 'Material' })}</dt>
              <dd>{selected.material || '-'}</dd>
              <dt className="text-content-secondary">{t('stockpiles.field.base', { defaultValue: 'Base surface' })}</dt>
              <dd>{selected.base_name || '-'}</dd>
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon={<Plus size={16} />} onClick={() => setSurveyFor(selected)}>
                {t('stockpiles.action.add_survey', { defaultValue: 'Add survey' })}
              </Button>
            </div>

            {projectId && (
              <Suspense fallback={<Skeleton className="h-64" />}>
                <StockpilePlanView projectId={projectId} stockpileId={selected.id} />
              </Suspense>
            )}

            <h3 className="oe-card-title">{t('stockpiles.surveys', { defaultValue: 'Surveys' })}</h3>
            {surveys.length === 0 ? (
              <p className="text-content-tertiary">{t('stockpiles.no_surveys', { defaultValue: 'No survey yet.' })}</p>
            ) : (
              <div className="space-y-3" data-testid="survey-list">
                {surveys.map((sv) => (
                  <Card key={sv.id} className="space-y-2 p-3" data-testid="survey-row">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span><bdi dir="ltr" className="font-mono">{sv.surveyed_on}</bdi> {sv.pile_name}</span>
                      <span className="flex items-center gap-2">
                        <VarianceBadge survey={sv} tolerance={selected.variance_tolerance_pct} />
                        <Badge variant={sv.status === 'booked' ? 'blue' : 'neutral'}>
                          {t(`stockpiles.status.${sv.status}`, { defaultValue: sv.status })}
                        </Badge>
                      </span>
                    </div>
                    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-4">
                      <dt className="text-content-secondary">{t('stockpiles.field.volume', { defaultValue: 'Volume (m³)' })}</dt>
                      <dd data-testid="survey-volume"><bdi dir="ltr">{formatM3(sv.volume_m3, lang)}</bdi></dd>
                      <dt className="text-content-secondary">{t('stockpiles.field.density', { defaultValue: 'Density (t/m³)' })}</dt>
                      <dd>
                        <bdi dir="ltr">{sv.density_t_m3}</bdi> {t(`stockpiles.density.${sv.density_source}`, { defaultValue: sv.density_source })}
                      </dd>
                      <dt className="text-content-secondary">{t('stockpiles.field.tonnes', { defaultValue: 'Tonnes' })}</dt>
                      <dd data-testid="survey-tonnes"><bdi dir="ltr">{formatTonnes(sv.tonnes, lang)}</bdi></dd>
                      <dt className="text-content-secondary">{t('stockpiles.field.variance', { defaultValue: 'Variance' })}</dt>
                      <dd data-testid="survey-variance">
                        <bdi dir="ltr">{formatTonnes(sv.variance_t, lang)} ({formatVariance(sv.variance_pct, lang)})</bdi>
                      </dd>
                    </dl>
                    {sv.findings.length > 0 && (
                      <ul className="space-y-1" data-testid="survey-findings">
                        {sv.findings.map((f) => (
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
                    {sv.adjustment && sv.adjustment.status !== 'cancelled' && (
                      <p className="flex items-center gap-1" data-testid="survey-adjustment">
                        <CheckCircle2 size={14} aria-hidden />
                        {t(sv.adjustment.status === 'confirmed' ? 'stockpiles.adjustment.booked' : 'stockpiles.adjustment.proposed', {
                          defaultValue: sv.adjustment.status === 'confirmed' ? 'Booked: {{qty}} t' : 'Proposed: {{qty}} t',
                          qty: formatTonnes(sv.adjustment.delta_t, lang),
                        })}
                        {sv.adjustment.confirmed_by_name && <span className="text-content-secondary"> {sv.adjustment.confirmed_by_name}</span>}
                      </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {sv.status === 'open' && sv.variance_t != null && sv.variance_t !== 0 && sv.adjustment?.status !== 'proposed' && (
                        <Button size="sm" variant="secondary" icon={<Send size={14} />} loading={propose.isPending} onClick={() => propose.mutate(sv.id)} data-testid="survey-propose">
                          {t('stockpiles.action.propose', { defaultValue: 'Propose adjustment' })}
                        </Button>
                      )}
                      {sv.adjustment?.status === 'proposed' && (
                        <>
                          <Button size="sm" variant="primary" icon={<CheckCircle2 size={14} />} loading={confirm.isPending} onClick={() => confirm.mutate(sv.adjustment!.id)} data-testid="survey-confirm-adjustment">
                            {t('stockpiles.action.confirm_adjustment', { defaultValue: 'Confirm adjustment' })}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => withdraw.mutate(sv.adjustment!.id)}>
                            {t('stockpiles.action.cancel_proposal', { defaultValue: 'Withdraw proposal' })}
                          </Button>
                        </>
                      )}
                      <Button
                        size="sm"
                        variant="secondary"
                        icon={<FileDown size={14} />}
                        onClick={() => void downloadWithAuth(stockpileReportUrl(sv.id, lang), `${selected.code}-${sv.surveyed_on}.pdf`)}
                      >
                        {t('volumes.action.print_report', { defaultValue: 'Print report' })}
                      </Button>
                      {sv.status === 'open' && (
                        <Button size="sm" variant="ghost" onClick={() => remove.mutate(sv.id)}>
                          {t('common.delete', { defaultValue: 'Delete' })}
                        </Button>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
            )}
            <p className="text-xs text-content-tertiary">
              {t('stockpiles.adjustment.hint', { defaultValue: 'Nothing is booked in the inventory until someone with survey rights confirms.' })}
            </p>
          </div>
        )}
      </SideDrawer>

      <NewStockpileDialog
        open={newOpen}
        projectId={projectId}
        isAdvanced={isAdvanced}
        onClose={() => setNewOpen(false)}
        onCreated={(pile) => setSelectedId(pile.id)}
      />
      <AddSurveyDialog
        open={!!surveyFor}
        projectId={projectId}
        pile={surveyFor}
        isAdvanced={isAdvanced}
        onClose={() => setSurveyFor(null)}
      />
    </div>
  );
}

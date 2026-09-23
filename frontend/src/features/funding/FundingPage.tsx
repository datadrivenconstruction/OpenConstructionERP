// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// FundingPage - the register of public funding on a project.
//
// Three tabs, because a funded project is read three different ways by the
// same person on different days. Applications is the file: which programme,
// what was asked, what came back. Deadlines is the week: every dated thing
// across every application, soonest first, because a deadline belongs to a
// calendar and not to one grant. Programmes is the catalogue: what could be
// applied for, which is a different question from what has been.
//
// The explainer sits above the tabs and the insights panel below the header,
// per the module page rules. Amounts render from the exact decimal strings
// the API sends; the numeric conversion in fundingInsights is for charting
// only and never reaches the screen as an amount.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Banknote,
  CalendarClock,
  CheckCircle2,
  FileCheck2,
  Landmark,
  Percent,
  Plus,
  Search,
} from 'lucide-react';

import {
  Badge,
  type BadgeVariant,
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  EmptyState,
  ModuleGuideButton,
  SkeletonTable,
  StatCard,
} from '@/shared/ui';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { fetchProjectList } from '@/shared/lib/projectList';
import { fmtDate } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  createApplication,
  createProgramme,
  declaresPercent,
  fundingKeys,
  getProjectSummary,
  listApplications,
  listProgrammes,
  listProjectObligations,
  localToday,
  percentText,
  updateObligation,
} from './api';
import type { FundingApplication, FundingObligation, FundingProgramme } from './api';
import { ApplicationPanel } from './ApplicationPanel';
import { buildFundingInsights } from './fundingInsights';
import { fundingGuide } from './fundingGuide';
import { obligationLabel } from './obligationLabel';

type TabId = 'applications' | 'deadlines' | 'programmes';

interface Project {
  id: string;
  name: string;
}

/** The terms a new catalogue entry starts from, and what the form resets to. */
const BLANK_PROGRAMME = {
  code: '',
  name: '',
  authority_name: '',
  country: '',
  instrument: 'grant' as FundingProgramme['instrument'],
  status: 'open' as FundingProgramme['status'],
  funding_rate_percent: '',
  aid_intensity_cap_percent: '',
  own_share_percent: '',
  proof_of_use_due_days: '',
  disbursement_spend_days: '',
  retention_years: '',
  requires_application_before_start: true,
};

const INSTRUMENTS: FundingProgramme['instrument'][] = [
  'grant',
  'repayment_grant',
  'loan',
  'guarantee',
  'equity',
  'tax_relief',
];

const PROGRAMME_STATUSES: FundingProgramme['status'][] = ['open', 'draft', 'closed', 'suspended'];

/** A percentage or day count the API wants as a number, empty meaning zero. */
function numeric(value: string): string {
  const trimmed = value.trim();
  return trimmed === '' ? '0' : trimmed;
}

/** Badge colour for an application status. */
function statusVariant(status: string): BadgeVariant {
  if (status === 'approved') return 'success';
  if (status === 'rejected' || status === 'withdrawn') return 'error';
  if (status === 'submitted' || status === 'in_review') return 'blue';
  if (status === 'closed') return 'neutral';
  return 'warning';
}

export function FundingPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Every hook sits above the first early return. The insights hook builds a
  // memo internally, and React throws "rendered fewer hooks than expected" on
  // whichever branch skips it, which neither the build nor the tests catch.
  const insights = useModuleInsights('funding', { defaultOpen: false });

  const [tab, setTab] = useState<TabId>('applications');
  const [search, setSearch] = useState('');
  const [countryFilter, setCountryFilter] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [draftCode, setDraftCode] = useState('');
  const [draftTitle, setDraftTitle] = useState('');
  const [draftProgramme, setDraftProgramme] = useState('');
  const [draftBase, setDraftBase] = useState('');
  const [draftRequested, setDraftRequested] = useState('');
  const [showProgrammeForm, setShowProgrammeForm] = useState(false);
  const [programmeDraft, setProgrammeDraft] = useState(BLANK_PROGRAMME);
  const [openApplication, setOpenApplication] = useState<string | null>(null);

  /** Updates one field of the programme draft, leaving the rest alone. */
  function setProgrammeField<K extends keyof typeof BLANK_PROGRAMME>(
    key: K,
    value: (typeof BLANK_PROGRAMME)[K],
  ) {
    setProgrammeDraft((prev) => ({ ...prev, [key]: value }));
  }

  const today = localToday();

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });
  const projectId = activeProjectId || projects[0]?.id || '';
  const breadcrumbProjectName = activeProjectId
    ? projects.find((p) => p.id === activeProjectId)?.name
    : undefined;

  const {
    data: applicationPage,
    isLoading: loadingApplications,
    isError: applicationsFailed,
  } = useQuery({
    queryKey: fundingKeys.applications(projectId),
    queryFn: () => listApplications(projectId),
    enabled: Boolean(projectId),
  });

  const { data: obligationPage } = useQuery({
    queryKey: fundingKeys.obligations(projectId),
    queryFn: () => listProjectObligations(projectId, { today, openOnly: false }),
    enabled: Boolean(projectId),
  });

  const { data: summary } = useQuery({
    queryKey: fundingKeys.projectSummary(projectId),
    queryFn: () => getProjectSummary(projectId, today),
    enabled: Boolean(projectId),
  });

  const { data: programmePage, isLoading: loadingProgrammes } = useQuery({
    queryKey: fundingKeys.programmes({ country: countryFilter, search }),
    queryFn: () => listProgrammes({ country: countryFilter || undefined, search: search || undefined, limit: 100 }),
  });

  const applications = useMemo<FundingApplication[]>(
    () => applicationPage?.items ?? [],
    [applicationPage],
  );
  const obligations = useMemo<FundingObligation[]>(() => obligationPage?.items ?? [], [obligationPage]);
  const programmes = useMemo<FundingProgramme[]>(() => programmePage?.items ?? [], [programmePage]);

  const programmeById = useMemo(() => {
    const map = new Map<string, FundingProgramme>();
    programmes.forEach((row) => map.set(row.id, row));
    return map;
  }, [programmes]);

  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildFundingInsights(applications, obligations, programmeById, t),
    [applications, obligations, programmeById, t],
  );

  const createMutation = useMutation({
    mutationFn: () =>
      createApplication({
        project_id: projectId,
        programme_id: draftProgramme,
        code: draftCode.trim(),
        title: draftTitle.trim(),
        eligible_cost_base: draftBase || '0',
        requested_amount: draftRequested || '0',
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('funding.created', { defaultValue: 'Application created' }),
      });
      setShowCreate(false);
      setDraftCode('');
      setDraftTitle('');
      setDraftProgramme('');
      setDraftBase('');
      setDraftRequested('');
      void qc.invalidateQueries({ queryKey: fundingKeys.applications(projectId) });
      void qc.invalidateQueries({ queryKey: fundingKeys.projectSummary(projectId) });
    },
    onError: (err: unknown) => {
      addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) });
    },
  });

  // A catalogue nobody can add to is a dead end: the country packs bring the
  // programmes of their own market, and everywhere else the first entry has to
  // come from the person who read the terms.
  const programmeMutation = useMutation({
    mutationFn: () =>
      createProgramme({
        code: programmeDraft.code.trim(),
        name: programmeDraft.name.trim(),
        authority_name: programmeDraft.authority_name.trim(),
        country: programmeDraft.country.trim().toUpperCase(),
        instrument: programmeDraft.instrument,
        status: programmeDraft.status,
        funding_rate_percent: numeric(programmeDraft.funding_rate_percent),
        aid_intensity_cap_percent: numeric(programmeDraft.aid_intensity_cap_percent),
        own_share_percent: numeric(programmeDraft.own_share_percent),
        proof_of_use_due_days: Number(numeric(programmeDraft.proof_of_use_due_days)),
        disbursement_spend_days: Number(numeric(programmeDraft.disbursement_spend_days)),
        retention_years: Number(numeric(programmeDraft.retention_years)),
        requires_application_before_start: programmeDraft.requires_application_before_start,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('funding.programme_created', { defaultValue: 'Programme added to the catalogue' }),
      });
      setShowProgrammeForm(false);
      setProgrammeDraft(BLANK_PROGRAMME);
      void qc.invalidateQueries({ queryKey: ['funding', 'programmes'] });
    },
    onError: (err: unknown) => {
      addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) });
    },
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => updateObligation(id, { status: 'done', completed_on: today }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: fundingKeys.obligations(projectId) });
      void qc.invalidateQueries({ queryKey: fundingKeys.projectSummary(projectId) });
    },
    onError: (err: unknown) => {
      addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) });
    },
  });

  const overdueCount = obligations.filter((row) => row.overdue).length;
  const currency = summary?.currency || applications[0]?.currency || '';

  // The intensity bar only means something when a programme declared a
  // ceiling. Drawing it against zero would tell every reader they are at
  // infinity percent of nothing.
  const cap = Number(summary?.aid_intensity_cap_percent ?? '0');
  const intensity = Number(summary?.aid_intensity_percent ?? '0');
  const capDeclared = declaresPercent(summary?.aid_intensity_cap_percent);

  // The wire carries a plain decimal string, and printing it beside a currency
  // code is not the same as writing money. A reader in Germany or Spain reads
  // the point as a thousands separator, so "100000.00 EUR" is both unformatted
  // and, for half the world, a different number. `formatCurrency` is the house
  // formatter and is deliberate about the part a naive one gets wrong: an
  // unknown currency yields a grouped number with no symbol rather than a euro
  // sign over somebody else's money.
  function money(value: string | undefined): string {
    if (!value) return '—';
    return formatCurrency(value, currency);
  }

  /**
   * A stored date as the reader reads dates.
   *
   * The same split `ApplicationPanel` makes: the record keeps ISO-8601
   * everywhere the string is a value rather than a label - date inputs, the
   * draft state behind them, the `today=` the queries send, sort keys and
   * ids - and this is only for the ones that are read off the screen.
   */
  function date(value: string | null | undefined): string {
    return value ? fmtDate(value) : '—';
  }

  // A selection only lives as long as the row behind it. Switching project or
  // removing the application drops back to the register on its own, so the
  // panel never asks the API for something this project does not have.
  const activeApplicationId = applications.some((row) => row.id === openApplication)
    ? openApplication
    : null;

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <Breadcrumb
          items={[
            ...(breadcrumbProjectName
              ? [{ label: breadcrumbProjectName, to: `/projects/${activeProjectId}` }]
              : []),
            { label: t('funding.title', { defaultValue: 'Public Funding' }) },
          ]}
        />
        <div className="flex items-center gap-2">
          <InsightsToggleButton open={insights.open} onClick={() => insights.setOpen(!insights.open)} />
          <ModuleGuideButton content={fundingGuide} />
          <Button onClick={() => setShowCreate(true)} disabled={!projectId}>
            <Plus className="h-4 w-4" />
            {t('funding.new_application', { defaultValue: 'New application' })}
          </Button>
        </div>
      </div>

      <InsightsPanel
        open={insights.open}
        title={t('funding.insights.title', { defaultValue: 'Public funding insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <CollapsibleSection
        storageKey="funding.how"
        icon={<Landmark className="h-4 w-4" />}
        title={t('funding.how_title', { defaultValue: 'How public funding fits the project' })}
        subtitle={t('funding.how_subtitle', {
          defaultValue: 'Programme, application, draw, proof of use - and the dates that decide all four',
        })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-gray-600 dark:text-gray-300">
          <li>
            {t('funding.how_step_1', {
              defaultValue:
                'Find the programme. Its terms set the funding rate, the share you must carry, and every deadline that follows.',
            })}
          </li>
          <li>
            {t('funding.how_step_2', {
              defaultValue:
                'File before work starts. Work begun first is usually unfundable in full, and no later approval repairs it.',
            })}
          </li>
          <li>
            {t('funding.how_step_3', {
              defaultValue:
                'Split the cost plan into what the programme counts and what it does not, and record why for each.',
            })}
          </li>
          <li>
            {t('funding.how_step_4', {
              defaultValue:
                'Request draws against real spending inside the award period, then show where the money went before the report is due.',
            })}
          </li>
        </ol>
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
          {t('funding.how_links', {
            defaultValue:
              'Works with the cost plan for the eligible base, the schedule for the award period, and invoicing for the draws.',
          })}
        </p>
      </CollapsibleSection>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t('funding.kpi_approved', { defaultValue: 'Approved' })}
          value={money(summary?.approved_amount)}
          sub={t('funding.kpi_approved_sub', {
            count: summary?.approved_count ?? 0,
            defaultValue_one: 'across {{count}} application',
            defaultValue_other: 'across {{count}} applications',
          })}
          icon={Banknote}
          tone="success"
        />
        <StatCard
          label={t('funding.kpi_received', { defaultValue: 'Received' })}
          value={money(summary?.received_amount)}
          sub={t('funding.kpi_outstanding', {
            amount: money(summary?.outstanding_amount),
            defaultValue: '{{amount}} still to draw',
          })}
          icon={CheckCircle2}
          tone="blue"
        />
        <StatCard
          label={t('funding.kpi_intensity', { defaultValue: 'Aid intensity' })}
          value={capDeclared ? percentText(summary?.aid_intensity_percent ?? 0) : '—'}
          sub={
            capDeclared
              ? t('funding.kpi_intensity_cap', {
                  cap: percentText(summary?.aid_intensity_cap_percent),
                  defaultValue: 'ceiling {{cap}}',
                })
              : t('funding.kpi_intensity_none', { defaultValue: 'no programme declares a ceiling' })
          }
          icon={Percent}
          tone={capDeclared && intensity > cap ? 'danger' : 'default'}
          tintValue={capDeclared && intensity > cap}
        />
        <StatCard
          label={t('funding.kpi_deadlines', { defaultValue: 'Open deadlines' })}
          value={summary?.obligations_open ?? 0}
          sub={t('funding.kpi_overdue', {
            count: overdueCount,
            defaultValue_one: '{{count}} overdue',
            defaultValue_other: '{{count}} overdue',
          })}
          icon={CalendarClock}
          tone={overdueCount > 0 ? 'danger' : 'default'}
          tintValue={overdueCount > 0}
        />
      </div>

      <div className="flex gap-1 border-b border-gray-200 dark:border-gray-700">
        {(['applications', 'deadlines', 'programmes'] as TabId[]).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={
              tab === id
                ? 'border-b-2 border-blue-600 px-3 py-2 text-sm font-medium text-blue-700 dark:text-blue-300'
                : 'px-3 py-2 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white'
            }
          >
            {t(`funding.tab_${id}`, {
              defaultValue:
                id === 'applications' ? 'Applications' : id === 'deadlines' ? 'Deadlines' : 'Programmes',
            })}
          </button>
        ))}
      </div>

      {tab === 'applications' && activeApplicationId ? (
        <ApplicationPanel
          applicationId={activeApplicationId}
          projectId={projectId}
          currency={currency}
          onBack={() => setOpenApplication(null)}
        />
      ) : null}

      {tab === 'applications' && !activeApplicationId && (
        <Card>
          {!projectId ? (
            <EmptyState
              icon={<Landmark className="h-8 w-8" />}
              title={t('funding.no_project', { defaultValue: 'Choose a project first' })}
              description={t('funding.no_project_hint', {
                defaultValue: 'Funding applications belong to a project, because the award period is checked against it.',
              })}
            />
          ) : loadingApplications ? (
            <SkeletonTable rows={5} />
          ) : applicationsFailed ? (
            <EmptyState
              icon={<AlertTriangle className="h-8 w-8" />}
              title={t('funding.load_failed', { defaultValue: 'Could not load applications' })}
            />
          ) : applications.length === 0 ? (
            <EmptyState
              icon={<Landmark className="h-8 w-8" />}
              title={t('funding.empty_title', { defaultValue: 'No funding applications yet' })}
              description={t('funding.empty_body', {
                defaultValue:
                  'Pick a programme from the catalogue and open an application. The deadlines it carries appear here the moment an award is recorded.',
              })}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-gray-500 dark:text-gray-400">
                  <tr>
                    <th className="px-3 py-2">{t('funding.field.code', { defaultValue: 'Reference' })}</th>
                    <th className="px-3 py-2">{t('funding.field.programme', { defaultValue: 'Programme' })}</th>
                    <th className="px-3 py-2">{t('funding.field.status', { defaultValue: 'Status' })}</th>
                    <th className="px-3 py-2 text-right">
                      {t('funding.field.requested', { defaultValue: 'Requested' })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('funding.field.approved', { defaultValue: 'Approved' })}
                    </th>
                    <th className="px-3 py-2">{t('funding.field.period', { defaultValue: 'Award period' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {applications.map((row) => {
                    const programme = programmeById.get(row.programme_id);
                    return (
                      <tr
                        key={row.id}
                        onClick={() => setOpenApplication(row.id)}
                        className="cursor-pointer border-t border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/40"
                      >
                        <td className="px-3 py-2 font-medium">
                          <button
                            type="button"
                            onClick={() => setOpenApplication(row.id)}
                            className="text-blue-700 hover:underline dark:text-blue-300"
                          >
                            {row.code}
                          </button>
                        </td>
                        <td className="px-3 py-2">
                          {programme ? programme.name || programme.code : '—'}
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant={statusVariant(row.status)}>
                            {t(`funding.status.${row.status}`, { defaultValue: row.status })}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{money(row.requested_amount)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{money(row.approved_amount)}</td>
                        {/* Two dates and a separator: keep the browser from choosing
                            the middle of one of them as the place to break. */}
                        <td className="whitespace-nowrap px-3 py-2 tabular-nums text-gray-600 dark:text-gray-300">
                          {row.award_period_start || row.award_period_end
                            ? `${date(row.award_period_start)} … ${date(row.award_period_end)}`
                            : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === 'deadlines' && (
        <Card>
          {obligations.length === 0 ? (
            <EmptyState
              icon={<CalendarClock className="h-8 w-8" />}
              title={t('funding.no_deadlines', { defaultValue: 'No deadlines yet' })}
              description={t('funding.no_deadlines_hint', {
                defaultValue:
                  'Deadlines are worked out from the programme terms the moment an award is recorded, so they appear here on their own.',
              })}
            />
          ) : (
            <ul className="divide-y divide-gray-100 dark:divide-gray-800">
              {obligations.map((row) => (
                <li key={row.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
                  {/* Deliberately NOT `whitespace-nowrap`, unlike the date ranges.
                      This is a single date in a fixed 7rem gutter that cannot
                      grow, and a formatted date is longer than the ISO string
                      that used to sit here and has spaces to break at. Held on
                      one line it would overrun into the title beside it; allowed
                      to wrap it stays inside its own column. */}
                  <span
                    className={
                      row.overdue
                        ? 'w-28 shrink-0 font-medium tabular-nums text-red-600 dark:text-red-400'
                        : 'w-28 shrink-0 tabular-nums text-gray-600 dark:text-gray-300'
                    }
                  >
                    {date(row.due_on)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{obligationLabel(row, t)}</span>
                    <span className="block truncate text-xs text-gray-500 dark:text-gray-400">
                      {t(`funding.obligation_source.${row.source}`, { defaultValue: row.source })}
                      {row.source_reference ? ` · ${row.source_reference}` : ''}
                    </span>
                  </span>
                  {row.overdue && (
                    <Badge variant="error">
                      {t('funding.obligation_overdue', { defaultValue: 'Overdue' })}
                    </Badge>
                  )}
                  {row.status === 'open' ? (
                    <Button
                      variant="secondary"
                      onClick={() => completeMutation.mutate(row.id)}
                      disabled={completeMutation.isPending}
                    >
                      <FileCheck2 className="h-4 w-4" />
                      {t('funding.mark_done', { defaultValue: 'Mark done' })}
                    </Button>
                  ) : (
                    <Badge variant="success">
                      {t(`funding.obligation_status.${row.status}`, { defaultValue: row.status })}
                    </Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === 'programmes' && (
        <Card>
          <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 p-3 dark:border-gray-800">
            <div className="relative">
              <Search className="pointer-events-none absolute start-2 top-2.5 h-4 w-4 text-gray-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('funding.search_programmes', { defaultValue: 'Search programmes' })}
                className="rounded border border-gray-300 py-1.5 ps-8 pe-2 text-sm dark:border-gray-600 dark:bg-gray-800"
              />
            </div>
            <input
              value={countryFilter}
              onChange={(e) => setCountryFilter(e.target.value.toUpperCase().slice(0, 2))}
              placeholder={t('funding.filter_country', { defaultValue: 'Country' })}
              className="w-24 rounded border border-gray-300 px-2 py-1.5 text-sm uppercase dark:border-gray-600 dark:bg-gray-800"
            />
            <Button
              variant="secondary"
              className="ml-auto"
              onClick={() => setShowProgrammeForm(true)}
            >
              <Plus className="mr-1 h-4 w-4" />
              {t('funding.new_programme', { defaultValue: 'New programme' })}
            </Button>
          </div>
          {loadingProgrammes ? (
            <SkeletonTable rows={5} />
          ) : programmes.length === 0 ? (
            <EmptyState
              icon={<Landmark className="h-8 w-8" />}
              title={t('funding.no_programmes', { defaultValue: 'No programmes in the catalogue' })}
              description={t('funding.no_programmes_hint', {
                defaultValue:
                  'Country packs bring the programmes of their own market. Until one is installed the catalogue is yours to fill.',
              })}
              action={{
                label: t('funding.new_programme', { defaultValue: 'New programme' }),
                onClick: () => setShowProgrammeForm(true),
              }}
            />
          ) : (
            <ul className="divide-y divide-gray-100 dark:divide-gray-800">
              {programmes.map((row) => (
                <li key={row.id} className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{row.name || row.code}</span>
                    <Badge variant="neutral">{row.code}</Badge>
                    {row.country && <Badge variant="blue">{row.country}</Badge>}
                    <Badge variant={row.status === 'open' ? 'success' : 'neutral'}>
                      {t(`funding.programme_status.${row.status}`, { defaultValue: row.status })}
                    </Badge>
                    {row.requires_application_before_start && (
                      <Badge variant="warning">
                        {t('funding.before_start_badge', { defaultValue: 'Apply before starting' })}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                    {row.authority_name}
                    {declaresPercent(row.funding_rate_percent)
                      ? ` · ${t('funding.rate_label', {
                          rate: percentText(row.funding_rate_percent),
                          defaultValue: 'up to {{rate}} of eligible cost',
                        })}`
                      : ''}
                    {row.last_verified_on
                      ? ` · ${t('funding.verified_on', {
                          date: fmtDate(row.last_verified_on),
                          defaultValue: 'terms checked {{date}}',
                        })}`
                      : ''}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {showProgrammeForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4">
          <Card className="my-auto w-full max-w-2xl p-4">
            <h2 className="mb-3 text-lg font-semibold">
              {t('funding.new_programme', { defaultValue: 'New programme' })}
            </h2>
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="block text-sm">
                  <span className="mb-1 block text-gray-600 dark:text-gray-300">
                    {t('funding.field.code', { defaultValue: 'Reference' })}
                  </span>
                  <input
                    value={programmeDraft.code}
                    onChange={(e) => setProgrammeField('code', e.target.value)}
                    className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-gray-600 dark:text-gray-300">
                    {t('funding.field.title', { defaultValue: 'Title' })}
                  </span>
                  <input
                    value={programmeDraft.name}
                    onChange={(e) => setProgrammeField('name', e.target.value)}
                    className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-gray-600 dark:text-gray-300">
                    {t('funding.field.authority', { defaultValue: 'Authority' })}
                  </span>
                  <input
                    value={programmeDraft.authority_name}
                    onChange={(e) => setProgrammeField('authority_name', e.target.value)}
                    className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-gray-600 dark:text-gray-300">
                    {t('funding.filter_country', { defaultValue: 'Country' })}
                  </span>
                  <input
                    value={programmeDraft.country}
                    onChange={(e) => setProgrammeField('country', e.target.value.toUpperCase().slice(0, 2))}
                    className="w-full rounded border border-gray-300 px-2 py-1.5 uppercase dark:border-gray-600 dark:bg-gray-800"
                  />
                </label>
              </div>

              <fieldset className="space-y-3 border-t border-gray-100 pt-3 dark:border-gray-800">
                <legend className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  {t('funding.programme_terms', { defaultValue: 'Terms' })}
                </legend>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.instrument', { defaultValue: 'Instrument' })}
                    </span>
                    <select
                      value={programmeDraft.instrument}
                      onChange={(e) =>
                        setProgrammeField('instrument', e.target.value as FundingProgramme['instrument'])
                      }
                      className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                    >
                      {INSTRUMENTS.map((value) => (
                        <option key={value} value={value}>
                          {t(`funding.instrument.${value}`, { defaultValue: value })}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.status', { defaultValue: 'Status' })}
                    </span>
                    <select
                      value={programmeDraft.status}
                      onChange={(e) =>
                        setProgrammeField('status', e.target.value as FundingProgramme['status'])
                      }
                      className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                    >
                      {PROGRAMME_STATUSES.map((value) => (
                        <option key={value} value={value}>
                          {t(`funding.programme_status.${value}`, { defaultValue: value })}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.rate', { defaultValue: 'Funding rate, %' })}
                    </span>
                    <input
                      value={programmeDraft.funding_rate_percent}
                      onChange={(e) => setProgrammeField('funding_rate_percent', e.target.value)}
                      inputMode="decimal"
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.aid_cap', { defaultValue: 'Aid intensity ceiling, %' })}
                    </span>
                    <input
                      value={programmeDraft.aid_intensity_cap_percent}
                      onChange={(e) => setProgrammeField('aid_intensity_cap_percent', e.target.value)}
                      inputMode="decimal"
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.own_share_percent', { defaultValue: 'Own contribution, %' })}
                    </span>
                    <input
                      value={programmeDraft.own_share_percent}
                      onChange={(e) => setProgrammeField('own_share_percent', e.target.value)}
                      inputMode="decimal"
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                    />
                  </label>
                </div>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={programmeDraft.requires_application_before_start}
                    onChange={(e) =>
                      setProgrammeField('requires_application_before_start', e.target.checked)
                    }
                    className="mt-0.5"
                  />
                  <span className="text-gray-600 dark:text-gray-300">
                    {t('funding.field.before_start', {
                      defaultValue: 'The application must be filed before the works begin',
                    })}
                  </span>
                </label>
              </fieldset>

              <fieldset className="space-y-3 border-t border-gray-100 pt-3 dark:border-gray-800">
                <legend className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  {t('funding.programme_clock', { defaultValue: 'Deadlines these terms create' })}
                </legend>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.proof_days', { defaultValue: 'Proof of use due, days' })}
                    </span>
                    <input
                      value={programmeDraft.proof_of_use_due_days}
                      onChange={(e) => setProgrammeField('proof_of_use_due_days', e.target.value)}
                      inputMode="numeric"
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.spend_days', { defaultValue: 'Spend a draw within, days' })}
                    </span>
                    <input
                      value={programmeDraft.disbursement_spend_days}
                      onChange={(e) => setProgrammeField('disbursement_spend_days', e.target.value)}
                      inputMode="numeric"
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1 block text-gray-600 dark:text-gray-300">
                      {t('funding.field.retention_years', { defaultValue: 'Keep records, years' })}
                    </span>
                    <input
                      value={programmeDraft.retention_years}
                      onChange={(e) => setProgrammeField('retention_years', e.target.value)}
                      inputMode="numeric"
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                    />
                  </label>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {t('funding.programme_clock_hint', {
                    defaultValue:
                      'Left at zero, no deadline is derived from this programme and every date has to be entered by hand.',
                  })}
                </p>
              </fieldset>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setShowProgrammeForm(false);
                  setProgrammeDraft(BLANK_PROGRAMME);
                }}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                onClick={() => programmeMutation.mutate()}
                disabled={!programmeDraft.code.trim() || programmeMutation.isPending}
              >
                {t('common.create', { defaultValue: 'Create' })}
              </Button>
            </div>
          </Card>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <Card className="w-full max-w-lg p-4">
            <h2 className="mb-3 text-lg font-semibold">
              {t('funding.new_application', { defaultValue: 'New application' })}
            </h2>
            <div className="space-y-3">
              <label className="block text-sm">
                <span className="mb-1 block text-gray-600 dark:text-gray-300">
                  {t('funding.field.code', { defaultValue: 'Reference' })}
                </span>
                <input
                  value={draftCode}
                  onChange={(e) => setDraftCode(e.target.value)}
                  className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-gray-600 dark:text-gray-300">
                  {t('funding.field.title', { defaultValue: 'Title' })}
                </span>
                <input
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-gray-600 dark:text-gray-300">
                  {t('funding.field.programme', { defaultValue: 'Programme' })}
                </span>
                <select
                  value={draftProgramme}
                  onChange={(e) => setDraftProgramme(e.target.value)}
                  className="w-full rounded border border-gray-300 px-2 py-1.5 dark:border-gray-600 dark:bg-gray-800"
                >
                  <option value="">
                    {t('funding.choose_programme', { defaultValue: 'Choose a programme' })}
                  </option>
                  {programmes.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.code} · {row.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-sm">
                  <span className="mb-1 block text-gray-600 dark:text-gray-300">
                    {t('funding.field.eligible_base', { defaultValue: 'Eligible cost base' })}
                  </span>
                  <input
                    value={draftBase}
                    onChange={(e) => setDraftBase(e.target.value)}
                    inputMode="decimal"
                    className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-gray-600 dark:text-gray-300">
                    {t('funding.field.requested', { defaultValue: 'Requested' })}
                  </span>
                  <input
                    value={draftRequested}
                    onChange={(e) => setDraftRequested(e.target.value)}
                    inputMode="decimal"
                    className="w-full rounded border border-gray-300 px-2 py-1.5 text-right tabular-nums dark:border-gray-600 dark:bg-gray-800"
                  />
                </label>
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setShowCreate(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                onClick={() => createMutation.mutate()}
                disabled={!draftCode.trim() || !draftProgramme || createMutation.isPending}
              >
                {t('common.create', { defaultValue: 'Create' })}
              </Button>
            </div>
          </Card>
        </div>
      )}

      <p className="text-xs text-gray-400 dark:text-gray-500">
        {t('funding.locale_note', {
          defaultValue: 'Deadline checks use your own calendar date, not the server clock.',
        })}
      </p>
    </div>
  );
}

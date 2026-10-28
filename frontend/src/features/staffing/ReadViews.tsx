// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The four read-only views of the staffing plan: the organisation chart, the
// compliance matrix (people against required documents), what is coming up
// (expiring documents, arrivals, leave) and planned against booked time.
//
// The compliance matrix shows a state per cell and nothing else: no number,
// no date of birth, no document content.

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { CalendarClock, KeyRound, Network, ShieldCheck, Timer } from 'lucide-react';
import clsx from 'clsx';

import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate, fmtList, fmtNumber } from '@/shared/lib/formatters';

import {
  downloadExport,
  type Compliance,
  type OrgChart,
  type PlannedVsActualRow,
  type Position,
  type StaffingCatalogue,
  type Upcoming,
} from './api';
import {
  CELL_STATE,
  DOCUMENT_STATUS,
  FILL_STATUS,
  LEAVE_STATUS,
  PHASE,
  catalogueName,
  positionName,
  vocab,
  whyNot,
  type LabelContext,
} from './labels';
import { fteDecimals } from './rules';
import { CELL_TONE, ClearedBadge, ExportButtons, LEAVE_TONE, ToneBadge, personLabel } from './StaffingBits';

interface ViewBase {
  projectId: string;
  catalogue: StaffingCatalogue | null;
  labels: LabelContext;
}

export function OrgChartView({ projectId, catalogue, labels, chart }: ViewBase & { chart: OrgChart }) {
  const { t } = useTranslation();
  if (chart.phases.length === 0) {
    return (
      <EmptyState
        icon={<Network size={28} />}
        title={t('staffing.org_chart.empty_title', { defaultValue: 'No organisation chart yet' })}
        description={t('staffing.org_chart.empty_body', {
          defaultValue: 'The chart draws itself from the positions of the staffing plan. Add positions on the Staffing plan tab first.',
        })}
      />
    );
  }
  return (
    <div className="space-y-5" data-testid="org-chart">
      <div className="flex justify-end">
        <ExportButtons download={(format) => downloadExport(projectId, 'org_chart', format)} />
      </div>
      {chart.phases.map((phase) => (
        <section key={phase.phase} className="space-y-2" data-testid={`org-phase-${phase.phase}`}>
          <h2 className="text-base font-semibold text-content-primary">{vocab(t, PHASE, phase.phase)}</h2>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {phase.organisations.map((org) => (
              <div key={org.organisation} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="org-box">
                <h3 className="mb-2 text-sm font-medium text-content-secondary">
                  {catalogueName(labels, catalogue, 'organisation', org.organisation)}
                </h3>
                <ul className="space-y-2">
                  {org.positions.map((p) => (
                    <li key={p.position_id} className="rounded-md bg-surface-secondary px-2.5 py-1.5" data-testid="org-position">
                      <div className="flex items-center gap-1.5 text-sm font-medium text-content-primary">
                        {positionName(labels, catalogue, p)}
                        {p.key_role && <KeyRound size={12} className="text-oe-blue-text" aria-label={t('staffing.position.key_role', { defaultValue: 'Key role' })} />}
                      </div>
                      {p.people.length === 0 ? (
                        <div className="text-xs text-semantic-error" data-testid="org-vacant">
                          {t('staffing.vacant', { defaultValue: 'Vacant' })}
                        </div>
                      ) : (
                        <ul className="text-xs text-content-secondary">
                          {p.people.map((person, i) => (
                            <li key={i}>
                              {person.status === 'proposed'
                                ? t('staffing.org_chart.person_proposed', {
                                    defaultValue: '{{name}} ({{status}})',
                                    name: personLabel(labels.t, person.name),
                                    status: vocab(t, FILL_STATUS, person.status),
                                  })
                                : personLabel(labels.t, person.name)}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** The states the project summary counts, in the order the server lists them. */
const SUMMARY_STATES = ['valid', 'expiring', 'expired', 'missing', 'waived'] as const;

export function ComplianceView({
  projectId,
  catalogue,
  labels,
  compliance,
  onOpenFile,
}: ViewBase & { compliance: Compliance; onOpenFile: (fileId: string) => void }) {
  const { t } = useTranslation();
  if (compliance.items.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck size={28} />}
        title={t('staffing.compliance.empty_title', { defaultValue: 'Nobody to check yet' })}
        description={t('staffing.compliance.empty_body', {
          defaultValue: 'Once people are assigned to positions, this matrix shows for each person which required documents are valid, expiring or missing.',
        })}
      />
    );
  }
  return (
    <div className="space-y-3" data-testid="compliance">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm text-content-secondary">
          {t('staffing.compliance.intro', {
            defaultValue: 'Each cell shows where a required document stands. A person is cleared to work when nothing required is missing or expired.',
          })}
        </p>
        <ExportButtons download={(format) => downloadExport(projectId, 'compliance', format)} />
      </div>
      {compliance.summary.length > 0 && (
        <section className="space-y-2" data-testid="compliance-summary">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('staffing.compliance.summary_title', { defaultValue: 'People whose file you cannot open, by document' })}
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('staffing.compliance.summary_hint', {
              defaultValue: 'Counts of people only, and only for a document at least {{min}} of them must hold. Health documents are left out.',
              min: fmtNumber(compliance.summary_min_group, 0),
            })}
          </p>
          <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                  <th scope="col" className="px-3 py-2 font-medium">{t('staffing.document.kind', { defaultValue: 'Document' })}</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t('staffing.compliance.summary_people', { defaultValue: 'People' })}
                  </th>
                  {SUMMARY_STATES.map((state) => (
                    <th key={state} scope="col" className="px-3 py-2 text-right font-medium">
                      {vocab(t, CELL_STATE, state)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compliance.summary.map((line) => (
                  <tr key={line.document_kind} className="border-b border-border-light last:border-b-0" data-testid="compliance-summary-row">
                    <th scope="row" className="px-3 py-2 text-left font-medium text-content-primary">
                      {catalogueName(labels, catalogue, 'document_kind', line.document_kind)}
                    </th>
                    <td className="px-3 py-2 text-right tabular-nums" data-testid="compliance-summary-people">
                      {fmtNumber(line.required, 0)}
                    </td>
                    {line.uniform ? (
                      // Everybody held back stands the same: a split would say how each of them stands.
                      <td colSpan={SUMMARY_STATES.length} className="px-3 py-2 text-xs text-content-tertiary" data-testid="compliance-summary-uniform">
                        {t('staffing.compliance.summary_uniform', { defaultValue: 'Not split by state: all of them stand the same.' })}
                      </td>
                    ) : (
                      SUMMARY_STATES.map((state) => (
                        <td key={state} className="px-3 py-2 text-right tabular-nums" data-state={state}>
                          {fmtNumber(line[state] ?? 0, 0)}
                        </td>
                      ))
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
              <th scope="col" className="sticky left-0 bg-surface-primary px-3 py-2 font-medium">
                {t('staffing.fill.person', { defaultValue: 'Person' })}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">{t('staffing.people.clearance', { defaultValue: 'Clearance' })}</th>
              {compliance.document_kinds.map((k) => (
                <th key={k} scope="col" className="min-w-[7rem] px-3 py-2 font-medium">
                  {catalogueName(labels, catalogue, 'document_kind', k)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {compliance.items.map((row) => (
              <tr key={row.roster_member_id} className="border-b border-border-light last:border-b-0" data-testid="compliance-row">
                <th scope="row" className="sticky left-0 bg-surface-primary px-3 py-2 text-left font-medium text-content-primary">
                  {row.file_id ? (
                    <button type="button" className="text-left hover:underline" onClick={() => onOpenFile(row.file_id as string)}>
                      {personLabel(labels.t, row.name)}
                    </button>
                  ) : (
                    personLabel(labels.t, row.name)
                  )}
                  <div className="text-xs font-normal text-content-tertiary">
                    {fmtList(row.roles.map((r) => catalogueName(labels, catalogue, 'role', r)))}
                  </div>
                </th>
                <td className="px-3 py-2">
                  <ClearedBadge cleared={row.cleared_to_work} />
                </td>
                {!row.can.see_documents.allowed && compliance.document_kinds.length > 0 && (
                  <td colSpan={compliance.document_kinds.length} className="px-3 py-2 text-xs text-content-tertiary" data-testid="compliance-hidden">
                    {whyNot(labels.t, row.can.see_documents)}
                  </td>
                )}
                {row.can.see_documents.allowed && compliance.document_kinds.map((k) => {
                  const cell = row.cells[k];
                  if (!cell) return <td key={k} className="px-3 py-2" />;
                  return (
                    <td key={k} className="px-3 py-2" data-testid="compliance-cell" data-state={cell.state}>
                      <span className={clsx(cell.state === 'not_required' && 'opacity-60')}>
                        <ToneBadge tone={CELL_TONE[cell.state]}>
                          {cell.state === 'expiring' && typeof cell.days === 'number'
                            ? t('staffing.cell.expiring_in', { defaultValue: 'Expires in {{count}} days', count: cell.days })
                            : vocab(t, CELL_STATE, cell.state)}
                        </ToneBadge>
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {compliance.items.some((row) => !row.can.see_documents.allowed) && (
        <p className="text-xs text-content-tertiary" role="status" data-testid="compliance-restricted">
          {t('staffing.compliance.restricted', {
            defaultValue: 'Document states are shown only for the people whose personnel file you may open.',
          })}
        </p>
      )}
    </div>
  );
}

function UpcomingBlock({ title, empty, children, count, testId }: { title: string; empty: string; children: ReactNode; count: number; testId: string }) {
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid={testId}>
      <h2 className="mb-2 text-sm font-semibold text-content-primary">{title}</h2>
      {count === 0 ? <p className="text-sm text-content-tertiary">{empty}</p> : <ul className="space-y-1.5">{children}</ul>}
    </section>
  );
}

export function UpcomingView({
  catalogue,
  labels,
  upcoming,
  onOpenFile,
}: Omit<ViewBase, 'projectId'> & { upcoming: Upcoming; onOpenFile: (fileId: string) => void }) {
  const { t } = useTranslation();
  const nothing = upcoming.expiring.length + upcoming.mobilisations.length + upcoming.leave.length === 0;
  if (nothing) {
    return (
      <EmptyState
        icon={<CalendarClock size={28} />}
        title={t('staffing.upcoming.empty_title', { defaultValue: 'Nothing coming up' })}
        description={t('staffing.upcoming.empty_body', {
          defaultValue: 'Documents about to expire, arrivals on site and leave of the people whose files you may open appear here.',
        })}
      />
    );
  }
  const who = (fileId: string, name: string | null) => (
    <button type="button" className="font-medium text-content-primary hover:underline" onClick={() => onOpenFile(fileId)}>
      {personLabel(labels.t, name)}
    </button>
  );
  return (
    <div className="grid gap-3 lg:grid-cols-3" data-testid="upcoming">
      <UpcomingBlock
        testId="upcoming-expiring"
        title={t('staffing.upcoming.expiring', { defaultValue: 'Documents expiring' })}
        empty={t('staffing.upcoming.expiring_none', { defaultValue: 'No document expires in the next 90 days.' })}
        count={upcoming.expiring.length}
      >
        {upcoming.expiring.map((e, i) => (
          <li key={`${e.file_id}:${e.document_kind}:${i}`} className="text-sm" data-testid="expiring-row">
            {who(e.file_id, e.name)}
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-content-secondary">
              {catalogueName(labels, catalogue, 'document_kind', e.document_kind)}
              <ToneBadge tone={e.days < 0 ? 'error' : e.days <= 30 ? 'warning' : 'neutral'}>
                {e.days < 0
                  ? vocab(t, DOCUMENT_STATUS, 'expired')
                  : t('staffing.cell.expiring_in', { defaultValue: 'Expires in {{count}} days', count: e.days })}
              </ToneBadge>
              {e.valid_until && <span>{fmtDate(e.valid_until)}</span>}
            </div>
          </li>
        ))}
      </UpcomingBlock>
      <UpcomingBlock
        testId="upcoming-mobilisations"
        title={t('staffing.upcoming.mobilisations', { defaultValue: 'Arrivals in the next 14 days' })}
        empty={t('staffing.upcoming.mobilisations_none', { defaultValue: 'Nobody arrives on site in the next 14 days.' })}
        count={upcoming.mobilisations.length}
      >
        {upcoming.mobilisations.map((m) => (
          <li key={m.id} className="text-sm" data-testid="mobilisation-row">
            {who(m.file_id, m.name)}
            <div className="text-xs text-content-secondary">
              {fmtList([m.depart_date ? fmtDate(m.depart_date) : '', m.to_place])}
            </div>
          </li>
        ))}
      </UpcomingBlock>
      <UpcomingBlock
        testId="upcoming-leave"
        title={t('staffing.upcoming.leave', { defaultValue: 'Leave' })}
        empty={t('staffing.upcoming.leave_none', { defaultValue: 'No leave is requested or approved.' })}
        count={upcoming.leave.length}
      >
        {upcoming.leave.map((lv) => (
          <li key={lv.id} className="text-sm" data-testid="upcoming-leave-row">
            {who(lv.file_id, lv.name)}
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-content-secondary">
              {catalogueName(labels, catalogue, 'leave_type', lv.leave_type)}
              <ToneBadge tone={LEAVE_TONE[lv.status]}>{vocab(t, LEAVE_STATUS, lv.status)}</ToneBadge>
              {lv.from_date && lv.to_date && (
                <span>{t('staffing.period_range', { defaultValue: '{{from}} to {{to}}', from: fmtDate(lv.from_date), to: fmtDate(lv.to_date) })}</span>
              )}
            </div>
          </li>
        ))}
      </UpcomingBlock>
    </div>
  );
}

const days = (value: string) => fmtNumber(value, fteDecimals(value));
/** A decimal the server sent, with the decimals it needs and no padding zeros: 8.00 reads 8, 7.50 reads 7.5. */
const plainNumber = (value: string) => fmtNumber(value, (value.split('.')[1] ?? '').replace(/0+$/, '').length);

export function PlannedVsActualView({
  catalogue,
  labels,
  rows,
  positions,
}: Omit<ViewBase, 'projectId'> & { rows: PlannedVsActualRow[]; positions: Position[] }) {
  const { t } = useTranslation();
  // The comparison names a position by its role code only; the plan knows its title or custom name.
  const byId = new Map(positions.map((p) => [p.id, p]));
  const nameOf = (r: PlannedVsActualRow) => {
    const position = byId.get(r.position_id);
    return position ? positionName(labels, catalogue, position) : catalogueName(labels, catalogue, 'role', r.role_code);
  };
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Timer size={28} />}
        title={t('staffing.pva.empty_title', { defaultValue: 'Nothing to compare yet' })}
        description={t('staffing.pva.empty_body', {
          defaultValue: 'A position is compared once it has a start date. Planned days come from its FTE; booked days come from the site timesheets of the people on it.',
        })}
      />
    );
  }
  return (
    <div className="space-y-3" data-testid="planned-vs-actual">
      <p className="text-sm text-content-secondary">
        {t('staffing.pva.intro', {
          defaultValue:
            'Planned FTE days up to today against the days booked on site timesheets, with {{hours}} hours counted as one day. Read only.',
          // The length of a day is the project work calendar's, as the server sends it with every row.
          hours: plainNumber(rows[0]?.hours_per_day ?? ''),
        })}
      </p>
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
              <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.role', { defaultValue: 'Role' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('staffing.pva.working_days', { defaultValue: 'Working days' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('staffing.pva.planned_days', { defaultValue: 'Planned FTE days' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('staffing.pva.actual_days', { defaultValue: 'Booked days' })}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('staffing.pva.variance', { defaultValue: 'Variance' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.position_id} className="border-b border-border-light last:border-b-0" data-testid="pva-row">
                <td className="px-3 py-2 text-content-primary">
                  {nameOf(r)}
                  {r.linked_resources === 0 && (
                    <div className="text-xs text-content-tertiary" data-testid="pva-unlinked">
                      {t('staffing.pva.unlinked', { defaultValue: 'Nobody on this position is linked to a timesheet resource yet.' })}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums" data-testid="pva-working-days">{fmtNumber(r.working_days, 0)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{days(r.planned_fte_days)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.linked_resources === 0 ? '' : days(r.actual_fte_days)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.linked_resources === 0 ? '' : days(r.variance_fte_days)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

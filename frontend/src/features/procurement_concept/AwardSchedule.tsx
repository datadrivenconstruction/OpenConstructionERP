// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The award schedule: for every package, when procurement must start and
// when the award is due so the contract is in place by the need date. The
// dates are the server's proposal, counted back from the need date. Nothing
// reaches the project schedule until a person confirms the rows.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Calendar, CheckCircle2 } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate } from '@/shared/lib/formatters';

import { confirmSchedule, type Concept, type ScheduleView } from './api';
import { catalogueName, type LabelContext } from './labels';
import { FindingList, ReasonedButton, RefusalBox, ToneBadge } from './ProcurementBits';
import { hasProposal, isConfirmed, steerVerdict } from './rules';

export interface AwardScheduleProps {
  projectId: string;
  concept: Concept;
  schedule: ScheduleView;
  labels: LabelContext;
  onGoToPackages: () => void;
  onChanged: () => void;
}

export function AwardSchedule({ projectId, concept, schedule, labels, onGoToPackages, onChanged }: AwardScheduleProps) {
  const { t } = useTranslation();
  const rows = schedule.items;
  const ready = rows.filter(hasProposal);
  // Rows start selected when they have a proposal that is not in the schedule yet.
  const [picked, setPicked] = useState<Set<string>>(() => new Set(ready.filter((r) => !isConfirmed(r)).map((r) => r.package_id)));
  const [done, setDone] = useState(0);
  const selected = ready.filter((r) => picked.has(r.package_id)).map((r) => r.package_id);

  const confirm = useMutation({
    mutationFn: () => confirmSchedule(projectId, selected),
    onSuccess: (page) => {
      setDone(page.items.length);
      setPicked(new Set());
      onChanged();
    },
  });
  const toggle = (id: string) =>
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Calendar size={28} />}
        title={t('procurement_concept.ui.schedule.empty_title', { defaultValue: 'No award dates to plan yet' })}
        description={t('procurement_concept.ui.schedule.empty_body', {
          defaultValue:
            'The schedule counts back from the date each package is needed on site. Give a package a need date and a procedure, and its start and award dates appear here.',
        })}
        action={{ label: t('procurement_concept.tabs.packages', { defaultValue: 'Packages' }), onClick: onGoToPackages }}
      />
    );
  }

  return (
    <div className="space-y-3" data-testid="award-schedule">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-2xl text-sm text-content-secondary">
          {t('procurement_concept.ui.schedule.intro', {
            defaultValue:
              'Award due is the need date less the lead time. Start is the award less the days the procedure takes. Confirming writes both as milestones to the project schedule.',
          })}
          {schedule.release_date && (
            <>
              {' '}
              {t('procurement_concept.ui.schedule.release', {
                defaultValue: 'The main works are released on {{date}}; only advance packages may start earlier.',
                date: fmtDate(schedule.release_date),
              })}
            </>
          )}
        </p>
        <ReasonedButton
          verdict={steerVerdict(concept)}
          disabled={selected.length === 0}
          loading={confirm.isPending}
          onClick={() => confirm.mutate()}
          data-testid="schedule-confirm"
        >
          {t('procurement_concept.actions.confirm_schedule', { defaultValue: 'Confirm milestones' })}
        </ReasonedButton>
      </div>
      {confirm.error ? <RefusalBox error={confirm.error} /> : null}
      {done > 0 && !confirm.error && (
        <p className="flex items-center gap-2 rounded-md bg-semantic-success-bg px-3 py-2 text-sm text-content-primary" role="status" data-testid="schedule-confirmed">
          <CheckCircle2 size={16} className="text-semantic-success" aria-hidden />
          {t('procurement_concept.ui.schedule.confirmed', {
            defaultValue: 'Milestones written to the project schedule. Packages: {{n}}.',
            n: done,
          })}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full text-left text-sm" data-testid="schedule-table">
          <thead className="bg-surface-secondary text-xs text-content-tertiary">
            <tr>
              <th className="px-3 py-2 font-medium">
                <span className="sr-only">{t('procurement_concept.ui.schedule.col_pick', { defaultValue: 'Confirm' })}</span>
              </th>
              <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.package.col_package', { defaultValue: 'Package' })}</th>
              <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.schedule.col_start', { defaultValue: 'Start procurement' })}</th>
              <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.package.col_dates', { defaultValue: 'Award due' })}</th>
              <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.schedule.col_need', { defaultValue: 'Needed on site' })}</th>
              <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.schedule.col_status', { defaultValue: 'In the project schedule' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const proposal = hasProposal(r);
              return (
                <tr key={r.package_id} className="border-t border-border-light align-top" data-testid="schedule-row" data-package={r.code}>
                  <td className="px-3 py-2.5">
                    <input
                      type="checkbox"
                      disabled={!proposal}
                      checked={picked.has(r.package_id)}
                      onChange={() => toggle(r.package_id)}
                      aria-label={t('procurement_concept.ui.schedule.pick', {
                        defaultValue: 'Confirm the milestones of {{code}}',
                        code: r.code,
                      })}
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="font-medium text-content-primary">
                      <span className="font-mono text-xs text-content-tertiary">{r.code}</span> {r.title}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-content-tertiary">
                      {r.procedure_code && <span>{catalogueName(labels, 'procedure', r.procedure_code)}</span>}
                      {r.procedure_days !== null && (
                        <span>{t('procurement_concept.ui.days', { defaultValue: '{{count}} days', count: r.procedure_days })}</span>
                      )}
                      {r.is_advance && (
                        <ToneBadge tone="purple">{t('procurement_concept.ui.package.advance', { defaultValue: 'Advance package' })}</ToneBadge>
                      )}
                    </div>
                    {r.findings.length > 0 && (
                      <div className="mt-1.5">
                        <FindingList findings={r.findings} refLabel={() => ''} testId="schedule-findings" />
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-content-primary">{r.proposed_start_date ? fmtDate(r.proposed_start_date) : '-'}</td>
                  <td className="px-3 py-2.5 text-content-primary">{r.proposed_award_date ? fmtDate(r.proposed_award_date) : '-'}</td>
                  <td className="px-3 py-2.5 text-content-primary">
                    {r.need_date ? fmtDate(r.need_date) : '-'}
                    {r.lead_time_days ? (
                      <div className="text-xs text-content-tertiary">
                        {t('procurement_concept.ui.schedule.lead_time', {
                          defaultValue: 'lead time {{days}} days',
                          days: r.lead_time_days,
                        })}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5">
                    {isConfirmed(r) ? (
                      <ToneBadge tone="success" testId="schedule-in">
                        {t('procurement_concept.ui.schedule.in_schedule', { defaultValue: 'Milestones set' })}
                      </ToneBadge>
                    ) : proposal ? (
                      <ToneBadge tone="neutral" testId="schedule-proposed">
                        {t('procurement_concept.ui.schedule.proposed', { defaultValue: 'Proposal' })}
                      </ToneBadge>
                    ) : (
                      <span className="text-xs text-content-tertiary" data-testid="schedule-incomplete">
                        {t('procurement_concept.ui.schedule.incomplete', { defaultValue: 'Needs a need date and a procedure' })}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

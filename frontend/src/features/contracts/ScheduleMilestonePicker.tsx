// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ScheduleMilestonePicker - choose the schedule milestone an instalment waits
// for.
//
// The list is the milestones of every schedule in the contract's project,
// filed under the schedule's name and searchable by WBS code. "Milestone"
// means what the link route means when it decides whether to warn: a
// milestone-type activity, or one with no duration. An ordinary task can still
// be linked through the API and the route will say so; the picker does not
// offer one, except the activity a line is already linked to, so opening the
// form never hides the current link.
//
// A link to an activity that has since been deleted is shown as such rather
// than as an empty box: the line still carries the id, and the person needs
// to know the date it falls back to is the contract's own.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { SearchableSelect, type SearchableSelectOption } from '@/shared/ui/SearchableSelect';
import { fmtDate } from '@/shared/lib/formatters';
import { listScheduleMilestoneCandidates } from './api';

export function milestoneCandidatesKey(projectId: string) {
  return ['contracts', 'milestone-candidates', projectId] as const;
}

export function ScheduleMilestonePicker({
  projectId,
  value,
  onChange,
  currentActivityName,
  currentActivityMissing = false,
  disabled = false,
  id,
}: {
  projectId: string;
  /** The linked activity id, or '' for none. */
  value: string;
  onChange: (activityId: string) => void;
  /** The name the plan reported for the current link, for a link the list no longer holds. */
  currentActivityName?: string | null;
  currentActivityMissing?: boolean;
  disabled?: boolean;
  id?: string;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: milestoneCandidatesKey(projectId),
    queryFn: () => listScheduleMilestoneCandidates(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });

  const options = useMemo<SearchableSelectOption[]>(() => {
    const rows = (q.data ?? []).filter((a) => a.is_milestone || a.id === value);
    const out: SearchableSelectOption[] = rows.map((a) => ({
      value: a.id,
      label: a.name,
      hint: a.wbs_code || undefined,
      meta: [
        a.end_date ? fmtDate(a.end_date) : null,
        a.is_milestone
          ? null
          : t('contracts.plan_picker_not_milestone', { defaultValue: 'task, not a milestone' }),
      ]
        .filter(Boolean)
        .join(' · ') || undefined,
      group: a.schedule_name,
    }));
    if (value && !rows.some((a) => a.id === value)) {
      out.unshift({
        value,
        label: currentActivityMissing
          ? t('contracts.plan_activity_missing', {
              defaultValue: 'The linked schedule activity was deleted',
            })
          : currentActivityName || value,
      });
    }
    return out;
  }, [q.data, value, currentActivityName, currentActivityMissing, t]);

  const noMilestones = q.isSuccess && options.length === 0;

  return (
    <div className="flex flex-col gap-1">
      <SearchableSelect
        id={id}
        value={value}
        onChange={onChange}
        options={options}
        loading={q.isLoading}
        disabled={disabled}
        allowEmpty
        emptyLabel={t('contracts.plan_picker_none', { defaultValue: 'Not linked to the schedule' })}
        placeholder={t('contracts.plan_picker_placeholder', {
          defaultValue: 'Pick a schedule milestone',
        })}
        searchPlaceholder={t('contracts.plan_picker_search', {
          defaultValue: 'Search by name or WBS code',
        })}
        data-testid="schedule-milestone-picker"
      />
      {noMilestones && (
        <p className="text-2xs text-content-tertiary">
          {t('contracts.plan_picker_empty', {
            defaultValue: 'The schedule of this project has no milestones yet.',
          })}
        </p>
      )}
      {q.isError && (
        <p className="text-2xs text-semantic-error">
          {t('contracts.plan_picker_error', {
            defaultValue: 'The schedule could not be loaded.',
          })}
        </p>
      )}
    </div>
  );
}

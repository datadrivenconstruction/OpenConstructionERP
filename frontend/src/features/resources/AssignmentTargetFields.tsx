// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What an assignment is *for*: the project it is booked against and the
// schedule activity - the Gantt row - it staffs.
//
// A user reported they could not find a way to book a resource onto a task,
// and they were right. Both modals that write an assignment dropped project_id
// on the floor and never offered the activity at all, so a booking could say
// who and when but never what. The pair lives in one component because both
// modals need exactly the same two fields; typed out twice they would drift.
//
// Activities are reachable only through a project - an activity hangs off a
// schedule and a schedule hangs off a project, and no endpoint lists them
// across projects. So the activity picker stays disabled until a project is
// chosen and says why, and changing the project clears the chosen activity:
// carrying it across would let one booking name a project and an activity that
// belong to different projects.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import {
  SearchableSelect,
  WideModalField,
  type SearchableSelectOption,
} from '@/shared/ui';
import { projectsApi } from '@/features/projects/api';
import { scheduleApi, type Activity as ScheduleActivity } from '@/features/schedule/api';

/** Schedule activities of one project, as picker rows grouped by schedule. */
export function useProjectActivityOptions(projectId: string): {
  options: SearchableSelectOption[];
  loading: boolean;
} {
  const q = useQuery({
    queryKey: ['resources', 'project-activities', projectId],
    queryFn: async () => {
      const { items: schedules } = await scheduleApi.listSchedules(projectId);
      return Promise.all(
        schedules.map((s) =>
          scheduleApi
            .getGantt(s.id)
            .then((g) => ({ schedule: s, activities: g.activities ?? [] }))
            // One unreadable schedule must not blank the whole picker.
            .catch(() => ({ schedule: s, activities: [] as ScheduleActivity[] })),
        ),
      );
    },
    enabled: !!projectId,
    staleTime: 60_000,
  });

  const options = useMemo(() => {
    const out: SearchableSelectOption[] = [];
    for (const { schedule, activities } of q.data ?? []) {
      for (const a of activities) {
        out.push({
          value: a.id,
          label: a.name,
          hint: a.wbs_code || undefined,
          meta: a.start_date ? a.start_date.slice(0, 10) : undefined,
          group: schedule.name,
          keywords: a.activity_type,
        });
      }
    }
    return out;
  }, [q.data]);

  return { options, loading: !!projectId && q.isLoading };
}

export function AssignmentTargetFields({
  projectId,
  activityId,
  onChange,
  projectTestId,
  activityTestId,
}: {
  projectId: string;
  activityId: string;
  onChange: (next: { project_id: string; activity_id: string }) => void;
  projectTestId?: string;
  activityTestId?: string;
}) {
  const { t } = useTranslation();

  const projectsQ = useQuery({
    // Same key the Requests tab uses, so both read one cached project list.
    queryKey: ['resources', 'requests-projects'],
    queryFn: () => projectsApi.list(),
    staleTime: 60_000,
  });

  const { options: activityOptions, loading: activitiesLoading } =
    useProjectActivityOptions(projectId);

  const projectOptions: SearchableSelectOption[] = useMemo(
    () => (projectsQ.data ?? []).map((p) => ({ value: p.id, label: p.name })),
    [projectsQ.data],
  );

  const activityHint = !projectId
    ? t('resources.activity_needs_project', {
        defaultValue: 'Pick a project first - activities belong to its schedule.',
      })
    : !activitiesLoading && activityOptions.length === 0
      ? t('resources.activity_none', {
          defaultValue: 'This project has no schedule activities yet.',
        })
      : undefined;

  return (
    <>
      <WideModalField label={t('common.project', { defaultValue: 'Project' })}>
        <SearchableSelect
          value={projectId}
          onChange={(next) => onChange({ project_id: next, activity_id: '' })}
          options={projectOptions}
          allowEmpty
          emptyLabel={t('resources.no_project', { defaultValue: 'Unassigned' })}
          loading={projectsQ.isLoading}
          placeholder={t('resources.pick_project', { defaultValue: 'Pick a project' })}
          searchPlaceholder={t('resources.search_project', {
            defaultValue: 'Search projects…',
          })}
          data-testid={projectTestId}
        />
      </WideModalField>
      <WideModalField
        label={t('resources.activity', { defaultValue: 'Schedule activity' })}
        hint={activityHint}
      >
        <SearchableSelect
          value={activityId}
          onChange={(next) => onChange({ project_id: projectId, activity_id: next })}
          options={activityOptions}
          allowEmpty
          emptyLabel={t('resources.no_activity', { defaultValue: 'No activity' })}
          loading={activitiesLoading}
          disabled={!projectId}
          placeholder={
            projectId
              ? t('resources.pick_activity', { defaultValue: 'Pick an activity' })
              : t('resources.activity_needs_project', {
                  defaultValue: 'Pick a project first - activities belong to its schedule.',
                })
          }
          searchPlaceholder={t('resources.search_activity', {
            defaultValue: 'Search by name or WBS code…',
          })}
          data-testid={activityTestId}
        />
      </WideModalField>
    </>
  );
}

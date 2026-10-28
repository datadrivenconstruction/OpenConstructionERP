// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project records a stakeholder event or a commitment can point at: the
// meetings and the letters of the same project. They are read from the
// modules that own them and offered as plain choices. When one of those
// modules is switched off the list is simply empty, and a link that is
// already stored stays as it is.

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { fetchCorrespondence } from '@/features/correspondence/api';
import { fetchMeetings } from '@/features/meetings/api';
import { fetchTasks } from '@/features/tasks/api';
import { fmtDate } from '@/shared/lib/formatters';

import { listGates, listProjectRisks, listReleaseItems, listRequirementOptions, stakeholderKeys } from './api';
import type { TickOption } from './StakeholderBits';
import type { TFn } from './labels';

/** A record named by its title and, when it has one, its day. */
export function datedName(t: TFn, title: string, date: string | null | undefined): string {
  if (!date) return title;
  return t('stakeholders.ui.link.dated', { defaultValue: '{{title}} ({{date}})', title, date: fmtDate(date) });
}

export interface LinkOptions {
  options: TickOption[];
  loading: boolean;
}

/** The meetings of the project, newest first as the meetings module lists them. */
export function useMeetingOptions(projectId: string, t: TFn, enabled = true): LinkOptions {
  const query = useQuery({
    queryKey: [...stakeholderKeys.project(projectId), 'link-meetings'],
    queryFn: () => fetchMeetings({ project_id: projectId }),
    enabled: !!projectId && enabled,
    retry: false,
    staleTime: 60_000,
  });
  const options = useMemo(
    () => (query.data ?? []).map((m) => ({ id: m.id, label: datedName(t, m.title, m.date) })),
    [query.data, t],
  );
  return { options, loading: query.isLoading };
}

/** The letters of the project, incoming and outgoing. */
export function useCorrespondenceOptions(projectId: string, t: TFn, enabled = true): LinkOptions {
  const query = useQuery({
    queryKey: [...stakeholderKeys.project(projectId), 'link-correspondence'],
    queryFn: () => fetchCorrespondence({ project_id: projectId }).then((page) => page.items),
    enabled: !!projectId && enabled,
    retry: false,
    staleTime: 60_000,
  });
  const options = useMemo(
    () => (query.data ?? []).map((c) => ({ id: c.id, label: datedName(t, c.subject, c.date_received ?? c.date_sent) })),
    [query.data, t],
  );
  return { options, loading: query.isLoading };
}

/** The risk register of the project, each entry by its code and title. */
export function useRiskOptions(projectId: string, t: TFn, enabled = true): LinkOptions {
  const query = useQuery({
    queryKey: [...stakeholderKeys.project(projectId), 'link-risks'],
    queryFn: () => listProjectRisks(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
    retry: false,
    staleTime: 60_000,
  });
  const options = useMemo(
    () =>
      (query.data ?? []).map((r) => ({
        id: r.id,
        label: r.code
          ? t('stakeholders.ui.link.coded', { defaultValue: '{{code}}: {{title}}', code: r.code, title: r.title })
          : r.title,
      })),
    [query.data, t],
  );
  return { options, loading: query.isLoading };
}

/** The tasks of the project. */
export function useTaskOptions(projectId: string, t: TFn, enabled = true): LinkOptions {
  const query = useQuery({
    queryKey: [...stakeholderKeys.project(projectId), 'link-tasks'],
    queryFn: () => fetchTasks({ project_id: projectId }).then((page) => page.items),
    enabled: !!projectId && enabled,
    retry: false,
    staleTime: 60_000,
  });
  const options = useMemo(
    () => (query.data ?? []).map((task) => ({ id: task.id, label: datedName(t, task.title, task.due_date) })),
    [query.data, t],
  );
  return { options, loading: query.isLoading };
}

export interface GateChoices extends LinkOptions {
  /** False once the server says the project is run without gates. Until it answers, gates count as in use. */
  inUse: boolean;
  /** The project events only a gate can cause, as the server lists them. */
  gateBound: string[];
}

const NO_EVENTS: string[] = [];

/** The gates of the project's phase model, in their order. The id of a choice is the gate code. */
export function useGateOptions(projectId: string, enabled = true): GateChoices {
  const query = useQuery({
    queryKey: [...stakeholderKeys.project(projectId), 'link-gates'],
    queryFn: () => listGates(projectId),
    enabled: !!projectId && enabled,
    retry: false,
    staleTime: 60_000,
  });
  const options = useMemo(() => (query.data?.items ?? []).map((g) => ({ id: g.code, label: g.name || g.code })), [query.data]);
  return {
    options,
    loading: query.isLoading,
    inUse: query.data?.gates_in_use ?? true,
    gateBound: query.data?.gate_bound_event_triggers ?? NO_EVENTS,
  };
}

/** The requirements of the project's requirement sets, each named by what it is about and its set. */
export function useRequirementOptions(projectId: string, t: TFn, enabled = true): LinkOptions {
  const query = useQuery({
    queryKey: [...stakeholderKeys.project(projectId), 'link-requirements'],
    queryFn: () => listRequirementOptions(projectId).then((list) => list.items),
    enabled: !!projectId && enabled,
    retry: false,
    staleTime: 60_000,
  });
  const options = useMemo(
    () =>
      (query.data ?? []).map((r) => ({
        id: r.id,
        label: t('stakeholders.ui.link.requirement', {
          defaultValue: '{{entity}}, {{attribute}} ({{set}})',
          entity: r.entity,
          attribute: r.attribute,
          set: r.set_name,
        }),
      })),
    [query.data, t],
  );
  return { options, loading: query.isLoading };
}

export interface ReleaseItemChoices extends LinkOptions {
  /** False while no installed module provides release items; the server then refuses to store one. */
  available: boolean;
}

/** The release items of the project. Until the answer is in, the picker counts as available. */
export function useReleaseItemOptions(projectId: string, t: TFn, enabled = true): ReleaseItemChoices {
  const query = useQuery({
    queryKey: [...stakeholderKeys.project(projectId), 'link-release-items'],
    queryFn: () => listReleaseItems(projectId),
    enabled: !!projectId && enabled,
    retry: false,
    staleTime: 60_000,
  });
  const options = useMemo(
    () =>
      (query.data?.items ?? []).map((r) => ({
        id: r.id,
        label: r.code
          ? t('stakeholders.ui.link.coded', { defaultValue: '{{code}}: {{title}}', code: r.code, title: r.title })
          : r.title,
      })),
    [query.data, t],
  );
  return { options, loading: query.isLoading, available: query.data?.available ?? true };
}

/** The choices of a single-record picker, keeping a stored link the list no longer offers. */
export function withStored(options: TickOption[], storedId: string, keptLabel: string): TickOption[] {
  if (!storedId || options.some((o) => o.id === storedId)) return options;
  return [{ id: storedId, label: keptLabel }, ...options];
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * React Query hooks for the Work Requests screens. One query key root
 * (`wr`) so a mutation anywhere invalidates every list, board, planner
 * and drawer that shows the same request.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchDepartments,
  fetchMe,
  fetchTemplates,
  fetchMyQueue,
  fetchPlanner,
  fetchProjects,
  fetchRequest,
  fetchRequests,
  fetchSummary,
  fetchUsers,
  type Department,
  type RequestFilters,
  type WorkRequest,
} from './api';
import { errorText, isModuleMissing, type Me } from './lib';

export const WR = 'wr';

/**
 * The departments. `includeInactive` (the Manage screen) is a SEPARATE
 * cache entry on purpose: the two answers differ - one carries retired
 * request types and one must not - and sharing a key would let whichever
 * loaded last decide what the raise dialog offers.
 */
export function useDepartments(includeInactive = false) {
  return useQuery<Department[]>({
    queryKey: [WR, 'departments', includeInactive ? 'all' : 'active'],
    queryFn: () => fetchDepartments(includeInactive),
    retry: (count, err) => !isModuleMissing(err) && count < 2,
    staleTime: 60_000,
  });
}

export function useRequests(filters: RequestFilters, enabled = true) {
  return useQuery<WorkRequest[]>({
    queryKey: [WR, 'requests', filters],
    queryFn: () => fetchRequests(filters),
    retry: (count, err) => !isModuleMissing(err) && count < 2,
    enabled,
    staleTime: 15_000,
  });
}

/**
 * The templates for a department (or every department). A SEPARATE cache
 * entry from the ordinary list on purpose: templates are hidden from
 * `useRequests`, and sharing a key would let a template leak into a board.
 * Only fetched once somebody opens the "start from a template" picker.
 */
export function useTemplates(department: string | undefined, enabled: boolean) {
  return useQuery<WorkRequest[]>({
    queryKey: [WR, 'templates', department ?? 'all'],
    queryFn: () => fetchTemplates(department),
    enabled,
    retry: false,
    staleTime: 60_000,
  });
}

export function useRequest(id: string | null | undefined) {
  return useQuery<WorkRequest>({
    queryKey: [WR, 'request', id],
    queryFn: () => fetchRequest(id as string),
    enabled: !!id,
    retry: (count, err) => !isModuleMissing(err) && count < 2,
    staleTime: 10_000,
  });
}

export function useSummary(projectId: string | null) {
  return useQuery({
    queryKey: [WR, 'summary', projectId],
    queryFn: () => fetchSummary(projectId),
    retry: false,
    staleTime: 30_000,
  });
}

export function useMyQueue(enabled: boolean) {
  return useQuery({
    queryKey: [WR, 'my-queue'],
    queryFn: fetchMyQueue,
    enabled,
    retry: false,
    staleTime: 15_000,
  });
}

export function usePlanner(department: string | null, from: string, to: string) {
  return useQuery({
    queryKey: [WR, 'planner', department, from, to],
    queryFn: () => fetchPlanner(department as string, from, to),
    enabled: !!department,
    retry: false,
    staleTime: 15_000,
  });
}

export function useUsers() {
  return useQuery({ queryKey: [WR, 'users'], queryFn: fetchUsers, staleTime: 300_000, retry: false });
}

export function useProjects() {
  return useQuery({ queryKey: [WR, 'projects'], queryFn: fetchProjects, staleTime: 300_000, retry: false });
}

/** The signed-in user as `{id, name}` (null until the round trip lands). */
export function useMe(): Me | null {
  const q = useQuery({ queryKey: [WR, 'me'], queryFn: fetchMe, staleTime: Infinity, retry: false });
  if (!q.data) return null;
  return { id: q.data.id, name: q.data.full_name || q.data.email };
}

/**
 * Whether to OFFER the Manage screen. `work_requests.manage` is
 * manager-level on the server, and the server stays the authority - this
 * only decides whether a button that would 403 is worth showing. A role
 * the client cannot read (an older token, a role name this list does not
 * know) errs towards showing it: a 403 the screen explains is better
 * than a screen a manager cannot find.
 */
const MANAGE_ROLES = new Set(['admin', 'manager', 'owner']);
const READ_ONLY_ROLES = new Set(['viewer', 'editor', 'site_inspector', 'site_foreman', 'field_worker']);

export function useCanManageWr(): boolean {
  const role = useAuthStore((s) => s.userRole);
  if (!role) return true;
  return MANAGE_ROLES.has(role) || !READ_ONLY_ROLES.has(role);
}

/** Invalidate every Work Requests query (after any write). */
export function useInvalidateWr() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: [WR] });
}

/**
 * A mutation that toasts on failure with the server's words and refreshes
 * every list on success. Callers that need the 409 inline pass `onError`
 * and get the toast skipped.
 */
export function useWrMutation<TArgs, TOut>(
  fn: (args: TArgs) => Promise<TOut>,
  opts?: { onSuccess?: (out: TOut, args: TArgs) => void; onError?: (err: unknown, args: TArgs) => void; quiet?: boolean },
) {
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  return useMutation<TOut, unknown, TArgs>({
    mutationFn: fn,
    onSuccess: (out, args) => {
      void qc.invalidateQueries({ queryKey: [WR] });
      opts?.onSuccess?.(out, args);
    },
    onError: (err, args) => {
      if (opts?.onError) {
        opts.onError(err, args);
        return;
      }
      if (!opts?.quiet) addToast({ type: 'error', title: errorText(err) });
    },
  });
}

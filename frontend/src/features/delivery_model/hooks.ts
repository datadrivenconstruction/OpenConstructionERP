// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the delivery model screens, plus the context every
// screen needs: who is looking (for the button verdicts), how to name a
// catalogue item in the reader's language, and how to say why a write failed.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { getErrorMessage } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

import {
  deliveryErrorCode,
  deliveryKeys,
  deliveryServerMessage,
  getAllocations,
  getComparison,
  getConsistency,
  getModel,
  getPinnedCatalogue,
  getReadiness,
  listCatalogues,
  listDecisions,
  listContractItems,
  listOfi,
  listPackages,
} from './api';
import type { Viewer } from './access';
import { errorText, type LabelContext } from './labels';
import { fetchLinkTargets, type LinkKind } from './linkTargets';

/** The model, or null when the project has none yet (404 `model_missing`), which is an empty state and not an error. */
export function useDeliveryModel(projectId: string) {
  return useQuery({
    queryKey: deliveryKeys.model(projectId),
    queryFn: async () => {
      try {
        return await getModel(projectId);
      } catch (err) {
        // Only `model_missing` is the empty state. A bare 404 also means the
        // project is not visible to this user, and that must read as an error.
        if (deliveryErrorCode(err) === 'model_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

export function useDeliveryCatalogues(enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.catalogues,
    queryFn: () => listCatalogues().then((page) => page.items),
    enabled,
    staleTime: 60_000,
  });
}

export function usePinnedCatalogue(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.catalogue(projectId),
    queryFn: () => getPinnedCatalogue(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useComparison(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.comparison(projectId),
    queryFn: () => getComparison(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useDecisions(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.decisions(projectId),
    queryFn: () => listDecisions(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useAllocations(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.allocations(projectId),
    queryFn: () => getAllocations(projectId),
    enabled: !!projectId && enabled,
  });
}

export function usePackages(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.packages(projectId),
    queryFn: () => listPackages(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useConsistency(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.consistency(projectId),
    queryFn: () => getConsistency(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useOfi(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.ofi(projectId),
    queryFn: () => listOfi(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

export function useContractItems(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.contractItems(projectId),
    queryFn: () => listContractItems(projectId).then((page) => page.items),
    enabled: !!projectId && enabled,
  });
}

/** What the governance gate reads from this module: a decision, every risk allocated, no open errors. */
export function useReadiness(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deliveryKeys.readiness(projectId),
    queryFn: () => getReadiness(projectId),
    enabled: !!projectId && enabled,
  });
}

/**
 * A name for a user id. The API sends ids only and this module has no roster
 * to read, so the one person it can name is the reader; anyone else is null
 * and the screen then leaves the name out instead of printing an id.
 */
export function usePersonName(): (userId: string | null | undefined) => string | null {
  const userId = useAuthStore((s) => s.userId);
  const fullName = useAuthStore((s) => s.userFullName);
  return useCallback((id) => (id && id === userId && fullName ? fullName : null), [userId, fullName]);
}

/** Records of one kind a package or item can link to; `null` data means that kind has no list. */
export function useLinkTargets(projectId: string, kind: LinkKind | null) {
  return useQuery({
    queryKey: deliveryKeys.linkTargets(projectId, kind ?? ''),
    queryFn: () => fetchLinkTargets(projectId, kind as LinkKind),
    enabled: !!projectId && !!kind,
    retry: false,
  });
}

/** Refetch everything the delivery model holds for the project after any write: one proposal touches all of it. */
export function useInvalidateDelivery(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: deliveryKeys.project(projectId) }), [qc, projectId]);
}

export function useViewer(): Viewer {
  const userId = useAuthStore((s) => s.userId);
  const role = useAuthStore((s) => s.userRole);
  return useMemo(() => ({ userId, role }), [userId, role]);
}

export function useLabelContext(): LabelContext {
  const { t, i18n } = useTranslation();
  return useMemo(
    () => ({
      t: t as LabelContext['t'],
      language: i18n.language || 'en',
      exists: (key: string) => (typeof i18n.exists === 'function' ? i18n.exists(key) : false),
    }),
    [t, i18n],
  );
}

/**
 * Why a write failed, in the reader's words: the sentence for the server's
 * refusal code when there is one, else whatever the request layer reports.
 */
export function useRefusalText(): (err: unknown) => string {
  const { t } = useTranslation();
  return useCallback(
    (err: unknown) => {
      const code = deliveryErrorCode(err);
      return code ? errorText(t as LabelContext['t'], code, deliveryServerMessage(err)) : getErrorMessage(err);
    },
    [t],
  );
}

/** An `onError` that shows the refusal as a toast, for writes that have no dialog to show it in. */
export function useRefusalToast(): (err: unknown) => void {
  const addToast = useToastStore((s) => s.addToast);
  const refusal = useRefusalText();
  return useCallback((err: unknown) => addToast({ type: 'error', title: refusal(err) }), [addToast, refusal]);
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for File Transmittals (W7).

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import {
  acknowledgeTransmittal,
  createTransmittal,
  getTransmittal,
  listTransmittals,
  sendTransmittal,
} from './api';
import type {
  Transmittal,
  TransmittalAcknowledgeResponse,
  TransmittalCreatePayload,
  TransmittalListRow,
} from './types';

const KEY_LIST = 'file-transmittals-list';
const KEY_DETAIL = 'file-transmittals-detail';

export function useTransmittals(
  projectId: string | null | undefined,
): UseQueryResult<TransmittalListRow[], Error> {
  return useQuery({
    queryKey: [KEY_LIST, projectId],
    queryFn: () => listTransmittals(projectId as string),
    enabled: Boolean(projectId),
    staleTime: 15_000,
  });
}

export function useTransmittal(
  transmittalId: string | null | undefined,
): UseQueryResult<Transmittal, Error> {
  return useQuery({
    queryKey: [KEY_DETAIL, transmittalId],
    queryFn: () => getTransmittal(transmittalId as string),
    enabled: Boolean(transmittalId),
    staleTime: 10_000,
  });
}

export function useCreateTransmittal(): UseMutationResult<
  Transmittal,
  Error,
  TransmittalCreatePayload
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: TransmittalCreatePayload) => createTransmittal(payload),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: [KEY_LIST, created.project_id] });
    },
  });
}

export function useSendTransmittal(): UseMutationResult<Transmittal, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (transmittalId: string) => sendTransmittal(transmittalId),
    onSuccess: (sent) => {
      void qc.invalidateQueries({ queryKey: [KEY_DETAIL, sent.id] });
      void qc.invalidateQueries({ queryKey: [KEY_LIST, sent.project_id] });
    },
  });
}

/**
 * Recipient-side acknowledgement — public, no auth.
 *
 * Used by the public ACK landing page when a recipient follows their
 * cover-sheet email link.
 */
export function useAcknowledgeTransmittal(): UseMutationResult<
  TransmittalAcknowledgeResponse,
  Error,
  string
> {
  return useMutation({
    mutationFn: (token: string) => acknowledgeTransmittal(token),
  });
}

export const transmittalQueryKeys = {
  list: KEY_LIST,
  detail: KEY_DETAIL,
};

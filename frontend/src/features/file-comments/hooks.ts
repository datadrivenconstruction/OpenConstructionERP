// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** React Query hooks for File Comments. */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import {
  acknowledgeMention,
  createComment,
  deleteComment,
  fileCommentKeys,
  listThreads,
  listUnreadMentions,
  updateComment,
  type ListThreadsArgs,
} from './api';
import type {
  FileCommentCreatePayload,
  FileCommentListResponse,
  FileCommentResponse,
  FileCommentUpdatePayload,
  UnreadMentionListResponse,
} from './types';

/** Load the threaded comment list for a file. */
export function useFileCommentThreads(
  args: ListThreadsArgs | null,
): ReturnType<typeof useQuery<FileCommentListResponse>> {
  return useQuery<FileCommentListResponse>({
    queryKey: [
      fileCommentKeys.threads,
      args?.projectId,
      args?.kind,
      args?.fileId,
      Boolean(args?.includeResolved),
    ],
    queryFn: () => listThreads(args as ListThreadsArgs),
    enabled: Boolean(args && args.projectId && args.fileId),
    staleTime: 10_000,
  });
}

/** Create-comment mutation + invalidate the surrounding thread list. */
export function useCreateFileComment(
  args: Pick<ListThreadsArgs, 'projectId' | 'kind' | 'fileId'> | null,
): UseMutationResult<FileCommentResponse, Error, FileCommentCreatePayload> {
  const qc = useQueryClient();
  return useMutation<FileCommentResponse, Error, FileCommentCreatePayload>({
    mutationFn: (payload) => createComment(payload),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: [
          fileCommentKeys.threads,
          args?.projectId,
          args?.kind,
          args?.fileId,
        ],
      });
      qc.invalidateQueries({ queryKey: [fileCommentKeys.mentions] });
    },
  });
}

export interface UpdateCommentVariables {
  commentId: string;
  payload: FileCommentUpdatePayload;
}

/** Patch-comment mutation. */
export function useUpdateFileComment(
  args: Pick<ListThreadsArgs, 'projectId' | 'kind' | 'fileId'> | null,
): UseMutationResult<FileCommentResponse, Error, UpdateCommentVariables> {
  const qc = useQueryClient();
  return useMutation<FileCommentResponse, Error, UpdateCommentVariables>({
    mutationFn: ({ commentId, payload }) => updateComment(commentId, payload),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: [
          fileCommentKeys.threads,
          args?.projectId,
          args?.kind,
          args?.fileId,
        ],
      });
    },
  });
}

/** Soft-delete-comment mutation. */
export function useDeleteFileComment(
  args: Pick<ListThreadsArgs, 'projectId' | 'kind' | 'fileId'> | null,
): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (commentId) => deleteComment(commentId),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: [
          fileCommentKeys.threads,
          args?.projectId,
          args?.kind,
          args?.fileId,
        ],
      });
    },
  });
}

/** Current user's unread @mentions. */
export function useUnreadMentions(
  limit = 50,
): ReturnType<typeof useQuery<UnreadMentionListResponse>> {
  return useQuery<UnreadMentionListResponse>({
    queryKey: [fileCommentKeys.mentions, limit],
    queryFn: () => listUnreadMentions(limit),
    staleTime: 30_000,
  });
}

/** Acknowledge mutation. */
export function useAcknowledgeMention(): UseMutationResult<
  void,
  Error,
  string
> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (mentionId) => acknowledgeMention(mentionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [fileCommentKeys.mentions] });
    },
  });
}

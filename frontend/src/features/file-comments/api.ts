// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** API client for the File Comments feature (W6).
 *
 * Endpoints live at `/api/v1/file-comments/`. Auto-mounted by the
 * module loader from `app/modules/file_comments/router.py`.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type {
  FileCommentCreatePayload,
  FileCommentListResponse,
  FileCommentResponse,
  FileCommentUpdatePayload,
  FileKind,
  UnreadMentionListResponse,
} from './types';

const BASE = '/v1/file-comments';

export interface ListThreadsArgs {
  projectId: string;
  kind: FileKind;
  fileId: string;
  includeResolved?: boolean;
}

/** Fetch all threads on a file. */
export async function listThreads(
  args: ListThreadsArgs,
): Promise<FileCommentListResponse> {
  const params = new URLSearchParams({
    project_id: args.projectId,
    kind: args.kind,
    file_id: args.fileId,
    include_resolved: String(Boolean(args.includeResolved)),
  });
  return apiGet<FileCommentListResponse>(`${BASE}/?${params.toString()}`);
}

/** Create a top-level comment or reply (when ``parent_id`` is set). */
export async function createComment(
  payload: FileCommentCreatePayload,
): Promise<FileCommentResponse> {
  return apiPost<FileCommentResponse, FileCommentCreatePayload>(
    `${BASE}/`,
    payload,
  );
}

/** Edit body / toggle resolved. */
export async function updateComment(
  commentId: string,
  payload: FileCommentUpdatePayload,
): Promise<FileCommentResponse> {
  return apiPatch<FileCommentResponse, FileCommentUpdatePayload>(
    `${BASE}/${commentId}/`,
    payload,
  );
}

/** Soft-delete a comment (body replaced with ``[deleted]``). */
export async function deleteComment(commentId: string): Promise<void> {
  await apiDelete<void>(`${BASE}/${commentId}/`);
}

/** Inbox: current user's unread @mentions. */
export async function listUnreadMentions(
  limit = 50,
): Promise<UnreadMentionListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiGet<UnreadMentionListResponse>(
    `${BASE}/mentions/me/?${params.toString()}`,
  );
}

/** Mark a single mention as notified (drops it from the inbox). */
export async function acknowledgeMention(mentionId: string): Promise<void> {
  await apiPost<void, Record<string, never>>(
    `${BASE}/mentions/${mentionId}/acknowledge/`,
    {},
  );
}

export const fileCommentKeys = {
  threads: 'file-comments-threads' as const,
  mentions: 'file-comments-mentions' as const,
};

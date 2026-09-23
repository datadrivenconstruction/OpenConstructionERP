// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The body of `POST /v1/erp_chat/stream/`, built in one place for both chat
 * surfaces (the dock and the /chat page) so they cannot drift apart.
 *
 * Besides the message it tells the assistant where the person is: the UI
 * language (`locale`), so replies and proposals come back in the language on
 * screen, and `client_context` with the current route and the project open in
 * the app, so "add a task for Friday" lands in the project the person is
 * looking at. Both are hints: the server drops a malformed value instead of
 * refusing the message, and checks the project against the person's access
 * before the model hears anything about it.
 */

export interface StreamRequestInput {
  message: string;
  sessionId: string | null;
  projectId: string | null;
  /** `i18n.language`, e.g. `de` or `pt-BR`. */
  locale: string | null | undefined;
  /** The router's current pathname. */
  route: string | null | undefined;
}

export interface StreamRequestBody {
  message: string;
  session_id: string | null;
  project_id: string | null;
  locale: string | null;
  client_context: { route: string | null; project_id: string | null };
}

function nonEmpty(value: string | null | undefined): string | null {
  const trimmed = typeof value === 'string' ? value.trim() : '';
  return trimmed ? trimmed : null;
}

export function buildStreamRequestBody(input: StreamRequestInput): StreamRequestBody {
  return {
    message: input.message,
    session_id: input.sessionId,
    project_id: input.projectId,
    locale: nonEmpty(input.locale),
    client_context: { route: nonEmpty(input.route), project_id: input.projectId },
  };
}

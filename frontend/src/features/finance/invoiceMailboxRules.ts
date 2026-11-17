// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

export interface MailboxDraft {
  enabled: boolean;
  host: string;
  port: number;
  use_ssl: boolean;
  username: string;
  password: string;
  folder: string;
  processed_folder: string;
  intake_address: string;
}

const HOST_RE = /^([A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '::1'];

/**
 * Field names (also the i18n suffixes `finance.inbox.mailbox_<field>`) whose value the
 * server would refuse. Mirrors the backend rules so the form can say so before saving;
 * the server stays the authority.
 */
export function mailboxDraftProblems(draft: MailboxDraft, hasStoredPassword: boolean): string[] {
  const out: string[] = [];
  const host = draft.host.trim();
  if (host && !HOST_RE.test(host)) out.push('host');
  if (!Number.isInteger(draft.port) || draft.port < 1 || draft.port > 65535) out.push('port');
  if (host && !draft.use_ssl && !LOCAL_HOSTS.includes(host.toLowerCase())) out.push('ssl');
  if (draft.intake_address.trim() && !EMAIL_RE.test(draft.intake_address.trim())) out.push('intake_address');
  if (
    draft.processed_folder.trim() &&
    draft.processed_folder.trim().toLowerCase() === draft.folder.trim().toLowerCase()
  ) {
    out.push('processed_folder');
  }
  if (draft.enabled) {
    if (!host && !out.includes('host')) out.push('host');
    if (!draft.username.trim()) out.push('username');
    if (!draft.password && !hasStoredPassword) out.push('password');
    if (!draft.folder.trim()) out.push('folder');
  }
  return out;
}

/** True when the API refused the host as an internal/private address (422, code `host_not_allowed`). */
export function isHostNotAllowed(error: unknown): boolean {
  const body = (error as { body?: unknown } | null)?.body;
  const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : undefined;
  return Array.isArray(detail) && detail.some((d) => (d as { code?: unknown } | null)?.code === 'host_not_allowed');
}

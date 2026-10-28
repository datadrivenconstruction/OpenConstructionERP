// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The decisions the clearance screen makes for itself.
 *
 * Everything else on the panel is the server's answer rendered as it came.
 * These are ours, and each has a wrong version that looks right: an action set
 * that ignores the state machine offers to send a document twice, and a
 * severity or status mapper without a fallback draws no badge at all for a word
 * the backend adds later.
 *
 * They live apart from the panel deliberately. Importing the panel pulls in the
 * shared UI barrel, which transitively boots i18next with the whole English
 * resource, and a vitest worker that does that never answers. The type import
 * below is erased at compile time, so this module has no runtime dependency on
 * anything.
 */

import type { ClearanceFinding, CountryRegime, DocumentStatus } from './api';

export type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

export type ClearanceAction = 'validate' | 'submit' | 'resolve' | 'cancel';

/**
 * A set spelled from the known vocabulary but read with an open one.
 *
 * The members are checked against `DocumentStatus`, so a typo here is a compile
 * error rather than a state that silently never matches. The lookup takes a
 * plain string, because what arrives is whatever /meta lists.
 */
function statusSet(...values: DocumentStatus[]): ReadonlySet<string> {
  return new Set<string>(values);
}

/**
 * Nothing has been sent yet, so the document is still the operator's to fix.
 * `rejected` belongs here: the authority answered no, and the same document is
 * corrected and sent again — that is what `retry_count` counts.
 */
const PRE_SEND = statusSet('draft', 'validated', 'queued', 'rejected');

/**
 * The three regime-specific successes. A clearance country's yes is `cleared`,
 * a reporting country's is `reported`, a network's is `delivered`, and only
 * from one of these is there anything at the platform to withdraw.
 */
const AUTHORITY_HOLDS = statusSet('cleared', 'reported', 'delivered');

/**
 * Sent, with no answer recorded against it.
 *
 * The adapters answer synchronously, so a document only stays here when the
 * transport failed before the platform replied — nobody knows whether it
 * arrived. That is the whole reason `resolve` exists.
 */
const IN_DOUBT: DocumentStatus = 'submitted';

/**
 * Exhaustive over the vocabulary as it stands: adding a state to
 * `DocumentStatus` without deciding how it looks is a compile error. The lookup
 * is still open, because the backend can add one without this file changing.
 */
const STATUS_VARIANTS: Record<DocumentStatus, BadgeVariant> = {
  // Draft and cancelled share a variant because neither is a claim about what
  // an authority answered; the label is what tells them apart.
  draft: 'neutral',
  cancelled: 'neutral',
  validated: 'blue',
  queued: 'blue',
  // Amber, not blue. A document sitting here is not progressing, it is waiting
  // for a human to go and look at the portal.
  submitted: 'warning',
  cleared: 'success',
  reported: 'success',
  delivered: 'success',
  rejected: 'error',
};

/**
 * /meta is the authority on the status vocabulary, so a status this file has
 * never seen has to land somewhere visible rather than drawing nothing.
 */
export function statusVariant(status: string): BadgeVariant {
  return (STATUS_VARIANTS as Record<string, BadgeVariant | undefined>)[status] ?? 'neutral';
}

/**
 * Severities come from the validation engine, which is free to add one.
 */
export function severityVariant(severity: string): BadgeVariant {
  if (severity === 'error' || severity === 'critical') return 'error';
  if (severity === 'warning') return 'warning';
  return 'neutral';
}

/**
 * Which acts the state machine leaves open on a document in this state.
 *
 * Two of these are narrower than the backend's own guard, on purpose:
 *
 * `submit` is not offered on a `submitted` document even though the server
 * would take it — only `FINAL_STATUSES` are refused there. Sending again a
 * document that may already have reached the platform risks two cleared
 * invoices for one sale, which is the exact outcome `resolve` was added to
 * avoid, so the screen offers the safe way out instead of the fast one.
 *
 * `cancel` additionally needs the country to have a cancellation flow at all.
 * Where it has none the correction is a further document, which is a different
 * act with different accounting, and a button that always 422s is worse than
 * no button.
 *
 * The cancellation *window* is deliberately not checked here. Deciding from
 * `cleared_at` in a browser whether a statutory deadline has passed is the
 * frontend re-deriving statute; the backend refuses, and it is right.
 */
export function availableActions(
  status: string,
  options: { cancellable?: boolean } = {},
): ClearanceAction[] {
  if (PRE_SEND.has(status)) return ['validate', 'submit'];
  if (status === IN_DOUBT) return ['resolve'];
  if (AUTHORITY_HOLDS.has(status)) return options.cancellable ? ['cancel'] : [];
  return [];
}

/** Whether this document is the one waiting on somebody reading the portal. */
export function isInDoubt(status: string): boolean {
  return status === IN_DOUBT;
}

/**
 * The findings a refusal carried.
 *
 * The module answers a refused act with `{detail: {message, findings}}`, and
 * the shared `getErrorMessage` resolves only `detail.message` — so "this
 * document cannot be submitted yet" reaches the toast and the names of what
 * blocked it are dropped on the floor. The backend states the missing national
 * field by name; this is how that name reaches the screen.
 *
 * Duck-typed rather than `instanceof ApiError`, because importing
 * `@/shared/lib/api` here would drag the auth store, the toast store, the
 * IndexedDB offline store and i18next into a module whose whole point is having
 * no runtime dependencies.
 */
export function findingsFromError(err: unknown): ClearanceFinding[] {
  const detail = (err as { body?: { detail?: unknown } } | null | undefined)?.body?.detail;
  if (!isRecord(detail)) return [];
  const raw = detail.findings;
  if (!Array.isArray(raw)) return [];
  const findings: ClearanceFinding[] = [];
  for (const entry of raw) {
    const finding = toFinding(entry);
    if (finding) findings.push(finding);
  }
  return findings;
}

/**
 * Whether a refusal was the waivable kind.
 *
 * A submission refused for warnings alone can be sent again with them
 * acknowledged; one carrying a single error cannot be waived at all. Told apart
 * by severity rather than by the refusal's English, which is not a contract.
 */
export function onlyWarnings(findings: ClearanceFinding[]): boolean {
  return findings.length > 0 && findings.every((f) => f.severity === 'warning');
}

/**
 * The registry entry for a document's country.
 *
 * A miss means the screen cannot say whether the country cancels at all, so it
 * offers nothing rather than guessing — the cancel button and the identifier
 * label both hang off this.
 */
export function countryRegime(
  countries: CountryRegime[],
  code: string,
): CountryRegime | undefined {
  const wanted = (code || '').trim().toUpperCase();
  if (!wanted) return undefined;
  return countries.find((c) => (c.country || '').toUpperCase() === wanted);
}

/* ── internals ─────────────────────────────────────────────────────────── */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function toFinding(entry: unknown): ClearanceFinding | null {
  if (!isRecord(entry)) return null;
  const rule_id = str(entry.rule_id);
  const message = str(entry.message);
  // Neither a name nor a sentence is not a finding, it is a blank row.
  if (!rule_id && !message) return null;
  return {
    key: str(entry.key),
    rule_id,
    severity: str(entry.severity),
    message,
    suggestion: str(entry.suggestion),
    details: isRecord(entry.details) ? entry.details : {},
  };
}

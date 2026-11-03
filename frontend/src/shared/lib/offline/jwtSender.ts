// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sender for plain queued writes that carry no device-side record (field-time
 * days, withdrawals, clock taps). The record queue routes every op without
 * `meta.entity` here, so those writes share one queue, one backoff and one
 * status pill with the diary, punch and inspection records.
 *
 * The body goes out exactly as queued: the idempotency keys (`entry_key`,
 * `client_op_id`) already live inside it, and the op id also travels as a header.
 */

import { fetchWithAuth, getAuthToken } from '@/shared/lib/api';
import { holdAuth, isAuthHeld } from './authHold';
import type { OpSender, QueuedOp, ReplayOutcome } from './mutationQueue';

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

async function jsonOf(res: Response): Promise<Record<string, unknown> | null> {
  try {
    return (await res.clone().json()) as Record<string, unknown> | null;
  } catch {
    return null;
  }
}

function detailOf(data: Record<string, unknown> | null): string | undefined {
  return data && typeof data.detail === 'string' ? data.detail : undefined;
}

/**
 *  - 2xx          applied (a redelivery also answers 200, so both stop the resend)
 *  - 401          held: expired credentials, the op stays untouched until re-login
 *  - 409          conflict: permanent, the person is told
 *  - other 4xx    rejected (408 and 429 are transient)
 *  - 5xx          retry
 */
export async function jwtOutcomeFromResponse(res: Response): Promise<ReplayOutcome> {
  if (res.ok) {
    const data = await jsonOf(res);
    const ts = data?.timesheet as { id?: unknown } | undefined;
    const id = typeof ts?.id === 'string' ? ts.id : typeof data?.id === 'string' ? data.id : null;
    return { kind: 'applied', httpStatus: res.status, resultId: id };
  }
  if (res.status === 401) {
    holdAuth('jwt', getAuthToken() ?? '');
    return { kind: 'held', httpStatus: 401 };
  }
  const detail = detailOf(await jsonOf(res));
  if (res.status === 409) return { kind: 'conflict', httpStatus: 409, detail };
  if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
    return { kind: 'rejected', httpStatus: res.status, detail };
  }
  return { kind: 'retry', httpStatus: res.status, detail };
}

export function createJwtSender(fetcher: Fetcher = fetchWithAuth): OpSender {
  return async (op: QueuedOp): Promise<ReplayOutcome> => {
    if (isAuthHeld('jwt')) return { kind: 'held', detail: 'auth_expired' };
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-Client-Op-Id': op.clientOpId,
    };
    const res = await fetcher(`/api${op.path}`, {
      method: op.method,
      headers,
      body: op.body === undefined ? undefined : JSON.stringify(op.body),
    });
    return jwtOutcomeFromResponse(res);
  };
}

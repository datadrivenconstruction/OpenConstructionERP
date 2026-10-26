// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Clock events captured with no signal​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠. They ride the field-time queue (same
 * IndexedDB, same JWT sender); `client_op_id` doubles as the server's
 * idempotency key and `occurred_at` is the device time of the tap, so a replay
 * an hour later still books the shift at the right moment.
 */

import { newClientOpId } from '@/shared/lib/offline';
import { getFieldTimeQueue } from './offlineQueue';
import type { ClockEventPayload } from './clockApi';

export const OP_CLOCK = 'field_time.clock';
const CLOCK_PATH = '/v1/field-time/clock/events/';

/** Queue one clock tap for replay; resolves to the id sent as client_op_id. */
export async function enqueueClockEvent(payload: ClockEventPayload): Promise<string> {
  const clientOpId = payload.client_op_id ?? newClientOpId();
  await getFieldTimeQueue().enqueue({
    clientOpId,
    method: 'POST',
    path: CLOCK_PATH,
    body: { ...payload, client_op_id: clientOpId },
    kind: OP_CLOCK,
  });
  return clientOpId;
}

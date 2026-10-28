// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The two pure decisions the payment clock screen makes for itself.
 *
 * They live apart from the panel deliberately. Importing the panel pulls in
 * the shared UI barrel, which transitively boots i18next with the whole
 * English resource, and a vitest worker that does that never answers. The type
 * import below is erased at compile time, so this module has no runtime
 * dependency on anything.
 */

import type { PaymentApplication } from './api';

/**
 * Severity strings come from the validation engine, not from a Literal, so an
 * unknown one has to land somewhere rather than render nothing.
 */
export function severityVariant(severity: string): 'warning' | 'error' | 'neutral' {
  if (severity === 'error' || severity === 'critical') return 'error';
  if (severity === 'warning') return 'warning';
  return 'neutral';
}

/**
 * Past the final date for payment, and still owed.
 *
 * Both halves matter. A paid application whose final date has passed is not
 * overdue, it is simply history, and flagging it would put a permanent red
 * badge on every settled payment. A null final date means the regime has not
 * produced one yet, which is not the same as a deadline that passed.
 *
 * Dates are compared as ISO strings on purpose: they arrive from the API as
 * `YYYY-MM-DD`, which sorts lexicographically, and parsing them into Date
 * would drag the browser's timezone into a statutory deadline.
 */
export function isOverdue(app: PaymentApplication, today: string): boolean {
  return app.status === 'open' && !!app.final_date && app.final_date < today;
}

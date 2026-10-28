// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The sentence a failed BOQ editor action shows the user.
 *
 * A refusal from the API carries the server's own (translated) reason and is
 * kept. A network failure or a timeout gets the shared translated wording.
 * Anything else is a thrown error whose text was written for developers
 * ("Failed to fetch", "Cannot read properties of undefined"): it goes to the
 * console, and the user reads a translated sentence with a way forward.
 */

import { ApiError, getErrorMessage } from '@/shared/lib/api';

type Translate = (key: string, opts?: Record<string, unknown>) => string;

export function editorErrorText(err: unknown, t: Translate): string {
  // Raw detail stays available to whoever opens the console.
  console.error('[boq editor]', err);
  if (err instanceof ApiError) return err.message;
  const text = getErrorMessage(err);
  const passedThrough = err instanceof Error && text === err.message;
  if (!passedThrough) return text;
  return t('boq.action_failed_generic', {
    defaultValue: 'The change could not be saved. Check your connection and try again; reload the page if it keeps failing.',
  });
}

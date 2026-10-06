// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One readable, translated sentence for a failed match request.
//
// A run that failed used to show the transport text verbatim -
// "500 Internal server error", or an English timeout sentence - in every
// language. The sentence here says what happened and what to do next;
// a specific reason the server gave for a 4xx is kept, because the
// backend words those for people already.

import type { TFunction } from 'i18next';

import { MatchApiError } from './api';

/**
 * Which request failed. A 404 means different things at different steps:
 * starting a session cannot find the PROJECT (or may not see it), while
 * any later step cannot find the SESSION.
 */
export type MatchErrorContext = 'session' | 'run';

export function describeMatchError(
  err: unknown,
  t: TFunction,
  context: MatchErrorContext = 'run',
): string {
  if (err instanceof MatchApiError) {
    if (err.kind === 'timeout') {
      return t('match_elements.error.timeout', {
        defaultValue:
          'The server did not answer in time. The match may still be running: wait a minute and refresh, or run it again.',
      });
    }
    if (err.kind === 'network') {
      return t('match_elements.error.network', {
        defaultValue: 'Could not reach the server. Check your connection and try again.',
      });
    }
    const status = err.status ?? 0;
    if (status >= 500) {
      return t('match_elements.error.server', {
        defaultValue:
          'The server hit an error while matching. Try again; if it keeps happening, the server log has the details.',
      });
    }
    if (status === 401) {
      return t('match_elements.error.sign_in', {
        defaultValue: 'Your sign-in has expired. Sign in again, then repeat the step.',
      });
    }
    if (status === 403) {
      return t('match_elements.error.forbidden', {
        defaultValue: 'You do not have access to matching in this project.',
      });
    }
    if (status === 404) {
      return context === 'session'
        ? t('match_elements.error.project_not_found', {
            defaultValue:
              'This project was not found, or you do not have access to it. Pick the project again or ask its owner.',
          })
        : t('match_elements.error.not_found', {
            defaultValue: 'This match session no longer exists. Start again from the first step.',
          });
    }
    if (status === 422) {
      // The raw validation text ("body.x: Input should be ...") is for
      // developers; the reader gets which fields, in their language.
      return err.fields.length > 0
        ? t('match_elements.error.invalid_input', {
            defaultValue: 'Some settings were not accepted: {{fields}}. Check them and try again.',
            fields: err.fields.join(', '),
          })
        : t('match_elements.error.invalid_input_any', {
            defaultValue: 'Some settings were not accepted. Check them and try again.',
          });
    }
    if (err.detail) return err.detail;
  }
  return t('match_elements.error.unknown', {
    defaultValue: 'Matching stopped with an unexpected error. Try again.',
  });
}

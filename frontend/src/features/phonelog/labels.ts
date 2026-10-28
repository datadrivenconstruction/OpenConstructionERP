// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shared display helpers for the phone log: badge variants, the canonical
// direction / channel picker sets, their translated labels, and a compact
// duration formatter. Kept in one place so the page, the filter bar, and the
// edit dialog render a call the same way instead of each redefining them.

import { formatDuration as formatSharedDuration } from '@/shared/lib/duration';
import type { PhoneChannel, PhoneDirection } from './types';

export type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

export const DIRECTION_VARIANT: Record<PhoneDirection, BadgeVariant> = {
  inbound: 'blue',
  outbound: 'success',
  internal: 'neutral',
  unknown: 'neutral',
};

export const CHANNEL_VARIANT: Record<PhoneChannel, BadgeVariant> = {
  phone: 'neutral',
  voice_note: 'warning',
  chat: 'blue',
  other: 'neutral',
};

// The canonical values the forms submit. The server also accepts informal
// synonyms, but the pickers offer the clean set so the stored value is exact.
export const DIRECTIONS: PhoneDirection[] = ['inbound', 'outbound', 'internal'];
export const CHANNELS: PhoneChannel[] = ['phone', 'voice_note', 'chat'];

type TFn = (k: string, o: { defaultValue: string }) => string;

/** `t` as the shared duration formatter needs it: it interpolates numbers too. */
type DurationTFn = Parameters<typeof formatSharedDuration>[0];

export function directionLabel(t: TFn, d: PhoneDirection): string {
  return t(`phonelog.direction_${d}`, {
    defaultValue: { inbound: 'Inbound', outbound: 'Outbound', internal: 'Internal', unknown: 'Unknown' }[d],
  });
}

export function channelLabel(t: TFn, c: PhoneChannel): string {
  return t(`phonelog.channel_${c}`, {
    defaultValue: { phone: 'Phone call', voice_note: 'Voice note', chat: 'Chat', other: 'Other' }[c],
  });
}

/**
 * A call length, at the scale of the call (#174).
 *
 * This used to floor at minutes, so a two-hour call read "120m". It now runs
 * through the shared formatter and reads "2h". Short calls are unchanged:
 * 45s stays "45s", 90s stays "1m 30s". The em-dash-free "-" is kept for a
 * call with no recorded length, because a blank cell in the table reads as a
 * rendering fault rather than as missing data.
 */
export function formatDuration(t: DurationTFn, seconds: number | null): string {
  return formatSharedDuration(t, seconds, 's', { parts: 2, empty: '-' });
}

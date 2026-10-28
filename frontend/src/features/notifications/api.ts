// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Notifications API client — preferences + event-type catalogue
 * (Wave 3 / T9).
 *
 * The legacy list / mark-read / delete endpoints stay where they are
 * (inlined in NotificationsPage.tsx) so this file is additive only.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

export type NotificationChannel = 'email' | 'inapp' | 'webhook' | 'none';
export type NotificationDigest = 'realtime' | 'hourly' | 'daily';

export interface NotificationPreference {
  id: string;
  user_id: string;
  event_type: string;
  channel: NotificationChannel;
  enabled: boolean;
  digest: NotificationDigest;
  created_at: string;
  updated_at: string;
}

export interface NotificationPreferenceRequest {
  event_type: string;
  channel: NotificationChannel;
  enabled: boolean;
  digest: NotificationDigest;
}

export interface NotificationEventType {
  event_type: string;
  module: string;
  description: string;
}

/**
 * Fetch every notification preference row for the current user.
 *
 * Endpoint: ``GET /v1/notifications/preferences/``
 */
export async function getPreferences(): Promise<NotificationPreference[]> {
  return apiGet<NotificationPreference[]>('/v1/notifications/preferences/');
}

/**
 * Upsert a single (event_type, channel) preference for the current user.
 *
 * Endpoint: ``POST /v1/notifications/preferences/``
 */
export async function setPreference(
  body: NotificationPreferenceRequest,
): Promise<NotificationPreference> {
  return apiPost<NotificationPreference, NotificationPreferenceRequest>(
    '/v1/notifications/preferences/',
    body,
  );
}

/**
 * Fetch the catalogue of known event types the platform may emit.
 *
 * Endpoint: ``GET /v1/notifications/event-types/``
 */
export async function getEventTypes(): Promise<NotificationEventType[]> {
  return apiGet<NotificationEventType[]>('/v1/notifications/event-types/');
}

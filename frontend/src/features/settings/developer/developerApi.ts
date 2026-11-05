// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wire types and calls for Settings, Developer: personal API keys and signed
 * webhooks. Scope and event catalogues come from the server, so the screen
 * never carries its own list of either.
 */
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, getErrorMessage } from '@/shared/lib/api';


export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  description: string;
  is_active: boolean;
  permissions: string[];
  rate_limit_per_min: number | null;
  allowed_cidrs: string[];
  request_count: number;
  rotated_from_id: string | null;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  /** The plaintext key; returned once, never again. */
  key: string;
}

export interface ApiKeyCreate {
  name: string;
  permissions: string[];
  expires_in_days: number | null;
  rate_limit_per_min: number | null;
  allowed_cidrs: string[];
}

export interface CatalogueEntry {
  name: string;
  module: string;
  i18n_key: string;
}

export interface ApiScope extends CatalogueEntry {
  action: string;
  min_role: string;
}

export type WebhookEvent = CatalogueEntry;

export interface Webhook {
  id: string;
  name: string;
  url: string;
  /** Redacted marker when a signing secret is set; never the secret itself. */
  secret: string | null;
  events: string[];
  is_active: boolean;
  last_triggered_at: string | null;
  last_status_code: number | null;
  failure_count: number;
  created_at: string;
}

export interface WebhookCreated extends Webhook {
  /** The signing secret; returned once, never again. */
  signing_secret: string;
}

export interface WebhookCreate {
  name: string;
  url: string;
  events: string[];
  secret?: string;
}

export type DeliveryStatus = 'pending' | 'retrying' | 'delivered' | 'dead';

export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  event_type: string;
  status_code: number | null;
  duration_ms: number | null;
  attempt: number;
  next_retry_at: string | null;
  status: DeliveryStatus;
  last_error: string;
  created_at: string;
}

/** Sends before a delivery is given up on: the first try plus four retries. */
export const MAX_ATTEMPTS = 5;

export const developerKeys = {
  all: ['developer'] as const,
  apiKeys: ['developer', 'api-keys'] as const,
  scopes: ['developer', 'scopes'] as const,
  webhooks: ['developer', 'webhooks'] as const,
  events: ['developer', 'events'] as const,
  deliveries: (webhookId: string) => ['developer', 'deliveries', webhookId] as const,
};

export const listApiKeys = () => apiGet<ApiKey[]>(`/v1/users/me/api-keys/`);
export const listApiScopes = () => apiGet<ApiScope[]>(`/v1/users/me/api-keys/scopes/`);
export const createApiKey = (body: ApiKeyCreate) => apiPost<ApiKeyCreated>(`/v1/users/me/api-keys/`, body);
export const rotateApiKey = (id: string) => apiPost<ApiKeyCreated>(`/v1/users/me/api-keys/${encodeURIComponent(id)}/rotate/`);
export const revokeApiKey = (id: string) => apiDelete(`/v1/users/me/api-keys/${encodeURIComponent(id)}`);

export const listWebhooks = () => apiGet<Webhook[]>(`/v1/integrations/webhooks/`);
export const listWebhookEvents = () => apiGet<WebhookEvent[]>(`/v1/integrations/webhooks/events/`);
export const createWebhook = (body: WebhookCreate) => apiPost<WebhookCreated>(`/v1/integrations/webhooks/`, body);
export const setWebhookActive = (id: string, isActive: boolean) =>
  apiPatch<Webhook>(`/v1/integrations/webhooks/${encodeURIComponent(id)}`, { is_active: isActive });
export const deleteWebhook = (id: string) => apiDelete(`/v1/integrations/webhooks/${encodeURIComponent(id)}`);
export const testWebhook = (id: string) =>
  apiPost<WebhookDelivery>(`/v1/integrations/webhooks/${encodeURIComponent(id)}/test/`);
export const listDeliveries = (id: string) =>
  apiGet<WebhookDelivery[]>(`/v1/integrations/webhooks/${encodeURIComponent(id)}/deliveries/`);
export const redeliver = (deliveryId: string) =>
  apiPost<WebhookDelivery>(`/v1/integrations/webhooks/deliveries/${encodeURIComponent(deliveryId)}/redeliver/`);

/** The server's reason when it gave one (`detail.message`), else the generic error text. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === 'string' && message) return message;
    }
  }
  return getErrorMessage(err);
}

/** One CIDR per line or separated by commas or spaces. */
export function parseCidrs(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

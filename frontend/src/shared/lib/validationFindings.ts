// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import i18next from 'i18next';
import { useToastStore } from '@/stores/useToastStore';

/** One rule finding as the backend rule gate serialises it (`failure.py: finding`). */
export interface ValidationFinding {
  rule_id?: string;
  code?: string;
  message?: string;
  params?: Record<string, unknown>;
}

function isFinding(v: unknown): v is ValidationFinding {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

/**
 * Text for one finding: the catalogue entry `api_errors.<code>` filled from `params`
 * when this build has one, else the server's message. Never the bare code.
 */
export function findingText(f: ValidationFinding): string | null {
  const code = typeof f.code === 'string' && f.code ? f.code : f.rule_id;
  if (typeof code === 'string' && code && i18next.exists(`api_errors.${code}`)) {
    const params = f.params && typeof f.params === 'object' ? f.params : {};
    return i18next.t(`api_errors.${code}`, params);
  }
  return typeof f.message === 'string' && f.message.length > 0 ? f.message : null;
}

/** Up to `limit` finding texts joined for display, with a "+n" tail for the rest. */
export function joinFindings(findings: unknown[], limit = 3): string | null {
  const texts = findings.filter(isFinding).map(findingText).filter((s): s is string => !!s);
  if (texts.length === 0) return null;
  const more = texts.length - limit;
  const head = texts.slice(0, limit).join('; ');
  return more > 0 ? `${head} (+${more})` : head;
}

/**
 * Show the non-blocking findings a write endpoint returns in `validation_warnings`
 * as one warning toast. The save already happened, so nothing is thrown.
 */
export function surfaceValidationWarnings(data: unknown): void {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return;
  const warnings = (data as Record<string, unknown>).validation_warnings;
  if (!Array.isArray(warnings) || warnings.length === 0) return;
  const message = joinFindings(warnings);
  if (!message) return;
  useToastStore.getState().addToast({
    type: 'warning',
    title: i18next.t('validation.saved_with_warnings', { defaultValue: 'Saved with warnings' }),
    message,
  });
}

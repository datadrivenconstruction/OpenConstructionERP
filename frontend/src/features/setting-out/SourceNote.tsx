// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Where a tolerance or threshold comes from: standard, edition, clause, and
 * whether the value was checked against the source. Shown next to the value
 * in setting-out and monitoring.
 */

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui/Badge';
import type { SourceStatus } from './api';

/** One line of source text: reference, then the clause when it adds something. */
export function sourceText(reference: string | undefined, clause?: string): string {
  const ref = (reference ?? '').trim();
  const cl = (clause ?? '').trim();
  if (!cl || ref.includes(cl)) return ref;
  return ref ? `${ref}, ${cl}` : cl;
}

/** A stored request reference ends with its status ("...; to_verify"); split it off for the badge. */
export function splitReference(stored: string | undefined): { text: string; status: SourceStatus } {
  const ref = (stored ?? '').trim();
  for (const status of ['to_verify', 'verified'] as const) {
    const tail = `; ${status}`;
    if (ref.endsWith(tail)) return { text: ref.slice(0, -tail.length), status };
  }
  return { text: ref, status: '' };
}

export function SourceNote({
  reference,
  clause,
  status,
  testId,
}: {
  reference?: string;
  clause?: string;
  status?: SourceStatus | string;
  testId?: string;
}) {
  const { t } = useTranslation();
  const text = sourceText(reference, clause);
  if (!text && !status) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-xs text-content-tertiary" data-testid={testId}>
      <span>
        {t('survey.source.label', { defaultValue: 'Source' })}: {text || '-'}
      </span>
      {status === 'verified' && (
        <Badge variant="success" size="sm">
          {t('survey.source.verified', { defaultValue: 'Clause cited' })}
        </Badge>
      )}
      {status === 'to_verify' && (
        <Badge variant="warning" size="sm">
          <span title={t('survey.source.to_verify_tip', { defaultValue: 'Not yet checked against the published standard. Confirm the value before you rely on it.' })}>
            {t('survey.source.to_verify', { defaultValue: 'To verify' })}
          </span>
        </Badge>
      )}
    </span>
  );
}

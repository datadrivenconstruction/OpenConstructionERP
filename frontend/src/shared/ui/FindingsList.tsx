// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FindingsList - compact list of validation findings returned by the API
 * (`rule_id`, `severity`, `message`, `params`, `suggestion`). Messages arrive
 * already worded in the caller's language. Renders nothing for an empty list.
 */
import { AlertCircle, AlertTriangle, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { fmtList } from '@/shared/lib/formatters';

export interface ValidationFinding {
  rule_id?: string;
  code?: string;
  rule_name?: string;
  severity?: string;
  message?: string;
  params?: Record<string, unknown> | null;
  element_ref?: string | null;
  suggestion?: string | null;
}

export interface FindingsListProps {
  findings: ValidationFinding[] | null | undefined;
  title?: string;
  testId?: string;
}

const SEVERITY: Record<string, { Icon: typeof Info; cls: string }> = {
  error: { Icon: AlertCircle, cls: 'text-semantic-error' },
  warning: { Icon: AlertTriangle, cls: 'text-semantic-warning' },
  info: { Icon: Info, cls: 'text-oe-blue' },
};

/** Scalar params the rule reported (the affected values), as "key: value". */
function affectedValues(params: ValidationFinding['params']): string[] {
  if (!params) return [];
  return Object.entries(params)
    .filter(([, v]) => typeof v === 'string' || typeof v === 'number')
    .slice(0, 3)
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`);
}

export function FindingsList({ findings, title, testId = 'findings-list' }: FindingsListProps) {
  const { t } = useTranslation();
  if (!findings || findings.length === 0) return null;

  return (
    <div
      className="rounded-lg border border-border-light bg-surface-primary px-3 py-2"
      data-testid={testId}
    >
      <p className="text-xs font-semibold text-content-primary">
        {title ??
          t('validation_findings.title', { defaultValue: 'Validation findings' })}{' '}
        <span className="font-normal text-content-tertiary">({findings.length})</span>
      </p>
      <ul className="mt-1.5 space-y-1.5">
        {findings.map((f, i) => {
          const sev = SEVERITY[f.severity ?? ''] ?? SEVERITY.info!;
          const values = affectedValues(f.params);
          return (
            <li
              key={`${f.rule_id ?? f.code ?? 'f'}-${i}`}
              className="flex items-start gap-2"
              data-testid="finding-item"
              data-severity={f.severity ?? 'info'}
            >
              <sev.Icon
                size={14}
                className={`mt-0.5 shrink-0 ${sev.cls}`}
                aria-label={t(`validation_findings.severity_${f.severity ?? 'info'}`, {
                  defaultValue: f.severity ?? 'info',
                })}
              />
              <div className="min-w-0 text-2xs text-content-secondary">
                <span>{f.message ?? f.rule_name ?? f.rule_id}</span>
                {values.length > 0 && (
                  <span className="ml-1.5 tabular-nums text-content-tertiary">
                    ({fmtList(values)})
                  </span>
                )}
                {f.suggestion && (
                  <span className="block text-content-tertiary">{f.suggestion}</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

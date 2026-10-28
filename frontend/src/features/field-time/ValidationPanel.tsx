// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <ValidationPanel> - traffic-light view of a timesheet's validation
 * report, consistent with how the platform surfaces validation elsewhere
 * (green = passed, yellow = warnings, red = errors). Each finding links a
 * plain-language message and, where the backend offers one, a suggested fix.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { CheckCircle2, AlertTriangle, XCircle, Info, Loader2 } from 'lucide-react';
import type { FieldTimeValidationReport, FieldTimeValidationResult } from './api';

type Severity = 'error' | 'warning' | 'info';

function severityOf(result: FieldTimeValidationResult): Severity {
  const s = result.severity.toLowerCase();
  if (s.includes('error')) return 'error';
  if (s.includes('warn')) return 'warning';
  return 'info';
}

const SEVERITY_STYLES: Record<Severity, { border: string; icon: string }> = {
  error: { border: 'border-l-semantic-error', icon: 'text-semantic-error' },
  warning: { border: 'border-l-semantic-warning', icon: 'text-semantic-warning' },
  info: { border: 'border-l-oe-blue', icon: 'text-oe-blue' },
};

function ResultIcon({ severity }: { severity: Severity }) {
  const cls = clsx('mt-0.5 shrink-0', SEVERITY_STYLES[severity].icon);
  if (severity === 'error') return <XCircle size={15} className={cls} />;
  if (severity === 'warning') return <AlertTriangle size={15} className={cls} />;
  return <Info size={15} className={cls} />;
}

export interface ValidationPanelProps {
  report: FieldTimeValidationReport | undefined;
  isLoading: boolean;
}

export function ValidationPanel({ report, isLoading }: ValidationPanelProps) {
  const { t } = useTranslation();

  const { errors, warnings, passedCount, failing } = useMemo(() => {
    const results = report?.results ?? [];
    const failingResults = results.filter((r) => !r.passed);
    return {
      errors: failingResults.filter((r) => severityOf(r) === 'error').length,
      warnings: failingResults.filter((r) => severityOf(r) === 'warning').length,
      passedCount: results.filter((r) => r.passed).length,
      failing: failingResults,
    };
  }, [report]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary p-3 text-sm text-content-tertiary">
        <Loader2 size={15} className="animate-spin" />
        {t('field_time.validation_loading', { defaultValue: 'Checking timesheet...' })}
      </div>
    );
  }

  if (!report) return null;

  const overall: Severity | 'passed' =
    errors > 0 ? 'error' : warnings > 0 ? 'warning' : 'passed';

  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-content-primary">
          {t('field_time.validation', { defaultValue: 'Validation' })}
        </h4>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="inline-flex items-center gap-1 rounded-full bg-semantic-error-bg px-2 py-0.5 text-2xs font-medium text-semantic-error">
            <XCircle size={11} />
            {t('field_time.validation_errors', { defaultValue: '{{count}} errors', count: errors })}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-semantic-warning-bg px-2 py-0.5 text-2xs font-medium text-[#b45309]">
            <AlertTriangle size={11} />
            {t('field_time.validation_warnings', {
              defaultValue: '{{count}} warnings',
              count: warnings,
            })}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-semantic-success-bg px-2 py-0.5 text-2xs font-medium text-semantic-success">
            <CheckCircle2 size={11} />
            {t('field_time.validation_passed_count', {
              defaultValue: '{{count}} passed',
              count: passedCount,
            })}
          </span>
        </div>
      </div>

      {overall === 'passed' && failing.length === 0 ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-semantic-success">
          <CheckCircle2 size={16} />
          {t('field_time.validation_all_passed', {
            defaultValue: 'All checks passed. This timesheet is ready to submit.',
          })}
        </div>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {failing.map((r) => {
            const severity = severityOf(r);
            return (
              <li
                key={r.rule_id}
                className={clsx(
                  'rounded-md border border-border-light border-l-2 bg-surface-secondary/40 p-2.5',
                  SEVERITY_STYLES[severity].border,
                )}
              >
                <div className="flex items-start gap-2">
                  <ResultIcon severity={severity} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-content-primary">{r.rule_name}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">
                      {r.message}
                    </p>
                    {r.suggestion && (
                      <p className="mt-1 text-xs leading-relaxed text-content-tertiary">
                        {t('field_time.validation_fix', { defaultValue: 'Fix:' })} {r.suggestion}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

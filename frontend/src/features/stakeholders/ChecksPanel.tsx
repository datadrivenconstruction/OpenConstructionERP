// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the validation rules of the module say about this project right now:
// a stakeholder without a category, an assessment that is due, a commitment
// without an owner, a decision nobody decides. The server runs the rules and
// writes each finding in the reader's language; this panel lists the ones
// that did not pass, the blocking ones first.

import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

import type { ValidationFinding } from './api';
import { useValidation } from './hooks';

/** The findings that need attention: not passed, errors before warnings, the server's order kept within each. */
export function openFindings(findings: readonly ValidationFinding[]): ValidationFinding[] {
  const failed = findings.filter((f) => !f.passed);
  const blocking = (f: ValidationFinding) => f.severity.toLowerCase().endsWith('error');
  return [...failed.filter(blocking), ...failed.filter((f) => !blocking(f))];
}

export function ChecksPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const query = useValidation(projectId);
  const title = t('stakeholders.ui.checks.title', { defaultValue: 'Checks' });
  if (query.isLoading) {
    return (
      <section aria-label={title} aria-busy className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="checks-loading">
        <p className="animate-pulse text-sm text-content-tertiary">
          {t('stakeholders.ui.checks.loading', { defaultValue: 'Running the checks on the register, the plan, the commitments and the mandates.' })}
        </p>
      </section>
    );
  }
  if (query.isError || !query.data) {
    return (
      <section aria-label={title} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="checks-panel" data-state="failed">
        <p className="text-sm text-content-secondary">
          {t('stakeholders.ui.checks.load_failed', { defaultValue: 'The checks could not be run. The lists on this page are still current.' })}
        </p>
      </section>
    );
  }

  const open = openFindings(query.data);
  if (open.length === 0) {
    return (
      <section aria-label={title} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="checks-panel" data-state="clear">
        <p className="flex items-center gap-2 text-sm text-content-secondary">
          <CheckCircle2 size={15} className="shrink-0 text-semantic-success" aria-hidden />
          {t('stakeholders.ui.checks.clear', { defaultValue: 'Every check on the register, the plan, the commitments and the mandates passes.' })}
        </p>
      </section>
    );
  }

  return (
    <section aria-label={title} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="checks-panel" data-state="open">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        {t('stakeholders.ui.checks.open_title', { defaultValue: 'Needs attention' })}
      </h2>
      <ul className="mt-2 space-y-1.5">
        {open.map((f, i) => {
          const blocking = f.severity.toLowerCase().endsWith('error');
          return (
            <li key={`${f.rule_id}-${f.element_ref ?? ''}-${i}`} className="flex items-start gap-2 text-sm" data-testid="check-finding" data-blocking={blocking}>
              {blocking ? (
                <XCircle size={15} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
              ) : (
                <AlertTriangle size={15} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
              )}
              <span className="min-w-0">
                <span className="text-content-primary">{f.message}</span>
                {f.suggestion && <span className="block text-xs text-content-secondary">{f.suggestion}</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

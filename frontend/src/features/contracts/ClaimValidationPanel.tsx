// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ClaimValidationPanel — the submission check of one progress claim, as a
// traffic light.
//
// Submitting a claim runs the payment application rules and refuses it on any
// error. Before this panel the only way to learn about a finding was to press
// Submit and read the first three errors in a toast, and warnings (a period
// that overlaps or leaves a gap, a percent that went backwards) were never
// shown at all, because they do not block. The report here is built by the
// same service method the submit gate uses, so what it shows is what Submit
// will do.
//
// It disables nothing. The server gate is what stops a claim with errors, and
// a second, client-side copy of that decision could only drift from it.
//
// Messages and suggestions arrive already in the reader's language: the rules
// translate them on the server from the contracts message catalogue.
//
// Refetching needs no wiring. The report is cached under the claim's own query
// key, and React Query invalidates by key prefix, so every place that already
// refreshes the claim (line edits, populate, the subcontractor roll-up, every
// status transition) refreshes the report with it.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, CheckCircle2, CircleSlash, Info, RefreshCw, ShieldX } from 'lucide-react';

import { Badge, Button, Card } from '@/shared/ui';
import {
  getAiaApplication,
  getClaimValidation,
  getPaymentApplication,
  type AIAApplication,
  type ClaimValidationFinding,
  type ClaimValidationReport,
} from './api';
import { findingKeys } from './findingKeys';
import { aiaApplicationKey, paymentApplicationKey } from './claimQueries';

/**
 * Under the claim's key on purpose: invalidating `['contracts', 'claim', id]`
 * reaches this query too, so the report can never outlive the claim it checks.
 */
export function claimValidationKey(claimId: string) {
  return ['contracts', 'claim', claimId, 'validation'] as const;
}

type Light = 'errors' | 'warnings' | 'passed' | 'skipped';

function lightOf(report: ClaimValidationReport): Light {
  if (report.errors.length > 0) return 'errors';
  if (report.warnings.length > 0) return 'warnings';
  // Nothing ran (no rule applies, or the rule set is not implemented). Saying
  // "no findings" there would read as a pass nobody performed.
  if (report.status === 'skipped' || report.status === 'unsupported') return 'skipped';
  return 'passed';
}

interface ClaimValidationPanelProps {
  claimId: string;
  /** True while the claim is a draft, so Submit is the next step. */
  awaitingSubmit: boolean;
  /** US/CA/AU projects, where the claim prints as a G702 with a line 7. */
  aiaEligible: boolean;
}

export function ClaimValidationPanel({ claimId, awaitingSubmit, aiaEligible }: ClaimValidationPanelProps) {
  const { t } = useTranslation();

  const reportQ = useQuery<ClaimValidationReport>({
    queryKey: claimValidationKey(claimId),
    queryFn: () => getClaimValidation(claimId),
    enabled: !!claimId,
  });

  // Previous certified amounts matter in every country. AIA projects share
  // their panel's cached request; other projects use the common figures API.
  const applicationQ = useQuery<AIAApplication>({
    queryKey: aiaEligible ? aiaApplicationKey(claimId) : paymentApplicationKey(claimId),
    queryFn: () => (aiaEligible ? getAiaApplication(claimId) : getPaymentApplication(claimId)),
    enabled: !!claimId,
  });
  const reconstructed = applicationQ.data?.summary.previous_certificates_basis === 'reconstructed';

  const recheck = (
    <Button
      variant="ghost"
      size="sm"
      icon={<RefreshCw size={14} className={clsx(reportQ.isFetching && 'animate-spin')} />}
      onClick={() => void reportQ.refetch()}
      disabled={reportQ.isFetching}
      data-testid="claim-validation-recheck"
    >
      {t('contracts.claim_validation.recheck', { defaultValue: 'Re-check' })}
    </Button>
  );

  if (reportQ.isLoading) {
    return (
      <Card padding="sm" data-testid="claim-validation-loading">
        <div className="h-5 w-48 animate-pulse rounded bg-surface-secondary" />
      </Card>
    );
  }

  if (reportQ.isError || !reportQ.data) {
    return (
      <Card padding="sm" data-testid="claim-validation-panel">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-content-secondary">
            {t('contracts.claim_validation.load_failed', {
              defaultValue: 'Could not run the submission check. Submit still runs it on the server.',
            })}
          </p>
          {recheck}
        </div>
      </Card>
    );
  }

  const report = reportQ.data;
  const light = lightOf(report);

  const heading = {
    errors: t('contracts.claim_validation.state_errors', { defaultValue: 'Errors found' }),
    warnings: t('contracts.claim_validation.state_warnings', { defaultValue: 'Warnings only' }),
    passed: t('contracts.claim_validation.state_passed', { defaultValue: 'No findings' }),
    skipped: t('contracts.claim_validation.state_skipped', { defaultValue: 'Nothing was checked' }),
  }[light];

  const LightIcon = { errors: ShieldX, warnings: AlertTriangle, passed: CheckCircle2, skipped: CircleSlash }[light];

  return (
    <Card padding="sm" data-testid="claim-validation-panel" data-light={light}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className={clsx(
              'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
              light === 'errors' && 'bg-semantic-error-bg text-semantic-error',
              light === 'warnings' && 'bg-semantic-warning-bg text-[#b45309]',
              light === 'passed' && 'bg-semantic-success-bg text-semantic-success',
              light === 'skipped' && 'bg-surface-secondary text-content-tertiary',
            )}
            aria-hidden="true"
          >
            <LightIcon size={15} />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('contracts.claim_validation.title', { defaultValue: 'Submission check' })}
            </p>
            <p className="text-sm font-semibold text-content-primary" data-testid="claim-validation-state">
              {heading}
            </p>
            <p className="mt-0.5 text-xs text-content-secondary">
              {awaitingSubmit
                ? t('contracts.claim_validation.hint_draft', {
                    defaultValue: 'Errors block Submit. Warnings do not: read them, then submit if the claim is right.',
                  })
                : t('contracts.claim_validation.hint_submitted', {
                    defaultValue: 'Checked as the claim stands now, including edits made after it was submitted.',
                  })}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant={report.errors.length > 0 ? 'error' : 'neutral'} size="sm">
            {t('contracts.claim_validation.errors', { defaultValue: 'Errors' })} {report.errors.length}
          </Badge>
          <Badge variant={report.warnings.length > 0 ? 'warning' : 'neutral'} size="sm">
            {t('contracts.claim_validation.warnings', { defaultValue: 'Warnings' })} {report.warnings.length}
          </Badge>
          {recheck}
        </div>
      </div>

      {(report.errors.length > 0 || report.warnings.length > 0) && (
        <div className="mt-3 space-y-1.5">
          <FindingList tone="error" findings={report.errors} />
          <FindingList tone="warning" findings={report.warnings} />
        </div>
      )}

      {reconstructed && (
        <p
          className="mt-3 flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2 text-xs text-content-secondary"
          data-testid="claim-validation-reconstructed"
        >
          <Info size={14} className="mt-0.5 shrink-0 text-content-tertiary" />
          <span>
            {t('contracts.claim_validation.reconstructed', {
              defaultValue:
                'Previous certified amounts are rebuilt from earlier claims because the previous claim stores no certified totals yet. Check them against what was actually certified.',
            })}
          </span>
        </p>
      )}
    </Card>
  );
}

function FindingList({ tone, findings }: { tone: 'error' | 'warning'; findings: ClaimValidationFinding[] }) {
  const keys = findingKeys(findings);
  if (findings.length === 0) return null;
  const isError = tone === 'error';
  return (
    <ul className="space-y-1.5" data-testid={`claim-validation-${tone}s`}>
      {findings.map((f, i) => (
        <li
          key={keys[i]}
          className={clsx(
            'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm',
            isError
              ? 'border-red-200 bg-red-50/60 dark:border-red-900 dark:bg-red-950/30'
              : 'border-amber-200 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/30',
          )}
        >
          {isError ? (
            <ShieldX size={15} className="mt-0.5 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
          ) : (
            <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
          )}
          <div className="min-w-0">
            <p className="text-content-primary">{f.message}</p>
            {f.suggestion && <p className="mt-0.5 text-xs text-content-secondary">{f.suggestion}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

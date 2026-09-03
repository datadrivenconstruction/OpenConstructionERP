// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// ComplianceGate — the pre-signature compliance check modal (Item #27).
//
// When a user signs a contract (draft -> active) the backend runs the
// project's compliance rule packs against the contract's schedule of values.
// Any blocking ERROR returns HTTP 422 and the signature does NOT happen.
//
// This modal makes that gate visible BEFORE the user commits: it previews the
// validation result, shows which jurisdiction rule packs apply, groups the
// violations by severity, and only enables the "Sign contract" button when
// there are no blocking errors. Warnings are surfaced but never block — the
// user can sign through them. The user fixes the underlying SoV data, hits
// "Re-check", and the gate clears.

import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  PenLine,
  Info,
} from 'lucide-react';
import clsx from 'clsx';

import { WideModal } from '@/shared/ui/WideModal';
import { Button, Badge } from '@/shared/ui';
import { ContractSigningPanel } from './ContractSigningPanel';
import { findingKeys } from './findingKeys';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  previewComplianceGate,
  signContract,
  asComplianceGateError,
  listComplianceRulePacks,
  type ComplianceGateReport,
  type ComplianceRulePack,
  type ComplianceViolation,
} from './api';

/**
 * Name a rule pack from the catalogue the backend already publishes.
 *
 * This was a four entry map written by hand, against sixteen packs in the
 * registry. The twelve it did not know fell through to the id with its
 * underscores swapped for spaces, so a Mexican project showed a lowercase
 * "mx compliance" next to "Germany / DACH" and nothing anywhere went red. The
 * names exist and are served by GET /v1/contracts/compliance-rule-packs/,
 * which the project settings screen has been reading all along, so the mirror
 * is deleted rather than extended: a seventeenth pack arrives named without
 * anybody editing this file.
 *
 * The id fallback stays for the moment before the catalogue resolves, and for
 * a pack the gate reports that the catalogue does not list.
 */
function packLabel(id: string, names: Map<string, string>): string {
  return names.get(id) ?? id.replace(/_/g, ' ');
}

interface ComplianceGateProps {
  contractId: string;
  contractCode: string;
  /** Called after a successful signature so the parent can refresh + close. */
  onSigned: () => void;
  onClose: () => void;
}

export function ComplianceGate({
  contractId,
  contractCode,
  onSigned,
  onClose,
}: ComplianceGateProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  // Same query key as the project settings screen, so the two share one cache
  // entry and this modal usually opens with the names already in hand.
  const packsQ = useQuery<ComplianceRulePack[]>({
    queryKey: ['compliance-rule-packs'],
    queryFn: listComplianceRulePacks,
    staleTime: 60 * 60 * 1000,
  });
  const packNames = new Map((packsQ.data ?? []).map((p) => [p.id, p.name] as const));
  const addToast = useToastStore((s) => s.addToast);

  const gateQ = useQuery<ComplianceGateReport>({
    queryKey: ['contracts', 'compliance-gate', contractId],
    queryFn: () => previewComplianceGate(contractId),
    refetchOnWindowFocus: false,
  });

  const signMut = useMutation({
    mutationFn: () => signContract(contractId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contracts', 'list'] });
      qc.invalidateQueries({ queryKey: ['contracts', 'dashboard', contractId] });
      addToast({
        type: 'success',
        title: t('contracts.signed_ok', { defaultValue: 'Contract signed' }),
      });
      onSigned();
    },
    onError: (err) => {
      // If the backend gate blocked the sign (data changed between preview and
      // commit), refresh the preview from the structured 422 body so the user
      // sees exactly what changed instead of a generic toast.
      const gateErr = asComplianceGateError(err);
      if (gateErr) {
        qc.setQueryData<ComplianceGateReport>(
          ['contracts', 'compliance-gate', contractId],
          {
            contract_id: contractId,
            contract_status: 'draft',
            rule_packs: gateErr.rule_packs,
            rule_sets: gateErr.rule_sets,
            status: gateErr.status,
            score: gateErr.score,
            blocked: true,
            counts: gateErr.counts,
            errors: gateErr.errors,
            warnings: gateErr.warnings,
          },
        );
        addToast({
          type: 'error',
          title: t('contracts.compliance.blocked_toast', {
            defaultValue: 'Compliance gate blocked the signature',
          }),
        });
        return;
      }
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const report = gateQ.data;
  const blocked = report?.blocked ?? false;
  const errors = report?.errors ?? [];
  const warnings = report?.warnings ?? [];
  const passedCount = report?.counts.passed ?? 0;

  const StatusBanner = () => {
    if (gateQ.isLoading) {
      return (
        <div className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-secondary px-4 py-3">
          <RefreshCw size={18} className="animate-spin text-content-tertiary" />
          <p className="text-sm text-content-secondary">
            {t('contracts.compliance.checking', {
              defaultValue: 'Running compliance checks…',
            })}
          </p>
        </div>
      );
    }
    if (gateQ.isError) {
      return (
        <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-800 dark:bg-amber-950/40">
          <AlertTriangle size={18} className="text-amber-600 dark:text-amber-400" />
          <p className="text-sm text-amber-800 dark:text-amber-300">
            {t('contracts.compliance.check_failed', {
              defaultValue:
                'Could not run the compliance check. Try again before signing.',
            })}
          </p>
        </div>
      );
    }
    if (blocked) {
      return (
        <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900 dark:bg-red-950/40">
          <ShieldX size={20} className="mt-0.5 shrink-0 text-red-600 dark:text-red-400" />
          <div>
            <p className="text-sm font-semibold text-red-800 dark:text-red-300">
              {t('contracts.compliance.blocked_title', {
                defaultValue: 'Signature blocked by compliance',
              })}
            </p>
            <p className="mt-0.5 text-sm text-red-700 dark:text-red-400">
              {t('contracts.compliance.blocked_desc', {
                defaultValue:
                  'Resolve the {{count}} blocking issue(s) below, then re-check to sign.',
                count: errors.length,
              })}
            </p>
          </div>
        </div>
      );
    }
    if (warnings.length > 0) {
      return (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-800 dark:bg-amber-950/40">
          <ShieldAlert size={20} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
          <div>
            <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">
              {t('contracts.compliance.warnings_title', {
                defaultValue: 'Compliance passed with warnings',
              })}
            </p>
            <p className="mt-0.5 text-sm text-amber-700 dark:text-amber-400">
              {t('contracts.compliance.warnings_desc', {
                defaultValue:
                  'No blocking issues - you can sign, but review the {{count}} warning(s) first.',
                count: warnings.length,
              })}
            </p>
          </div>
        </div>
      );
    }
    return (
      <div className="flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-900 dark:bg-emerald-950/40">
        <ShieldCheck size={20} className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <div>
          <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
            {t('contracts.compliance.passed_title', {
              defaultValue: 'Compliance checks passed',
            })}
          </p>
          <p className="mt-0.5 text-sm text-emerald-700 dark:text-emerald-400">
            {t('contracts.compliance.passed_desc', {
              defaultValue:
                'No blocking issues found. This contract is clear to sign.',
            })}
          </p>
        </div>
      </div>
    );
  };

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      busy={signMut.isPending}
      title={t('contracts.compliance.title', {
        defaultValue: 'Compliance gate',
      })}
      subtitle={t('contracts.compliance.subtitle', {
        defaultValue:
          'Contract {{code}} must clear the project compliance rules before it can be signed.',
        code: contractCode,
      })}
      footer={
        <div className="flex items-center justify-between gap-3">
          <Button
            variant="ghost"
            icon={<RefreshCw size={14} />}
            onClick={() => gateQ.refetch()}
            loading={gateQ.isFetching && !gateQ.isLoading}
          >
            {t('contracts.compliance.recheck', { defaultValue: 'Re-check' })}
          </Button>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              icon={<PenLine size={14} />}
              onClick={() => signMut.mutate()}
              loading={signMut.isPending}
              disabled={blocked || gateQ.isLoading || gateQ.isError}
              title={
                blocked
                  ? t('contracts.compliance.sign_disabled_hint', {
                      defaultValue: 'Resolve blocking issues before signing',
                    })
                  : undefined
              }
            >
              {t('contracts.compliance.sign', {
                defaultValue: 'Sign contract',
              })}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-4">
        <StatusBanner />

        {/* Active rule packs + headline counts */}
        {report && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border-light bg-surface-secondary px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('contracts.compliance.active_packs', {
                  defaultValue: 'Active packs',
                })}
              </span>
              {report.rule_packs.length === 0 ? (
                <span className="text-sm text-content-tertiary">—</span>
              ) : (
                <div className="flex flex-wrap gap-1">
                  {report.rule_packs.map((p) => (
                    <Badge key={p} variant="blue">
                      {packLabel(p, packNames)}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
            <span className="hidden h-4 w-px bg-border-light sm:block" />
            <div className="flex items-center gap-3 text-sm">
              <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={14} /> {passedCount}{' '}
                {t('contracts.compliance.passed_label', { defaultValue: 'passed' })}
              </span>
              <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                <ShieldAlert size={14} /> {warnings.length}{' '}
                {t('contracts.compliance.warnings_label', {
                  defaultValue: 'warnings',
                })}
              </span>
              <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400">
                <ShieldX size={14} /> {errors.length}{' '}
                {t('contracts.compliance.errors_label', { defaultValue: 'errors' })}
              </span>
            </div>
          </div>
        )}

        {/* Blocking errors */}
        {errors.length > 0 && (
          <ViolationGroup
            tone="error"
            title={t('contracts.compliance.errors_heading', {
              defaultValue: 'Blocking errors',
            })}
            violations={errors}
          />
        )}

        {/* Non-blocking warnings */}
        {warnings.length > 0 && (
          <ViolationGroup
            tone="warning"
            title={t('contracts.compliance.warnings_heading', {
              defaultValue: 'Warnings',
            })}
            violations={warnings}
          />
        )}

        {/* Who is signing, and did the paper move under them.
            Below the findings on purpose: the gate's verdict is what decides
            whether putting the contract up for signature is allowed at all, so
            the user should have read it before they reach the button. */}
        <ContractSigningPanel
          contractId={contractId}
          contractStatus={report?.contract_status}
          blocked={blocked}
          onContractChanged={onSigned}
        />

        {/* All clear — no findings at all */}
        {report && errors.length === 0 && warnings.length === 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-border-light px-4 py-6 text-sm text-content-secondary">
            <Info size={16} className="text-content-tertiary" />
            {t('contracts.compliance.no_findings', {
              defaultValue:
                'No compliance findings. Every applicable rule passed.',
            })}
          </div>
        )}
      </div>
    </WideModal>
  );
}

function ViolationGroup({
  tone,
  title,
  violations,
}: {
  tone: 'error' | 'warning';
  title: string;
  violations: ComplianceViolation[];
}) {
  const isError = tone === 'error';
  const keys = findingKeys(violations);
  return (
    <div>
      <p
        className={clsx(
          'mb-1.5 text-xs font-semibold uppercase tracking-wide',
          isError
            ? 'text-red-700 dark:text-red-400'
            : 'text-amber-700 dark:text-amber-400',
        )}
      >
        {title} ({violations.length})
      </p>
      <ul className="space-y-1.5">
        {violations.map((v, i) => (
          <li
            key={keys[i]}
            className={clsx(
              'rounded-lg border px-3 py-2 text-sm',
              isError
                ? 'border-red-200 bg-red-50/60 dark:border-red-900 dark:bg-red-950/30'
                : 'border-amber-200 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/30',
            )}
          >
            <div className="flex items-start gap-2">
              {isError ? (
                <ShieldX
                  size={15}
                  className="mt-0.5 shrink-0 text-red-600 dark:text-red-400"
                />
              ) : (
                <AlertTriangle
                  size={15}
                  className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
                />
              )}
              <div className="min-w-0">
                <p className="text-content-primary">{v.message}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-content-tertiary">
                  <span className="font-mono">{v.rule_id}</span>
                  {v.element_ref && (
                    <span className="font-mono">· {v.element_ref}</span>
                  )}
                </div>
                {v.suggestion && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {v.suggestion}
                  </p>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

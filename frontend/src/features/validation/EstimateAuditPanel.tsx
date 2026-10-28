// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ClipboardCheck,
  Wand2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
  TrendingUp,
  ExternalLink,
} from 'lucide-react';
import { Button, Card, Badge } from '@/shared/ui';
import { apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  type EstimateAuditResponse,
  type AuditFinding,
  type ApplyFixBody,
  groupFindings,
  groupLabel,
  fixLabel,
  scoreToPct,
  computeScoreDelta,
  toApplyFixBody,
} from './estimateAudit';

/**
 * Self-contained one-click estimate-audit panel: runs the `estimate_audit`
 * rule set over the finished BOQ, shows grouped findings with a per-finding
 * Apply-Fix button, and re-runs after each fix so the quality score delta is
 * visible. Fixes are applied through the BOQ module, so the estimate grid
 * accents (driven by the persisted validation status) refresh too.
 */
export function EstimateAuditPanel({
  projectId,
  boqId,
}: {
  projectId: string;
  boqId: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [report, setReport] = useState<EstimateAuditResponse | null>(null);
  // Score before the most recent re-run, so an applied fix can show a delta.
  const [prevScore, setPrevScore] = useState<number | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);

  const runAudit = useMutation({
    mutationFn: () =>
      apiPost<EstimateAuditResponse, { project_id: string; boq_id: string }>('/v1/validation/audit/', {
        project_id: projectId,
        boq_id: boqId,
      }),
    onSuccess: (data) => {
      setReport(data);
      // The audit wrote fresh validation status onto the positions and a new
      // report - refresh anything that reads either.
      queryClient.invalidateQueries({ queryKey: ['validation'] });
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('validation.audit_failed', { defaultValue: 'Audit failed' }),
        message: err.message,
      });
    },
  });

  const applyFix = useMutation({
    mutationFn: (body: ApplyFixBody) =>
      apiPost<{ applied: boolean }, ApplyFixBody>(`/v1/boq/boqs/${boqId}/audit/apply-fix/`, body),
    onSuccess: () => {
      // The fix mutated a position: refresh the BOQ grid, then re-run the audit
      // so the score improves and the remaining findings update.
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-cost-breakdown', boqId] });
      setPrevScore(report?.score ?? null);
      runAudit.mutate();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('validation.audit_fix_failed', { defaultValue: 'Could not apply fix' }),
        message: err.message,
      });
    },
    onSettled: () => setApplyingId(null),
  });

  const handleRun = useCallback(() => {
    if (!boqId) return;
    setPrevScore(null);
    runAudit.mutate();
  }, [boqId, runAudit]);

  const handleApplyFix = useCallback(
    (finding: AuditFinding) => {
      const body = toApplyFixBody(finding);
      if (!body) return;
      setApplyingId(finding.id);
      applyFix.mutate(body);
    },
    [applyFix],
  );

  const busy = runAudit.isPending || applyFix.isPending;
  const grouped = report ? groupFindings(report.findings) : [];
  const pct = report ? scoreToPct(report.score) : 0;
  const delta = report && prevScore !== null ? computeScoreDelta(prevScore, report.score) : null;

  return (
    <Card>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 text-oe-blue">
              <ClipboardCheck size={20} />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-content-primary">
                {t('validation.audit_title', { defaultValue: 'One-click estimate audit' })}
              </h3>
              <p className="mt-0.5 text-xs text-content-secondary">
                {t('validation.audit_subtitle', {
                  defaultValue:
                    'Run the finished estimate through the quality checks, fix each finding in one click, and watch the score improve.',
                })}
              </p>
            </div>
          </div>
          <div className="shrink-0">
            <span
              title={
                !boqId
                  ? t('validation.select_boq_first', { defaultValue: 'Select a BOQ first' })
                  : undefined
              }
            >
              <Button
                variant="primary"
                size="md"
                icon={<ClipboardCheck size={16} />}
                loading={runAudit.isPending}
                disabled={!boqId || busy}
                onClick={handleRun}
              >
                {report
                  ? t('validation.audit_rerun', { defaultValue: 'Re-run audit' })
                  : t('validation.audit_run', { defaultValue: 'Audit this estimate' })}
              </Button>
            </span>
          </div>
        </div>

        {report && (
          <div className="border-t border-border-light pt-4">
            {/* Score + delta strip */}
            <div className="mb-4 flex flex-wrap items-center gap-4">
              <div className="flex items-baseline gap-1.5">
                <span className="text-2xl font-bold tabular-nums text-content-primary">{pct}</span>
                <span className="text-sm font-medium text-content-secondary">%</span>
                <span className="ml-1 text-xs text-content-tertiary">
                  {t('validation.audit_quality_score', { defaultValue: 'quality score' })}
                </span>
              </div>
              {delta && delta.deltaPct !== 0 && (
                <Badge variant={delta.improved ? 'success' : 'warning'} size="sm">
                  <span className="inline-flex items-center gap-1">
                    <TrendingUp size={12} />
                    {delta.improved
                      ? t('validation.audit_score_up', {
                          defaultValue: '+{{pts}} pts',
                          pts: delta.deltaPct,
                        })
                      : t('validation.audit_score_change', {
                          defaultValue: '{{pts}} pts',
                          pts: delta.deltaPct,
                        })}
                  </span>
                </Badge>
              )}
              <span className="text-xs text-content-secondary">
                {report.findings.length > 0
                  ? t('validation.audit_findings_count', {
                      defaultValue: '{{count}} findings to review',
                      count: report.findings.length,
                    })
                  : t('validation.audit_no_findings', { defaultValue: 'no findings' })}
              </span>
            </div>

            {report.findings.length === 0 ? (
              <div className="flex items-center gap-3 rounded-xl bg-semantic-success-bg px-4 py-3">
                <CheckCircle2 size={18} className="shrink-0 text-semantic-success" />
                <p className="text-sm font-medium text-semantic-success">
                  {t('validation.audit_all_clear', {
                    defaultValue: 'No issues found - this estimate passed every audit check.',
                  })}
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {grouped.map(([groupKey, findings]) => (
                  <div key={groupKey}>
                    <div className="mb-1.5 flex items-center gap-2">
                      <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                        {groupLabel(groupKey, t)}
                      </h4>
                      <span className="text-xs text-content-quaternary tabular-nums">
                        {findings.length}
                      </span>
                    </div>
                    <div className="space-y-1.5">
                      {findings.map((finding) => (
                        <AuditFindingRow
                          key={finding.id}
                          finding={finding}
                          boqId={boqId}
                          busy={busy}
                          applying={applyingId === finding.id}
                          onApplyFix={handleApplyFix}
                          onNavigate={(pid) => navigate(`/boq/${boqId}?highlight=${pid}`)}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function AuditFindingRow({
  finding,
  boqId,
  busy,
  applying,
  onApplyFix,
  onNavigate,
}: {
  finding: AuditFinding;
  boqId: string;
  busy: boolean;
  applying: boolean;
  onApplyFix: (finding: AuditFinding) => void;
  onNavigate: (positionId: string) => void;
}) {
  const { t } = useTranslation();

  const icon =
    finding.severity === 'error' ? (
      <XCircle size={15} className="shrink-0 text-semantic-error" />
    ) : finding.severity === 'info' ? (
      <Info size={15} className="shrink-0 text-blue-500" />
    ) : (
      <AlertTriangle size={15} className="shrink-0 text-semantic-warning" />
    );

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-3 py-2">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {finding.ordinal && (
            <span className="shrink-0 font-mono text-xs text-content-tertiary">{finding.ordinal}</span>
          )}
          <span className="truncate text-sm text-content-primary">{finding.message}</span>
        </div>
      </div>
      {finding.position_id && boqId && (
        <button
          type="button"
          onClick={() => onNavigate(finding.position_id!)}
          aria-label={t('validation.audit_go_to_line', { defaultValue: 'Go to line' })}
          className="inline-flex shrink-0 items-center gap-1 text-xs text-oe-blue hover:underline"
        >
          {t('validation.audit_go_to_line', { defaultValue: 'Go to line' })}
          <ExternalLink size={11} />
        </button>
      )}
      {finding.fix ? (
        <Button
          variant="secondary"
          size="sm"
          icon={<Wand2 size={13} />}
          loading={applying}
          disabled={busy}
          onClick={() => onApplyFix(finding)}
        >
          {fixLabel(finding.fix, t)}
        </Button>
      ) : (
        <span className="shrink-0 text-xs italic text-content-tertiary">
          {t('validation.audit_review_manually', { defaultValue: 'Review manually' })}
        </span>
      )}
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ClashRuleSuggestionBanner — Wave A4 banner sitting at the top of the
// review list. When the run's false-positive history contains a
// discipline pair with ≥3 FPs the engine surfaces a rule proposal; this
// banner shows the count + a "Review" button that opens a modal with
// per-suggestion "Apply" / "Dismiss" actions.
//
// Apply → POST /apply-rule-suggestion → the backend appends the rule and
// re-evaluates results (flips sub-tolerance hards to ignored). The
// banner re-renders empty after a successful apply because the
// underlying FP pool was suggested-on (the suggestion list is
// recomputed by the backend and the next refetch hides it).

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Lightbulb, Check, X } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';

import { clashApi, type ClashRuleSuggestion } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

export interface ClashRuleSuggestionBannerProps {
  projectId: string;
  runId: string;
}

export function ClashRuleSuggestionBanner({
  projectId,
  runId,
}: ClashRuleSuggestionBannerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const { data } = useQuery<ClashRuleSuggestion[]>({
    queryKey: ['clash', projectId, runId, 'rule-suggestions'],
    queryFn: () => clashApi.listRuleSuggestions(projectId, runId),
    enabled: !!projectId && !!runId,
  });

  const visible = (data ?? []).filter(
    (s) =>
      s.rule !== null &&
      !dismissed.has(
        `${s.rule!.discipline_a}|${s.rule!.discipline_b}|${s.rule!.tolerance_m}`,
      ),
  );

  const apply = useMutation({
    mutationFn: (s: ClashRuleSuggestion) => {
      if (!s.rule) return Promise.reject(new Error('No rule'));
      return clashApi.applyRuleSuggestion(projectId, runId, {
        discipline_a: s.rule.discipline_a,
        discipline_b: s.rule.discipline_b,
        tolerance_m: s.rule.tolerance_m,
      });
    },
    onSuccess: (res) => {
      qc.invalidateQueries({
        queryKey: ['clash', projectId, runId, 'rule-suggestions'],
      });
      qc.invalidateQueries({ queryKey: ['clash', projectId, runId, 'rules'] });
      qc.invalidateQueries({ queryKey: ['clash-results', projectId, runId] });
      qc.invalidateQueries({ queryKey: ['clash-run', projectId, runId] });
      addToast({
        type: 'success',
        title: t('clash.suggestions.applied_title', {
          defaultValue: 'Rule applied',
        }),
        message: t('clash.suggestions.applied', {
          defaultValue: `${res.results_affected} clash(es) ignored`,
          count: res.results_affected,
        }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('clash.suggestions.apply_failed', {
          defaultValue: 'Could not apply rule',
        }),
        message: (err as Error).message,
      });
    },
  });

  if (visible.length === 0) return null;

  return (
    <>
      <div
        className="flex items-center justify-between gap-3 rounded-md border border-oe-blue/30 bg-oe-blue-subtle px-4 py-2.5"
        data-testid="clash-rule-suggestion-banner"
      >
        <div className="flex items-center gap-2 text-sm">
          <Lightbulb size={16} className="text-oe-blue" />
          <span>
            {t('clash.suggestions.banner', {
              defaultValue:
                'Engine suggests {{count}} new rule(s) based on this run’s false positives.',
              count: visible.length,
            })}
          </span>
        </div>
        <Button size="sm" variant="primary" onClick={() => setReviewOpen(true)}>
          {t('clash.suggestions.review', { defaultValue: 'Review' })}
        </Button>
      </div>

      <WideModal
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        title={t('clash.suggestions.modal_title', {
          defaultValue: 'Rule suggestions',
        })}
        size="lg"
        footer={
          <div className="flex justify-end">
            <Button variant="secondary" onClick={() => setReviewOpen(false)}>
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
          </div>
        }
      >
        <ul className="space-y-3" data-testid="clash-suggestion-list">
          {visible.map((s) => {
            if (!s.rule) return null;
            const key = `${s.rule.discipline_a}|${s.rule.discipline_b}|${s.rule.tolerance_m}`;
            return (
              <li
                key={key}
                className="border border-border rounded-md p-3 flex items-start justify-between gap-3"
              >
                <div className="flex-1">
                  <div className="font-medium text-sm">
                    {s.rule.discipline_a} × {s.rule.discipline_b}
                    {' - '}
                    <span className="text-oe-blue">
                      {fmtFixed(s.rule.tolerance_m, 3)} m
                    </span>
                  </div>
                  <div className="text-xs text-content-secondary mt-1">
                    {s.reason}
                  </div>
                  <div className="text-2xs text-content-tertiary mt-0.5">
                    {t('clash.suggestions.fp_count', {
                      defaultValue: 'Based on {{count}} false positive(s)',
                      count: s.fp_count,
                    })}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<Check size={14} />}
                    loading={apply.isPending}
                    onClick={() => apply.mutate(s)}
                  >
                    {t('clash.suggestions.apply', { defaultValue: 'Apply' })}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<X size={14} />}
                    onClick={() =>
                      setDismissed((p) => new Set(p).add(key))
                    }
                  >
                    {t('clash.suggestions.dismiss', {
                      defaultValue: 'Dismiss',
                    })}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      </WideModal>
    </>
  );
}

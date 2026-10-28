// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The rule set of the plan, run on request: how many rules hold, and each
// one that does not with the server's own sentence and its suggestion.

import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, ListChecks } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';

import { planProblem, validatePlan } from './api';
import { useWords } from './hooks';
import { tx } from './texts';

export function ChecksPanel({ projectId }: { projectId: string }) {
  const { t } = useWords();
  const run = useMutation({ mutationFn: () => validatePlan(projectId) });
  const open = (run.data?.results ?? []).filter((r) => !r.passed);

  return (
    <div className="space-y-3" data-testid="plan-checks">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-content-primary">{tx(t, 'checks.title')}</h3>
        <Button size="sm" variant="secondary" loading={run.isPending} onClick={() => run.mutate()} data-testid="plan-checks-run">
          <ListChecks size={14} className="mr-1" />
          {tx(t, 'checks.run')}
        </Button>
      </div>
      <p className="text-sm text-content-secondary">{tx(t, 'checks.lead')}</p>
      {run.isError ? (
        <div role="alert" className="rounded-lg border border-semantic-error/30 bg-semantic-error/5 p-3 text-sm" data-testid="plan-checks-error">
          <p className="font-medium text-content-primary">{tx(t, 'checks.failed')}</p>
          <p className="mt-1 text-content-secondary">{planProblem(run.error).message}</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => run.mutate()}>
            {tx(t, 'retry')}
          </Button>
        </div>
      ) : !run.data ? (
        !run.isPending && (
          <p className="text-sm text-content-tertiary" data-testid="plan-checks-idle">
            {tx(t, 'checks.not_run')}
          </p>
        )
      ) : (
        <>
          <p className="text-sm font-medium text-content-primary" data-testid="plan-checks-summary">
            {tx(t, 'checks.summary', {
              passed: run.data.counts.passed,
              errors: run.data.counts.errors,
              warnings: run.data.counts.warnings,
            })}
          </p>
          {open.length === 0 ? (
            <p className="flex items-center gap-2 text-sm text-content-secondary">
              <CheckCircle2 size={15} className="text-semantic-success" aria-hidden />
              {tx(t, 'checks.all_passed')}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {open.map((r, i) => (
                <li key={`${r.rule_id}-${r.element_ref}-${i}`} className="flex items-start gap-2 text-sm" data-testid="plan-check">
                  <Badge variant={r.severity === 'error' ? 'error' : 'warning'} size="sm">
                    {tx(t, r.severity === 'error' ? 'readiness.error' : 'readiness.warning')}
                  </Badge>
                  <span>
                    <span className="text-content-primary">{r.message || r.rule_name}</span>
                    {r.suggestion && <span className="block text-xs text-content-secondary">{r.suggestion}</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

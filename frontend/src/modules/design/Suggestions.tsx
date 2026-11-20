// Design module (ERP side of the design editor link).
/**
 * Suggestions from the ERP for a position without a direct cost item: the Cost Match result and its runners-up, and
 * assemblies that share words with the position. Nothing is applied until the person presses the button on a row;
 * rows in another unit or currency are shown but cannot be used.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { tr } from './BriefFields';
import { confirmSuggestion, fetchSuggestions, type Confirmation } from './suggestApi';

export function Suggestions({ projectId, positionId, rule, onDone }: {
  projectId: string; positionId: string; rule: string; onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['design-suggestions', projectId, positionId], queryFn: () => fetchSuggestions(projectId, positionId),
    retry: false, staleTime: 60_000,
  });
  const confirm = useMutation({
    mutationFn: (b: Confirmation) => confirmSuggestion(projectId, positionId, b),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['design-estimate'] }); onDone(); },
  });
  if (q.isLoading) return <p className="text-xs text-content-tertiary">…</p>;
  if (q.isError || !q.data) return null;
  const { cost_match: cm, assemblies } = q.data;
  const cands = cm?.candidates ?? [];
  if (cands.length === 0 && assemblies.length === 0) {
    return <p className="text-xs text-content-secondary" data-testid={`suggest-none-${rule}`}>{tr(t, 'design.estimate.suggest_none')}</p>;
  }
  const why = (r: string | null) => (r ? tr(t, `design.estimate.suggest_unusable.${r}`) : null);
  const btn = (usable: boolean, onClick: () => void, testid: string) => (
    <Button variant="secondary" disabled={!usable || confirm.isPending} onClick={onClick} data-testid={testid}>
      {tr(t, 'design.estimate.suggest_use')}
    </Button>
  );
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border-light p-2" data-testid={`suggestions-${rule}`}>
      <p className="text-xs text-content-secondary">{tr(t, 'design.estimate.suggest_hint')}</p>
      {cands.length > 0 && cm && (
        <ul className="flex flex-col gap-1">
          <li className="text-[11px] font-medium text-content-tertiary">{tr(t, 'design.estimate.suggest_costmatch', { region: cm.region })}</li>
          {cands.map((c) => (
            <li key={c.cost_item_id} className="flex flex-wrap items-center gap-2 text-xs" data-testid={`cm-${c.cost_item_id}`}>
              <span className="font-medium">{c.code}</span>
              <span className="min-w-0 flex-1 truncate">{c.description}</span>
              <span className="tabular-nums">{c.rate ?? '-'} {c.currency}/{c.unit}</span>
              <span className="text-content-tertiary">{Math.round(Number(c.confidence) * 100)} %</span>
              {c.suggested && <span className="text-content-tertiary">{tr(t, 'design.estimate.suggest_best')}</span>}
              {why(c.unusable_reason) && <span className="text-semantic-error">{why(c.unusable_reason)}</span>}
              {btn(c.usable, () => confirm.mutate({ result_id: cm.result_id, cost_item_id: c.cost_item_id }), `cm-use-${c.cost_item_id}`)}
            </li>
          ))}
        </ul>
      )}
      {assemblies.length > 0 && (
        <ul className="flex flex-col gap-1">
          <li className="text-[11px] font-medium text-content-tertiary">{tr(t, 'design.estimate.suggest_assemblies')}</li>
          {assemblies.map((a) => (
            <li key={a.assembly_id} className="flex flex-wrap items-center gap-2 text-xs" data-testid={`asm-${a.assembly_id}`}>
              <span className="font-medium">{a.code}</span>
              <span className="min-w-0 flex-1 truncate">{a.name}</span>
              <span className="tabular-nums">{a.rate} {a.currency}/{a.unit}</span>
              {why(a.unusable_reason) && <span className="text-semantic-error">{why(a.unusable_reason)}</span>}
              {btn(a.usable, () => confirm.mutate({ assembly_id: a.assembly_id }), `asm-use-${a.assembly_id}`)}
            </li>
          ))}
        </ul>
      )}
      {confirm.isError && <p role="alert" className="text-xs text-semantic-error">{tr(t, 'design.estimate.cost_pick_failed')} {getErrorMessage(confirm.error)}</p>}
    </div>
  );
}

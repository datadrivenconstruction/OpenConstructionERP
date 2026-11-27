// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Check that the resources of one position add up to its unit rate, and swap a
// resource row for a ranked match. The match is only proposed with its
// confidence; nothing changes until the estimator confirms.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';

import { Button, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { fmtList } from '@/shared/lib/formatters';
import {
  ISSUE_CODES,
  confidencePercent,
  positionCostItemApi,
  refusalText,
  type CompositionComponent,
  type MatchCandidate,
} from './positionCostItemApi';

interface Props {
  positionId: string;
  onClose: () => void;
  onChanged: () => void;
}

export function PositionCompositionDialog({ positionId, onClose, onChanged }: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [target, setTarget] = useState<CompositionComponent | null>(null);
  const [pending, setPending] = useState<MatchCandidate | null>(null);

  const comp = useQuery({
    queryKey: ['boq', 'position-composition', positionId],
    queryFn: () => positionCostItemApi.composition(positionId),
  });

  const matches = useQuery({
    queryKey: ['boq', 'resource-matches', positionId, target?.index],
    queryFn: () => positionCostItemApi.match(target?.name ?? '', target?.unit ?? ''),
    enabled: !!target,
  });

  const replaceMut = useMutation({
    mutationFn: (c: MatchCandidate) =>
      positionCostItemApi.replace(positionId, target?.index ?? 0, c.cost_item_id, c.score),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('boq.position_cost.replaced', { defaultValue: 'Resource replaced' }),
      });
      setTarget(null);
      setPending(null);
      onChanged();
      void comp.refetch();
    },
    onError: (e) => {
      const r = refusalText(e, 'replace');
      addToast({ type: 'error', title: t(r.key, { defaultValue: r.fallback }) });
    },
  });

  const data = comp.data;

  return (
    <WideModal
      open
      onClose={onClose}
      busy={replaceMut.isPending}
      size="xl"
      testId="boq-position-composition"
      title={t('boq.position_cost.check_title', { defaultValue: 'Composition check' })}
      subtitle={t('boq.position_cost.check_subtitle', {
        defaultValue: 'Does the sum of the resource rows give the unit rate of this line?',
      })}
      footer={
        <div className="flex justify-end">
          <Button variant="secondary" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
        </div>
      }
    >
      {comp.isError && (
        <p className="text-sm text-semantic-error">
          {t('boq.position_cost.err_generic', { defaultValue: 'The action failed. Nothing was changed.' })}
        </p>
      )}
      {data && (
        <div className="space-y-3">
          <dl className="grid grid-cols-4 gap-3 text-sm tabular-nums" data-testid="composition-summary">
            <div>
              <dt className="text-2xs text-content-quaternary">
                {t('boq.position_cost.stored', { defaultValue: 'Rate in the bill' })}
              </dt>
              <dd>{data.stored_unit_rate}</dd>
            </div>
            <div>
              <dt className="text-2xs text-content-quaternary">
                {t('boq.position_cost.derived', { defaultValue: 'Rate from resources' })}
              </dt>
              <dd>{data.derived_unit_rate}</dd>
            </div>
            <div>
              <dt className="text-2xs text-content-quaternary">
                {t('boq.position_cost.delta', { defaultValue: 'Difference' })}
              </dt>
              <dd>{data.delta}</dd>
            </div>
            <div>
              <dt className="text-2xs text-content-quaternary">
                {t('boq.position_cost.verdict', { defaultValue: 'Result' })}
              </dt>
              <dd data-testid="composition-verdict">
                {data.coherent
                  ? t('boq.position_cost.coherent', { defaultValue: 'Adds up' })
                  : t('boq.position_cost.not_coherent', { defaultValue: 'Does not add up' })}
              </dd>
            </div>
          </dl>
          {data.fx_missing.length > 0 && (
            <p className="text-xs text-semantic-warning" data-testid="composition-fx">
              {t('boq.position_cost.fx_missing', {
                defaultValue: 'No exchange rate in the project for: {{codes}}. These rows are left out of the sum.',
                codes: fmtList(data.fx_missing),
              })}
            </p>
          )}
          {data.components.length === 0 ? (
            <p className="text-sm text-content-secondary">
              {t('boq.position_cost.no_rows', { defaultValue: 'This line has no resource rows to check.' })}
            </p>
          ) : (
            <table className="oe-table oe-table-compact w-full">
              <thead>
                <tr>
                  <th className="text-left">{t('boq.position_cost.col_resource', { defaultValue: 'Resource' })}</th>
                  <th className="text-right">{t('boq.position_cost.col_qty', { defaultValue: 'Quantity' })}</th>
                  <th className="text-right">{t('boq.position_cost.col_rate', { defaultValue: 'Unit rate' })}</th>
                  <th className="text-left">{t('boq.position_cost.col_issues', { defaultValue: 'Issues' })}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.components.map((c) => (
                  <tr key={c.index}>
                    <td>{c.name}</td>
                    <td className="text-right tabular-nums">{c.quantity}</td>
                    <td className="text-right tabular-nums">{c.unit_rate}</td>
                    <td className="text-xs text-semantic-warning">
                      {fmtList(
                        c.issues.map((code) =>
                          (ISSUE_CODES as readonly string[]).includes(code)
                            ? t(`boq.position_cost.issue_${code}`, { defaultValue: code })
                            : code,
                        ),
                      )}
                    </td>
                    <td className="text-right">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setTarget(c);
                          setPending(null);
                        }}
                      >
                        {t('boq.position_cost.find_match', { defaultValue: 'Find match' })}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {target && (
            <section className="rounded-lg border border-border-light p-3" data-testid="composition-matches">
              <h3 className="text-sm font-medium">
                {t('boq.position_cost.matches_for', { defaultValue: 'Matches for {{name}}', name: target.name })}
              </h3>
              <p className="text-2xs text-content-quaternary">
                {t('boq.position_cost.confirm_hint', {
                  defaultValue: 'Review the match. Nothing changes until you confirm.',
                })}
              </p>
              {matches.data && matches.data.length === 0 && (
                <p className="mt-2 text-sm text-content-secondary">
                  {t('boq.position_cost.no_matches', { defaultValue: 'No match found.' })}
                </p>
              )}
              <ul className="mt-2 space-y-1">
                {(matches.data ?? []).map((m) => (
                  <li key={m.cost_item_id} className="flex items-center justify-between gap-3 text-sm">
                    <span>
                      <span className="tabular-nums text-content-quaternary">{m.code}</span> {m.description}
                      <span className="ml-2 tabular-nums">
                        {m.unit_rate} {m.currency}/{m.unit}
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="tabular-nums text-xs" data-testid="match-confidence">
                        {t('boq.position_cost.confidence', {
                          defaultValue: '{{pct}}% match',
                          pct: confidencePercent(m.score),
                        })}
                      </span>
                      {pending?.cost_item_id === m.cost_item_id ? (
                        <Button
                          variant="primary"
                          size="sm"
                          loading={replaceMut.isPending}
                          onClick={() => replaceMut.mutate(m)}
                        >
                          {t('boq.position_cost.confirm_replace', { defaultValue: 'Confirm replace' })}
                        </Button>
                      ) : (
                        <Button variant="secondary" size="sm" onClick={() => setPending(m)}>
                          {t('boq.position_cost.replace', { defaultValue: 'Replace' })}
                        </Button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </WideModal>
  );
}

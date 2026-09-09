// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a variation is priced against, chosen before its bill is opened
 * (Issue #435).
 *
 * The seeding endpoint has accepted `source_contract_lines` and
 * `source_positions` since the variation bill shipped, and the screen opened
 * every bill with an empty body. So a bill made through the product held no
 * provenance rows at all - not partial ones, none - and every line in it was
 * recorded as hand entered against nothing. `variations.boq_lines_are_traced`
 * then fired on each line, which is the rule correctly reporting that the only
 * writer of the trace table was unreachable.
 *
 * The picker is in front of opening the bill because seeding is the moment
 * the answer is cheapest to give; a line typed later acquires its provenance
 * from the bill editor's own trace control, which reads the same sources
 * through `useVariationSourceRows` below.
 *
 * Both source kinds are offered because a variation is priced against both.
 * Schedule-of-values lines answer "was this priced at contract rates", which
 * is the traceability the issue is titled for; estimating positions answer
 * "what did we think this scope cost when we tendered it".
 *
 * Each picked line also says what the variation does to it - added, removed
 * or modified - because a line citing a contract line could be extra quantity
 * of the item, a re-measure or the whole item omitted, and the three price
 * differently. The kind is the estimator's statement; the server checks it
 * against the numbers and reports a contradiction rather than resolving it.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { listContracts, listContractLines } from '../contracts/api';
import { boqApi, isSection } from '../boq/api';
import {
  VARIATION_CHANGE_KINDS,
  type CreateVariationBOQPayload,
  type VariationChangeKind,
} from './api';

const pickerInputCls =
  'h-8 w-24 rounded-lg border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const selectCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const kindSelectCls =
  'h-8 rounded-lg border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** One line of an existing bill or schedule, in the one shape the list needs. */
export interface SourceRow {
  id: string;
  code: string;
  description: string;
  unit: string;
  quantity: string;
}

/** What the estimator has said about one picked line. */
export interface PickedSource {
  quantity: string;
  change_kind: VariationChangeKind;
}

type Translate = ReturnType<typeof useTranslation>['t'];

/** The label a change kind reads as on screen, shared by every control that offers one. */
export function changeKindLabel(kind: VariationChangeKind, t: Translate): string {
  if (kind === 'removed') return t('variations.change_removed', { defaultValue: 'Removed' });
  if (kind === 'modified') return t('variations.change_modified', { defaultValue: 'Modified' });
  return t('variations.change_added', { defaultValue: 'Added' });
}

/**
 * The contracts and estimating bills of a project, and the lines of whichever
 * one `sourceKey` names (`contract:<id>` or `boq:<id>`).
 *
 * Shared between the picker in front of opening a bill and the trace control
 * in the bill editor, so the two offer exactly the same sources: a variation's
 * own bill is never one of them, because a chain of variations repricing each
 * other would record scope as coming from a change rather than from the
 * contract or the estimate it actually changes.
 */
export function useVariationSourceRows(projectId: string, sourceKey: string) {
  const contractsQ = useQuery({
    queryKey: ['variations', 'source-contracts', projectId],
    queryFn: () => listContracts({ project_id: projectId, limit: 200 }),
    enabled: Boolean(projectId),
  });

  const estimatesQ = useQuery({
    queryKey: ['variations', 'source-estimates', projectId],
    queryFn: () => boqApi.list(projectId),
    enabled: Boolean(projectId),
  });

  // Split rather than destructure: with noUncheckedIndexedAccess an element of
  // a split() result is string | undefined, and every query below wants a
  // string. Slicing at the first colon also leaves the id alone if one ever
  // arrives carrying a colon of its own.
  const separator = sourceKey.indexOf(':');
  const kind = separator === -1 ? '' : sourceKey.slice(0, separator);
  const sourceId = separator === -1 ? '' : sourceKey.slice(separator + 1);

  const linesQ = useQuery({
    queryKey: ['variations', 'source-contract-lines', sourceId],
    queryFn: () => listContractLines(sourceId),
    enabled: kind === 'contract' && Boolean(sourceId),
  });

  const positionsQ = useQuery({
    queryKey: ['variations', 'source-positions', sourceId],
    queryFn: () => boqApi.get(sourceId),
    enabled: kind === 'boq' && Boolean(sourceId),
  });

  const estimates = useMemo(
    () => (estimatesQ.data ?? []).filter((boq) => boq.estimate_type !== 'variation'),
    [estimatesQ.data],
  );

  const rows: SourceRow[] = useMemo(() => {
    if (kind === 'contract') {
      return (linesQ.data ?? []).map((line) => ({
        id: line.id,
        code: line.code,
        description: line.description,
        unit: line.unit ?? '',
        quantity: String(line.quantity ?? ''),
      }));
    }
    if (kind === 'boq') {
      return (positionsQ.data?.positions ?? [])
        .filter((position) => !isSection(position))
        .map((position) => ({
          id: position.id,
          code: position.ordinal,
          description: position.description,
          unit: position.unit,
          quantity: String(position.quantity ?? ''),
        }));
    }
    return [];
  }, [kind, linesQ.data, positionsQ.data]);

  const rowsLoading =
    (kind === 'contract' && linesQ.isLoading) || (kind === 'boq' && positionsQ.isLoading);
  const rowsError = kind === 'contract' ? linesQ.error : kind === 'boq' ? positionsQ.error : null;

  return {
    contracts: contractsQ.data?.items ?? [],
    estimates,
    /** 'contract' | 'boq' | '' - which kind of source `sourceKey` names. */
    kind,
    sourceId,
    rows,
    rowsLoading,
    rowsError,
  };
}

/**
 * The source select shared by the picker and the trace drawer: one option per
 * contract and per estimating bill of the project.
 */
export function VariationSourceSelect({
  value,
  onChange,
  contracts,
  estimates,
  className,
}: {
  value: string;
  onChange: (sourceKey: string) => void;
  contracts: ReturnType<typeof useVariationSourceRows>['contracts'];
  estimates: ReturnType<typeof useVariationSourceRows>['estimates'];
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={className ?? selectCls}
      aria-label={t('variations.boq_source_select', {
        defaultValue: 'Where the scope comes from',
      })}
    >
      <option value="">
        {t('variations.boq_source_choose', { defaultValue: 'Choose a source…' })}
      </option>
      {contracts.map((contract) => (
        <option key={contract.id} value={`contract:${contract.id}`}>
          {t('variations.boq_source_contract', { defaultValue: 'Contract' })}
          {' · '}
          {[contract.code, contract.title].filter(Boolean).join(' - ') || contract.id}
        </option>
      ))}
      {estimates.map((boq) => (
        <option key={boq.id} value={`boq:${boq.id}`}>
          {t('variations.boq_source_estimate', { defaultValue: 'Estimate' })}
          {' · '}
          {boq.name || boq.id}
        </option>
      ))}
    </select>
  );
}

/**
 * The chosen sources as the seeding endpoint reads them.
 *
 * Quantities go over as the string that was typed rather than a parsed float,
 * for the same reason the agreed amount does: the server holds these as
 * decimals and a round trip through binary is a change to the number nobody
 * asked for. Picking a line prefills its own quantity, because a variation
 * that re-measures part of a line starts from what the line says; a quantity
 * cleared to nothing is left out of the payload, which tells the server to
 * carry the source line's quantity across itself.
 *
 * The change kind is left out when it is `added`, which is what the server
 * records for a source that names none, so a body that says nothing about
 * the kind is the same body the endpoint has read since it shipped.
 */
export function buildSourcePayload(
  pickedLines: Record<string, PickedSource>,
  pickedPositions: Record<string, PickedSource>,
): CreateVariationBOQPayload {
  const payload: CreateVariationBOQPayload = {};
  const lines = Object.entries(pickedLines).map(([contract_line_id, picked]) => ({
    contract_line_id,
    ...(picked.quantity.trim() !== '' ? { quantity: picked.quantity.trim() } : {}),
    ...(picked.change_kind !== 'added' ? { change_kind: picked.change_kind } : {}),
  }));
  if (lines.length > 0) payload.source_contract_lines = lines;

  const positions = Object.entries(pickedPositions).map(([position_id, picked]) => ({
    position_id,
    ...(picked.quantity.trim() !== '' ? { quantity: picked.quantity.trim() } : {}),
    ...(picked.change_kind !== 'added' ? { change_kind: picked.change_kind } : {}),
  }));
  if (positions.length > 0) payload.source_positions = positions;
  return payload;
}

export function VariationSourcePicker({
  projectId,
  busy,
  onOpen,
  onCancel,
}: {
  projectId: string;
  busy: boolean;
  onOpen: (payload: CreateVariationBOQPayload) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [sourceKey, setSourceKey] = useState('');
  const [pickedLines, setPickedLines] = useState<Record<string, PickedSource>>({});
  const [pickedPositions, setPickedPositions] = useState<Record<string, PickedSource>>({});

  const { contracts, estimates, kind, rows, rowsLoading, rowsError } = useVariationSourceRows(
    projectId,
    sourceKey,
  );

  const picked = kind === 'contract' ? pickedLines : pickedPositions;
  const setPicked = kind === 'contract' ? setPickedLines : setPickedPositions;

  const toggle = (row: SourceRow) => {
    setPicked((prev) => {
      const next = { ...prev };
      if (row.id in next) delete next[row.id];
      else next[row.id] = { quantity: row.quantity, change_kind: 'added' };
      return next;
    });
  };

  const setQuantity = (id: string, value: string) => {
    setPicked((prev) => {
      const current = prev[id];
      if (!current) return prev;
      return { ...prev, [id]: { ...current, quantity: value } };
    });
  };

  const setKind = (id: string, change_kind: VariationChangeKind) => {
    setPicked((prev) => {
      const current = prev[id];
      if (!current) return prev;
      return { ...prev, [id]: { ...current, change_kind } };
    });
  };

  const total = Object.keys(pickedLines).length + Object.keys(pickedPositions).length;

  return (
    <Card padding="sm" className="space-y-2">
      <p className="text-sm text-content-secondary">
        {t('variations.boq_source_hint', {
          defaultValue:
            'Name the schedule-of-values lines and estimating positions this variation is priced against. Each seeded line records where it came from, so the price can be defended against the contract rather than asserted.',
        })}
      </p>

      <VariationSourceSelect
        value={sourceKey}
        onChange={setSourceKey}
        contracts={contracts}
        estimates={estimates}
      />

      {rowsLoading && (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      )}

      {rowsError != null && (
        <p className="text-sm text-content-tertiary">{getErrorMessage(rowsError)}</p>
      )}

      {sourceKey !== '' && !rowsLoading && rows.length === 0 && (
        <p className="text-sm text-content-tertiary">
          {t('variations.boq_source_empty', {
            defaultValue: 'This source has no lines to price against.',
          })}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="max-h-64 space-y-1 overflow-y-auto">
          {rows.map((row) => {
            const current = picked[row.id];
            const checked = current !== undefined;
            return (
              <li key={row.id} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={checked}
                  onChange={() => toggle(row)}
                  aria-label={`${row.code} ${row.description}`.trim()}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate">
                    <span className="text-content-tertiary">{row.code}</span>{' '}
                    {row.description || '—'}
                  </p>
                  {row.unit.trim() === '' && (
                    <p className="flex items-start gap-1.5 text-xs text-content-secondary">
                      <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                      {t('variations.boq_source_no_unit', {
                        defaultValue:
                          'This line carries no unit, so it arrives in the bill as a heading rather than a priced line.',
                      })}
                    </p>
                  )}
                </div>
                {current && (
                  <>
                    {/* What the variation does to this line. Only a schedule-of-values
                        line can be removed or modified - there is nothing contracted
                        behind an estimate position to omit - so the estimate side offers
                        the one kind that applies, and the server's rule would report the
                        others anyway. */}
                    {kind === 'contract' && (
                      <select
                        value={current.change_kind}
                        onChange={(e) => setKind(row.id, e.target.value as VariationChangeKind)}
                        className={clsx(kindSelectCls, 'shrink-0')}
                        aria-label={t('variations.boq_source_kind', {
                          defaultValue: 'What this variation does to {{code}}',
                          code: row.code,
                        })}
                      >
                        {VARIATION_CHANGE_KINDS.map((option) => (
                          <option key={option} value={option}>
                            {changeKindLabel(option, t)}
                          </option>
                        ))}
                      </select>
                    )}
                    <input
                      type="number"
                      step="any"
                      value={current.quantity}
                      onChange={(e) => setQuantity(row.id, e.target.value)}
                      className={clsx(pickerInputCls, 'shrink-0')}
                      aria-label={t('variations.boq_source_quantity', {
                        defaultValue: 'Quantity this variation changes',
                      })}
                    />
                  </>
                )}
                <span className="shrink-0 text-xs text-content-tertiary">{row.unit}</span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={total === 0}
          loading={busy}
          onClick={() => onOpen(buildSourcePayload(pickedLines, pickedPositions))}
        >
          {t('variations.open_bill_from_sources', {
            defaultValue: 'Open bill from {{count}} line',
            defaultValue_other: 'Open bill from {{count}} lines',
            count: total,
          })}
        </Button>
        <Button variant="secondary" onClick={() => onOpen({})} loading={busy}>
          {t('variations.open_empty_bill', { defaultValue: 'Open an empty bill' })}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </Card>
  );
}

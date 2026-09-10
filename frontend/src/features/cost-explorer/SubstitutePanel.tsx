// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Substitute" - a what-if on one resource line of a priced work. Pick the line
// to re-price, give a new unit price or swap in another catalog resource, and
// see the rate move. The change is incremental: only that line shifts, so the
// rest of the authored rate (overheads, other resources) is held intact.

import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowRight } from 'lucide-react';
import { Badge, Button, EmptyState, ErrorState, Input, TabBar } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { priceIntelligence, substitute, type CatalogResource } from './api';
import { ResourceSearchInput } from './ResourceSearchInput';
import { fmtMoney, MetaLine, signedPct } from './parts';
import { RowEstimateActions } from './RowEstimateActions';
import type { SubstituteSeed } from './types';

type Mode = 'price' | 'resource';

export function SubstitutePanel({ seed }: { seed: SubstituteSeed | null }) {
  const { t } = useTranslation();
  const [work, setWork] = useState<SubstituteSeed | null>(seed);
  const [resourceCode, setResourceCode] = useState(seed?.resource_code ?? '');
  const [resourceName, setResourceName] = useState(seed?.resource_name ?? '');
  const [mode, setMode] = useState<Mode>('price');
  const [newRate, setNewRate] = useState('');
  const [subResource, setSubResource] = useState<{ code: string; name: string } | null>(null);

  // Re-seed only when a new work is handed in from another tab (stable identity
  // between hand-offs means typing here is never wiped by a re-render).
  useEffect(() => {
    if (!seed) return;
    setWork(seed);
    setResourceCode(seed.resource_code ?? '');
    setResourceName(seed.resource_name ?? '');
    setNewRate('');
    setSubResource(null);
  }, [seed]);

  const priceQ = useQuery({
    queryKey: ['cost-explorer', 'price', resourceCode, work?.region ?? ''],
    queryFn: () => priceIntelligence(resourceCode, work?.region ?? null),
    enabled: resourceCode.trim().length > 0,
    staleTime: 60_000,
  });

  const sub = useMutation({
    mutationFn: () =>
      substitute({
        cost_item_id: work!.cost_item_id,
        resource_code: resourceCode.trim(),
        new_unit_rate: mode === 'price' ? newRate.trim() || null : null,
        substitute_resource_code: mode === 'resource' ? subResource?.code ?? null : null,
      }),
  });

  function pickLine(code: string, name: string) {
    setResourceCode(code);
    setResourceName(name);
    sub.reset();
  }
  function pickSubstitute(r: CatalogResource) {
    setSubResource({ code: r.resource_code, name: r.name || r.resource_code });
    sub.reset();
  }

  const canRun =
    !!work &&
    resourceCode.trim().length > 0 &&
    ((mode === 'price' && newRate.trim().length > 0) || (mode === 'resource' && !!subResource));

  if (!work) {
    return (
      <EmptyState
        title={t('costExplorer.substitute.startTitle', { defaultValue: 'Test a resource swap' })}
        description={t('costExplorer.substitute.startBody', {
          defaultValue: 'Open a work from By resources or Find work, then re-price one of its resources here.',
        })}
      />
    );
  }

  const stats = priceQ.data?.stats;
  const result = sub.data;

  return (
    <div className="space-y-4">
      {/* Target work */}
      <div className="rounded-lg border border-border-light bg-surface-primary p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-content-primary">{work.code}</span>
          {work.region && <Badge>{work.region}</Badge>}
        </div>
        {work.description && <p className="mt-0.5 text-sm text-content-secondary">{work.description}</p>}
        <div className="mt-1">
          <MetaLine parts={[work.unit]} />
        </div>
      </div>

      {/* Resource line to re-price */}
      <div>
        <label htmlFor="ce-sub-line" className="mb-1.5 block text-sm font-medium text-content-primary">
          {t('costExplorer.substitute.lineLabel', { defaultValue: 'Resource line to re-price' })}
        </label>
        {work.candidates && work.candidates.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {work.candidates.map((c) => (
              <button
                key={c.code}
                type="button"
                onClick={() => pickLine(c.code, c.name)}
                className={[
                  'rounded-full border px-2.5 py-1 text-xs',
                  c.code === resourceCode
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                ].join(' ')}
              >
                {c.name || c.code}
              </button>
            ))}
          </div>
        )}
        <ResourceSearchInput
          id="ce-sub-line"
          onPick={(r) => pickLine(r.resource_code, r.name || r.resource_code)}
          region={work.region ?? null}
          placeholder={t('costExplorer.substitute.linePlaceholder', { defaultValue: 'Search the resource inside this work' })}
        />
        {resourceCode && (
          <p className="mt-1.5 text-xs text-content-tertiary">
            {t('costExplorer.substitute.selectedLine', { defaultValue: 'Selected:' })}{' '}
            <span className="text-content-secondary">{resourceName || resourceCode}</span> ({resourceCode})
          </p>
        )}
      </div>

      {/* Price intelligence for the selected line */}
      {resourceCode && stats && stats.count > 0 && (
        <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs font-medium text-content-tertiary">
            {t('costExplorer.substitute.priceTitle', { defaultValue: 'Where this resource is priced' })}
            {priceQ.data?.stats_region && (
              <span className="rounded bg-surface-tertiary px-1.5 py-0.5 font-normal text-content-tertiary">
                {priceQ.data.stats_region}
                {stats.currency ? ` · ${stats.currency}` : ''}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <Stat label={t('costExplorer.substitute.min', { defaultValue: 'Low' })} value={fmtMoney(stats.min, stats.currency)} />
            <Stat label={t('costExplorer.substitute.median', { defaultValue: 'Median' })} value={fmtMoney(stats.median, stats.currency)} />
            <Stat label={t('costExplorer.substitute.max', { defaultValue: 'High' })} value={fmtMoney(stats.max, stats.currency)} />
            <Stat
              label={t('costExplorer.substitute.usage', { defaultValue: 'Used in' })}
              value={t('costExplorer.substitute.usageWorks', { defaultValue: '{{count}} works', count: priceQ.data?.usage_count ?? 0 })}
            />
          </div>
        </div>
      )}

      {/* Price intelligence failed to load: say so (distinct from "no data") and
          offer a retry, without blocking the substitution itself. */}
      {resourceCode && priceQ.isError && (
        <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
          <span className="min-w-0 flex-1">
            {t('costExplorer.substitute.priceError', {
              defaultValue: 'Could not load where this resource is priced. You can still test a substitution below.',
            })}
          </span>
          <button
            type="button"
            onClick={() => priceQ.refetch()}
            className="shrink-0 font-medium text-oe-blue hover:underline"
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </button>
        </div>
      )}

      {/* Replacement */}
      {resourceCode && (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('costExplorer.substitute.replacementLabel', { defaultValue: 'Replacement' })}
          </label>
          <TabBar<Mode>
            idPrefix="ce-sub-mode"
            ariaLabel={t('costExplorer.substitute.replacementLabel', { defaultValue: 'Replacement' })}
            variant="segmented"
            size="sm"
            tabs={[
              { id: 'price', label: t('costExplorer.substitute.modePrice', { defaultValue: 'New unit price' }) },
              { id: 'resource', label: t('costExplorer.substitute.modeResource', { defaultValue: 'Swap resource' }) },
            ]}
            activeId={mode}
            onChange={(m) => {
              setMode(m);
              sub.reset();
            }}
          />
          <div className="mt-2">
            {mode === 'price' ? (
              <Input
                type="number"
                min={0}
                step="any"
                value={newRate}
                onChange={(e) => {
                  setNewRate(e.target.value);
                  if (sub.data) sub.reset();
                }}
                aria-label={t('costExplorer.substitute.pricePlaceholder', { defaultValue: 'New unit price for this resource' })}
                placeholder={t('costExplorer.substitute.pricePlaceholder', { defaultValue: 'New unit price for this resource' })}
              />
            ) : (
              <ResourceSearchInput
                onPick={pickSubstitute}
                region={work.region ?? null}
                placeholder={t('costExplorer.substitute.swapPlaceholder', { defaultValue: 'Search a resource to swap in' })}
              />
            )}
            {mode === 'resource' && subResource && (
              <p className="mt-1.5 text-xs text-content-tertiary">
                {t('costExplorer.substitute.swapSelected', { defaultValue: 'Swap in:' })}{' '}
                <span className="text-content-secondary">{subResource.name}</span> ({subResource.code})
              </p>
            )}
          </div>
        </div>
      )}

      <Button onClick={() => sub.mutate()} disabled={!canRun || sub.isPending}>
        {sub.isPending ? t('common.calculating', { defaultValue: 'Calculating...' }) : t('costExplorer.substitute.run', { defaultValue: 'See the effect' })}
      </Button>

      {sub.isError && <ErrorState title={getErrorMessage(sub.error)} onRetry={() => sub.mutate()} />}

      {result && (
        <div className="rounded-lg border border-border-light bg-surface-primary p-4">
          <div className="flex flex-wrap items-center gap-4">
            <div>
              <div className="text-xs text-content-tertiary">{t('costExplorer.substitute.oldRate', { defaultValue: 'Current rate' })}</div>
              <div className="text-lg font-semibold tabular-nums text-content-primary">{fmtMoney(result.old_rate, result.currency)}</div>
            </div>
            <ArrowRight className="h-5 w-5 text-content-tertiary" aria-hidden />
            <div>
              <div className="text-xs text-content-tertiary">{t('costExplorer.substitute.newRate', { defaultValue: 'New rate' })}</div>
              <div className="text-lg font-semibold tabular-nums text-content-primary">{fmtMoney(result.new_rate, result.currency)}</div>
            </div>
            <div className="ml-auto text-right">
              <div className="text-xs text-content-tertiary">{t('costExplorer.substitute.change', { defaultValue: 'Change' })}</div>
              <div
                className={[
                  'text-lg font-semibold tabular-nums',
                  Number(result.delta) > 0 ? 'text-semantic-error' : Number(result.delta) < 0 ? 'text-semantic-success' : 'text-content-secondary',
                ].join(' ')}
              >
                {Number(result.delta) > 0 ? '+' : ''}
                {fmtMoney(result.delta, result.currency)} ({signedPct(result.delta_pct)})
              </div>
            </div>
          </div>

          <p className="mt-3 text-xs text-content-tertiary">
            {t('costExplorer.substitute.explain', {
              defaultValue:
                'Re-priced {{resource}} at {{qty}} per unit of work. Only this line changed; the rest of the rate is held.',
              resource: result.resource_name || result.resource_code,
              qty: fmtMoney(result.quantity),
            })}
          </p>

          {result.unit_mismatch && (
            <div className="mt-2 flex items-start gap-2 rounded-md border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
              <span>
                {t('costExplorer.substitute.unitMismatch', {
                  defaultValue:
                    'The replacement is priced per {{sub}}, but this line is measured in {{orig}}. The quantity was kept as-is, so check the unit basis before trusting the new rate.',
                  sub: result.substitute_unit,
                  orig: result.original_unit,
                })}
              </span>
            </div>
          )}

          {result.clamped && (
            <div className="mt-2 flex items-start gap-2 rounded-md border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2 text-xs text-content-secondary">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
              <span>
                {t('costExplorer.substitute.clamped', {
                  defaultValue: 'The change would drive the rate below zero, so it was floored at zero. Re-check the inputs.',
                })}
              </span>
            </div>
          )}

          <div className="mt-3 flex items-center gap-2 border-t border-border-light pt-3">
            <span className="text-xs text-content-tertiary">
              {t('costExplorer.substitute.useResult', { defaultValue: 'Use this rate' })}
            </span>
            <RowEstimateActions
              row={{
                cost_item_id: result.cost_item_id,
                code: result.code,
                description: result.description,
                unit: result.unit,
                rate: result.new_rate,
                currency: result.currency,
                region: result.region,
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-content-tertiary">{label}</div>
      <div className="tabular-nums text-content-primary">{value}</div>
    </div>
  );
}

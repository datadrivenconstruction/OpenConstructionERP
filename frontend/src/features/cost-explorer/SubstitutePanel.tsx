// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SubstitutePanel - the cross-base reprice drawer.
//
// Entry point: opened by RowEstimateActions from a BOQ / estimate row when
// more than one cost base is loaded. It looks up the position's SAME cost
// code across every other loaded base and lets the estimator:
//
//   1. Reprice-in-place: re-apply that code's rate from a chosen base. The
//      payload is built by ``buildRepricePayload`` (which reuses the same
//      ``buildBoqPositionDraft`` builder the add-to-BOQ flow uses) and PATCHed
//      to the position, so the position goes back through the server-side
//      variant-snapshot re-freeze with the provenance stamp
//      (cost_item_region / id / code / currency) updated to the new base.
//
//   2. Save as a cross-base assembly: persist the current composition as a
//      reusable assembly where every component remembers its source base.
//
// Currency is never blended into a stored figure. A foreign rate is applied
// verbatim (the BOQ FX rollup converts for display via the project's
// fx_rates); a multi-currency assembly pick is blocked, not converted.

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeftRight, AlertTriangle, Check, Info, Loader2, Package } from 'lucide-react';
import clsx from 'clsx';

import { SideDrawer, CountryFlag } from '@/shared/ui';
import { apiGet, apiPatch } from '@/shared/lib/api';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import { useToastStore } from '@/stores/useToastStore';
import { assembliesApi, type ComponentMetadata } from '@/features/assemblies/api';
import {
  buildCrossBaseAssemblyDraft,
  buildRepricePayload,
  type CrossBaseComponentDraft,
  type FullCostItem,
  type SynthLabels,
} from '@/features/costs/addToBoqHelpers';

/** The BOQ / estimate position being repriced. Everything the panel needs is
 *  read from the position row; no ambient store scope is required. */
export interface RepricePosition {
  id: string;
  /** Cost-database code to look up in the other bases (metadata.cost_item_code
   *  or the position's own code). Empty means the position is not repriceable. */
  code: string;
  description: string;
  unit: string;
  quantity: number;
  /** Current unit rate (number is fine for display / delta math only). */
  currentRate: number;
  /** ISO 4217 currency the current rate is denominated in. */
  currency: string;
  /** Current source base region (metadata.cost_item_region), or null. */
  region: string | null;
  /** Full position metadata_ so the assembly save can read resources[]. */
  metadata?: Record<string, unknown>;
}

export interface SubstitutePanelProps {
  open: boolean;
  onClose: () => void;
  position: RepricePosition;
  /** Called after a successful reprice or assembly save so the parent can
   *  refetch. The panel does not guess BOQ query keys. */
  onRepriced?: () => void;
}

/** Minimal row shape from the lite cost search. */
interface CostSearchRow {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  currency: string;
  region: string | null;
}

function normCur(c: string | null | undefined): string {
  return (c ?? '').trim().toUpperCase();
}

/** Currency-aware money formatter. Always renders the ISO code because rows
 *  can span EUR / TRY / CNY / VND. Falls back to a plain number + code when
 *  the ISO code is unknown to Intl. */
function fmtMoney(n: number, currency: string): string {
  const code = normCur(currency);
  const num = Number.isFinite(n) ? n : 0;
  if (!code) {
    return new Intl.NumberFormat(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(num);
  }
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: code,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(num);
  } catch {
    return `${new Intl.NumberFormat(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(num)} ${code}`;
  }
}

export function SubstitutePanel({ open, onClose, position, onRepriced }: SubstitutePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const posCode = (position.code || '').trim();
  const posCur = normCur(position.currency);

  const synthLabels: SynthLabels = useMemo(
    () => ({
      labor: t('costs.component_labor', { defaultValue: 'Labor' }),
      material: t('costs.component_material', { defaultValue: 'Material' }),
      equipment: t('costs.component_equipment', { defaultValue: 'Equipment' }),
    }),
    [t],
  );

  const regionLabel = useCallback(
    (region: string | null): string => {
      if (!region) return t('costs.reprice.unknown_base', { defaultValue: 'another base' });
      return REGION_MAP[region]?.name || REGION_MAP[region]?.label || region;
    },
    [t],
  );

  // Look up the SAME code across every loaded base in one request. ``q`` is a
  // substring match, so we keep only exact-code rows client-side. lite=1 keeps
  // the payload small (rate / currency / region / unit survive trimming).
  const {
    data: matches = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['reprice-cross-base', posCode],
    enabled: open && posCode.length > 0,
    staleTime: 60_000,
    retry: false,
    queryFn: async () => {
      const params = new URLSearchParams({ q: posCode, limit: '100', lite: '1' });
      const resp = await apiGet<{ items: CostSearchRow[] }>(`/v1/costs/?${params.toString()}`);
      return (resp.items ?? [])
        .filter((it) => (it.code || '').trim() === posCode)
        // Money can arrive as a Decimal string on some endpoints; coerce so
        // the delta math and formatting below stay numeric.
        .map((it) => ({ ...it, rate: Number(it.rate) || 0 }));
    },
  });

  // One candidate per other base (first row wins); the current base is excluded.
  const candidates = useMemo(() => {
    const byRegion = new Map<string, CostSearchRow>();
    for (const m of matches) {
      const reg = m.region ?? '';
      if (!reg || reg === (position.region ?? '')) continue;
      if (!byRegion.has(reg)) byRegion.set(reg, m);
    }
    return Array.from(byRegion.values());
  }, [matches, position.region]);

  // ── Reprice-in-place ──────────────────────────────────────────────────
  const [applyingRegion, setApplyingRegion] = useState<string | null>(null);

  const reprice = useCallback(
    async (row: CostSearchRow) => {
      setApplyingRegion(row.region ?? '');
      try {
        const full = await apiGet<FullCostItem>(`/v1/costs/${row.id}`);
        const currency = normCur(
          full.currency || REGION_MAP[full.region ?? '']?.currency || row.currency,
        );
        const payload = buildRepricePayload(full, currency, synthLabels, {
          fromRegion: position.region,
          fromCurrency: position.currency,
          existingMetadata: position.metadata,
        });
        await apiPatch(`/v1/boq/positions/${position.id}`, payload);

        const fx = Boolean(currency && posCur && currency !== posCur);
        addToast({
          type: 'success',
          title: t('costs.reprice.done_title', {
            defaultValue: 'Rate updated from {{base}}',
            base: regionLabel(row.region),
          }),
          message: fx
            ? t('costs.reprice.done_fx', {
                defaultValue:
                  'Stored in {{cur}}, not converted. The BOQ rollup converts it via your FX rates.',
                cur: currency,
              })
            : t('costs.reprice.done_same', {
                defaultValue: 'The position now uses the {{base}} rate.',
                base: regionLabel(row.region),
              }),
        });
        onRepriced?.();
        onClose();
      } catch (err) {
        addToast({
          type: 'error',
          title: t('costs.reprice.failed', { defaultValue: 'Reprice failed' }),
          message:
            err instanceof Error
              ? err.message
              : t('common.unknown_error', { defaultValue: 'Unknown error' }),
        });
      } finally {
        setApplyingRegion(null);
      }
    },
    [position, posCur, synthLabels, regionLabel, addToast, onRepriced, onClose, t],
  );

  // ── Save as cross-base assembly ───────────────────────────────────────
  const [assemblyName, setAssemblyName] = useState('');
  const [savingAssembly, setSavingAssembly] = useState(false);

  // Components come from the position's resource breakdown, each carrying its
  // source base. A position with no breakdown collapses to one component.
  const assembly = useMemo(() => {
    const draft = buildCrossBaseAssemblyDraft(position.metadata, position.region, position.currency);
    if (draft.components.length > 0) return draft;
    const single: CrossBaseComponentDraft = {
      description: position.description || posCode,
      resource_type: 'material',
      factor: 1,
      quantity: 1,
      unit: position.unit || 'pcs',
      unit_cost: Number.isFinite(position.currentRate) ? position.currentRate : 0,
      metadata: { source_base: position.region, source_currency: posCur },
    };
    return { components: [single], currencies: posCur ? [posCur] : [], blended: false };
  }, [position, posCode, posCur]);

  const distinctBases = useMemo(() => {
    const set = new Set<string>();
    for (const c of assembly.components) {
      const b = c.metadata.source_base;
      if (typeof b === 'string' && b) set.add(b);
    }
    return Array.from(set);
  }, [assembly]);

  const saveAssembly = useCallback(async () => {
    if (assembly.blended) {
      addToast({
        type: 'error',
        title: t('costs.reprice.assembly_blend_title', {
          defaultValue: 'Components span currencies',
        }),
        message: t('costs.reprice.assembly_blend_msg', {
          defaultValue:
            'An assembly stores a single currency. Reprice the lines to one currency before saving.',
        }),
      });
      return;
    }
    setSavingAssembly(true);
    try {
      const currency = assembly.currencies[0] || posCur || 'EUR';
      const suffix = Date.now().toString(36).slice(-4).toUpperCase();
      const code = `${(posCode || 'XB').slice(0, 90)}-XB${suffix}`;
      const name = (
        assemblyName.trim() ||
        position.description ||
        posCode ||
        t('costs.reprice.assembly_fallback_name', { defaultValue: 'Cross-base assembly' })
      ).slice(0, 250);

      const created = await assembliesApi.create({
        code,
        name,
        unit: position.unit || 'pcs',
        currency,
      });
      for (const c of assembly.components) {
        await assembliesApi.addComponent(created.id, {
          description: c.description || name,
          resource_type: c.resource_type,
          factor: c.factor,
          quantity: c.quantity,
          unit: c.unit || 'pcs',
          unit_cost: c.unit_cost,
          // ComponentMetadata carries an open string index signature, so the
          // source_base / source_currency keys ride through untyped. Cast is
          // safe: ComponentMetadata is assignable to Record<string, unknown>.
          metadata: c.metadata as ComponentMetadata,
        });
      }
      addToast({
        type: 'success',
        title: t('costs.reprice.assembly_saved_title', { defaultValue: 'Assembly saved' }),
        message: t('costs.reprice.assembly_saved_msg', {
          defaultValue: '{{count}} components saved, each keeping its source base.',
          count: assembly.components.length,
        }),
      });
      onRepriced?.();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('costs.reprice.assembly_failed', { defaultValue: 'Could not save assembly' }),
        message:
          err instanceof Error
            ? err.message
            : t('common.unknown_error', { defaultValue: 'Unknown error' }),
      });
    } finally {
      setSavingAssembly(false);
    }
  }, [assembly, assemblyName, posCode, posCur, position, addToast, onRepriced, t]);

  const busy = applyingRegion !== null || savingAssembly;

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      busy={busy}
      backdropCloses={!busy}
      title={t('costs.reprice.title', { defaultValue: 'Reprice from another base' })}
      subtitle={
        posCode
          ? t('costs.reprice.subtitle', {
              defaultValue: 'Code {{code}} - currently {{base}}',
              code: posCode,
              base: regionLabel(position.region),
            })
          : undefined
      }
      widthClass="max-w-lg"
    >
      <div className="space-y-5 p-5">
        {/* Current rate summary */}
        <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
          <div className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('costs.reprice.current', { defaultValue: 'Current rate' })}
          </div>
          <div className="mt-1 flex items-center gap-2">
            {position.region && <CountryFlag code={position.region} size={18} />}
            <span className="text-lg font-semibold tabular-nums text-content-primary">
              {fmtMoney(position.currentRate, posCur)}
            </span>
            <span className="text-xs text-content-tertiary">/ {position.unit || '-'}</span>
            <span className="ml-auto truncate text-xs text-content-secondary">
              {regionLabel(position.region)}
            </span>
          </div>
        </div>

        {/* Cross-base rate list */}
        <div>
          <div className="mb-2 flex items-center gap-1.5">
            <ArrowLeftRight size={14} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('costs.reprice.other_bases', { defaultValue: 'Same code in other bases' })}
            </h3>
          </div>

          {!posCode ? (
            <p className="rounded-md bg-surface-secondary/40 p-3 text-xs text-content-tertiary">
              {t('costs.reprice.no_code', {
                defaultValue: 'This position has no cost-database code to reprice.',
              })}
            </p>
          ) : isLoading ? (
            <div className="flex items-center gap-2 p-3 text-xs text-content-tertiary">
              <Loader2 size={14} className="animate-spin" />
              {t('costs.reprice.loading', { defaultValue: 'Looking up other bases...' })}
            </div>
          ) : isError ? (
            <p className="rounded-md bg-semantic-error-subtle p-3 text-xs text-semantic-error">
              {t('costs.reprice.lookup_failed', {
                defaultValue: 'Could not look up other bases. Try again.',
              })}
            </p>
          ) : candidates.length === 0 ? (
            <p className="rounded-md bg-surface-secondary/40 p-3 text-xs text-content-tertiary">
              {t('costs.reprice.not_in_others', {
                defaultValue: 'This code is not available in any other loaded base.',
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {candidates.map((row) => {
                const cur = normCur(row.currency || REGION_MAP[row.region ?? '']?.currency);
                const sameCur = Boolean(cur && posCur && cur === posCur);
                const deltaPct =
                  sameCur && position.currentRate > 0
                    ? ((row.rate - position.currentRate) / position.currentRate) * 100
                    : null;
                const applying = applyingRegion === (row.region ?? '');
                return (
                  <li
                    key={row.id}
                    className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary p-3"
                  >
                    {row.region && <CountryFlag code={row.region} size={18} />}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-content-primary">
                        {regionLabel(row.region)}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-content-secondary">
                        <span className="font-semibold tabular-nums">
                          {fmtMoney(row.rate, cur)}
                        </span>
                        <span className="text-content-tertiary">/ {row.unit || position.unit || '-'}</span>
                        {deltaPct !== null && (
                          <span
                            className={clsx(
                              'tabular-nums',
                              deltaPct > 0
                                ? 'text-semantic-error'
                                : deltaPct < 0
                                  ? 'text-semantic-success'
                                  : 'text-content-tertiary',
                            )}
                          >
                            {deltaPct >= 0 ? '+' : ''}
                            {deltaPct.toFixed(1)}%
                          </span>
                        )}
                        {!sameCur && (
                          <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-2xs font-medium text-amber-600 dark:text-amber-400">
                            <AlertTriangle size={10} />
                            {t('costs.reprice.diff_currency', {
                              defaultValue: '{{cur}}, not converted',
                              cur,
                            })}
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => reprice(row)}
                      className={clsx(
                        'inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium',
                        'bg-oe-blue text-white hover:bg-oe-blue/90',
                        'disabled:cursor-not-allowed disabled:opacity-50',
                      )}
                    >
                      {applying ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                      {t('costs.reprice.use', { defaultValue: 'Use this rate' })}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex items-start gap-1.5 text-2xs text-content-tertiary">
          <Info size={12} className="mt-0.5 shrink-0" />
          <span>
            {t('costs.reprice.fx_note', {
              defaultValue:
                'Rates are never converted on apply. A foreign rate is stored in its own currency and the BOQ rollup converts it for display via your FX rates.',
            })}
          </span>
        </div>

        {/* Save as cross-base assembly */}
        <div className="rounded-lg border border-border-light p-3">
          <div className="mb-2 flex items-center gap-1.5">
            <Package size={14} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('costs.reprice.save_assembly', { defaultValue: 'Save as cross-base assembly' })}
            </h3>
          </div>
          <p className="mb-2 text-2xs text-content-tertiary">
            {t('costs.reprice.save_assembly_hint', {
              defaultValue:
                'Store the current composition as a reusable assembly. Each component keeps the base it was priced from.',
            })}
          </p>
          <input
            type="text"
            value={assemblyName}
            onChange={(e) => setAssemblyName(e.target.value)}
            placeholder={position.description || posCode}
            aria-label={t('costs.reprice.assembly_name', { defaultValue: 'Assembly name' })}
            className="mb-2 w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
          <div className="flex flex-wrap items-center gap-2 text-2xs text-content-tertiary">
            {distinctBases.map((b) => (
              <span
                key={b}
                className="inline-flex items-center gap-1 rounded bg-surface-secondary/60 px-1.5 py-0.5"
              >
                <CountryFlag code={b} size={12} />
                {regionLabel(b)}
              </span>
            ))}
            <span className="ml-auto">
              {t('costs.reprice.component_count', {
                defaultValue: '{{count}} components',
                count: assembly.components.length,
              })}
            </span>
          </div>
          {assembly.blended && (
            <p className="mt-2 inline-flex items-center gap-1 text-2xs text-semantic-error">
              <AlertTriangle size={11} />
              {t('costs.reprice.assembly_blend_inline', {
                defaultValue: 'Lines span currencies - reprice to one currency to save.',
              })}
            </p>
          )}
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              disabled={busy || assembly.blended || assembly.components.length === 0}
              onClick={saveAssembly}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium',
                'text-content-primary hover:bg-surface-secondary',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
            >
              {savingAssembly ? <Loader2 size={13} className="animate-spin" /> : <Package size={13} />}
              {t('costs.reprice.save_assembly_btn', { defaultValue: 'Save assembly' })}
            </button>
          </div>
        </div>
      </div>
    </SideDrawer>
  );
}

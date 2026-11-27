/**
 * Insert an assembly into an existing BOQ position.
 *
 * The estimator picks one of their assemblies, sees its components and the
 * unit rate the position will end up with (a dry run on the server, so the
 * preview is the same arithmetic as the save), scales it with a quantity
 * factor, and applies. The position keeps its number, text and quantity; its
 * resources and unit rate come from the assembly.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, Layers, Loader2, Search, X } from 'lucide-react';

import { Button } from '@/shared/ui';
import { apiGet, apiPost, getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { resourceQuantityBasis } from './boqHelpers';
import { highlightMatch } from './highlightMatch';

export const FACTOR_MAX = 10_000;

export interface InsertAssemblyTarget {
  id: string;
  ordinal?: string | null;
  description?: string | null;
  unit?: string | null;
  metadata?: Record<string, unknown> | null;
}

interface AssemblyListItem {
  id: string;
  code: string;
  name: string;
  unit: string;
  category: string;
  total_rate: number | string;
  currency: string;
}

interface AppliedRow {
  name?: string;
  code?: string;
  unit?: string;
  type?: string;
  quantity?: number | string;
  unit_rate?: number | string;
  total?: number | string;
}

interface Snapshot {
  unit_rate: string;
  total: string;
  resource_count: number;
}

export interface ApplyToPositionResult {
  position_id: string;
  assembly_code: string;
  assembly_name: string;
  assembly_unit: string;
  position_unit: string;
  mode: 'replace' | 'append';
  factor: string;
  currency: string;
  quantity: string;
  assembly_rate: string;
  before: Snapshot;
  after: Snapshot;
  resources: AppliedRow[];
  warnings: Array<Record<string, string>>;
  previous?: { unit_rate: string; metadata: Record<string, unknown> };
}

/** A factor the server accepts, or null: above zero, at most FACTOR_MAX. */
export function parseFactor(text: string): number | null {
  if (!text.trim()) return 1;
  const v = parseDecimalInput(text);
  if (v === null || !Number.isFinite(v) || v <= 0 || v > FACTOR_MAX) return null;
  return v;
}

export function InsertAssemblyModal({
  position,
  onClose,
  onApplied,
}: {
  position: InsertAssemblyTarget;
  onClose: () => void;
  onApplied: (result: ApplyToPositionResult) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [picked, setPicked] = useState<AssemblyListItem | null>(null);
  const [factorText, setFactorText] = useState('1');
  const meta = position.metadata ?? {};
  const existingRows = Array.isArray(meta.resources) ? meta.resources.length : 0;
  const perPosition = resourceQuantityBasis(meta) === 'per_position';
  const [mode, setMode] = useState<'replace' | 'append'>('replace');
  const factor = parseFactor(factorText);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(handle);
  }, [search]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, { capture: true });
    return () => document.removeEventListener('keydown', onKey, { capture: true });
  }, [onClose]);

  const list = useQuery({
    queryKey: ['assemblies', debounced],
    queryFn: () =>
      apiGet<{ items: AssemblyListItem[] }>(`/v1/assemblies/?q=${encodeURIComponent(debounced)}&limit=20`).then(
        (r) => r.items,
      ),
    retry: false,
  });

  const body = useMemo(
    () => ({ position_id: position.id, factor: factor ?? 1, mode }),
    [position.id, factor, mode],
  );
  const preview = useQuery({
    queryKey: ['assembly-apply-preview', picked?.id, body],
    queryFn: () =>
      apiPost<ApplyToPositionResult>(`/v1/assemblies/${picked!.id}/apply-to-position/`, { ...body, dry_run: true }),
    enabled: Boolean(picked) && factor !== null,
    retry: false,
  });

  const apply = useMutation({
    mutationFn: () => apiPost<ApplyToPositionResult>(`/v1/assemblies/${picked!.id}/apply-to-position/`, body),
    onSuccess: (res) => onApplied(res),
  });

  const money = (v: string | number | undefined) => formatCurrency(v ?? 0, preview.data?.currency || undefined);
  const num = (v: string | number | undefined) =>
    new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 4 }).format(Number(v ?? 0));
  const p = preview.data;
  const positionLabel = `${position.ordinal ?? ''} ${position.description ?? ''}`.trim();

  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose} role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.insert_assembly.title', { defaultValue: 'Insert assembly into position' })}
        className="bg-surface-elevated rounded-2xl border border-border shadow-2xl w-full max-w-3xl mx-4 max-h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-purple-100 text-purple-600 dark:bg-purple-900/30">
              <Layers size={20} />
            </div>
            <div className="min-w-0">
              <h2 className="oe-section-title">{t('boq.insert_assembly.title', { defaultValue: 'Insert assembly into position' })}</h2>
              <p className="text-xs text-content-tertiary truncate" title={positionLabel}>{positionLabel}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {!picked ? (
            <>
              <div className="px-6 py-3 border-b border-border-light">
                <div className="relative">
                  <Search size={14} className="absolute start-3 top-1/2 -translate-y-1/2 text-content-quaternary" />
                  <input
                    type="text"
                    autoComplete="off"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={t('assemblies.search_placeholder', { defaultValue: 'Search assemblies...' })}
                    aria-label={t('assemblies.search_placeholder', { defaultValue: 'Search assemblies...' })}
                    className="oe-input w-full ps-9 pe-3"
                    autoFocus
                  />
                </div>
              </div>
              <div className="px-6 py-3">
                {list.isLoading ? (
                  <div className="flex items-center justify-center py-12 text-xs text-content-tertiary">
                    <Loader2 size={16} className="animate-spin me-2" />
                    {t('assemblies.loading', { defaultValue: 'Loading assemblies...' })}
                  </div>
                ) : list.isError ? (
                  <p className="py-8 text-center text-sm text-semantic-error" role="alert">
                    {t('boq.insert_assembly.list_failed', { defaultValue: 'Assemblies could not be loaded.' })}{' '}
                    {getErrorMessage(list.error)}
                  </p>
                ) : !list.data || list.data.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <Layers size={32} className="text-content-quaternary mb-3" />
                    <p className="text-sm font-medium text-content-secondary mb-1">
                      {debounced
                        ? t('assemblies.no_search_match', { defaultValue: 'No assemblies match your search' })
                        : t('assemblies.no_assemblies', { defaultValue: 'No assemblies yet' })}
                    </p>
                    {!debounced && (
                      <Button variant="secondary" size="sm" onClick={() => { onClose(); navigate('/assemblies'); }}>
                        {t('assemblies.manage_assemblies', { defaultValue: 'Manage Assemblies' })}
                      </Button>
                    )}
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {list.data.map((asm) => (
                      <li key={asm.id}>
                        <button
                          type="button"
                          onClick={() => setPicked(asm)}
                          className="w-full text-start rounded-xl border border-border-light bg-surface-primary hover:bg-surface-secondary/50 transition-colors p-3"
                        >
                          <div className="flex items-baseline gap-2">
                            <span className="text-sm font-semibold text-content-primary line-clamp-2">{highlightMatch(asm.name, search)}</span>
                            <span className="text-2xs font-mono text-content-quaternary shrink-0">{asm.code}</span>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-content-tertiary">
                            <span>{asm.unit}</span>
                            <span className="font-semibold text-content-primary tabular-nums">
                              {formatCurrency(asm.total_rate, asm.currency || undefined)}
                            </span>
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          ) : (
            <div className="px-6 py-4 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-content-primary">{picked.name}</p>
                  <p className="text-2xs font-mono text-content-quaternary">{picked.code} · {picked.unit}</p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setPicked(null)}>
                  {t('boq.insert_assembly.change', { defaultValue: 'Choose another' })}
                </Button>
              </div>

              <div className="flex flex-wrap items-start gap-4">
                <div>
                  <label htmlFor="insert-assembly-factor" className="oe-label">
                    {t('boq.insert_assembly.factor', { defaultValue: 'Quantity factor' })}
                  </label>
                  <input
                    id="insert-assembly-factor"
                    type="text"
                    inputMode="decimal"
                    value={factorText}
                    onChange={(e) => setFactorText(e.target.value)}
                    aria-invalid={factor === null || undefined}
                    className={`oe-input w-24 text-right tabular-nums ${factor === null ? 'border-semantic-error' : ''}`}
                  />
                  <p className={`mt-1 text-2xs ${factor === null ? 'text-semantic-error' : 'text-content-tertiary'}`}>
                    {factor === null
                      ? t('boq.insert_assembly.factor_invalid', { defaultValue: 'Enter a number above 0 and up to {{max}}.', max: FACTOR_MAX })
                      : t('boq.insert_assembly.factor_hint', { defaultValue: 'Multiplies every component quantity, e.g. 1.1 for 10 % waste.' })}
                  </p>
                </div>
                {existingRows > 0 && (
                  <fieldset>
                    <legend className="oe-label">
                      {t('boq.insert_assembly.existing', { defaultValue: 'Resources already on this position: {{n}}', n: existingRows })}
                    </legend>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="radio" name="insert-assembly-mode" checked={mode === 'replace'} onChange={() => setMode('replace')} />
                      {t('boq.insert_assembly.mode_replace', { defaultValue: 'Replace them' })}
                    </label>
                    <label
                      className={`flex items-center gap-2 text-sm ${perPosition ? 'opacity-50' : ''}`}
                      title={perPosition ? t('boq.insert_assembly.append_per_position', { defaultValue: 'These resources are entered for the whole position, so the assembly can only replace them.' }) : undefined}
                    >
                      <input
                        type="radio"
                        name="insert-assembly-mode"
                        checked={mode === 'append'}
                        disabled={perPosition}
                        onChange={() => setMode('append')}
                      />
                      {t('boq.insert_assembly.mode_append', { defaultValue: 'Add the assembly to them' })}
                    </label>
                  </fieldset>
                )}
              </div>

              {preview.isLoading && factor !== null ? (
                <div className="flex items-center justify-center py-8 text-xs text-content-tertiary">
                  <Loader2 size={16} className="animate-spin me-2" />
                  {t('boq.insert_assembly.previewing', { defaultValue: 'Working out the new rate…' })}
                </div>
              ) : preview.isError ? (
                <p className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error" role="alert">
                  {getErrorMessage(preview.error)}
                </p>
              ) : p ? (
                <>
                  {p.warnings.length > 0 && (
                    <ul className="space-y-1" data-testid="insert-assembly-warnings">
                      {p.warnings.map((w) => (
                        <li key={w.code} className="flex items-start gap-2 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning">
                          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                          {w.code === 'unit_mismatch'
                            ? t('boq.insert_assembly.warn_unit', { defaultValue: 'The assembly is priced per {{assembly}}, the position is measured in {{position}}. Check the factor.', assembly: w.assembly_unit, position: w.position_unit })
                            : w.code === 'currency_mismatch'
                              ? t('boq.insert_assembly.warn_currency', { defaultValue: 'The assembly is in {{assembly}} and the project in {{project}}; it is converted at the project rate when one is set.', assembly: w.assembly_currency, project: w.project_currency })
                              : t('boq.insert_assembly.warn_empty', { defaultValue: 'This assembly has no components, so it adds nothing to the rate.' })}
                        </li>
                      ))}
                    </ul>
                  )}
                  <table className="w-full text-xs" data-testid="insert-assembly-components">
                    <thead className="text-content-tertiary">
                      <tr>
                        <th className="text-start font-medium py-1">{t('boq.insert_assembly.col_component', { defaultValue: 'Component' })}</th>
                        <th className="text-end font-medium py-1">{t('boq.insert_assembly.col_qty', { defaultValue: 'Qty per {{unit}}', unit: p.position_unit || p.assembly_unit })}</th>
                        <th className="text-end font-medium py-1">{t('boq.insert_assembly.col_rate', { defaultValue: 'Rate' })}</th>
                        <th className="text-end font-medium py-1">{t('boq.insert_assembly.col_amount', { defaultValue: 'Amount' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.resources.map((r, i) => (
                        <tr key={`${r.code ?? ''}-${i}`} className="border-t border-border-light">
                          <td className="py-1 pe-2">{r.name}</td>
                          <td className="py-1 text-end tabular-nums">{num(r.quantity)} {r.unit}</td>
                          <td className="py-1 text-end tabular-nums">{money(r.unit_rate)}</td>
                          <td className="py-1 text-end tabular-nums">{money(Number(r.quantity ?? 0) * Number(r.unit_rate ?? 0))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 rounded-xl border border-border-light bg-surface-secondary/40 p-3" data-testid="insert-assembly-result">
                    <div>
                      <p className="text-2xs uppercase tracking-wide text-content-tertiary">{t('boq.insert_assembly.now', { defaultValue: 'Now' })}</p>
                      <p className="text-sm tabular-nums">{money(p.before.unit_rate)} / {p.position_unit}</p>
                      <p className="text-2xs text-content-tertiary tabular-nums">{money(p.before.total)}</p>
                    </div>
                    <ArrowRight size={16} className="text-content-tertiary" />
                    <div>
                      <p className="text-2xs uppercase tracking-wide text-content-tertiary">{t('boq.insert_assembly.after', { defaultValue: 'After' })}</p>
                      <p className="text-base font-semibold tabular-nums">{money(p.after.unit_rate)} / {p.position_unit}</p>
                      <p className="text-2xs text-content-tertiary tabular-nums">
                        {t('boq.insert_assembly.total_for', { defaultValue: '{{total}} for {{qty}} {{unit}}', total: money(p.after.total), qty: num(p.quantity), unit: p.position_unit })}
                      </p>
                    </div>
                  </div>
                </>
              ) : null}
              {apply.isError && (
                <p className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error" role="alert">
                  {t('assemblies.apply_failed', { defaultValue: 'Failed to apply assembly' })}: {getErrorMessage(apply.error)}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 px-6 py-3 border-t border-border-light bg-surface-secondary/30 shrink-0">
          <span className="text-2xs text-content-quaternary">
            {t('boq.insert_assembly.keeps_text', { defaultValue: 'Number, text and quantity stay; resources and unit rate come from the assembly. You can undo it.' })}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => apply.mutate()}
              loading={apply.isPending}
              disabled={!p || factor === null || apply.isPending || preview.isFetching}
              title={!picked ? t('boq.insert_assembly.pick_first', { defaultValue: 'Choose an assembly first.' }) : undefined}
            >
              {t('boq.insert_assembly.apply', { defaultValue: 'Insert into position' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

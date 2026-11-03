// Gap plugs, totals and checks for the bid leveling grid, plus the package type selector.
import { useState } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Pencil, X } from 'lucide-react';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import type {
  BidLevelingRow,
  LevelingCheck,
  LevelingPlug,
  PackageType,
  PlugSource,
} from './api';

const SOURCE_LABELS: Record<PlugSource, [string, string]> = {
  median: ['bid_management.plug_source_median', 'Median of bids'],
  estimate: ['bid_management.plug_source_estimate', 'Estimate rate'],
  single_bid: ['bid_management.plug_source_single_bid', 'Single bid'],
  manual: ['bid_management.plug_source_manual', 'Manual'],
  none: ['bid_management.plug_source_none', 'No source'],
};

export function PlugCell({
  plug,
  currency,
  busy,
  readOnly,
  onSave,
}: {
  plug: LevelingPlug;
  currency?: string;
  busy?: boolean;
  readOnly?: boolean;
  onSave: (amount: string | null) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [key, dflt] = SOURCE_LABELS[plug.source] ?? SOURCE_LABELS.none;
  const amount = plug.amount == null ? null : Number(plug.amount);

  const commit = () => {
    const v = value.trim();
    if (v === '' || Number.isNaN(Number(v))) return;
    onSave(v);
    setEditing(false);
  };

  return (
    <div
      data-testid="plug-cell"
      data-source={plug.source}
      className="rounded border border-dashed border-amber-400 bg-amber-50/70 px-1.5 py-1 text-right dark:border-amber-700 dark:bg-amber-950/20"
    >
      {editing ? (
        <div className="flex items-center justify-end gap-1">
          <input
            type="number"
            min="0"
            step="any"
            autoFocus
            aria-label={t('bid_management.plug_amount', { defaultValue: 'Plug amount' })}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit();
              if (e.key === 'Escape') setEditing(false);
            }}
            className="h-7 w-24 rounded border border-border bg-surface-primary px-1.5 text-right text-xs"
          />
          <button
            type="button"
            disabled={busy}
            onClick={commit}
            className="rounded bg-oe-blue px-1.5 py-0.5 text-2xs text-white"
          >
            {t('common.save', { defaultValue: 'Save' })}
          </button>
        </div>
      ) : (
        <button
          type="button"
          disabled={readOnly || busy}
          title={t('bid_management.plug_edit', { defaultValue: 'Override this plug' })}
          onClick={() => {
            setValue(amount != null ? String(amount) : '');
            setEditing(true);
          }}
          className="inline-flex items-center gap-1 tabular-nums"
        >
          {amount != null ? (
            <MoneyDisplay amount={amount} currency={currency} />
          ) : (
            <span className="text-content-tertiary">—</span>
          )}
          {!readOnly && <Pencil size={10} className="text-content-tertiary" />}
        </button>
      )}
      <div className="mt-0.5 flex items-center justify-end gap-1">
        <span
          data-testid="plug-source"
          className={clsx(
            'rounded px-1 text-2xs',
            plug.source === 'manual'
              ? 'bg-oe-blue/10 text-oe-blue'
              : plug.source === 'none'
                ? 'bg-red-100 text-red-700'
                : 'bg-amber-100 text-amber-800',
          )}
        >
          {t(key, { defaultValue: dflt })}
        </span>
        {plug.source === 'manual' && !readOnly && (
          <button
            type="button"
            disabled={busy}
            aria-label={t('bid_management.plug_clear', { defaultValue: 'Clear manual plug' })}
            title={t('bid_management.plug_clear', { defaultValue: 'Clear manual plug' })}
            onClick={() => onSave(null)}
            className="text-content-tertiary hover:text-red-600"
          >
            <X size={11} />
          </button>
        )}
      </div>
    </div>
  );
}

export function PlugTotalsRows({
  columns,
  rows,
  currency,
}: {
  columns: { id: string; name: string }[];
  rows: BidLevelingRow[];
  currency?: string;
}) {
  const { t } = useTranslation();
  const byBidder = new Map(rows.map((r) => [r.bidder_id, r] as const));
  const cellCls = 'px-3 py-1.5 text-right tabular-nums text-xs';
  const labelCell = 'px-3 py-1.5 sticky left-0 bg-surface-secondary text-xs text-content-secondary';
  return (
    <>
      <tr data-testid="total-without-plugs" className="border-t border-border-light bg-surface-secondary">
        <td className={labelCell}>
          {t('bid_management.total_without_plugs', { defaultValue: 'Total without plugs' })}
        </td>
        {columns.map((c) => {
          const r = byBidder.get(c.id);
          return (
            <td key={c.id} className={cellCls}>
              {r ? <MoneyDisplay amount={Number(r.raw_total) || 0} currency={currency} /> : '—'}
            </td>
          );
        })}
      </tr>
      <tr data-testid="total-with-plugs" className="bg-surface-secondary font-semibold">
        <td className={labelCell}>
          {t('bid_management.total_with_plugs', { defaultValue: 'Total with plugs' })}
        </td>
        {columns.map((c) => {
          const r = byBidder.get(c.id);
          return (
            <td key={c.id} className={cellCls}>
              {r ? (
                <MoneyDisplay
                  amount={Number(r.plugged_total ?? r.normalized_total) || 0}
                  currency={currency}
                />
              ) : (
                '—'
              )}
            </td>
          );
        })}
      </tr>
      <tr data-testid="gap-counts" className="bg-surface-secondary">
        <td className={labelCell}>
          {t('bid_management.gap_lines', { defaultValue: 'Gap lines (unpriced)' })}
        </td>
        {columns.map((c) => {
          const r = byBidder.get(c.id);
          return (
            <td key={c.id} className={cellCls}>
              {r ? `${r.gap_lines ?? 0} (${r.unpriced_gap_lines ?? 0})` : '—'}
            </td>
          );
        })}
      </tr>
    </>
  );
}

export function LevelingCheckBanner({ check }: { check?: LevelingCheck | null }) {
  const failed = (check?.results ?? []).filter((r) => !r.passed);
  if (failed.length === 0) return null;
  return (
    <div
      data-testid="leveling-check"
      className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200"
    >
      {failed.map((r) => (
        <div key={`${r.rule_id}-${r.element_ref ?? ''}`} className="flex items-start gap-2">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            {r.message}
            {r.suggestion ? ` ${r.suggestion}` : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

export function PackageTypeField({
  value,
  onChange,
  disabled,
  className,
}: {
  value: PackageType;
  onChange: (v: PackageType) => void;
  disabled?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const label = t('bid_management.package_type', { defaultValue: 'Package type' });
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-content-secondary">{label}</label>
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as PackageType)}
        className={className}
      >
        <option value="subcontract">
          {t('bid_management.package_type_subcontract', { defaultValue: 'Subcontract' })}
        </option>
        <option value="supply">
          {t('bid_management.package_type_supply', { defaultValue: 'Supply' })}
        </option>
      </select>
      <p data-testid="package-type-hint" className="mt-1 text-xs text-content-tertiary">
        {value === 'supply'
          ? t('bid_management.package_type_hint_supply', {
              defaultValue: 'Award creates a purchase order for the supplier, no subcontract.',
            })
          : t('bid_management.package_type_hint_subcontract', {
              defaultValue:
                'Award creates a subcontract agreement with its schedule of values (and the contract record), no purchase order.',
            })}
      </p>
    </div>
  );
}

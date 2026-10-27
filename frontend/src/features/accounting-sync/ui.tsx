// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Small presentational pieces shared by the accounting sync screens. */
import { useTranslation } from 'react-i18next';
import { formatCurrency } from '@/shared/lib/money';
import { Badge } from '@/shared/ui';
import { logStatusLabel, logStatusVariant } from './labels';

export const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
export const compactInputCls =
  'h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
export const warnInputCls =
  'h-8 w-full rounded-md border border-amber-400 bg-amber-50 px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-amber-300 dark:bg-amber-950/30';

export function Money({ value, currency }: { value: string | null | undefined; currency: string }) {
  if (value === null || value === undefined || value === '') return <span>—</span>;
  return <span className="tabular-nums">{formatCurrency(value, currency)}</span>;
}

export function StatusChip({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <Badge variant={logStatusVariant(status)} size="sm">
      {logStatusLabel(t, status)}
    </Badge>
  );
}

/** Labelled checkbox row used for the on/off settings. */
export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-start gap-2.5 text-sm">
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="font-medium text-content-primary">{label}</span>
        {hint && <span className="block text-2xs text-content-tertiary">{hint}</span>}
      </span>
    </label>
  );
}

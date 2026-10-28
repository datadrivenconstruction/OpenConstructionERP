// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { usePreferencesStore, useNumberLocale } from '../../stores/usePreferencesStore';
import { convertUnit, getDisplayUnit, isMetricUnit } from '../lib/unitConversion';

export interface QuantityDisplayProps {
  value: number | string | null | undefined;
  unit: string;
  precision?: number;
  className?: string;
}

/**
 * Locale-aware quantity display with automatic unit conversion.
 *
 * When the user prefers imperial and the source unit is metric (or vice versa),
 * the value is automatically converted and the unit label is updated.
 * Number formatting respects the user's locale preference.
 */
export function QuantityDisplay({
  value,
  unit,
  precision = 2,
  className,
}: QuantityDisplayProps) {
  // Selector-scoped reads — keep this component out of the re-render
  // path for unrelated preferences-store mutations (v4.3 audit).
  const measurementSystem = usePreferencesStore((s) => s.measurementSystem);
  // The shared resolver, so a quantity and the money beside it are written
  // with the same separators. See `useNumberLocale`.
  const numberLocale = useNumberLocale();

  if (value == null) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  const numericValue = typeof value === 'string' ? parseFloat(value) : value;

  if (Number.isNaN(numericValue)) {
    return <span className={clsx('text-content-tertiary', className)}>&mdash;</span>;
  }

  // Determine whether conversion is needed
  const sourceIsMetric = isMetricUnit(unit);
  const needsConversion =
    sourceIsMetric !== null &&
    ((sourceIsMetric && measurementSystem === 'imperial') ||
      (!sourceIsMetric && measurementSystem === 'metric'));

  let displayValue = numericValue;
  let displayUnit = getDisplayUnit(unit);

  if (needsConversion) {
    const result = convertUnit(numericValue, unit, measurementSystem);
    displayValue = result.value;
    displayUnit = result.displayUnit;
  }

  let formatted: string;
  try {
    formatted = new Intl.NumberFormat(numberLocale, {
      minimumFractionDigits: 0,
      maximumFractionDigits: precision,
    }).format(displayValue);
  } catch {
    formatted = displayValue.toFixed(precision);
  }

  return (
    <span className={className}>
      {formatted}
      {displayUnit && (
        <>
          {' '}
          <span className="text-content-tertiary">{displayUnit}</span>
        </>
      )}
    </span>
  );
}

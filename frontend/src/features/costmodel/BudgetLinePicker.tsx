// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Book a purchase-order line or a subcontract agreement to a budget line
 * (cost code x cost type). The commitment then counts on that line alone
 * instead of being shared over every cost type of the cost code.
 *
 * Options come from the cost-type grid, so the picker and the grid read one
 * source. Renders nothing while the project has no budget lines (nothing to
 * choose from). A user who may not change the link still sees the control,
 * disabled, with the reason as its tooltip and a visible line of text.
 */

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { costTypeGridKey, fetchCostTypeGrid } from './costTypeGridApi';

export interface BudgetLinePickerProps {
  projectId: string;
  /** Selected budget line, or null when the line is not booked to one. */
  value: string | null;
  onChange: (budgetLineId: string | null) => void;
  /** Line number within an order, for the accessible name. */
  line?: number;
  disabled?: boolean;
  /** Why the control is disabled; shown under it and as its tooltip. */
  disabledReason?: string;
  'data-testid'?: string;
}

export function BudgetLinePicker({
  projectId,
  value,
  onChange,
  line,
  disabled = false,
  disabledReason,
  'data-testid': testId,
}: BudgetLinePickerProps) {
  const { t } = useTranslation();

  const grid = useQuery({
    queryKey: costTypeGridKey(projectId),
    queryFn: () => fetchCostTypeGrid(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
    retry: false,
  });

  const typeLabels = useMemo<Record<string, string>>(
    () => ({
      labor: t('costmodel.cat_labor', { defaultValue: 'Labor' }),
      material: t('costmodel.cat_material', { defaultValue: 'Material' }),
      equipment: t('costmodel.cat_equipment', { defaultValue: 'Equipment' }),
      subcontractor: t('costmodel.cat_subcontractor', { defaultValue: 'Subcontractor' }),
      other: t('costmodel.cat_other', { defaultValue: 'Other' }),
    }),
    [t],
  );

  const options = useMemo(
    () =>
      (grid.data?.groups ?? []).flatMap((group) =>
        group.rows.map((row) => ({
          id: row.line_id,
          label: [row.cost_code || null, typeLabels[row.category] ?? row.category, row.description || null]
            .filter(Boolean)
            .join(' · '),
        })),
      ),
    [grid.data, typeLabels],
  );

  // A saved link must stay visible even while the grid is loading or fails.
  if (options.length === 0 && !value) return null;

  const label = t('costmodel.ctg_pick_label', { defaultValue: 'Budget line' });
  const ariaLabel =
    line !== undefined
    ? t('costmodel.ctg_pick_label_for', { defaultValue: 'Budget line for line {{line}}', line })
    : label;
  const listed = options.some((o) => o.id === value);

  return (
    <div className="flex flex-col gap-1">
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        aria-label={ariaLabel}
        data-testid={testId}
        className="oe-select"
      >
        <option value="">{t('costmodel.ctg_pick_none', { defaultValue: 'Not booked to a budget line' })}</option>
        {value && !listed && <option value={value}>{value}</option>}
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
      {disabled && disabledReason && (
        <p className="text-2xs leading-tight text-content-tertiary">{disabledReason}</p>
      )}
    </div>
  );
}

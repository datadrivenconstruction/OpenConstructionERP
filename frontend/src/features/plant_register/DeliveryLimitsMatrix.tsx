// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The delivery limit matrix: items down, delivery steps across, and in each
// cell the party that carries the step. An empty cell is a gap, shown in red
// rather than left blank, because a gap is what the matrix exists to find.

import { useTranslation } from 'react-i18next';
import { Grid3x3 } from 'lucide-react';
import clsx from 'clsx';

import { EmptyState } from '@/shared/ui/EmptyState';

import type { LimitMatrix, PlantCatalogue } from './api';
import { catalogueName, type LabelContext } from './labels';

export interface DeliveryLimitsMatrixProps {
  matrix: LimitMatrix;
  catalogue: PlantCatalogue;
  labels: LabelContext;
  onOpen: (itemId: string) => void;
}

export function DeliveryLimitsMatrix({ matrix, catalogue, labels, onOpen }: DeliveryLimitsMatrixProps) {
  const { t } = useTranslation();
  // The matrix is drawn for main components: they are the items several
  // parties touch between the factory and the handover.
  const rows = matrix.rows.filter((r) => r.item_class === 'main_component' || Object.keys(r.cells).length > 0);

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Grid3x3 size={28} />}
        title={t('plant.limits.empty_title', { defaultValue: 'No delivery limits yet' })}
        description={t('plant.limits.empty_body', {
          defaultValue:
            'Add main components to the register, then say on each one who supplies, offloads, sets, connects, tests and commissions it.',
        })}
      />
    );
  }

  return (
    <div className="space-y-2" data-testid="plant-limit-matrix">
      <p className="text-xs text-content-secondary">
        {t('plant.limits.matrix_hint', {
          defaultValue: 'One party per step. A red cell is a step nobody carries yet. Open an item to fill its row.',
        })}
      </p>
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[60rem] text-left text-xs">
          <thead className="bg-surface-secondary text-content-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">{t('plant.limits.item', { defaultValue: 'Item' })}</th>
              {matrix.steps.map((step) => (
                <th key={step} scope="col" className="px-2 py-2 font-medium">
                  {catalogueName(labels, catalogue, 'delivery_limit_steps', step)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {rows.map((row) => (
              <tr key={row.item_id} data-testid="limit-matrix-row">
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  <button type="button" className="font-mono text-oe-blue-text hover:underline" onClick={() => onOpen(row.item_id)}>
                    {row.code}
                  </button>
                  <span className="block max-w-[14rem] truncate text-content-secondary" title={row.title}>
                    {row.title}
                  </span>
                </th>
                {matrix.steps.map((step) => {
                  const cell = row.cells[step];
                  const filled = !!cell && (!!cell.party || !!cell.contract_package_id);
                  return (
                    <td
                      key={step}
                      data-testid="limit-matrix-cell"
                      data-gap={!filled || undefined}
                      className={clsx('px-2 py-2', filled ? 'text-content-primary' : 'bg-semantic-error-bg text-semantic-error')}
                    >
                      {cell?.party
                        ? catalogueName(labels, catalogue, 'parties', cell.party)
                        : cell?.contract_package_id
                          ? t('plant.limits.package', { defaultValue: 'Package' })
                          : t('plant.limits.gap', { defaultValue: 'Open' })}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

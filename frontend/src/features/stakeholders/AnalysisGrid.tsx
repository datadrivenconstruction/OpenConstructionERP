// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The analysis: where every stakeholder sits under one method. A method with
// two number scales is drawn as a square (the classic power and interest
// grid); any other method is shown as one group per class. Stakeholders
// nobody assessed under this method are listed apart, so the grid never
// suggests a position that was not given.

import { useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Grid3x3 } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';

import type { GridItem, GridResponse } from './api';
import { FIELD_CLASS } from './StakeholderBits';
import { useGrid } from './hooks';
import { itemName, nameOf } from './labels';
import { gridAxes } from './rules';
import { stakeholderName, type Screen } from './screen';

export interface AnalysisGridProps {
  screen: Screen;
  method: string;
  onMethod: (code: string) => void;
  onOpen: (stakeholderId: string) => void;
}

export function AnalysisGrid({ screen, method, onMethod, onOpen }: AnalysisGridProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels } = screen;
  const methods = settings.framework.analysis_methods;
  const gridQ = useGrid(projectId, method);

  const picker = methods.length > 1 && (
    <label className="flex items-center gap-2 text-sm text-content-secondary">
      {t('stakeholders.ui.assessment.method', { defaultValue: 'Analysis method' })}
      <select
        className={`${FIELD_CLASS} w-auto`}
        value={method}
        onChange={(e) => onMethod(e.target.value)}
        data-testid="grid-method"
      >
        {methods.map((m) => (
          <option key={m.code} value={m.code}>
            {itemName(labels, m)}
          </option>
        ))}
      </select>
    </label>
  );

  if (gridQ.isLoading) return <SkeletonTable rows={5} columns={5} />;
  if (gridQ.isError || !gridQ.data) {
    return (
      <ErrorState
        title={t('stakeholders.ui.grid.load_failed', { defaultValue: 'The analysis could not be loaded' })}
        hint={getErrorMessage(gridQ.error)}
        onRetry={() => gridQ.refetch()}
      />
    );
  }

  const grid = gridQ.data;
  const placed = grid.items.filter((i) => i.assessment_id);
  const unplaced = grid.items.filter((i) => !i.assessment_id);

  if (grid.items.length === 0) {
    return (
      <EmptyState
        icon={<Grid3x3 size={28} />}
        title={t('stakeholders.ui.grid.empty_title', { defaultValue: 'Nothing to analyse yet' })}
        description={t('stakeholders.ui.grid.empty_body', {
          defaultValue: 'Add stakeholders on the Register tab and assess them. Each one then appears here by how much they can affect the project.',
        })}
      />
    );
  }

  const chip = (item: GridItem) => (
    <button
      key={item.stakeholder_id}
      type="button"
      onClick={() => onOpen(item.stakeholder_id)}
      title={stakeholderName(t, item)}
      data-testid="grid-chip"
      className="max-w-full truncate rounded-full border border-border-light bg-surface-primary px-2 py-0.5 text-xs text-content-primary hover:border-oe-blue"
    >
      {stakeholderName(t, item)}
    </button>
  );

  return (
    <div className="space-y-4" data-testid="analysis-grid">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-content-secondary">
          {t('stakeholders.ui.grid.intro', {
            defaultValue: 'Each stakeholder sits where the latest assessment under this method put them.',
          })}
        </p>
        {picker}
      </div>

      {placed.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-secondary" data-testid="grid-none-placed">
          {t('stakeholders.ui.grid.none_placed', {
            defaultValue: 'Nobody is assessed under this method yet. Open a stakeholder and assess them.',
          })}
        </p>
      ) : gridAxes(grid) ? (
        <Square grid={grid} items={placed} screen={screen} chip={chip} />
      ) : (
        <ByClass grid={grid} items={placed} screen={screen} chip={chip} />
      )}

      {unplaced.length > 0 && (
        <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="grid-unplaced">
          <h3 className="text-xs font-semibold text-content-secondary">
            {t('stakeholders.ui.grid.unplaced', { defaultValue: 'Not assessed under this method' })}
          </h3>
          <div className="mt-2 flex flex-wrap gap-1.5">{unplaced.map(chip)}</div>
        </section>
      )}
    </div>
  );
}

interface ViewProps {
  grid: GridResponse;
  items: GridItem[];
  screen: Screen;
  chip: (item: GridItem) => ReactNode;
}

function Square({ grid, items, screen, chip }: ViewProps) {
  const { t } = useTranslation();
  const { labels } = screen;
  const axis = (name: string, value: number) =>
    t('stakeholders.ui.grid.axis', { defaultValue: '{{name}} {{value}}', name, value });
  const axes = gridAxes(grid)!;
  const xDim = grid.dimensions.find((d) => d.code === axes.x)!;
  const yDim = grid.dimensions.find((d) => d.code === axes.y)!;
  const xs = Array.from({ length: xDim.max - xDim.min + 1 }, (_, i) => xDim.min + i);
  const ys = Array.from({ length: yDim.max - yDim.min + 1 }, (_, i) => yDim.max - i);
  const byCell = useMemo(() => {
    const map = new Map<string, GridItem[]>();
    for (const item of items) {
      const key = `${item.position?.x}|${item.position?.y}`;
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return map;
  }, [items]);

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] table-fixed border-separate border-spacing-1" data-testid="grid-square">
        <caption className="sr-only">
          {t('stakeholders.ui.grid.caption', {
            defaultValue: '{{vertical}} against {{horizontal}}',
            vertical: itemName(labels, yDim),
            horizontal: itemName(labels, xDim),
          })}
        </caption>
        <tbody>
          {ys.map((y) => (
            <tr key={y}>
              <th scope="row" className="w-24 pr-2 text-right text-xs font-normal text-content-tertiary">
                {axis(itemName(labels, yDim), y)}
              </th>
              {xs.map((x) => {
                const here = byCell.get(`${x}|${y}`) ?? [];
                return (
                  <td
                    key={x}
                    data-testid="grid-cell"
                    data-x={x}
                    data-y={y}
                    className="h-16 rounded-md bg-surface-secondary p-1 align-top"
                  >
                    <div className="flex flex-wrap gap-1">{here.map(chip)}</div>
                  </td>
                );
              })}
            </tr>
          ))}
          <tr>
            <td />
            {xs.map((x) => (
              <th key={x} scope="col" className="pt-1 text-center text-xs font-normal text-content-tertiary">
                {axis(itemName(labels, xDim), x)}
              </th>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function ByClass({ grid, items, screen, chip }: ViewProps) {
  const { t } = useTranslation();
  const { labels } = screen;
  const codes = [...grid.classes.map((c) => c.code), ...new Set(items.map((i) => i.classification))].filter(
    (code, i, all) => all.indexOf(code) === i,
  );
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="grid-classes">
      {codes.map((code) => {
        const here = items.filter((i) => i.classification === code);
        return (
          <section key={code} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="grid-class">
            <h3 className="flex items-center justify-between text-sm font-medium text-content-primary">
              {code ? nameOf(labels, grid.classes, code) : t('stakeholders.ui.unclassified', { defaultValue: 'Unclassified' })}
              <span className="text-xs font-normal text-content-tertiary">{here.length}</span>
            </h3>
            <div className="mt-2 flex flex-wrap gap-1.5">{here.map(chip)}</div>
          </section>
        );
      })}
    </div>
  );
}

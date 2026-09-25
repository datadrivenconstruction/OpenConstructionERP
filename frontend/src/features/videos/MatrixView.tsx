// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The library as a coverage map: roles or countries down the side, the eight
// project stages across, and in each cell how many videos sit there. It shows
// at a glance where the academy is deep and where it has nothing yet, and a
// cell is a way in: it filters the list to that row and stage.
//
// It counts the videos the other filters leave, so the map answers the
// question the reader is already asking. A video for every role counts in
// every role's row, the way the role filter treats it.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ROLE_META } from '@/features/cases/roles';
import { STAGE_META } from '@/features/cases/stages';
import type { ProfessionalRole } from '@/features/cases/types';
import type { AcademyVideo } from './academyTypes';
import { catalogMarkets, coverage } from './academy';
import type { VideoLabels } from './videoLabels';

export type MatrixRows = 'roles' | 'markets';

/** The row key for videos that apply in any market. */
export const ANY_MARKET = 'universal';

const ROLE_IDS = ROLE_META.map((r) => r.id);
const STAGE_IDS = STAGE_META.map((s) => s.id);

export function roleRowsOf(video: AcademyVideo): readonly ProfessionalRole[] {
  return video.roles.length > 0 ? video.roles : ROLE_IDS;
}

export function marketRowsOf(video: AcademyVideo): readonly string[] {
  return [video.market ?? ANY_MARKET];
}

/** Five steps of blue, by share of the fullest cell; zero stays neutral. */
function heat(count: number, max: number): string {
  if (count === 0) return 'bg-surface-secondary/60 text-content-quaternary';
  const step = Math.min(4, Math.ceil((count / Math.max(1, max)) * 4));
  return [
    '',
    'bg-oe-blue/10 text-oe-blue',
    'bg-oe-blue/25 text-oe-blue',
    'bg-oe-blue/45 text-white dark:text-white',
    'bg-oe-blue/80 text-white',
  ][step]!;
}

export interface MatrixViewProps {
  videos: AcademyVideo[];
  rows: MatrixRows;
  onRowsChange: (rows: MatrixRows) => void;
  labels: VideoLabels;
  onPick: (row: string, stage: string) => void;
}

export function MatrixView({ videos, rows, onRowsChange, labels, onPick }: MatrixViewProps) {
  const { t } = useTranslation();
  const rowIds: string[] = useMemo(
    () => (rows === 'roles' ? [...ROLE_IDS] : [...catalogMarkets(), ANY_MARKET]),
    [rows],
  );
  const grid = useMemo(
    () =>
      rows === 'roles'
        ? coverage(ROLE_IDS, roleRowsOf, STAGE_IDS, videos)
        : coverage(rowIds, marketRowsOf, STAGE_IDS, videos),
    [rows, rowIds, videos],
  );
  let max = 0;
  for (const cells of grid.values()) for (const list of cells.values()) max = Math.max(max, list.length);

  const rowLabel = (id: string) =>
    rows === 'roles'
      ? labels.role(id as ProfessionalRole)
      : id === ANY_MARKET
        ? t('videos.market_any', { defaultValue: 'Any country' })
        : labels.country(id);

  return (
    <div data-testid="videos-matrix" className="space-y-2">
      <div role="group" aria-label={t('videos.matrix_rows', { defaultValue: 'Rows' })} className="flex gap-1 text-xs">
        {(['roles', 'markets'] as const).map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={rows === r}
            onClick={() => onRowsChange(r)}
            className={clsx(
              'rounded-full border px-3 py-1 font-medium transition-colors',
              rows === r
                ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                : 'border-border-light text-content-secondary hover:border-oe-blue/40',
            )}
          >
            {r === 'roles'
              ? t('videos.filter_role', { defaultValue: 'Role' })
              : t('videos.country', { defaultValue: 'Country' })}
          </button>
        ))}
      </div>
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <table className="w-full min-w-[40rem] border-separate border-spacing-1 text-xs">
          <caption className="sr-only">
            {t('videos.matrix_note', {
              defaultValue: 'How many videos cover each role or country at each project stage. Choose a cell to list them.',
            })}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="w-40" />
              {STAGE_META.map((s) => (
                <th key={s.id} scope="col" className="px-1 pb-1 text-center text-2xs font-medium text-content-tertiary">
                  <span className="block tabular-nums text-content-quaternary">{s.num}</span>
                  {labels.stageShort(s.id)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rowIds.map((row) => (
              <tr key={row}>
                <th scope="row" className="max-w-[10rem] truncate pr-2 text-left text-xs font-medium text-content-secondary">
                  {rowLabel(row)}
                </th>
                {STAGE_META.map((s) => {
                  const n = grid.get(row)?.get(s.id)?.length ?? 0;
                  const label = t('videos.matrix_cell', {
                    defaultValue: '{{row}}, {{stage}}: {{n}}',
                    row: rowLabel(row),
                    stage: labels.stage(s.id),
                    n,
                  });
                  return (
                    <td key={s.id} className="p-0">
                      <button
                        type="button"
                        disabled={n === 0}
                        onClick={() => onPick(row, s.id)}
                        aria-label={label}
                        title={label}
                        data-testid="videos-matrix-cell"
                        data-row={row}
                        data-stage={s.id}
                        className={clsx(
                          'flex h-9 w-full items-center justify-center rounded-md font-semibold tabular-nums transition-transform',
                          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue enabled:hover:scale-105',
                          heat(n, max),
                        )}
                      >
                        {n || '·'}
                      </button>
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

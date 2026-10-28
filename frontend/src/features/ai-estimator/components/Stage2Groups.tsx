// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Stage 2 - Group quantities (human-confirm checkpoint #2). AI-derived
// groups with summed canonical quantities, shown Takeoff-style: a summary
// strip + checkbox rows with inline quantity / unit / description edits and
// exclude. Multi-select drives merge (combine selected groups) and split
// (pull elements out of one group into a new one). No confidence here -
// these are quantities, not rates. Edits commit live via
// PATCH /runs/{id}/groups/{gid}; merge/split via their own endpoints.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Layers, Boxes, Merge, Split, Loader2 } from 'lucide-react';
import { Button, EmptyState } from '@/shared/ui';
import { SplitGroupDrawer } from './SplitGroupDrawer';
import { toNum } from '../helpers';
import type { GroupSummary, GroupUpdate } from '../api';

export interface Stage2GroupsProps {
  runId: string;
  groups: GroupSummary[];
  loading: boolean;
  /** Commit an edit to one group (live PATCH). */
  onEdit: (groupId: string, patch: GroupUpdate) => void;
  /** Merge the selected group ids into one. */
  onMerge: (groupIds: string[]) => void;
  merging: boolean;
  /** group id currently being saved (disables its inputs briefly). */
  savingId: string | null;
}

export function Stage2Groups({
  runId,
  groups,
  loading,
  onEdit,
  onMerge,
  merging,
  savingId,
}: Stage2GroupsProps) {
  const { t } = useTranslation();

  // Local draft values for the number/text inputs so typing is smooth;
  // commit happens on blur via onEdit.
  const [draftQty, setDraftQty] = useState<Record<string, string>>({});
  const [draftUnit, setDraftUnit] = useState<Record<string, string>>({});
  const [draftDesc, setDraftDesc] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [splitGroupId, setSplitGroupId] = useState<string | null>(null);

  const included = useMemo(() => groups.filter((g) => g.status !== 'skipped'), [groups]);

  const totalElements = useMemo(
    () => included.reduce((sum, g) => sum + g.element_count, 0),
    [included],
  );

  if (loading) {
    return (
      <div className="space-y-2.5">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-14 animate-pulse rounded-lg border border-border-light bg-surface-secondary"
          />
        ))}
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <EmptyState
        icon={<Layers className="h-6 w-6" />}
        title={t('aiest.groups.empty_title', { defaultValue: 'No groups yet' })}
        description={t('aiest.groups.empty_desc', {
          defaultValue:
            'The source produced no estimable groups. Go back and check the source, or add more detail.',
        })}
      />
    );
  }

  const allIncluded = included.length === groups.length;

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  /** Commit a quantity edit by writing it into the chosen-unit slot. The
   *  existing quantities may arrive as numbers or Decimal-strings; coerce the
   *  whole map to finite numbers so the PATCH body is always numeric and the
   *  edit never round-trips a NaN. */
  const commitQty = (g: GroupSummary) => {
    const raw = draftQty[g.id];
    if (raw == null || raw.trim() === '') return;
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    const unit = draftUnit[g.id] ?? g.chosen_unit ?? '_';
    const merged: Record<string, number> = {};
    for (const [k, v] of Object.entries(g.quantities)) merged[k] = toNum(v);
    merged[unit] = n;
    onEdit(g.id, { quantities: merged });
  };

  const commitUnit = (g: GroupSummary) => {
    const unit = draftUnit[g.id];
    if (unit == null || unit === (g.chosen_unit ?? '')) return;
    onEdit(g.id, { chosen_unit: unit });
  };

  const commitDesc = (g: GroupSummary) => {
    const desc = draftDesc[g.id];
    if (desc == null || desc === (g.description ?? '')) return;
    onEdit(g.id, { description: desc });
  };

  const doMerge = () => {
    if (selected.size < 2) return;
    onMerge([...selected]);
    setSelected(new Set());
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-content-secondary">
        {t('aiest.groups.help', {
          defaultValue:
            'These are the groups the agent derived, with quantities summed from your data. Edit a quantity, unit or label, exclude a group, or select several to merge. Split a group to pull elements into a new one.',
        })}
      </p>

      {/* Summary strip */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border-light bg-surface-secondary px-4 py-3">
          <div className="text-2xl font-semibold tabular-nums text-content-primary">
            {included.length}
          </div>
          <div className="text-xs text-content-secondary">
            {t('aiest.groups.included', { defaultValue: 'Groups included' })}
          </div>
        </div>
        <div className="rounded-lg border border-border-light bg-surface-secondary px-4 py-3">
          <div className="text-2xl font-semibold tabular-nums text-content-primary">
            {totalElements}
          </div>
          <div className="text-xs text-content-secondary">
            {t('aiest.groups.elements', { defaultValue: 'Elements covered' })}
          </div>
        </div>
        <div className="flex items-center justify-end">
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              groups.forEach((g) =>
                onEdit(g.id, { status: allIncluded ? 'skipped' : 'unmatched' }),
              )
            }
          >
            {allIncluded
              ? t('aiest.groups.exclude_all', { defaultValue: 'Exclude all' })
              : t('aiest.groups.include_all', { defaultValue: 'Include all' })}
          </Button>
        </div>
      </div>

      {/* Selection toolbar */}
      <div className="flex flex-wrap items-center gap-2" aria-live="polite">
        <span className="text-xs text-content-secondary">
          {selected.size > 0
            ? t('aiest.groups.selected_n', {
                defaultValue: '{{n}} selected',
                n: selected.size,
              })
            : t('aiest.groups.select_hint', {
                defaultValue: 'Select groups to merge',
              })}
        </span>
        <Button
          variant="secondary"
          size="sm"
          icon={merging ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Merge className="h-3.5 w-3.5" />}
          disabled={selected.size < 2 || merging}
          onClick={doMerge}
        >
          {t('aiest.groups.merge', { defaultValue: 'Merge selected' })}
        </Button>
        {selected.size > 0 && (
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
            {t('aiest.groups.clear_selection', { defaultValue: 'Clear' })}
          </Button>
        )}
      </div>

      {/* Group rows */}
      <div className="overflow-hidden rounded-lg border border-border-light">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-content-secondary">
            <tr>
              <th className="w-10 px-3 py-2" />
              <th className="w-10 px-3 py-2" />
              <th className="px-3 py-2 text-left font-medium">
                {t('aiest.groups.group', { defaultValue: 'Group' })}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('aiest.groups.quantity', { defaultValue: 'Quantity' })}
              </th>
              <th className="px-3 py-2 text-left font-medium">
                {t('aiest.groups.unit', { defaultValue: 'Unit' })}
              </th>
              <th className="w-12 px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const excluded = g.status === 'skipped';
              const qtyVal = draftQty[g.id] ?? String(toNum(g.primary_quantity));
              const unitVal = draftUnit[g.id] ?? g.chosen_unit ?? '';
              const descVal = draftDesc[g.id] ?? g.description ?? g.group_key;
              const saving = savingId === g.id;
              return (
                <tr
                  key={g.id}
                  className={clsx('border-t border-border-light/60', excluded && 'opacity-50')}
                >
                  {/* Merge select */}
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={selected.has(g.id)}
                      onChange={() => toggleSelect(g.id)}
                      className="accent-oe-blue"
                      aria-label={t('aiest.groups.select', { defaultValue: 'Select for merge' })}
                    />
                  </td>
                  {/* Include toggle */}
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={!excluded}
                      onChange={() =>
                        onEdit(g.id, { status: excluded ? 'unmatched' : 'skipped' })
                      }
                      className="accent-emerald-500"
                      aria-label={t('aiest.groups.toggle', { defaultValue: 'Include group' })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Boxes className="h-4 w-4 shrink-0 text-content-tertiary" />
                      <div className="min-w-0 flex-1">
                        <input
                          type="text"
                          value={descVal}
                          disabled={excluded || saving}
                          onChange={(e) =>
                            setDraftDesc((p) => ({ ...p, [g.id]: e.target.value }))
                          }
                          onBlur={() => commitDesc(g)}
                          className="w-full truncate rounded border border-transparent bg-transparent px-1 py-0.5 font-medium text-content-primary hover:border-border-light focus:border-oe-blue focus:bg-surface-elevated focus:outline-none disabled:opacity-50"
                          aria-label={t('aiest.groups.label', { defaultValue: 'Group label' })}
                        />
                        <div className="px-1 text-xs text-content-tertiary">
                          {t('aiest.groups.element_count', {
                            defaultValue: '{{n}} elements',
                            n: g.element_count,
                          })}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <input
                      type="number"
                      value={qtyVal}
                      disabled={excluded || saving}
                      onChange={(e) =>
                        setDraftQty((p) => ({ ...p, [g.id]: e.target.value }))
                      }
                      onBlur={() => commitQty(g)}
                      className="w-28 rounded border border-border-light bg-surface-elevated px-2 py-1 text-right text-sm tabular-nums disabled:opacity-50"
                      aria-label={t('aiest.groups.quantity', { defaultValue: 'Quantity' })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="text"
                      value={unitVal}
                      disabled={excluded || saving}
                      onChange={(e) =>
                        setDraftUnit((p) => ({ ...p, [g.id]: e.target.value }))
                      }
                      onBlur={() => commitUnit(g)}
                      className="w-20 rounded border border-border-light bg-surface-elevated px-2 py-1 text-sm disabled:opacity-50"
                      aria-label={t('aiest.groups.unit', { defaultValue: 'Unit' })}
                    />
                  </td>
                  <td className="px-3 py-2 text-center">
                    {g.element_count > 1 && !excluded && (
                      <button
                        type="button"
                        onClick={() => setSplitGroupId(g.id)}
                        className="inline-flex items-center justify-center rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue"
                        title={t('aiest.groups.split', { defaultValue: 'Split group' })}
                        aria-label={t('aiest.groups.split', { defaultValue: 'Split group' })}
                      >
                        <Split className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {splitGroupId && (
        <SplitGroupDrawer
          runId={runId}
          groupId={splitGroupId}
          open
          onClose={() => setSplitGroupId(null)}
        />
      )}
    </div>
  );
}

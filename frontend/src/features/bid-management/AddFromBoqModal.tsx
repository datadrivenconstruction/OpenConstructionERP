// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Add scope lines to a bid package straight from the project's bill.
 *
 * Each line keeps the bill position it came from. The award carries that link
 * onto the contract line, where the progress bridge bills against it, so the
 * contract, the bid and the estimate all talk about the same position.
 *
 * Section headers are not offered: they carry no quantity to price. Positions
 * already in the package are shown as added and cannot be picked again; the
 * server skips them too, so a second click never doubles a line.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ListPlus, Search } from 'lucide-react';

import { Button, WideModal } from '@/shared/ui';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';

import { addLinesFromBoq } from './api';

interface BoqOption {
  id: string;
  name: string;
}

export interface BoqPositionRow {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number | string;
  unit_rate?: number | string;
}

/** Same rule as the server's `_is_section`: no unit and nothing to price. */
export function isSectionRow(p: BoqPositionRow): boolean {
  const unit = (p.unit || '').trim().toLowerCase();
  return (unit === '' || unit === 'section') && !Number(p.quantity) && !Number(p.unit_rate ?? 0);
}

export function AddFromBoqModal({
  packageId,
  projectId,
  linkedPositionIds,
  onClose,
}: {
  packageId: string;
  projectId: string;
  linkedPositionIds: string[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [boqId, setBoqId] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const boqsQ = useQuery({
    queryKey: ['bid-management', 'boq-options', projectId],
    queryFn: () => apiGet<BoqOption[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    enabled: !!projectId,
  });
  const activeBoqId = boqId || boqsQ.data?.[0]?.id || '';

  const positionsQ = useQuery({
    queryKey: ['bid-management', 'boq-positions', activeBoqId],
    queryFn: () => apiGet<{ positions?: BoqPositionRow[] }>(`/v1/boq/boqs/${activeBoqId}`),
    enabled: !!activeBoqId,
  });

  const linked = useMemo(() => new Set(linkedPositionIds), [linkedPositionIds]);
  const rows = useMemo(() => {
    const all = (positionsQ.data?.positions ?? []).filter((p) => !isSectionRow(p));
    const s = search.trim().toLowerCase();
    if (!s) return all;
    return all.filter(
      (p) => p.ordinal.toLowerCase().includes(s) || p.description.toLowerCase().includes(s),
    );
  }, [positionsQ.data, search]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const addMut = useMutation({
    mutationFn: () => addLinesFromBoq(packageId, [...selected]),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['bid-management', 'lines', packageId] });
      qc.invalidateQueries({ queryKey: ['bid-management', 'leveling-matrix', packageId] });
      addToast({
        type: 'success',
        title: t('bid_management.boq_lines_added', {
          defaultValue: 'Scope lines added from the BOQ: {{n}}',
          n: created.length,
        }),
      });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bid_management.add_from_boq_title', { defaultValue: 'Add scope lines from the BOQ' })}
      subtitle={t('bid_management.add_from_boq_subtitle', {
        defaultValue:
          'Each line keeps its bill position, and the contract drafted on award bills against the same position.',
      })}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            icon={<ListPlus size={14} />}
            disabled={selected.size === 0}
            loading={addMut.isPending}
            onClick={() => addMut.mutate()}
          >
            {t('bid_management.add_selected_lines', {
              defaultValue: 'Add selected ({{n}})',
              n: selected.size,
            })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {(boqsQ.data?.length ?? 0) > 1 && (
          <select
            value={activeBoqId}
            onChange={(e) => {
              setBoqId(e.target.value);
              setSelected(new Set());
            }}
            aria-label={t('bid_management.boq_select', { defaultValue: 'Bill of quantities' })}
            className="w-full rounded border border-border-light px-2 py-1 text-sm"
          >
            {(boqsQ.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        )}
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('bid_management.boq_search', { defaultValue: 'Search positions' })}
            className="w-full rounded border border-border-light py-1 pl-8 pr-2 text-sm"
          />
        </div>
        {boqsQ.isSuccess && (boqsQ.data?.length ?? 0) === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('bid_management.no_boq', { defaultValue: 'This project has no BOQ yet.' })}
          </p>
        ) : positionsQ.isLoading || boqsQ.isLoading ? (
          <p className="text-xs text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        ) : rows.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('bid_management.no_boq_positions', { defaultValue: 'No positions to add.' })}
          </p>
        ) : (
          <ul className="max-h-[50vh] space-y-1 overflow-y-auto text-xs">
            {rows.map((p) => {
              const already = linked.has(p.id);
              return (
                <li key={p.id}>
                  <label className="flex items-center gap-2 border-b border-border-light py-1">
                    <input
                      type="checkbox"
                      checked={already || selected.has(p.id)}
                      disabled={already}
                      onChange={() => toggle(p.id)}
                    />
                    <span className="w-20 shrink-0 font-mono">{p.ordinal}</span>
                    <span className="min-w-0 flex-1 truncate">{p.description}</span>
                    <span className="tabular-nums text-content-secondary">
                      {Number(p.quantity).toLocaleString(getNumberLocale())} {p.unit}
                    </span>
                    {already && (
                      <span className="text-content-tertiary">
                        {t('bid_management.boq_already_added', { defaultValue: 'added' })}
                      </span>
                    )}
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </WideModal>
  );
}

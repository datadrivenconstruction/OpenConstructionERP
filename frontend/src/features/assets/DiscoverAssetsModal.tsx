// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Discover-assets modal.
 *
 * The Asset Register starts empty: assets only appear once a human flags a
 * BIM element, one at a time, in the 3D viewer. For a real model with
 * thousands of elements that is unworkable. This modal asks the backend to
 * rank every element by how likely it is to be a managed asset (pumps,
 * AHUs, electrical gear) and lets the user bulk-promote the real ones.
 *
 * Promotion writes the suggested manufacturer / model / tag through the
 * existing BIM Hub ``PATCH /asset-info`` endpoint (which auto-flips
 * ``is_tracked_asset``), so no new write path is introduced.
 *
 * AI-suggests / human-confirms: nothing is auto-promoted; the user picks.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Loader2, Sparkles, X } from 'lucide-react';

import { Badge, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { updateElementAssetInfo } from '@/features/bim/api';

import { discoverAssets, type DiscoveryCandidate } from './api';

interface DiscoverAssetsModalProps {
  projectId: string;
  onClose: () => void;
  onPromoted: (count: number) => void;
}

function scoreTone(score: number): string {
  if (score >= 70) return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
  if (score >= 50) return 'bg-sky-500/15 text-sky-300 border-sky-500/30';
  return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
}

export function DiscoverAssetsModal({ projectId, onClose, onPromoted }: DiscoverAssetsModalProps) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const query = useQuery({
    queryKey: ['asset-discovery', projectId],
    queryFn: () => discoverAssets(projectId, { threshold: 35 }),
    enabled: !!projectId,
    refetchOnWindowFocus: false,
  });

  const candidates = query.data?.items ?? [];

  const allSelected = useMemo(
    () => candidates.length > 0 && selected.size === candidates.length,
    [candidates.length, selected.size],
  );

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(candidates.map((c) => c.id)));
  };

  const promote = useMutation({
    mutationFn: async () => {
      const picked = candidates.filter((c) => selected.has(c.id));
      let ok = 0;
      const errors: string[] = [];
      // Sequential to avoid hammering the BIM Hub with a burst of writes;
      // promotion sets is_tracked_asset=true via the merge endpoint.
      for (const c of picked) {
        try {
          const info: Record<string, string> = { ...c.suggested_asset_info };
          // Default newly-discovered assets to operational so they land in
          // the register with a sensible status the user can refine.
          if (!info.operational_status) info.operational_status = 'operational';
          await updateElementAssetInfo(c.id, info, true);
          ok += 1;
        } catch (err) {
          errors.push(err instanceof Error ? err.message : String(err));
        }
      }
      return { ok, failed: picked.length - ok, errors };
    },
    onSuccess: ({ ok, failed }) => {
      queryClient.invalidateQueries({ queryKey: ['bim-assets'] });
      queryClient.invalidateQueries({ queryKey: ['asset-portfolio', projectId] });
      queryClient.invalidateQueries({ queryKey: ['asset-ops-list'] });
      if (ok > 0) {
        toast({
          type: 'success',
          title: t('assets.discover.promoted', {
            defaultValue: '{{count}} assets added to the register',
            count: ok,
          }),
        });
      }
      if (failed > 0) {
        toast({
          type: 'error',
          title: t('assets.discover.promote_partial', {
            defaultValue: '{{count}} could not be added',
            count: failed,
          }),
        });
      }
      onPromoted(ok);
    },
    onError: (err: unknown) => {
      toast({
        type: 'error',
        title: t('assets.discover.promote_failed', { defaultValue: 'Promotion failed' }),
        message: err instanceof Error ? err.message : undefined,
      });
    },
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="discover-assets-title"
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-border-light bg-surface-primary shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="discover-assets-modal"
      >
        <div className="flex items-center justify-between border-b border-border-light px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-oe-blue" />
            <h2 id="discover-assets-title" className="font-medium text-content-primary">
              {t('assets.discover.title', { defaultValue: 'Discover assets from BIM' })}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>

        <div className="border-b border-border-light px-4 py-2 text-xs text-content-secondary">
          {t('assets.discover.subtitle', {
            defaultValue:
              'We ranked BIM elements that look like managed assets (equipment with manufacturers, serials, warranties). Pick the real ones to add them to the register.',
          })}
          {query.data && (
            <span className="ml-1 text-content-tertiary">
              {t('assets.discover.scan_stats', {
                defaultValue:
                  'Scanned {{scanned}} elements across {{models}} models, {{tracked}} already tracked.',
                scanned: query.data.scanned_elements,
                models: query.data.models_scanned,
                tracked: query.data.already_tracked,
              })}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-auto">
          {query.isLoading ? (
            <div className="flex items-center gap-2 p-6 text-sm text-content-secondary">
              <Loader2 size={14} className="animate-spin" />
              {t('assets.discover.scanning', { defaultValue: 'Scanning BIM models…' })}
            </div>
          ) : query.isError ? (
            <p className="p-6 text-sm text-rose-400">
              {t('assets.discover.error', {
                defaultValue: 'Could not scan for assets. The Asset Operations module may be off.',
              })}
            </p>
          ) : candidates.length === 0 ? (
            <p className="p-6 text-sm italic text-content-tertiary">
              {t('assets.discover.empty', {
                defaultValue:
                  'No likely assets found. Upload a BIM model with equipment, or flag elements manually in the 3D viewer.',
              })}
            </p>
          ) : (
            <table className="w-full text-sm" data-testid="discover-table">
              <thead className="sticky top-0 z-10 bg-surface-primary text-xs uppercase tracking-wider text-content-tertiary">
                <tr>
                  <th className="w-10 px-3 py-2 text-left">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      aria-label={t('assets.discover.select_all', { defaultValue: 'Select all' })}
                      data-testid="discover-select-all"
                    />
                  </th>
                  <th className="px-3 py-2 text-left">{t('assets.col.element', { defaultValue: 'Element' })}</th>
                  <th className="px-3 py-2 text-left">{t('assets.discover.col_why', { defaultValue: 'Why' })}</th>
                  <th className="px-3 py-2 text-right">{t('assets.discover.col_score', { defaultValue: 'Score' })}</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c: DiscoveryCandidate) => (
                  <tr
                    key={c.id}
                    className="cursor-pointer border-t border-border-light hover:bg-surface-secondary"
                    onClick={() => toggle(c.id)}
                    data-testid={`discover-row-${c.stable_id}`}
                  >
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(c.id)}
                        onChange={() => toggle(c.id)}
                        aria-label={c.name || c.stable_id}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-content-primary">{c.name || c.element_type}</div>
                      <div className="text-xs text-content-tertiary">
                        {c.stable_id}
                        {c.storey ? ` · ${c.storey}` : ''} · {c.model_name}
                      </div>
                      {Object.keys(c.suggested_asset_info).length > 0 && (
                        <div className="mt-0.5 text-[11px] text-content-secondary">
                          {Object.entries(c.suggested_asset_info)
                            .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
                            .join(' · ')}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {c.reasons.slice(0, 3).map((r) => (
                          <span
                            key={r}
                            className="rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-[10px] text-content-tertiary"
                          >
                            {r.split(':').slice(-1)[0]}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className={`inline-block rounded-md border px-2 py-0.5 text-xs ${scoreTone(c.score)}`}>
                        {c.score}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border-light px-4 py-3">
          <span className="text-xs text-content-tertiary">
            {selected.size > 0 && (
              <Badge variant="neutral">
                {t('assets.discover.selected', {
                  defaultValue: '{{count}} selected',
                  count: selected.size,
                })}
              </Badge>
            )}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              onClick={() => promote.mutate()}
              disabled={selected.size === 0 || promote.isPending}
              data-testid="discover-promote"
            >
              {promote.isPending ? (
                <Loader2 size={14} className="mr-1 animate-spin" />
              ) : (
                <CheckCircle2 size={14} className="mr-1" />
              )}
              {t('assets.discover.promote', {
                defaultValue: 'Add {{count}} to register',
                count: selected.size,
              })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default DiscoverAssetsModal;

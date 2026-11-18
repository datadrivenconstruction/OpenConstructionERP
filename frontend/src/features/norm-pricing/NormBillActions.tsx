// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project's graded labour rates applied to one bill, and the bill as the
// market's estimate sheet. Writing rates is preview first: the server proposes,
// the person unticks what should stay, and only the ticked rows are written,
// each re-derived on the server and refused if the preview went stale.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Eye } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { boqApi } from '@/features/boq/api';
import { normPricingApi, rateDerivation, type PricingProfile, type WritebackPreview } from './api';

const rowKey = (positionId: string, index: number) => `${positionId}#${index}`;

export function NormBillActions({ projectId, profile }: { projectId: string; profile: PricingProfile }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [boqId, setBoqId] = useState('');
  const [preview, setPreview] = useState<WritebackPreview | null>(null);
  const [unticked, setUnticked] = useState<Set<string>>(() => new Set());

  const boqsQuery = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => boqApi.list(projectId),
    staleTime: 60_000,
  });
  const boqs = boqsQuery.data ?? [];
  const canPreview = Boolean(profile.base_grade && profile.settings.estimate_wage);

  const previewMut = useMutation({
    mutationFn: () => normPricingApi.writebackPreview(projectId, boqId),
    onSuccess: (next) => {
      setPreview(next);
      setUnticked(new Set());
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const chosen = useMemo(
    () => (preview?.changes ?? []).filter((c) => !unticked.has(rowKey(c.position_id, c.resource_index))),
    [preview, unticked],
  );

  const applyMut = useMutation({
    mutationFn: () =>
      normPricingApi.writebackApply(
        projectId,
        boqId,
        chosen.map((c) => ({ position_id: c.position_id, resource_index: c.resource_index, rate: c.proposed_rate })),
      ),
    onSuccess: (res) => {
      setPreview(null);
      queryClient.invalidateQueries({ queryKey: ['boq'] });
      addToast({
        type: 'success',
        title: t('normPricing.applied', {
          defaultValue: 'Lines updated: {{count}}',
          count: res.updated_positions,
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const exportMut = useMutation({
    mutationFn: () => normPricingApi.exportSheet(projectId, boqId, i18n.language),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!canPreview && !profile.has_export_layout) return null;

  const toggle = (key: string) =>
    setUnticked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="mt-6 border-t border-border-light pt-4" data-testid="norm-bill-actions">
      <h4 className="text-sm font-medium text-content-primary">
        {t('normPricing.bill_title', { defaultValue: 'Apply to a bill' })}
      </h4>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-boq" className="oe-label">
            {t('normPricing.bill_pick', { defaultValue: 'Bill' })}
          </label>
          <select
            id="np-boq"
            value={boqId}
            onChange={(e) => {
              setBoqId(e.target.value);
              setPreview(null);
            }}
            className="oe-input w-72"
          >
            <option value="">{t('normPricing.bill_none', { defaultValue: 'Choose a bill' })}</option>
            {boqs.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        {canPreview && (
          <Button
            variant="secondary"
            size="sm"
            icon={<Eye size={14} />}
            disabled={!boqId}
            loading={previewMut.isPending}
            onClick={() => previewMut.mutate()}
          >
            {t('normPricing.preview', { defaultValue: 'Preview labour rates' })}
          </Button>
        )}
        {profile.has_export_layout && (
          <Button
            variant="secondary"
            size="sm"
            icon={<Download size={14} />}
            disabled={!boqId}
            loading={exportMut.isPending}
            onClick={() => exportMut.mutate()}
          >
            {t('normPricing.export', { defaultValue: 'Export estimate sheet (Excel)' })}
          </Button>
        )}
      </div>

      {preview && (
        <div className="mt-3" data-testid="norm-writeback-preview">
          {preview.changes.length === 0 ? (
            <p className="text-xs text-content-tertiary">
              {t('normPricing.preview_empty', { defaultValue: 'Every graded labour rate in this bill already matches.' })}
            </p>
          ) : (
            <>
              <p className="text-xs text-content-tertiary md:max-w-xl">
                {t('normPricing.preview_hint', {
                  defaultValue: 'Nothing changes until you apply. Untick a row to keep its current rate.',
                })}
              </p>
              <table className="mt-2 text-sm">
                <thead>
                  <tr className="text-left text-xs text-content-secondary">
                    <th className="pr-3" />
                    <th className="pr-4 font-medium">{t('normPricing.col_position', { defaultValue: 'Pos.' })}</th>
                    <th className="pr-4 font-medium">{t('normPricing.col_resource', { defaultValue: 'Resource' })}</th>
                    <th className="pr-4 font-medium">{t('normPricing.grade', { defaultValue: 'Grade' })}</th>
                    <th className="pr-4 font-medium">{t('normPricing.col_current', { defaultValue: 'Current rate' })}</th>
                    <th className="font-medium">{t('normPricing.col_new', { defaultValue: 'New rate' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.changes.map((c) => {
                    const key = rowKey(c.position_id, c.resource_index);
                    return (
                      <tr key={key} title={rateDerivation(c.derivation, preview)}>
                        <td className="pr-3">
                          <input
                            type="checkbox"
                            aria-label={`${c.ordinal} ${c.resource_name}`}
                            checked={!unticked.has(key)}
                            onChange={() => toggle(key)}
                          />
                        </td>
                        <td className="pr-4 tabular-nums">{c.ordinal}</td>
                        <td className="pr-4">{c.resource_name}</td>
                        <td className="pr-4 tabular-nums">{c.grade}</td>
                        <td className="pr-4 tabular-nums text-content-tertiary">{c.current_rate ?? '-'}</td>
                        <td className="tabular-nums font-medium">{c.proposed_rate}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="mt-2">
                <Button
                  variant="primary"
                  size="sm"
                  disabled={chosen.length === 0}
                  loading={applyMut.isPending}
                  onClick={() => applyMut.mutate()}
                >
                  {t('normPricing.apply', { defaultValue: 'Apply rates: {{count}}', count: chosen.length })}
                </Button>
              </div>
            </>
          )}
          {preview.skipped.length > 0 && (
            <p className="mt-2 text-xs text-content-tertiary">
              {t('normPricing.skipped', {
                defaultValue: 'Labour rows left out (no grade, or a grade off the scale): {{count}}',
                count: preview.skipped.length,
              })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

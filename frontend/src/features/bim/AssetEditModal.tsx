/**
 * Reusable asset-info edit modal.
 *
 * Extracted from ``AssetsPage`` so the BIM viewer can open the same
 * editor for a selected element without duplicating the form. Accepts
 * an ``AssetSummary`` (shape identical to what the list endpoint
 * returns) and patches it via the ``PATCH /asset-info`` endpoint.
 *
 * After a successful save:
 *   * ``['bim-assets']`` and ``['bim-asset-single', elementId]`` queries
 *     are invalidated so the Asset Register list and the in-viewer card
 *     refresh.
 *   * ``onSaved`` is called so the parent can close the modal and
 *     show its own success toast.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';

import { Button, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { updateElementAssetInfo, type AssetInfoPayload, type AssetSummary } from './api';

/** Operational-status vocabulary shared with ``AssetsPage`` filter chips. */
export const OPERATIONAL_STATUS_OPTIONS = [
  'operational',
  'under_maintenance',
  'decommissioned',
  'planned',
] as const;

export interface AssetEditModalProps {
  asset: AssetSummary;
  onClose: () => void;
  onSaved: (updated: AssetSummary) => void;
}

export function AssetEditModal({ asset, onClose, onSaved }: AssetEditModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToastStore((s) => s.addToast);

  const [form, setForm] = useState<AssetInfoPayload>({ ...asset.asset_info });

  useEffect(() => {
    setForm({ ...asset.asset_info });
  }, [asset.id, asset.asset_info]);

  const mutation = useMutation({
    mutationFn: (payload: AssetInfoPayload) => updateElementAssetInfo(asset.id, payload),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['bim-assets'] });
      queryClient.invalidateQueries({ queryKey: ['bim-asset-single', asset.id] });
      onSaved(updated);
    },
    onError: (err: unknown) => {
      toast({
        type: 'error',
        title: t('assets.save_failed', { defaultValue: 'Could not save asset info' }),
        message: err instanceof Error ? err.message : undefined,
      });
    },
  });

  const patch = useCallback((key: keyof AssetInfoPayload, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const submit = () => {
    // Convert empty strings to null so the backend clears keys that
    // were previously non-empty but the user just wiped out.
    const payload: AssetInfoPayload = {};
    for (const [key, value] of Object.entries(form)) {
      payload[key] = value === '' ? null : value;
    }
    mutation.mutate(payload);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-lg border border-neutral-700 bg-neutral-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="asset-edit-modal"
      >
        <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-neutral-500">
              {t('assets.edit.element', { defaultValue: 'Element' })}
            </div>
            <div className="font-medium text-neutral-100">{asset.name || asset.element_type}</div>
            <div className="font-mono text-xs text-neutral-500">{asset.stable_id}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
          <ModalField
            label={t('assets.field.manufacturer', { defaultValue: 'Manufacturer' })}
            value={form.manufacturer ?? ''}
            onChange={(v) => patch('manufacturer', v)}
            testId="asset-field-manufacturer"
          />
          <ModalField
            label={t('assets.field.model', { defaultValue: 'Model' })}
            value={form.model ?? ''}
            onChange={(v) => patch('model', v)}
            testId="asset-field-model"
          />
          <ModalField
            label={t('assets.field.serial', { defaultValue: 'Serial number' })}
            value={form.serial_number ?? ''}
            onChange={(v) => patch('serial_number', v)}
            testId="asset-field-serial"
          />
          <ModalField
            label={t('assets.field.installation_date', { defaultValue: 'Installation date' })}
            value={form.installation_date ?? ''}
            onChange={(v) => patch('installation_date', v)}
            type="date"
            testId="asset-field-install-date"
          />
          <ModalField
            label={t('assets.field.warranty_until', { defaultValue: 'Warranty until' })}
            value={form.warranty_until ?? ''}
            onChange={(v) => patch('warranty_until', v)}
            type="date"
            testId="asset-field-warranty"
          />
          <div className="flex flex-col gap-1">
            <label className="text-xs text-neutral-400">
              {t('assets.field.operational_status', { defaultValue: 'Operational status' })}
            </label>
            <select
              value={form.operational_status ?? ''}
              onChange={(e) => patch('operational_status', e.target.value)}
              className="rounded-md border border-neutral-700 bg-neutral-800 px-2 py-1 text-sm text-neutral-100 focus:border-primary-500 focus:outline-none"
              data-testid="asset-field-status"
            >
              <option value="">—</option>
              {OPERATIONAL_STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s.replace('_', ' ')}
                </option>
              ))}
            </select>
          </div>
          <ModalField
            label={t('assets.field.parent_system', { defaultValue: 'Parent system' })}
            value={form.parent_system ?? ''}
            onChange={(v) => patch('parent_system', v)}
            testId="asset-field-parent-system"
            className="sm:col-span-2"
          />
          <div className="flex flex-col gap-1 sm:col-span-2">
            <label className="text-xs text-neutral-400">
              {t('assets.field.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes ?? ''}
              onChange={(e) => patch('notes', e.target.value)}
              rows={3}
              className="rounded-md border border-neutral-700 bg-neutral-800 px-2 py-1 text-sm text-neutral-100 focus:border-primary-500 focus:outline-none"
              data-testid="asset-field-notes"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-neutral-800 px-4 py-3">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={submit} disabled={mutation.isPending} data-testid="asset-save">
            {mutation.isPending
              ? t('common.saving', { defaultValue: 'Saving…' })
              : t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

interface ModalFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  testId?: string;
  className?: string;
}

function ModalField({ label, value, onChange, type = 'text', testId, className }: ModalFieldProps) {
  return (
    <div className={`flex flex-col gap-1 ${className ?? ''}`}>
      <label className="text-xs text-neutral-400">{label}</label>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type}
        data-testid={testId}
      />
    </div>
  );
}

export default AssetEditModal;

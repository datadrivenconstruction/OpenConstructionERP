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
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, X } from 'lucide-react';

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

/** Keys that get a dedicated input in the form; everything else renders
 *  as a user-defined custom field. */
const BUILTIN_KEYS = new Set([
  'manufacturer',
  'model',
  'serial_number',
  'installation_date',
  'warranty_until',
  'operational_status',
  'parent_system',
  'notes',
]);

const CUSTOM_FIELD_SUGGESTIONS_KEY = 'oe_bim_asset_custom_fields';

function readCustomFieldSuggestions(): string[] {
  try {
    const raw = localStorage.getItem(CUSTOM_FIELD_SUGGESTIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((s): s is string => typeof s === 'string')
      : [];
  } catch {
    return [];
  }
}

function writeCustomFieldSuggestions(keys: string[]): void {
  try {
    // Dedup + keep last 50 to cap storage growth.
    const uniq = Array.from(new Set(keys.filter(Boolean))).slice(-50);
    localStorage.setItem(CUSTOM_FIELD_SUGGESTIONS_KEY, JSON.stringify(uniq));
  } catch {
    /* ignore quota errors */
  }
}

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
  const [suggestions, setSuggestions] = useState<string[]>(() => readCustomFieldSuggestions());
  const [newFieldKey, setNewFieldKey] = useState('');

  useEffect(() => {
    setForm({ ...asset.asset_info });
  }, [asset.id, asset.asset_info]);

  /** Custom field keys are every non-builtin key on the element's
   *  asset_info plus any suggestions the user has previously saved. */
  const customKeys = useMemo(() => {
    const fromPayload = Object.keys(form).filter(
      (k) => !BUILTIN_KEYS.has(k) && form[k] != null && form[k] !== '',
    );
    const merged = new Set<string>([...fromPayload, ...suggestions]);
    // Drop keys the user just cleared but that still live in state as
    // empty strings (they'll be null'd on submit anyway).
    return Array.from(merged).sort();
  }, [form, suggestions]);

  const addCustomField = useCallback(() => {
    const key = newFieldKey.trim().toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
    if (!key || BUILTIN_KEYS.has(key)) {
      setNewFieldKey('');
      return;
    }
    setForm((prev) => ({ ...prev, [key]: prev[key] ?? '' }));
    setSuggestions((prev) => {
      if (prev.includes(key)) return prev;
      const next = [...prev, key];
      writeCustomFieldSuggestions(next);
      return next;
    });
    setNewFieldKey('');
  }, [newFieldKey]);

  const removeCustomField = useCallback((key: string) => {
    setForm((prev) => {
      const next = { ...prev };
      next[key] = null;
      return next;
    });
  }, []);

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
    // Record non-empty custom field names as suggestions for future use.
    const used = Object.keys(payload).filter(
      (k) => !BUILTIN_KEYS.has(k) && payload[k] != null,
    );
    if (used.length > 0) {
      const merged = Array.from(new Set([...suggestions, ...used]));
      writeCustomFieldSuggestions(merged);
    }
    mutation.mutate(payload);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-lg border border-border-light bg-surface-primary shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="asset-edit-modal"
      >
        <div className="flex items-center justify-between border-b border-border-light px-4 py-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('assets.edit.element', { defaultValue: 'Element' })}
            </div>
            <div className="font-medium text-content-primary">{asset.name || asset.element_type}</div>
            <div className="font-mono text-xs text-content-tertiary">{asset.stable_id}</div>
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
            <label className="text-xs text-content-tertiary">
              {t('assets.field.operational_status', { defaultValue: 'Operational status' })}
            </label>
            <select
              value={form.operational_status ?? ''}
              onChange={(e) => patch('operational_status', e.target.value)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
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
            <label className="text-xs text-content-tertiary">
              {t('assets.field.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes ?? ''}
              onChange={(e) => patch('notes', e.target.value)}
              rows={3}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
              data-testid="asset-field-notes"
            />
          </div>

          {/* Custom user fields — persisted as free-form JSON. Previously-used
              field names are remembered in localStorage and offered the next
              time the modal opens. */}
          <div className="flex flex-col gap-2 sm:col-span-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-content-secondary">
                {t('assets.custom.title', { defaultValue: 'Custom fields' })}
              </span>
              <span className="text-[10px] text-content-tertiary">
                {t('assets.custom.hint', {
                  defaultValue: 'Stored in asset_info — snake_case keys.',
                })}
              </span>
            </div>
            {customKeys.map((k) => (
              <div key={k} className="flex items-end gap-2">
                <div className="flex-1 flex flex-col gap-1">
                  <label className="text-xs text-content-tertiary">{k.replace(/_/g, ' ')}</label>
                  <Input
                    value={(form[k] ?? '') as string}
                    onChange={(e) => patch(k as keyof AssetInfoPayload, e.target.value)}
                    data-testid={`asset-field-custom-${k}`}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => removeCustomField(k)}
                  className="mb-1 rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-rose-600"
                  aria-label={t('assets.custom.remove', {
                    defaultValue: 'Remove {{key}}',
                    key: k,
                  })}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <div className="flex items-end gap-2">
              <div className="flex-1 flex flex-col gap-1">
                <label className="text-xs text-content-tertiary">
                  {t('assets.custom.add_label', { defaultValue: 'Field name' })}
                </label>
                <Input
                  value={newFieldKey}
                  onChange={(e) => setNewFieldKey(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addCustomField();
                    }
                  }}
                  placeholder={t('assets.custom.add_placeholder', {
                    defaultValue: 'e.g. power_rating_kw',
                  })}
                  data-testid="asset-custom-field-name"
                />
              </div>
              <Button
                variant="secondary"
                onClick={addCustomField}
                disabled={!newFieldKey.trim()}
                data-testid="asset-custom-field-add"
              >
                <Plus size={14} className="mr-1" />
                {t('assets.custom.add', { defaultValue: 'Add field' })}
              </Button>
            </div>
            {suggestions.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-[10px] text-content-tertiary mr-1">
                  {t('assets.custom.suggestions', { defaultValue: 'Recently used:' })}
                </span>
                {suggestions
                  .filter((k) => !(k in form))
                  .slice(0, 8)
                  .map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => {
                        setForm((prev) => ({ ...prev, [k]: '' }));
                      }}
                      className="inline-flex items-center gap-0.5 rounded-full border border-border-light bg-surface-secondary px-2 py-0.5 text-[10px] text-content-secondary hover:bg-surface-tertiary hover:text-content-primary"
                    >
                      <Plus size={9} />
                      {k.replace(/_/g, ' ')}
                    </button>
                  ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border-light px-4 py-3">
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
      <label className="text-xs text-content-tertiary">{label}</label>
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

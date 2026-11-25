// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Change one resource of a region's price sheet: preview what it touches
// (work items, assemblies, bills) with the price delta each would get, then
// apply on confirmation. Money stays a decimal STRING end to end.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Eye } from 'lucide-react';

import { Button, WideModal } from '@/shared/ui';
import { apiPost, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import type { ResourcePriceRow } from './useResourcePrices';

export interface ResourceImpactIssue {
  code: string;
  blocking: boolean;
  detail: string;
}

export interface ResourceImpactResponse {
  region: string;
  resource_key: string;
  new_resource_key: string;
  old_name: string;
  new_name: string;
  old_unit_price: string;
  new_unit_price: string;
  currency: string;
  cost_items_count: number;
  cost_items_unreadable: number;
  cost_items_delta_total: string;
  cost_items: {
    id: string;
    code: string;
    description: string;
    unit: string;
    lines: number;
    old_rate: string;
    new_rate: string;
    delta: string;
  }[];
  assemblies_count: number;
  assemblies: { id: string; code: string; name: string; components: number; delta: string }[];
  boq_positions_count: number;
  boqs: { boq_id: string; boq_name: string; project_id: string; positions: number; delta_total: string }[];
  issues: ResourceImpactIssue[];
  truncated: boolean;
  applied: boolean;
  audit_id: string | null;
}

export interface ResourceChangeBody {
  resource_key: string;
  new_unit_price?: string;
  new_name?: string;
  expected_cost_items?: number;
}

const enc = encodeURIComponent;

export const resourceImpactApi = {
  preview: (region: string, body: ResourceChangeBody) =>
    apiPost<ResourceImpactResponse, ResourceChangeBody>(
      `/v1/costs/resource-prices/${enc(region)}/impact/`,
      body,
    ),
  apply: (region: string, body: ResourceChangeBody) =>
    apiPost<ResourceImpactResponse, ResourceChangeBody>(
      `/v1/costs/resource-prices/${enc(region)}/impact/apply/`,
      body,
    ),
};

/** Build the request body: only fields that actually change are sent. */
export function buildChangeBody(
  row: Pick<ResourcePriceRow, 'resource_key' | 'resource_name' | 'unit_price'>,
  price: string,
  name: string,
): ResourceChangeBody {
  const body: ResourceChangeBody = { resource_key: row.resource_key };
  if (price.trim() !== '' && price.trim() !== row.unit_price.trim()) body.new_unit_price = price.trim();
  if (name.trim() !== '' && name.trim() !== row.resource_name) body.new_name = name.trim();
  return body;
}

interface Props {
  region: string;
  row: ResourcePriceRow;
  onClose: () => void;
}

export function ResourceImpactDialog({ region, row, onClose }: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const [price, setPrice] = useState(row.unit_price);
  const [name, setName] = useState(row.resource_name);
  const [preview, setPreview] = useState<ResourceImpactResponse | null>(null);

  const body = buildChangeBody(row, price, name);
  const previewMut = useMutation({
    mutationFn: () => resourceImpactApi.preview(region, body),
    onSuccess: setPreview,
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('costs.resource_impact.preview_failed', { defaultValue: 'Preview failed' }),
        message: getErrorMessage(e),
      }),
  });
  const applyMut = useMutation({
    mutationFn: () =>
      resourceImpactApi.apply(region, { ...body, expected_cost_items: preview?.cost_items_count }),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('costs.resource_impact.applied_title', { defaultValue: 'Resource updated' }),
        message: t('costs.resource_impact.applied_msg', {
          defaultValue: 'Work items updated: {{n}}.',
          n: res.cost_items_count,
        }),
      });
      void qc.invalidateQueries({ queryKey: ['costs', 'resource-prices', region] });
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('costs.resource_impact.apply_failed', { defaultValue: 'Change not applied' }),
        message: getErrorMessage(e),
      }),
  });

  const blocking = preview?.issues.some((i) => i.blocking) ?? false;
  const issueLabels: Record<string, string> = {
    'resource.change.nothing_to_change': t('costs.resource_impact.issue_nothing_to_change', {
      defaultValue: 'Nothing changes: edit the name or the price first.',
    }),
    'resource.change.empty_name': t('costs.resource_impact.issue_empty_name', {
      defaultValue: 'The name cannot be empty.',
    }),
    'resource.change.key_collision': t('costs.resource_impact.issue_key_collision', {
      defaultValue: 'Another resource of this region already has this name.',
    }),
    'resource.change.unreadable_lines': t('costs.resource_impact.issue_unreadable_lines', {
      defaultValue: 'Some work items carry this resource without a quantity and will be left alone.',
    }),
    'resource.change.zero_price': t('costs.resource_impact.issue_zero_price', {
      defaultValue: 'A price of 0 leaves the resource unpriced.',
    }),
  };
  const issueLabel = (code: string) => issueLabels[code] ?? code;

  return (
    <WideModal
      open
      onClose={onClose}
      busy={applyMut.isPending}
      size="xl"
      title={t('costs.resource_impact.title', { defaultValue: 'Change resource' })}
      subtitle={t('costs.resource_impact.subtitle', {
        defaultValue: 'Preview what this change touches, then apply it.',
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="secondary"
            icon={<Eye size={14} />}
            loading={previewMut.isPending}
            onClick={() => previewMut.mutate()}
          >
            {t('costs.resource_impact.preview', { defaultValue: 'Preview impact' })}
          </Button>
          <Button
            variant="primary"
            disabled={!preview || blocking}
            loading={applyMut.isPending}
            onClick={() => applyMut.mutate()}
          >
            {t('costs.resource_impact.apply', { defaultValue: 'Apply change' })}
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-xs text-content-secondary">
          {t('costs.resource_impact.name', { defaultValue: 'Name' })}
          <input
            className="oe-input-sm mt-1 w-full"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setPreview(null);
            }}
          />
        </label>
        <label className="text-xs text-content-secondary">
          {t('costs.resource_impact.price', { defaultValue: 'Unit price' })} ({row.currency})
          <input
            className="oe-input-sm mt-1 w-full text-right tabular-nums"
            inputMode="decimal"
            value={price}
            onChange={(e) => {
              setPrice(e.target.value);
              setPreview(null);
            }}
          />
        </label>
      </div>

      {preview && (
        <div className="mt-4 space-y-3 text-sm" data-testid="resource-impact-preview">
          <div className="grid grid-cols-3 gap-3 tabular-nums">
            <div>
              <div className="text-2xs text-content-tertiary">
                {t('costs.resource_impact.cost_items', { defaultValue: 'Work items' })}
              </div>
              <div className="font-semibold">{preview.cost_items_count}</div>
              <div className="text-2xs text-content-tertiary">
                {t('costs.resource_impact.delta_total', { defaultValue: 'Rate change in total' })}:{' '}
                {preview.cost_items_delta_total} {preview.currency}
              </div>
            </div>
            <div>
              <div className="text-2xs text-content-tertiary">
                {t('costs.resource_impact.assemblies', { defaultValue: 'Assemblies' })}
              </div>
              <div className="font-semibold">{preview.assemblies_count}</div>
            </div>
            <div>
              <div className="text-2xs text-content-tertiary">
                {t('costs.resource_impact.boq_positions', { defaultValue: 'BOQ positions' })}
              </div>
              <div className="font-semibold">{preview.boq_positions_count}</div>
              <div className="text-2xs text-content-tertiary">
                {t('costs.resource_impact.boq_note', {
                  defaultValue: 'Bills keep their prices until you align them.',
                })}
              </div>
            </div>
          </div>

          {preview.issues.map((i) => (
            <div
              key={i.code}
              className={i.blocking ? 'flex items-center gap-1.5 text-semantic-error' : 'flex items-center gap-1.5 text-semantic-warning'}
            >
              <AlertTriangle size={14} />
              {issueLabel(i.code)}
              {i.detail ? ` (${i.detail})` : ''}
            </div>
          ))}

          {preview.cost_items.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-content-tertiary">
                  <th className="text-left">{t('costs.resource_impact.col_item', { defaultValue: 'Work item' })}</th>
                  <th className="text-right">{t('costs.resource_impact.col_old', { defaultValue: 'Old rate' })}</th>
                  <th className="text-right">{t('costs.resource_impact.col_new', { defaultValue: 'New rate' })}</th>
                  <th className="text-right">{t('costs.resource_impact.col_delta', { defaultValue: 'Delta' })}</th>
                </tr>
              </thead>
              <tbody>
                {preview.cost_items.slice(0, 50).map((it) => (
                  <tr key={it.id}>
                    <td>
                      <span className="tabular-nums text-content-tertiary">{it.code}</span> {it.description}
                    </td>
                    <td className="text-right tabular-nums">{it.old_rate}</td>
                    <td className="text-right tabular-nums">{it.new_rate}</td>
                    <td className="text-right tabular-nums">{it.delta}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </WideModal>
  );
}

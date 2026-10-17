// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PositionSuggestedSupplier - the supplier an estimator suggests for the
// materials of one BOQ position (issue #516).
//
// One choice for the whole position, and optionally one per material that
// overrides it. The suggestion travels into requisitions raised from the bill
// and is only a hint there: nobody's order goes to a supplier because of it.
// Changing it here does not touch quantities, rates or totals, and does not
// change requisitions that were already raised.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Skeleton } from '@/shared/ui';
import { apiGet, apiPut, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { VendorSelect } from './RequisitionSupply';

export interface SuggestedSupplierResource {
  resource_key: string;
  name: string;
  code: string | null;
  unit: string | null;
  suggested_vendor_id: string | null;
  effective_vendor_id: string | null;
  effective_vendor_name: string | null;
  effective_vendor_status: string | null;
  origin: 'resource' | 'position' | null;
}

export interface SuggestedSupplier {
  position_id: string;
  default_vendor_id: string | null;
  default_vendor_name: string | null;
  default_vendor_status: string | null;
  resources: SuggestedSupplierResource[];
}

export function getSuggestedSupplier(positionId: string): Promise<SuggestedSupplier> {
  return apiGet<SuggestedSupplier>(`/v1/boq/positions/${encodeURIComponent(positionId)}/suggested-supplier`);
}

export function setSuggestedSupplier(
  positionId: string,
  body: { vendor_id: string | null; resource_key?: string | null },
): Promise<SuggestedSupplier> {
  return apiPut<SuggestedSupplier, typeof body>(
    `/v1/boq/positions/${encodeURIComponent(positionId)}/suggested-supplier`,
    body,
  );
}

export function PositionSuggestedSupplier({ positionId }: { positionId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const key = ['boq-suggested-supplier', positionId];
  const { data, isLoading, error } = useQuery({ queryKey: key, queryFn: () => getSuggestedSupplier(positionId) });

  const save = useMutation({
    mutationFn: (body: { vendor_id: string | null; resource_key?: string | null }) =>
      setSuggestedSupplier(positionId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(key, updated);
      queryClient.invalidateQueries({ queryKey: ['resource-buy-list'] });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  return (
    <section className="rounded-lg border border-border-light p-3">
      <h4 className="text-sm font-semibold text-content-primary">
        {t('procurement.suggested.title', { defaultValue: 'Suggested supplier' })}
      </h4>
      <p className="mt-0.5 text-xs text-content-tertiary">
        {t('procurement.suggested.hint', {
          defaultValue:
            'A hint for purchasing, copied into new requisitions. It does not choose the supplier of an order and does not change any price.',
        })}
      </p>
      {isLoading ? (
        <Skeleton className="mt-2 h-16 w-full" />
      ) : error ? (
        <p role="alert" className="mt-2 text-xs text-semantic-error">
          {getErrorMessage(error)}
        </p>
      ) : data ? (
        <div className="mt-2 space-y-2">
          <label className="block text-xs font-medium text-content-secondary">
            {t('procurement.suggested.position_default', { defaultValue: 'For all materials of this position' })}
            <div className="mt-1">
              <VendorSelect
                size="sm"
                value={data.default_vendor_id ?? ''}
                fallbackName={data.default_vendor_name}
                disabled={save.isPending}
                emptyLabel={t('procurement.requisitions.no_suggestion', { defaultValue: 'No suggestion' })}
                onChange={(id) => save.mutate({ vendor_id: id || null, resource_key: null })}
              />
            </div>
          </label>
          {data.resources.length === 0 ? (
            <p className="text-xs text-content-tertiary">
              {t('procurement.suggested.no_materials', {
                defaultValue: 'This position has no material resources.',
              })}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {data.resources.map((r) => (
                <li key={r.resource_key} className="grid grid-cols-[1fr_11rem] items-center gap-2 text-xs">
                  <span className="truncate text-content-primary" title={r.name}>
                    {r.name}
                    {r.unit ? <span className="text-content-tertiary"> ({r.unit})</span> : null}
                  </span>
                  <VendorSelect
                    size="sm"
                    value={r.suggested_vendor_id ?? ''}
                    fallbackName={r.origin === 'resource' ? r.effective_vendor_name : null}
                    disabled={save.isPending}
                    ariaLabel={t('procurement.suggested.for_material', {
                      defaultValue: 'Suggested supplier for {{name}}',
                      name: r.name,
                    })}
                    emptyLabel={
                      data.default_vendor_name
                        ? t('procurement.suggested.use_default_named', {
                            defaultValue: 'As the position: {{name}}',
                            name: data.default_vendor_name,
                          })
                        : t('procurement.requisitions.no_suggestion', { defaultValue: 'No suggestion' })
                    }
                    onChange={(id) => save.mutate({ vendor_id: id || null, resource_key: r.resource_key })}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}

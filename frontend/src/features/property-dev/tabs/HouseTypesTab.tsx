// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * House Types tab - grid view of reusable house templates (semi /
 * detached / terrace) with their variants summarised as inline
 * chips. Extracted from the monolithic ``PropertyDevPage.tsx`` to
 * keep the orchestrator under 800 lines.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Home } from 'lucide-react';
import { Card, Badge, EmptyState } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { listVariants, type HouseType } from '../api';
import { toNumber } from './_shared';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';

export function HouseTypesTab({
  rows,
  onCreate,
}: {
  rows: HouseType[];
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Home size={22} />}
          title={t('propdev.empty_house_types', { defaultValue: 'No house types' })}
          description={t('propdev.empty_house_types_desc', {
            defaultValue: 'Define reusable house types (semi, detached, terrace) with base prices.',
          })}
          action={{
            label: t('propdev.new_house_type', { defaultValue: 'New House Type' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {rows.map((h) => (
        <HouseTypeCard key={h.id} ht={h} />
      ))}
    </div>
  );
}

function HouseTypeCard({ ht }: { ht: HouseType }) {
  const { t } = useTranslation();
  const q = useDisplayQuantity();
  const area = q.convert(toNumber(ht.total_area_m2), 'm²');
  const variantsQ = useQuery({
    queryKey: ['propdev', 'variants', ht.id],
    queryFn: () => listVariants(ht.id),
    staleTime: 60_000,
  });
  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold text-content-primary truncate" title={ht.name || ht.code}>
            {ht.name || ht.code}
          </h3>
          <p className="mt-0.5 text-xs font-mono text-content-tertiary">{ht.code}</p>
        </div>
        <Badge variant="blue">{ht.bedrooms} BR</Badge>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <p className="text-content-tertiary">{t('propdev.area', { defaultValue: 'Area' })}</p>
          <p className="font-medium">{fmtFixed(area.value, 1)} {area.unit}</p>
        </div>
        <div>
          <p className="text-content-tertiary">{t('propdev.levels', { defaultValue: 'Levels' })}</p>
          <p className="font-medium">{ht.levels}</p>
        </div>
        <div>
          <p className="text-content-tertiary">{t('propdev.base_price', { defaultValue: 'Base price' })}</p>
          <p className="font-medium">
            <MoneyDisplay amount={toNumber(ht.base_price)} currency={ht.currency || undefined} />
          </p>
        </div>
      </div>
      {variantsQ.data && variantsQ.data.length > 0 && (
        <div className="mt-3">
          <p className="text-xs uppercase tracking-wide text-content-tertiary mb-1">
            {t('propdev.variants', { defaultValue: 'Variants' })}
          </p>
          <div className="flex flex-wrap gap-1">
            {variantsQ.data.map((v) => (
              <Badge key={v.id} variant="neutral">
                {v.code} ({toNumber(v.modifier_pct) > 0 ? '+' : ''}
                {fmtPercent(toNumber(v.modifier_pct))})
              </Badge>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

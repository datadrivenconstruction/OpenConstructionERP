// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Portfolio KPI strip for the Asset Register.
 *
 * Reads the computed roll-up from ``/v1/assets/portfolio`` (warranty /
 * maintenance / attention counts that the backend derives from each
 * asset's stored dates). Renders nothing while the active project has no
 * tracked assets so it never adds noise to an empty register.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CalendarClock, Gauge, ShieldAlert, Wrench } from 'lucide-react';

import { Card } from '@/shared/ui';

import { fetchPortfolio, type PortfolioSummary } from './api';

interface AssetPortfolioStripProps {
  projectId: string;
  /** Click a KPI tile to apply the matching filter on the parent list. */
  onFilter?: (filter: {
    warrantyStatus?: 'expired' | 'expiring';
    maintenanceStatus?: 'due' | 'overdue';
    attention?: boolean;
  }) => void;
}

function Tile({
  icon,
  label,
  value,
  tone,
  onClick,
  testId,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  tone: string;
  onClick?: () => void;
  testId?: string;
}) {
  const clickable = !!onClick;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!clickable}
      data-testid={testId}
      className={`flex min-w-[120px] flex-1 items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors ${tone} ${
        clickable ? 'cursor-pointer hover:brightness-110' : 'cursor-default'
      }`}
    >
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0">
        <span className="block text-lg font-semibold leading-none">{value}</span>
        <span className="block truncate text-[11px] opacity-80">{label}</span>
      </span>
    </button>
  );
}

export function AssetPortfolioStrip({ projectId, onFilter }: AssetPortfolioStripProps) {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ['asset-portfolio', projectId],
    queryFn: () => fetchPortfolio(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const s: PortfolioSummary | undefined = query.data;
  if (!s || s.total_assets === 0) return null;

  return (
    <Card className="mb-4" data-testid="asset-portfolio-strip">
      <div className="flex flex-wrap gap-2 p-3">
        <Tile
          icon={<Gauge size={18} />}
          label={t('assets.kpi.total', { defaultValue: 'Tracked assets' })}
          value={s.total_assets}
          tone="border-border-medium bg-surface-secondary text-content-primary"
          testId="asset-kpi-total"
        />
        <Tile
          icon={<ShieldAlert size={18} />}
          label={t('assets.kpi.warranty_expired', { defaultValue: 'Warranty expired' })}
          value={s.warranties_expired}
          tone="border-rose-500/30 bg-rose-500/10 text-rose-300"
          onClick={onFilter ? () => onFilter({ warrantyStatus: 'expired' }) : undefined}
          testId="asset-kpi-warranty-expired"
        />
        <Tile
          icon={<CalendarClock size={18} />}
          label={t('assets.kpi.warranty_expiring', { defaultValue: 'Expiring soon' })}
          value={s.warranties_expiring_soon}
          tone="border-amber-500/30 bg-amber-500/10 text-amber-300"
          onClick={onFilter ? () => onFilter({ warrantyStatus: 'expiring' }) : undefined}
          testId="asset-kpi-warranty-expiring"
        />
        <Tile
          icon={<Wrench size={18} />}
          label={t('assets.kpi.maintenance_overdue', { defaultValue: 'Maintenance overdue' })}
          value={s.maintenance_overdue}
          tone="border-rose-500/30 bg-rose-500/10 text-rose-300"
          onClick={onFilter ? () => onFilter({ maintenanceStatus: 'overdue' }) : undefined}
          testId="asset-kpi-maint-overdue"
        />
        <Tile
          icon={<AlertTriangle size={18} />}
          label={t('assets.kpi.needs_attention', { defaultValue: 'Needs attention' })}
          value={s.needs_attention}
          tone="border-oe-blue/30 bg-oe-blue/10 text-oe-blue"
          onClick={onFilter ? () => onFilter({ attention: true }) : undefined}
          testId="asset-kpi-attention"
        />
        {s.avg_age_years != null && (
          <Tile
            icon={<Gauge size={18} />}
            label={t('assets.kpi.avg_age', { defaultValue: 'Avg age (yrs)' })}
            value={s.avg_age_years}
            tone="border-border-medium bg-surface-secondary text-content-secondary"
            testId="asset-kpi-avg-age"
          />
        )}
      </div>
    </Card>
  );
}

export default AssetPortfolioStrip;

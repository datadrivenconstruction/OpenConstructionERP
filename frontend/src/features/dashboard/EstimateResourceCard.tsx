// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * EstimateResourceCard - dashboard widget surfacing the ESTIMATE side's
 * resource rollup for the active project.
 *
 * The dashboard already shows field-side labour cost (actuals vs budget);
 * this card closes the loop with the estimate side by reading the resource
 * summary - the procurement demand aggregated from every BOQ position's
 * stored resource split - and showing three at-a-glance figures: labour
 * hours, total resource cost and the number of distinct resources.
 *
 * Money arrives from the backend as a Decimal string and is rendered
 * through formatCurrency (never coerced to a float for display maths).
 *
 * Self-hides (returns null) when there is no active project, while the
 * statement is loading, or when the estimate carries no resources yet
 * (line_count <= 0), so a fresh project never shows an empty card. This
 * mirrors the self-hide convention of BIMCoverageCard / RfiTurnaroundCard.
 * The header action clicks through to the full Resource Summary page.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, InfoHint } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getResourceStatement } from '@/features/resource-summary/api';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { KpiStrip } from './KpiStrip';

// Whole-number formatter for labour hours and the distinct-resource count.
// Locale is left undefined so it follows the active UI locale, matching the
// other KpiStrip cards (see RfiTurnaroundCard).
const wholeFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export function EstimateResourceCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  const { data, isLoading } = useQuery({
    queryKey: ['resource-summary', 'dashboard', projectId],
    queryFn: () => getResourceStatement(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  });

  // Hide entirely on no-project / loading / no-resources so the dashboard
  // stays clean for estimates that have not been broken down into resources
  // yet. line_count is the number of distinct aggregated resource lines.
  if (!projectId) return null;
  if (isLoading) return null;
  if (!data || data.line_count <= 0) return null;

  const hoursText = wholeFormat.format(toNum(data.labor_hours));
  const countText = wholeFormat.format(data.line_count);
  // total_cost is a Decimal string; formatCurrency coerces it safely and
  // renders with the estimate's own currency (no hardcoded symbol).
  const costText = formatCurrency(data.total_cost, data.currency, undefined, {
    maximumFractionDigits: 0,
  });

  return (
    <Card className="h-full">
      <CardHeader
        title={t('dashboard.estimate_resources_title', {
          defaultValue: 'Estimate resources',
        })}
        subtitle={t('dashboard.estimate_resources_subtitle', {
          defaultValue: 'Procurement demand aggregated from the estimate',
        })}
        action={
          <button
            type="button"
            onClick={() => navigate('/resource-summary')}
            className="text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.estimate_resources_open', {
              defaultValue: 'Open resource summary',
            })}
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('dashboard.estimate_resources_hours', {
                defaultValue: 'Labour hours',
              }),
              value: hoursText,
            },
            {
              label: t('dashboard.estimate_resources_cost', {
                defaultValue: 'Resource cost',
              }),
              value: costText,
            },
            {
              label: t('dashboard.estimate_resources_count', {
                defaultValue: 'Resources',
              }),
              value: countText,
              tone: 'text-content-secondary',
            },
          ]}
        />
        {/* Coverage, stated on the card itself. "Resource cost" is the subtotal
            of the positions that carry a resource breakdown - never the bill's
            grand total - because lump-sum and subcontract lines are priced
            without one. Unlabelled, that subtotal reads as a contradiction of
            the BOQ total shown elsewhere on this same dashboard. */}
        <p className="mt-2 text-2xs text-content-tertiary">
          {t('dashboard.estimate_resources_coverage', {
            defaultValue: 'From {{count}} positions with a resource breakdown',
            count: data.position_count,
          })}
        </p>
        <InfoHint
          className="mt-3"
          text={t('dashboard.estimate_resources_help', {
            defaultValue:
              'Rolled up from the positions that carry a resource breakdown, not from the whole bill: their total labour hours, the combined cost of all resources (labour, materials, plant and subcontractors) and how many distinct resources are demanded. Lump-sum and subcontract lines priced without a breakdown are excluded, so this figure is a subtotal of the estimate rather than its grand total.',
          })}
        />
      </CardContent>
    </Card>
  );
}

export default EstimateResourceCard;

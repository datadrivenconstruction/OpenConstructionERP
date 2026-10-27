// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CarbonBudgetCard​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - dashboard widget: the active project's carbon
 * budget against its target and the top hotspot by cost group. Self-hides
 * without a project, while loading, on error and when no budget is set.
 */
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { KpiStrip } from '@/features/dashboard/KpiStrip';
import { getCarbonWidget } from './lifecycleApi';
import { budgetTone, kgToTonnes } from './lifecycle';

const TONE_CLS = {
  success: 'text-emerald-600',
  warning: 'text-amber-600',
  error: 'text-rose-600',
  neutral: 'text-content-secondary',
} as const;

export function CarbonBudgetCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const { data, isLoading, isError } = useQuery({
    queryKey: ['carbon', 'widget', projectId],
    queryFn: () => getCarbonWidget(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });

  if (!projectId || isLoading || isError || !data) return null;
  const b = data.budget;
  if (Number(b.budget_kg) <= 0) return null;
  const locale = getNumberLocale();
  const tone = budgetTone(b);
  const hot = data.top_hotspot;

  return (
    <Card className="h-full">
      <CardHeader
        title={t('carbon.lc.widget_title', { defaultValue: 'Carbon budget' })}
        subtitle={t('carbon.lc.widget_subtitle', { defaultValue: 'Embodied carbon against the project target' })}
        action={
          <button
            type="button"
            onClick={() => navigate('/carbon')}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('carbon.lc.widget_open', { defaultValue: 'Open carbon' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('carbon.lc.widget_actual', { defaultValue: 'Actual, tCO2e' }),
              value: kgToTonnes(b.actual_kg, locale),
              tone: TONE_CLS[tone],
            },
            {
              label: t('carbon.lc.widget_budget', { defaultValue: 'Budget, tCO2e' }),
              value: kgToTonnes(b.budget_kg, locale),
            },
            {
              label: t('carbon.lc.widget_used', { defaultValue: 'Used' }),
              value: `${b.used_pct.toLocaleString(locale, { maximumFractionDigits: 0 })}%`,
              tone: TONE_CLS[tone],
            },
          ]}
        />
        {hot && (
          <div className="mt-3 text-xs text-content-secondary">
            {t('carbon.lc.widget_hotspot', {
              defaultValue: 'Top hotspot: group {{group}}, {{share}}% of embodied carbon',
              group:
                hot.group === 'unclassified'
                  ? t('carbon.lc.unclassified', { defaultValue: 'Unclassified' })
                  : hot.group,
              share: hot.share_pct.toLocaleString(locale, { maximumFractionDigits: 0 }),
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default CarbonBudgetCard;

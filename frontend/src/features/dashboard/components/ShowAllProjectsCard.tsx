// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Layers } from 'lucide-react';
import { Card } from '@/shared/ui';

interface ShowAllProjectsCardProps {
  totalCount: number;
  hiddenCount: number;
  style?: React.CSSProperties;
}

export function ShowAllProjectsCard({ totalCount, hiddenCount, style }: ShowAllProjectsCardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <Card
      hoverable
      padding="none"
      className="group cursor-pointer relative animate-card-in overflow-hidden rounded-xl border-2 border-dashed border-border-light/80 bg-gradient-to-b from-surface-secondary/40 to-surface-primary hover:border-oe-blue/50 hover:shadow-lg focus-within:ring-2 focus-within:ring-oe-blue/30 motion-safe:transition-all"
      style={style}
      onClick={() => navigate('/projects')}
    >
      <div className="flex h-full min-h-[152px] flex-col items-center justify-center gap-2 p-3.5 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-oe-blue/10 text-oe-blue ring-1 ring-inset ring-oe-blue/20 transition-transform duration-normal ease-oe group-hover:scale-110">
          <Layers size={18} strokeWidth={1.75} />
        </div>
        <div className="text-sm font-semibold text-content-primary">
          {t('dashboard.show_all_projects', { defaultValue: 'View all projects' })}
        </div>
        {hiddenCount > 0 && (
          <div className="text-2xs text-content-tertiary">
            {t('dashboard.show_all_more', {
              defaultValue: '+{{count}} more',
              count: hiddenCount,
            })}
          </div>
        )}
        <div className="text-2xs text-content-quaternary tabular-nums">
          {t('dashboard.show_all_total', {
            defaultValue: '{{count}} total',
            count: totalCount,
          })}
        </div>
        <div className="mt-1 inline-flex items-center gap-1 text-2xs font-medium text-oe-blue opacity-80 transition-opacity group-hover:opacity-100">
          {t('common.open', { defaultValue: 'Open' })}
          <ArrowRight size={11} className="transition-transform group-hover:translate-x-0.5" />
        </div>
      </div>
    </Card>
  );
}

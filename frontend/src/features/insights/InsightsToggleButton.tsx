// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The header control that shows or hides a module's Insights panel. Lives in
 * the page's action cluster (PageHeader `actions`) so every module toggles its
 * charts from the same, obvious spot.
 */
import { useTranslation } from 'react-i18next';
import { BarChart3, ChevronDown } from 'lucide-react';
import { Button } from '@/shared/ui';

interface InsightsToggleButtonProps {
  open: boolean;
  onClick: () => void;
}

export function InsightsToggleButton({ open, onClick }: InsightsToggleButtonProps) {
  const { t } = useTranslation();
  return (
    <Button
      variant="secondary"
      icon={<BarChart3 size={16} />}
      onClick={onClick}
      aria-expanded={open}
      className={open ? 'border-oe-blue/40 ring-1 ring-oe-blue/20' : ''}
    >
      <span className="inline-flex items-center gap-1">
        {t('insights.toggle', { defaultValue: 'Insights' })}
        <ChevronDown size={14} className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </span>
    </Button>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Says so when the open model imported without quantities.
 *
 * A `degraded` model renders like a ready one (its elements and geometry are
 * there), so without this the viewer looked complete while every quantity was
 * empty because the DDC converter was missing. The text comes from the
 * model's warning code through i18n; dismissing hides it for this model until
 * the page is reloaded.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, X } from 'lucide-react';
import { bimQuantityWarningCode, bimQuantityWarningText } from '@/shared/lib/bimQuantityWarning';

interface QuantityWarningBannerProps {
  model: {
    id: string;
    status?: string | null;
    error_code?: string | null;
    metadata?: Record<string, unknown> | null;
  } | null | undefined;
}

export function QuantityWarningBanner({ model }: QuantityWarningBannerProps) {
  const { t } = useTranslation();
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);
  const code = bimQuantityWarningCode(model);
  if (!model || !code || dismissedFor === model.id) return null;
  const text = bimQuantityWarningText(code);

  return (
    <div className="absolute bottom-6 left-3 z-30 max-w-md">
      <div
        role="status"
        data-testid="bim-quantity-warning"
        className="flex items-start gap-2.5 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/95 dark:bg-amber-950/40 px-3.5 py-2.5 text-amber-800 dark:text-amber-200 shadow-md backdrop-blur-sm"
      >
        <AlertTriangle size={16} className="shrink-0 mt-0.5 text-amber-500" />
        <div className="min-w-0">
          <p className="text-xs font-semibold">
            {t('bim.quantity_warning.title', { defaultValue: 'Imported without quantities' })}
          </p>
          <p className="text-xs mt-0.5">{t(text.key, { defaultValue: text.defaultValue })}</p>
        </div>
        <button
          type="button"
          onClick={() => setDismissedFor(model.id)}
          aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
          className="shrink-0 rounded p-0.5 text-amber-600 hover:bg-amber-100 dark:hover:bg-amber-900/40"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

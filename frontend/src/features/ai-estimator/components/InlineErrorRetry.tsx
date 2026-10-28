// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small inline error-with-retry block used inside wizard stages when a
// query (groups, preview) fails. Keeps the user in the flow rather than
// dropping an error boundary.

import { useTranslation } from 'react-i18next';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '@/shared/ui';

export function InlineErrorRetry({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-4 dark:border-rose-900/50 dark:bg-rose-900/20">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-500" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-content-primary">
            {t('aiest.error.title', { defaultValue: 'Something went wrong' })}
          </div>
          <p className="mt-0.5 break-words text-xs text-content-tertiary">{message}</p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={onRetry}
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The honest state for a server that does not carry the Work Requests
 * module yet. The frontend ships ahead of the backend restart, so every
 * screen lands here on a 404 instead of a spinner or a blank board.
 */

import { useTranslation } from 'react-i18next';
import { ClipboardList } from 'lucide-react';

export function ModuleMissing({ onRetry }: { onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="wr-empty" role="status" style={{ padding: '40px 24px' }}>
      <ClipboardList size={28} style={{ opacity: 0.5, marginBottom: 8 }} aria-hidden />
      <b>{t('wr.missing_title', { defaultValue: 'This server does not have the Work Requests module yet.' })}</b>
      {t('wr.missing_body', {
        defaultValue:
          'The screen is installed but the running backend answered 404 for /api/v1/work-requests. Restart the backend so it loads the module, then reload this page. Nothing raised elsewhere is lost.',
      })}
      {onRetry && (
        <div style={{ marginTop: 12 }}>
          <button type="button" className="wr-btn-quiet" onClick={onRetry}>
            {t('wr.retry', { defaultValue: 'Try again' })}
          </button>
        </div>
      )}
    </div>
  );
}

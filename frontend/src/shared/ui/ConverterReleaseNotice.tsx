// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Small dismissible notice shown wherever a CAD/BIM conversion starts, while
 * the new converters are fresh. Reports carry format and versions only, never
 * file contents.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Mail, Megaphone, X } from 'lucide-react';
import { useAuthStore } from '@/stores/useAuthStore';
import { APP_VERSION } from '@/shared/lib/version';
import {
  converterMailtoUrl,
  converterReportUrl,
  dismissConverterNotice,
  isConverterNoticeActive,
  isConverterNoticeDismissed,
} from '@/shared/lib/converterReleaseNotice';

export function ConverterReleaseNotice({
  format,
  converterVersion,
  className = '',
}: {
  format?: string;
  converterVersion?: string | null;
  className?: string;
}) {
  const { t } = useTranslation();
  const userId = useAuthStore((s) => s.userId);
  const [hidden, setHidden] = useState(() => isConverterNoticeDismissed(userId));
  if (hidden || !isConverterNoticeActive()) return null;

  const info = { format, converterVersion, appVersion: APP_VERSION };
  return (
    <div
      role="note"
      data-testid="converter-release-notice"
      className={`flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-3 text-start ${className}`}
    >
      <Megaphone size={16} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-2">
        <p className="text-xs leading-relaxed text-content-secondary">
          {t('converter_notice.text', {
            defaultValue:
              'We have just released new versions of the converters (RVT, IFC, DWG). Some files may convert with errors or gaps. If anything looks wrong, please tell us right away.',
          })}
        </p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <a
            href={converterReportUrl(info)}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="converter-notice-report"
            className="text-xs font-semibold text-oe-blue hover:underline"
          >
            {t('converter_notice.report', { defaultValue: 'Report a problem' })}
          </a>
          <a
            href={converterMailtoUrl(info)}
            data-testid="converter-notice-email"
            className="inline-flex items-center gap-1 text-xs font-medium text-content-secondary hover:underline"
          >
            <Mail size={12} aria-hidden="true" />
            {t('converter_notice.email', { defaultValue: 'Write to us by email' })}
          </a>
        </div>
      </div>
      <button
        type="button"
        onClick={() => {
          dismissConverterNotice(userId);
          setHidden(true);
        }}
        aria-label={t('converter_notice.dismiss', { defaultValue: 'Dismiss this notice' })}
        data-testid="converter-notice-dismiss"
        className="shrink-0 rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

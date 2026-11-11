// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * AutoInstallConverterNotice — the inline, transparent status note shown
 * while a CAD/BIM converter is auto-installing in the background after a
 * file upload (see useAutoInstallConverter).
 *
 * It deliberately leads with reassurance, not instructions:
 *   - Default / in-progress: a short "Preparing the {FORMAT} converter
 *     (one-time, ~{N} MB)…" line plus the existing ConverterInstallProgressBar.
 *   - For IFC, it adds that a built-in fallback parser opens the model
 *     meanwhile, so the wait never blocks the user.
 *   - Manual-install guidance is the LAST resort: it only appears AFTER an
 *     automatic attempt has failed (``errored``), with a Retry button and a
 *     GitHub link.
 *
 * The manual Install / Retry buttons elsewhere (status banner, install
 * prompt) remain as fallbacks; this component never requires a click to
 * start an install.
 */

import { useTranslation } from 'react-i18next';
import { AlertCircle, Download, ExternalLink, Loader2, RefreshCw } from 'lucide-react';

import { ConverterInstallProgressBar } from './ConverterInstallProgressBar';
import type { AutoInstallConverterState } from './useAutoInstallConverter';

/** GitHub root for the manual-install fallback link. Matches the URL used
 *  by BIMConverterStatusBanner. */
const DDC_REPO_URL =
  'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG/releases/tag/v2026.10.0';

interface AutoInstallConverterNoticeProps {
  state: AutoInstallConverterState;
  /** Visual variant forwarded to the progress bar. ``dark`` suits the
   *  DWG-takeoff dark upload surfaces; ``light`` (default) suits the BIM
   *  panel backgrounds. */
  variant?: 'light' | 'dark';
  className?: string;
}

export function AutoInstallConverterNotice({
  state,
  variant = 'light',
  className,
}: AutoInstallConverterNoticeProps): JSX.Element | null {
  const { t } = useTranslation();
  const { installing, converterId, sizeMb, errored, hasFallback, retry } = state;

  if (!converterId) return null;
  // Nothing to show once a converter is installed and there was no error:
  // the parent stops rendering us as soon as the upload proceeds.
  if (!installing && !errored) return null;

  const formatLabel = converterId.toUpperCase();
  const sizeHint = sizeMb > 0 ? sizeMb : null;

  // ── Error fallback (manual install is the LAST resort) ─────────────────
  if (errored) {
    return (
      <div
        className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg px-3 py-2.5 text-2xs text-semantic-warning"
        data-testid={`auto-install-error-${converterId}`}
        role="status"
      >
        <AlertCircle size={14} className="shrink-0 mt-0.5 text-semantic-warning" />
        <div className="flex-1 space-y-1.5 leading-relaxed">
          <p className="font-semibold">
            {t('bim.auto_install_failed_title', {
              defaultValue: 'Could not finish preparing the {{format}} converter',
              format: formatLabel,
            })}
          </p>
          <p className="opacity-90">
            {t('bim.auto_install_failed_body', {
              defaultValue:
                'You can retry the automatic install, or install it manually from GitHub.',
            })}
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-0.5">
            <button
              type="button"
              onClick={retry}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-2xs font-semibold bg-semantic-warning hover:bg-semantic-warning text-white transition-colors"
            >
              <RefreshCw size={12} />
              {t('bim.auto_install_retry', { defaultValue: 'Retry install' })}
            </button>
            <a
              href={DDC_REPO_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-2xs font-semibold border border-semantic-warning/30 text-semantic-warning hover:bg-semantic-warning-bg transition-colors"
            >
              <ExternalLink size={12} />
              {t('bim.auto_install_manual_link', {
                defaultValue: 'Install manually on GitHub',
              })}
            </a>
          </div>
        </div>
      </div>
    );
  }

  // ── In-progress (default) — reassuring, no manual steps ────────────────
  const tone =
    variant === 'dark'
      ? 'border-semantic-info/30 bg-semantic-info/10 text-semantic-info'
      : 'border-semantic-info/30 bg-semantic-info-bg text-semantic-info';

  return (
    <div
      className={[
        'rounded-lg border px-3 py-2.5 space-y-1.5',
        tone,
        className ?? '',
      ].join(' ')}
      data-testid={`auto-install-progress-${converterId}`}
      role="status"
    >
      <p className="flex items-center gap-1.5 text-2xs font-semibold">
        <Loader2 size={12} className="animate-spin shrink-0" />
        {sizeHint !== null
          ? t('bim.auto_install_preparing_sized', {
              defaultValue: 'Preparing the {{format}} converter (one-time, ~{{size}} MB)…',
              format: formatLabel,
              size: sizeHint,
            })
          : t('bim.auto_install_preparing', {
              defaultValue: 'Preparing the {{format}} converter (one-time)…',
              format: formatLabel,
            })}
      </p>
      <p className="text-2xs opacity-80 leading-relaxed flex items-start gap-1">
        <Download size={10} className="shrink-0 mt-0.5" />
        <span>
          {hasFallback
            ? t('bim.auto_install_hint_fallback', {
                defaultValue:
                  'This runs in the background, no action needed. IFC files open right away with the built-in reader; the converter upgrades them to full meshes when ready.',
              })
            : t('bim.auto_install_hint', {
                defaultValue:
                  'This runs in the background, no action needed. Your upload continues meanwhile.',
              })}
        </span>
      </p>
      <ConverterInstallProgressBar
        converterId={converterId}
        installing={installing}
        sizeMb={sizeMb}
        variant={variant}
      />
    </div>
  );
}

export default AutoInstallConverterNotice;

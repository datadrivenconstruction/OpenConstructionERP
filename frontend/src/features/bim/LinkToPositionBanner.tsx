// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * LinkToPositionBanner - the strip the BIM page shows while the user is
 * picking model elements for one BOQ position ("Link from model" in the BOQ
 * editor). It names the position, counts the current selection and hands the
 * selection to the usual Add-to-BOQ dialog, which opens on that position.
 *
 * Linking needs bim.create. A role without it (a viewer following a shared
 * link) gets a sentence saying so and the way back, not a button that 403s.
 */

import { useTranslation } from 'react-i18next';
import { ArrowLeft, Link2, X } from 'lucide-react';
import type { LinkFromModelTarget } from './quantityRuleLinks';

interface LinkToPositionBannerProps {
  target: LinkFromModelTarget;
  selectionCount: number;
  /** The role may create links (bim.create). Defaults to true. */
  canLink?: boolean;
  onLink: () => void;
  onBack: () => void;
  onCancel: () => void;
}

export function LinkToPositionBanner({
  target,
  selectionCount,
  canLink = true,
  onLink,
  onBack,
  onCancel,
}: LinkToPositionBannerProps) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      data-testid="bim-link-position-banner"
      className="absolute bottom-4 left-1/2 -translate-x-1/2 z-30 flex max-w-[calc(100%-2rem)] flex-wrap items-center gap-2 rounded-xl border border-oe-blue/40 bg-surface-primary/95 px-3 py-2 text-xs shadow-lg backdrop-blur-sm"
    >
      <Link2 size={14} className="shrink-0 text-oe-blue" />
      <span className="min-w-0 text-content-secondary">
        {!canLink
          ? t('bim.link_mode_no_permission', {
              defaultValue: 'Your role can view the model but cannot link elements to BOQ positions.',
            })
          : target.label
          ? t('bim.link_mode_banner', {
              defaultValue: 'Linking to BOQ position {{label}}. Select elements in the model, then press Link selection.',
              label: target.label,
            })
          : t('bim.link_mode_banner_unnamed', {
              defaultValue: 'Linking to a BOQ position. Select elements in the model, then press Link selection.',
            })}
      </span>
      {canLink && (
        <button
          type="button"
          onClick={onLink}
          disabled={selectionCount === 0}
          data-testid="bim-link-position-go"
          className="flex items-center gap-1 rounded-lg bg-oe-blue px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-oe-blue-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t('bim.link_mode_link', { defaultValue: 'Link selection ({{n}})', n: selectionCount })}
        </button>
      )}
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1 rounded-lg border border-border-light px-2.5 py-1 text-[11px] font-medium text-content-secondary hover:bg-surface-secondary"
      >
        <ArrowLeft size={12} />
        {t('bim.link_mode_back', { defaultValue: 'Back to BOQ' })}
      </button>
      <button
        type="button"
        onClick={onCancel}
        aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
        title={t('common.cancel', { defaultValue: 'Cancel' })}
        className="rounded p-1 text-content-tertiary hover:bg-surface-secondary"
      >
        <X size={13} />
      </button>
    </div>
  );
}

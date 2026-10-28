// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PartnerLogoBadge — co-branding strip shown on every page when a
 * partner pack is active.
 *
 * Variants:
 *  - "nav"      — slim chip with partner logo + "in partnership with X",
 *                 mounted in the top nav-bar center where space allows.
 *  - "dashboard" — wider banner with logo + powered-by line, mounted at
 *                 the top of the dashboard.
 *
 * Clicking the badge opens the in-app Partner Packs page
 * (``/modules?tab=partner-packs``) so the user can see what the active pack
 * configures, switch it, or reach the partner's website/contact shown there.
 *
 * Dismiss behaviour: the user can hide the badge for the current session
 * via a small ✕. We persist the dismissal to ``sessionStorage`` so it
 * comes back on next browser launch — matches the product spec ("logo
 * can be hidden but reappears on next launch").
 */

import { X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { usePartnerPack } from '@/shared/hooks/usePartnerPack';
import { PackEmblem } from '@/shared/ui/PackEmblem';
import { packNameSlug } from '@/shared/lib/regionalPack';
import { useTranslation } from 'react-i18next';

const SESSION_DISMISS_KEY = 'partner-pack:dismissed';

/** In-app destination for the co-brand badge. */
const PACKS_ROUTE = '/modules?tab=partner-packs';

interface PartnerLogoBadgeProps {
  variant: 'nav' | 'dashboard';
  className?: string;
}

export function PartnerLogoBadge({ variant, className = '' }: PartnerLogoBadgeProps) {
  const { t } = useTranslation();
  const packQ = usePartnerPack();
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(SESSION_DISMISS_KEY) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (dismissed) {
      try {
        sessionStorage.setItem(SESSION_DISMISS_KEY, '1');
      } catch {
        /* ignore — sessionStorage may be unavailable */
      }
    }
  }, [dismissed]);

  if (packQ.isLoading || !packQ.data?.active || dismissed) return null;

  const m = packQ.data.manifest!;
  // Same computed-key shape as the other pack surfaces (see regionalPack.ts):
  // the manifest strings are English fallbacks, the locale files name the pack.
  const packName = t(`modules.pp_name_${packNameSlug(m.slug)}`, { defaultValue: m.partner_name });
  const packDesc = m.description
    ? t(`modules.pp_desc_${packNameSlug(m.slug)}`, { defaultValue: m.description })
    : '';
  // Brand colour (pack's primary). Only an exact 6-digit hex can synthesize the
  // alpha-tinted banner background; otherwise fall back to the app accent token
  // (a CSS var can't carry an alpha suffix).
  const brand = m.branding.primary_color || '';
  const isHex = /^#[0-9a-f]{6}$/i.test(brand);
  const accent = isHex ? brand : 'var(--accent)';
  // Clearly-visible, brand-tinted background for the dashboard banner.
  const dashBg = isHex
    ? `linear-gradient(90deg, ${brand}26, ${brand}0d 55%, transparent)`
    : undefined;

  if (variant === 'nav') {
    return (
      <div
        className={`inline-flex items-center gap-2 rounded-full bg-surface-secondary/60 px-2.5 py-1 text-xs text-content-secondary backdrop-blur ${className}`}
        data-testid="partner-logo-nav"
      >
        <Link
          to={PACKS_ROUTE}
          className="inline-flex items-center gap-1.5 hover:text-content-primary"
          title={m.branding.powered_by_text}
        >
          <PackEmblem pack={m} size={20} />
          <span className="max-w-[10rem] truncate font-medium">{packName}</span>
        </Link>
        <button
          type="button"
          aria-label={t('common.hide_partner_badge', { defaultValue: 'Hide partner badge' })}
          onClick={() => setDismissed(true)}
          className="rounded p-0.5 text-content-tertiary hover:text-content-primary hover:bg-surface-tertiary"
        >
          <X size={12} />
        </button>
      </div>
    );
  }

  // variant === 'dashboard'
  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-lg border border-border border-l-[3px] bg-surface-secondary px-4 py-3 text-sm shadow-sm ${className}`}
      style={{ borderLeftColor: accent, backgroundImage: dashBg }}
      data-testid="partner-logo-dashboard"
    >
      <Link
        to={PACKS_ROUTE}
        className="flex min-w-0 items-center gap-3 hover:opacity-90"
        title={m.branding.powered_by_text}
      >
        <PackEmblem pack={m} size={44} />
        <div className="min-w-0 leading-tight">
          <div className="text-sm font-semibold text-content-primary">{packName}</div>
          <div className="mt-0.5 text-2xs uppercase tracking-wide text-content-tertiary">
            {m.branding.powered_by_text}
          </div>
          {packDesc && (
            <div className="mt-0.5 max-w-2xl truncate text-xs text-content-secondary">
              {packDesc}
            </div>
          )}
        </div>
      </Link>
      <button
        type="button"
        aria-label={t('common.hide_partner_badge', { defaultValue: 'Hide partner badge' })}
        onClick={() => setDismissed(true)}
        className="shrink-0 rounded p-1 text-content-tertiary hover:text-content-primary hover:bg-surface-tertiary"
      >
        <X size={14} />
      </button>
    </div>
  );
}

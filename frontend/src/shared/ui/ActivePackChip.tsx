// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ActivePackChip — the top-bar readout of which regional pack is in use.
 *
 * A pack decides the workspace's currency, tax template, validation standards
 * and which modules are on. That is a large amount of behaviour to carry with
 * no visible statement of where it came from, and until now the header made
 * that statement only when a pack was applied: `PartnerLogoBadge` returns null
 * for `active: false`, and the header additionally gated it behind
 * `packActive`. Measured on a stock install, eighteen packs are on disk and
 * `active_slug` is null, so the header said nothing at all - which is the one
 * state where the reader most needs to be told, because "no pack" and "a pack
 * I have not noticed" look identical from inside the app and produce different
 * numbers.
 *
 * So this renders in both states and is deliberately NOT the co-brand badge.
 * `PartnerLogoBadge` can be dismissed for the session by product spec, which is
 * right for a partner's mark and wrong for a status readout: a reader who
 * dismissed the mark once would lose the answer to "which pack am I on" for the
 * rest of the session. The two live side by side, and this one is quiet enough
 * to sit next to it - tertiary text, no fill, no accent - because it is
 * reference rather than promotion.
 *
 * The empty state is a link rather than a label. Nothing else in the app tells
 * a first-time reader that country packs exist, and a chip that says "none"
 * without saying "none of eighteen" is a dead end.
 */

import { Globe2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { useInstalledPacks } from '@/shared/hooks/usePartnerPack';
import { packNameSlug } from '@/shared/lib/regionalPack';
import { PackEmblem } from '@/shared/ui/PackEmblem';

/** Where the chip sends the reader, in both states. */
const PACKS_ROUTE = '/modules?tab=packs';

interface ActivePackChipProps {
  className?: string;
}

export function ActivePackChip({ className = '' }: ActivePackChipProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useInstalledPacks();

  // While the list is in flight there is no honest thing to say: "none" would
  // be a guess that is wrong for every reader who does have a pack, and it
  // would flip a moment later.
  if (isLoading || !data) return null;

  // `active_slug` rather than a separate call to /current: the same envelope
  // already carries which pack is applied, and two sources for one fact drift.
  const applied = data.installed.find((p) => p.slug === data.active_slug) ?? null;

  const base =
    'inline-flex max-w-[13rem] items-center gap-1.5 rounded-full px-2 py-1 text-xs transition-colors';

  if (!applied) {
    return (
      <Link
        to={PACKS_ROUTE}
        data-testid="active-pack-chip"
        data-pack-state="none"
        className={`${base} text-content-tertiary hover:bg-surface-secondary hover:text-content-primary ${className}`}
        title={t('modules.pack_chip_none_hint', {
          defaultValue:
            'No regional pack is applied. A pack sets the currency, tax template and validation standards for this workspace.',
        })}
      >
        <Globe2 size={13} strokeWidth={2} aria-hidden="true" />
        <span className="truncate">
          {t('modules.pack_chip_none', { defaultValue: 'No regional pack' })}
        </span>
      </Link>
    );
  }

  return (
    <Link
      to={PACKS_ROUTE}
      data-testid="active-pack-chip"
      data-pack-state="applied"
      data-pack-slug={applied.slug}
      className={`${base} text-content-secondary hover:bg-surface-secondary hover:text-content-primary ${className}`}
      title={t('modules.pack_chip_applied_hint', {
        defaultValue: 'Regional pack in use. Opens the pack list.',
      })}
    >
      <PackEmblem pack={applied} size={16} />
      <span className="truncate font-medium">
        {/* The same computed key the pack picker, the dashboard card and the
            case chip read, written inline so check_i18n_computed_keys.py can
            see it. A helper returning the finished key hides the whole family
            from the gate. */}
        {t(`modules.pp_name_${packNameSlug(applied.slug)}`, {
          defaultValue: applied.partner_name,
        })}
      </span>
    </Link>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CasePackStrip - the regional pack a case needs, offered on the case CARD.
 *
 * `MarketPackPanel` put the same offer on the case PAGE, which answers the
 * question only for a reader who has already opened a case. The catalogue is
 * where a reader decides which market they work in: filter to the United
 * Kingdom and ten cards say they follow British standards, with nothing
 * anywhere on that screen saying that the pack carrying those standards is on
 * disk and switched off. The install lived two screens away, under a name the
 * reader had to carry there by eye.
 *
 * Germany was the example in this paragraph until it was measured against the
 * artifact instead of the checkout, and it was the one market where the
 * premise is false. A source tree carries twenty packs; the released wheel
 * force-includes seventeen, and `bimhessen-de` and `batimatech-ca` are not
 * among them. On the build a user installs there is no German and no Canadian
 * pack to switch on, so this strip renders nothing for all twenty-three of
 * those cards. Ten Spanish cases are in the same position for a different
 * reason: no pack declares ES at all. Thirty-three of the eighty cases that
 * name a market therefore have nothing to offer here, and the statement that
 * says so lives in `MarketPackPanel`, where the catalogue makes it once for a
 * filtered market rather than thirteen times over in a grid.
 *
 * The strip is deliberately thin. Thirteen cards each shouting the pack's full
 * description would be noise, so this is one line: what the case needs, and the
 * word that starts it. The pack is named because "Set up" alone does not say
 * what would be installed, and a card that installs something unnamed is worse
 * than a card that installs nothing.
 *
 * ── Why it sits above the hover panel ────────────────────────────────────────
 * The card carries a full-bleed hover panel at `z-10` that covers every pixel
 * of it. The pin and the edit controls already solved this: `relative z-20`
 * plus a treatment that switches to light-on-dark for as long as the panel is
 * up, so the control is legible in both states and never opacity-gated (touch
 * and keyboard never hover). This follows them exactly rather than inventing a
 * second answer. The caller pads the panel's foot by the strip's height so the
 * panel's own last line is not the thing that gets covered.
 *
 * ── Why the resolution is not done here ──────────────────────────────────────
 * `useMarketPackOffers` takes every market in the catalogue and resolves them
 * ONCE for the whole grid, and the strip is handed the answer. Twelve cards
 * mount per batch and every one of them would otherwise re-run the same
 * resolution against the same list. It also lets the card know whether a strip
 * will render before it renders one, which is what the hover panel's padding
 * depends on.
 *
 * ── States ───────────────────────────────────────────────────────────────────
 *   - install     - the pack is on disk, switched off, and the reader may
 *                   switch it on. A button that opens the same
 *                   `PartnerPackApplyDialog` the Modules page and the case
 *                   page open: a dry run of what changes, then a streamed
 *                   install with named steps. Nothing is applied by pressing
 *                   here; this only opens the preview.
 *   - installed   - the pack is the applied one. No button: there is nothing
 *                   left to press. The dialog invalidates the whole
 *                   `['partner-pack']` prefix when it finishes, so the strip
 *                   reaches this state on its own without the page reloading.
 *   - unavailable - the reader is not an admin. The backend guards
 *                   `/apply` and `/full-install-stream` with
 *                   `RequireRole("admin")` and self-registration hands out
 *                   `viewer`, so for most readers of a live deployment this is
 *                   the state, and it says so in words rather than greying a
 *                   button and leaving the reason in a tooltip.
 *
 * There is deliberately no "installing" state HERE. It exists, and it belongs
 * to the dialog: `WideModal` is passed `busy` while the stream runs, which
 * blocks Escape, the backdrop and the close button, so the reader cannot get
 * back to this card while an install of it is under way. A state the strip can
 * never be seen in would be a state nobody could ever check.
 *
 * A market with no pack renders nothing at all. Ten shipped cases carry ES and
 * no Spanish pack exists; a nearest-neighbour guess would put German standards
 * under a Spanish case, and an "unavailable" row on 140 unmarked cases would
 * be a permanent apology on the majority of the catalogue.
 *
 * Every string here already existed in all locales. `cases.regional_pack_needed`
 * and `cases.regional_pack_set_up` in particular were shipped for the chip this
 * replaces and then left unread by every component; this puts them back to work
 * rather than adding synonyms of them to forty-three files.
 */

import clsx from "clsx";
import { Check, Package } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useInstalledPacks } from "@/shared/hooks/usePartnerPack";
import { packNameSlug, resolveMarketPacks } from "@/shared/lib/regionalPack";

/** The one pack a market's cards offer, already named in the reader's language. */
export interface CasePackOffer {
  /** Pack slug, the id the apply dialog and the registry both take. */
  slug: string;
  /** Localised pack name, for the label and for the dialog's heading. */
  name: string;
  /** Whether this pack is the applied one. */
  applied: boolean;
}

/**
 * Resolve every market in the catalogue to the pack that serves it, once.
 *
 * Keyed by the region string the CASES spell (`"DE"`), not the one the packs
 * spell (`"de"`), so a caller with a playbook in hand can look its own value up
 * without knowing that the two files disagree about case.
 *
 * Returns an empty map while the list is in flight. There is no honest strip to
 * draw before the answer arrives: "no pack" would be wrong for every market
 * that has one and would flip a moment later.
 */
export function useMarketPackOffers(
  regions: readonly string[],
): Map<string, CasePackOffer> {
  const { t } = useTranslation();
  const { data } = useInstalledPacks();

  return useMemo(() => {
    const offers = new Map<string, CasePackOffer>();
    if (!data) return offers;
    for (const region of regions) {
      const { packs, applied } = resolveMarketPacks(
        data.installed,
        data.active_slug,
        region,
      );
      // The applied pack when there is one, otherwise the first that serves
      // this market. Several can - us-california, us-costdata and us-texas all
      // declare US - and the rest stay one click away in the registry.
      const lead = applied ?? packs[0];
      if (!lead) continue;
      offers.set(region, {
        slug: lead.slug,
        // Written out inline, template literal and all: the computed-key gate
        // recognises `modules.pp_name_*` only in this exact shape, and a helper
        // that returned the finished key would hide a family of names from it.
        name: t(`modules.pp_name_${packNameSlug(lead.slug)}`, {
          defaultValue: lead.partner_name,
        }),
        applied: applied !== null,
      });
    }
    return offers;
  }, [data, regions, t]);
}

interface CasePackStripProps {
  /** The pack this card's market needs, or null/undefined to render nothing. */
  pack: CasePackOffer | null | undefined;
  /** Whether this reader may apply a pack. Only an admin may; the backend
   *  agrees, so a false here is a statement rather than a precaution. */
  canInstall: boolean;
  /** Opens the apply dialog the whole app installs packs through. */
  onActivate: (pack: CasePackOffer) => void;
  className?: string;
}

export function CasePackStrip({
  pack,
  canInstall,
  onActivate,
  className,
}: CasePackStripProps) {
  const { t } = useTranslation();
  if (!pack) return null;

  const needed = t("cases.regional_pack_needed", {
    defaultValue: "Needs {{name}}",
    name: pack.name,
  });
  const inUse = t("cases.regional_pack_in_use", {
    defaultValue: "Regional pack in use: {{name}}",
    name: pack.name,
  });

  // Shared by both states so the strip keeps one height whichever it is in,
  // and the row above it never moves when a pack is switched on.
  const base =
    "relative z-20 flex w-full items-center gap-1.5 border-t border-border-light px-2.5 py-1.5 text-start text-2xs transition-colors";
  // For as long as the hover panel is up the strip wears the panel's own
  // near-black, so it reads as the foot of that panel rather than as a lit
  // sliver left behind by it.
  const overPanel =
    "group-hover:border-white/20 group-hover:bg-slate-900 group-hover:text-white group-focus-visible:border-white/20 group-focus-visible:bg-slate-900 group-focus-visible:text-white";

  if (pack.applied) {
    return (
      <p
        data-testid="case-pack-strip"
        data-pack-state="installed"
        data-pack-slug={pack.slug}
        title={inUse}
        className={clsx(
          base,
          "bg-semantic-success/5 text-semantic-success",
          overPanel,
          className,
        )}
      >
        <Check size={12} aria-hidden="true" className="shrink-0" />
        {/* The picture is the tick and the name; the sentence that says what
            the tick MEANS is read out rather than drawn, because the card has
            room for one of the two and not for both. */}
        <span className="sr-only">{inUse}</span>
        <span aria-hidden="true" className="min-w-0 flex-1 truncate font-medium">
          {pack.name}
        </span>
        <span aria-hidden="true" className="shrink-0 font-semibold">
          {t("modules.active", { defaultValue: "Active" })}
        </span>
      </p>
    );
  }

  return (
    <button
      type="button"
      data-testid="case-pack-strip"
      data-pack-state={canInstall ? "install" : "unavailable"}
      data-pack-slug={pack.slug}
      disabled={!canInstall}
      // The card underneath is one click target; without this a reader aiming
      // at the install would open the case instead.
      onClick={(e) => {
        e.stopPropagation();
        onActivate(pack);
      }}
      title={t("cases.regional_pack_setup_hint", {
        defaultValue:
          "This case follows the standards of its market. Opens the pack that carries them, where you can switch it on.",
      })}
      className={clsx(
        base,
        "bg-oe-blue/5 text-content-secondary",
        overPanel,
        canInstall
          ? "hover:bg-oe-blue/10 group-hover:hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-oe-blue/40"
          : "cursor-default opacity-80",
        className,
      )}
    >
      <Package size={12} aria-hidden="true" className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{needed}</span>
      <span
        className={clsx(
          "shrink-0 font-semibold",
          canInstall && "text-oe-blue-text group-hover:text-white",
        )}
      >
        {canInstall
          ? t("cases.regional_pack_set_up", { defaultValue: "Set up" })
          : t("modules.admin_only", { defaultValue: "Admin only" })}
      </span>
    </button>
  );
}

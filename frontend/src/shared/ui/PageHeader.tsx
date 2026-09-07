// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { type ReactNode } from 'react';
import clsx from 'clsx';

/**
 * Canonical module page top block (MODULE_STYLE_GUIDE.md section 2).
 *
 * The module NAME and ICON live in the top app bar (Header + routeIcons) -
 * they are never repeated inside the page. What a page renders at the top is
 * exactly this, in this order:
 *
 *   1. `Breadcrumb` - only when it has depth (project link / detail trail);
 *      the shared component hides single-item trails by itself.
 *   2. THIS component: one muted subtitle sentence (what the module does)
 *      on the left, the page actions on the right.
 *   3. `DismissibleInfo` - the collapsible "Module information" card.
 *
 * Keeping every page on this exact block is what makes the app read as one
 * product instead of ~90 hand-rolled headers.
 */
export interface PageHeaderProps {
  /** One sentence, i18n, `text-content-tertiary` - NOT the module name. */
  subtitle?: ReactNode;
  /** Primary action first, then secondary; rendered right-aligned. */
  actions?: ReactNode;
  /**
   * Accessible page heading for screen readers. The top bar is meant to show
   * the same words, and `Header.titleKeys.test.ts` is what holds the two
   * together: it pairs this key with the route's `TITLE_I18N_MAP` entry and
   * fails when they differ. Pass the key the module names itself by, normally
   * `<module>.title`, not a `nav.*` variant of it.
   *
   * The parenthetical here once simply stated the top bar shows it, which was
   * untrue on four screens: this heading said "Site prep", "Interface
   * management", "RFIs", "Risk Register" while the bar above said "Site
   * Mobilisation", "Interface Register", "RFI", "Risks". Since the element is
   * `sr-only`, no one reader saw both, so it read as correct to everybody.
   */
  srTitle?: string;
  className?: string;
}

export function PageHeader({ subtitle, actions, srTitle, className }: PageHeaderProps) {
  if (!subtitle && !actions) {
    // srTitle-only pages (chat / full-bleed surfaces) still need the a11y
    // heading, but NOT the min-h-9 row - that rendered as an empty 36px
    // midline above the content (uniformity sweep, shared issue).
    return srTitle ? <h1 className="sr-only">{srTitle}</h1> : null;
  }
  return (
    // items-center: the (usually single-line) subtitle sits on the same
    // vertical midline as the h-8/h-9 action buttons. Top-aligning them
    // (items-start) left the text floating above the buttons and read as
    // misaligned chrome on every page (founder feedback 2026-06-06).
    // NO own margin (audit fix S1): the page root's space-y-5 is the ONLY
    // vertical rhythm - a built-in mb-4 stacked on top of it produced the
    // double gaps the founder flagged.
    <div className={clsx('flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-2', className)}>
      {srTitle && <h1 className="sr-only">{srTitle}</h1>}
      {subtitle ? (
        <p className="min-w-0 flex-1 basis-64 text-sm leading-relaxed text-content-tertiary">
          {subtitle}
        </p>
      ) : (
        <div className="min-w-0 flex-1" aria-hidden />
      )}
      {/* max-w-full: shrink-0 keeps the buttons from being squeezed while they
          share the row with the subtitle, but it also meant this box was never
          narrowed to the container, so its own flex-wrap could never fire. On a
          390px viewport the seven action buttons laid out in one 668px line and
          scrolled the whole page sideways. The cap is inert whenever the row
          fits, so wide layouts are unchanged. */}
      {actions && (
        <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  );
}

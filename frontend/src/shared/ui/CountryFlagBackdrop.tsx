// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { CountryFlag } from './CountryFlag';

/**
 * CountryFlagBackdrop - a huge, barely-there flag watermark for pages scoped
 * to a selected country cost database (founder request 2026-06-06: pick the
 * German database and the page background carries a faint German flag).
 *
 * Composition contract: the page root adds `relative` and renders this as its
 * FIRST child. Deliberately NO z-index and NO `isolate` on the page root - a
 * per-page stacking context traps fixed z-50 modals under the sticky header
 * (modal_relative_isolate_trap). The wash paints at ~5% opacity and stays
 * non-interactive (pointer-events-none); fixed overlays still win.
 *
 * Accepts raw region keys ("DE_BERLIN", "USA_USD") or ISO codes ("de") - the
 * underlying CountryFlag resolves both. Renders nothing when no country is
 * selected, so pages can pass their state straight through.
 *
 * Two sizes, because a wash tuned for a full page reads as nothing at all
 * inside a block a few hundred pixels tall. `page` (the default) is unchanged.
 * `panel` is for a bounded region - the expanded body of one cost-base family,
 * say - where the flag has to be smaller and a little stronger to register.
 * Both keep the same nesting and the same mask.
 */
const MASK = 'radial-gradient(70% 70% at 55% 45%, black 25%, transparent 75%)';

export function CountryFlagBackdrop({
  code,
  className,
  variant = 'page',
}: {
  code?: string | null;
  className?: string;
  variant?: 'page' | 'panel';
}) {
  if (!code) return null;
  const panel = variant === 'panel';
  return (
    <div
      aria-hidden
      className={clsx('pointer-events-none absolute inset-0 select-none overflow-hidden', className)}
    >
      {/* The wash opacity lives on THIS outer div; the fade-in runs on the
          inner keyed div. Nesting matters: animate-fade-in tweens the
          animated element's own opacity 0 -> 1, so putting it on the same
          node as opacity-[0.06] flashed the flag at full strength for the
          first frames of every country switch (founder report). Nested,
          the opacities multiply: the flag fades from 0 to 6%, never above. */}
      <div
        className={
          panel
            ? 'absolute -right-20 -top-28 rotate-[-8deg] opacity-[0.13] blur-[1px] saturate-[1.25] dark:opacity-[0.10] dark:blur-[2px] dark:brightness-75'
            : 'absolute -right-24 top-6 rotate-[-8deg] opacity-[0.06] blur-[1.5px] saturate-[1.2] dark:opacity-[0.05] dark:blur-[3px] dark:brightness-75'
        }
        style={{ maskImage: MASK, WebkitMaskImage: MASK }}
      >
        <div key={code} className="animate-fade-in motion-reduce:animate-none">
          <CountryFlag code={code} size={panel ? 620 : 880} className="!rounded-[2.5rem]" />
        </div>
      </div>
    </div>
  );
}

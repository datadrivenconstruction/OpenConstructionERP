import { useState, useCallback, useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, Info, X } from 'lucide-react';
import { useModuleInfoStore } from '@/stores/useModuleInfoStore';

/**
 * Contextual info / help card used across every module page.
 *
 * It explains - in the UI itself - what a page is for and how it connects to
 * the rest of the platform, while staying out of the way of power users. It is
 * a light, notion-style help card (NOT a loud alert) with TWO states only:
 *
 *  - Expanded: a soft, translucent card with an info chip, a title and the
 *    body. Clicking anywhere on the card - or on the X - collapses it.
 *  - Collapsed: NOTHING renders in the page (founder decision 2026-06-06).
 *    The card registers itself in `useModuleInfoStore`, and the top app bar
 *    shows a small info icon right after the module name (project pill >
 *    module name > info icon). Clicking that icon re-expands the card here.
 *
 * There is no longer a dismissed-forever state. The X simply collapses, and
 * the top-bar icon keeps the card always reachable on every breakpoint.
 *
 * Persistence lives under ``oce.intro.<storageKey>`` in localStorage:
 *
 *   - missing / "0" -> expanded
 *   - "1"           -> collapsed
 *   - "2"           -> collapsed (LEGACY "dismissed" value: users who pressed
 *                      the old X now get the top-bar icon instead of nothing)
 *
 * Use the SAME ``storageKey`` you would pass to the old SectionIntro so
 * existing preferences carry over. The public API (storageKey, title,
 * children, links, className) is consumed by 18+ pages and must not change.
 */

export interface DismissibleInfoLink {
  label: string;
  onClick: () => void;
}

/* ── IntroRichText ────────────────────────────────────────────────────────
   Canonical formatter for the "Show more" long-form module explanations.
   Renders a translated plain string with a tiny markdown subset - enough
   for professional structure without pulling in a markdown dependency:

     - blank line ("\n\n")      -> paragraph break
     - lines starting with "- " -> bulleted list
     - lines starting with "1. "-> numbered list (any digits + dot)
     - **bold** inline          -> <strong> (lead-ins like "**You put in:**")

   Translators keep the same markers in all 27 locales; everything else is
   rendered verbatim, so there is no HTML-injection surface. */

function renderInline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={i} className="font-semibold text-content-primary">
        {part.slice(2, -2)}
      </strong>
    ) : (
      part
    ),
  );
}

export function IntroRichText({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/).filter((b) => b.trim().length > 0);
  return (
    <div className="space-y-2.5">
      {blocks.map((block, bi) => {
        const lines = block.split('\n').map((l) => l.trim()).filter(Boolean);
        if (lines.every((l) => l.startsWith('- '))) {
          return (
            <ul key={bi} className="list-disc space-y-1 pl-5">
              {lines.map((l, li) => (
                <li key={li}>{renderInline(l.slice(2))}</li>
              ))}
            </ul>
          );
        }
        if (lines.every((l) => /^\d+\.\s/.test(l))) {
          return (
            <ol key={bi} className="list-decimal space-y-1 pl-5">
              {lines.map((l, li) => (
                <li key={li}>{renderInline(l.replace(/^\d+\.\s/, ''))}</li>
              ))}
            </ol>
          );
        }
        return <p key={bi}>{renderInline(lines.join(' '))}</p>;
      })}
    </div>
  );
}

/** Persisted display states for an info card. */
type IntroState = 'expanded' | 'collapsed';

function readState(lsKey: string): IntroState {
  try {
    const raw = localStorage.getItem(lsKey);
    // Both "1" (collapsed) and the legacy "2" (old dismissed) now resolve to
    // collapsed, so previously-hidden cards reappear as the bare line.
    if (raw === '1' || raw === '2') return 'collapsed';
    return 'expanded';
  } catch {
    return 'expanded';
  }
}

const STATE_TO_RAW: Record<IntroState, string> = {
  expanded: '0',
  collapsed: '1',
};

export function DismissibleInfo({
  storageKey,
  title,
  children,
  more,
  links,
  className,
}: {
  /** Stable key - display state is remembered under `oce.intro.<storageKey>`. */
  storageKey: string;
  title: string;
  children?: ReactNode;
  /**
   * Optional EXTENDED explanation (founder 2026-06-06): a few more
   * paragraphs revealed behind a "Show more" toggle inside the card -
   * a step-by-step, professionally formatted walkthrough of how the
   * module works. Pass `<IntroRichText text={t('x.intro_more', ...)} />`
   * for canonical formatting (paragraphs, bullets, bold lead-ins).
   */
  more?: ReactNode;
  /** Optional cross-module shortcuts rendered as inline pills. */
  links?: DismissibleInfoLink[];
  /** Extra classes for the outer wrapper (e.g. margin overrides). */
  className?: string;
}) {
  const { t } = useTranslation();
  const lsKey = `oce.intro.${storageKey}`;

  const [state, setState] = useState<IntroState>(() => readState(lsKey));

  const persist = useCallback(
    (next: IntroState) => {
      setState(next);
      try {
        localStorage.setItem(lsKey, STATE_TO_RAW[next]);
      } catch {
        /* private mode / quota - non-fatal, state just resets next load */
      }
    },
    [lsKey],
  );

  const collapse = useCallback(() => persist('collapsed'), [persist]);
  const expand = useCallback(() => persist('expanded'), [persist]);

  // "Show more" is session-local (not persisted): a returning user sees the
  // short card again and opens the long read only when they want it.
  const [showMore, setShowMore] = useState(false);

  // While collapsed the card renders nothing here - it hands itself to the
  // top app bar instead (Header shows an info icon after the module name
  // that calls `expand`). Unmount (navigation) unregisters automatically.
  const register = useModuleInfoStore((s) => s.register);
  const unregister = useModuleInfoStore((s) => s.unregister);
  useEffect(() => {
    if (state !== 'collapsed') return undefined;
    register({ key: lsKey, expand });
    return () => unregister(lsKey);
  }, [state, lsKey, expand, register, unregister]);

  if (state === 'collapsed') return null;

  // Expanded: a soft, translucent card - a VISIBLE light blue tint
  // (bg-oe-blue/10 ~ #e5f1fc over white; /[0.14] over the dark surfaces),
  // founder feedback 2026-06-06: the previous bg-oe-blue-subtle/25 emitted
  // no CSS at all (alpha on an opaque var) so cards looked transparent.
  // The X and the link pills are interactive, so they cannot live inside a
  // role=button (nesting interactive content is invalid ARIA). Instead the
  // outer row is a plain div with a click/keyboard handler (whole-card
  // toggle), and a dedicated header BUTTON carries aria-expanded for AT.
  // No default margin (audit fix S2): pages provide rhythm via the root
  // space-y-5; a built-in mb-5 doubled the gap below every info card.
  // Tint at 80% of the first visible pass (founder 2026-06-06: "светло
  // синий, добавь немного прозрачности, фон на 80%"): /10 -> /[0.08].
  // NO backdrop-blur here (founder 2026-06-06: cards "look opaque"): the
  // app backdrop's texture is a 0.9px dot grid, and even blur-sm wipes it
  // out completely - the tint then reads as a solid plate. With the blur
  // gone the grid shows through the 8% tint and the card is visibly
  // translucent.
  const wrapper = `group rounded-xl border border-oe-blue/20 border-l-2 border-l-oe-blue/70 bg-oe-blue/[0.08] dark:bg-oe-blue/[0.11] shadow-sm animate-fade-in ${
    className ?? ''
  }`;

  return (
    <div className={wrapper}>
      {/* Collapse on click anywhere in the header strip. Keyboard access is
          covered by the dedicated buttons inside (Show more toggle, close),
          so the wrapper itself stays a plain div. */}
      <div
        onClick={collapse}
        className="flex cursor-pointer items-start gap-3 rounded-xl px-4 py-4 transition-colors hover:bg-oe-blue/[0.06]"
      >
        {/* Chip and title share the same 28px midline (uniformity sweep: the
            mt-0.5 chip on an items-start row read ~5px low on every page). */}
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-oe-blue/15">
          <Info size={16} className="text-oe-blue-text" />
        </span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={(e) => {
              // The header button is the keyboard/AT toggle (Enter/Space fire
              // a native click). The outer div also handles pointer clicks, so
              // swallow this one to avoid a double-toggle when the pointer
              // lands on the title.
              e.stopPropagation();
              collapse();
            }}
            aria-expanded
            title={t('common.collapse', { defaultValue: 'Collapse' })}
            className="flex min-h-7 items-center rounded-sm text-left text-base font-medium leading-snug text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
          >
            {title}
          </button>
          {children != null && (
            <div className="mt-1.5 text-sm leading-relaxed text-content-secondary">{children}</div>
          )}
          {more != null && (
            <>
              {showMore && (
                <div className="mt-3 border-t border-oe-blue/15 pt-3 text-sm leading-relaxed text-content-secondary animate-fade-in">
                  {more}
                </div>
              )}
              <button
                type="button"
                onClick={(e) => {
                  // The toggle lives inside the clickable card - never collapse.
                  e.stopPropagation();
                  setShowMore((v) => !v);
                }}
                aria-expanded={showMore}
                className="mt-2 inline-flex items-center gap-1 rounded-sm text-xs font-medium text-oe-blue-text transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
              >
                {showMore
                  ? t('common.show_less', { defaultValue: 'Show less' })
                  : t('common.show_more', { defaultValue: 'Show more' })}
                {showMore ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </button>
            </>
          )}
          {links && links.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {links.map((l) => (
                <button
                  key={l.label}
                  type="button"
                  onClick={(e) => {
                    // Inner pills must never toggle the card.
                    e.stopPropagation();
                    l.onClick();
                  }}
                  className="inline-flex items-center gap-1 rounded-full border border-oe-blue/30 bg-surface-primary px-2.5 py-1 text-xs font-medium text-oe-blue-text transition-colors hover:bg-oe-blue hover:text-content-inverse"
                >
                  {l.label}
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={(e) => {
            // The X now simply collapses - it must not bubble into the card
            // toggle (which would double-fire), and it no longer hides forever.
            e.stopPropagation();
            collapse();
          }}
          aria-label={t('common.collapse', { defaultValue: 'Collapse' })}
          title={t('common.collapse', { defaultValue: 'Collapse' })}
          className="-mr-1 -mt-1 shrink-0 rounded-md p-1.5 text-content-tertiary opacity-60 transition-all hover:bg-surface-secondary hover:text-content-primary hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
        >
          <X size={15} />
        </button>
      </div>
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * A section you can fold away, and that stays how you left it.
 *
 * An expanded register row is long: the fields, the workflow, the drop
 * zone, the whole correspondence thread. Rendered as one wall it pushes
 * the thing you actually came for off the bottom of the screen, and on
 * a laptop the steps — the part you work from daily — are the first
 * casualty.
 *
 * So: `<details>/<summary>`, a count in the heading so a closed section
 * still tells you what is inside, and the open ones remembered.
 *
 * The state is keyed and persisted, because a section that springs back
 * open on every poll is worse than one that never folded: this page
 * re-renders every 45 seconds.
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight } from 'lucide-react';
import { useMenu } from './ContextMenu';

const STORE_PREFIX = 'ci-fold:';
/** "Expand all / Collapse all" reaches every fold on the page through one event. */
const FOLD_ALL_EVENT = 'ci-fold-all';
function foldAll(open: boolean) {
  window.dispatchEvent(new CustomEvent<{ open: boolean }>(FOLD_ALL_EVENT, { detail: { open } }));
}

function remembered(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(STORE_PREFIX + key);
    return raw === null ? fallback : raw === '1';
  } catch {
    // Private mode / storage disabled - fold still works, it just forgets.
    return fallback;
  }
}

export function Fold({
  id,
  title,
  count,
  hint,
  defaultOpen = true,
  openWhen = false,
  openSignal = 0,
  right,
  children,
}: {
  /** Stable key for the remembered state. Per SECTION, not per item -
   *  "I keep the thread shut" is a habit about the section, not about
   *  one RFQ, and keying per item would relearn it on every new job. */
  id: string;
  title: ReactNode;
  /** Shown beside the title so a shut section still says what is in it. */
  count?: number | string;
  hint?: string;
  defaultOpen?: boolean;
  /** Open the section ONCE, when this becomes true.
   *
   *  `defaultOpen` is read only on mount, so it cannot answer "open if
   *  there is something in here" for content that arrives later - a
   *  prefill from another register, or this job's remembered answers,
   *  both land a beat after the form mounts. This watches instead, and
   *  fires once: a later manual close stays closed. */
  openWhen?: boolean;
  /** Open NOW, every time this number changes (0 = never). The boolean
   *  `openWhen` latches once, which is right for "content arrived" and
   *  wrong for a click: the 📧 badge pressed a second time - after the
   *  person folded the section shut - must open it again, or the click
   *  does nothing and reads as broken. */
  openSignal?: number;
  /** Controls that belong to the section header, not the body. */
  right?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const menu = useMenu();
  const [open, setOpen] = useState(() => remembered(id, defaultOpen));
  const [auto, setAuto] = useState(false);

  useEffect(() => {
    if (!openWhen || auto) return;
    setAuto(true);
    setOpen(true);
  }, [openWhen, auto]);

  useEffect(() => {
    const onAll = (e: Event) => setOpen(!!(e as CustomEvent<{ open: boolean }>).detail?.open);
    window.addEventListener(FOLD_ALL_EVENT, onAll);
    return () => window.removeEventListener(FOLD_ALL_EVENT, onAll);
  }, []);

  useEffect(() => {
    if (openSignal) setOpen(true);
  }, [openSignal]);

  useEffect(() => {
    try {
      localStorage.setItem(STORE_PREFIX + id, open ? '1' : '0');
    } catch {
      /* nothing to do - see remembered() */
    }
  }, [id, open]);

  const toggle = useCallback(() => setOpen((v) => !v), []);

  return (
    <section className={`qfold ${open ? 'on' : ''}`}>
      <div
        className="qfoldhd"
        onContextMenu={(e) =>
          menu.openFromEvent(
            e,
            [
              {
                label: open
                  ? t('ci.fold_close_this', { defaultValue: 'Fold this one away' })
                  : t('ci.fold_open_this', { defaultValue: 'Open this one' }),
                onClick: toggle,
              },
              null,
              { label: t('ci.fold_expand_all', { defaultValue: 'Expand all folds' }), onClick: () => foldAll(true) },
              { label: t('ci.fold_collapse_all', { defaultValue: 'Collapse all folds' }), onClick: () => foldAll(false) },
            ],
            { head: typeof title === 'string' ? title : undefined },
          )
        }
      >
        {menu.element}
        <button
          type="button"
          className="qfoldbtn"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={`fold-${id}`}
          title={hint}
        >
          <ChevronRight className={`qfoldchev ${open ? 'open' : ''}`} />
          <span className="qfoldttl">{title}</span>
          {count !== undefined && count !== '' && <span className="badge">{count}</span>}
        </button>
        {/* Header controls sit OUTSIDE the toggle button: nesting a button
            inside a button is invalid, and clicking "attach" would also
            have folded the section away under the file dialog. */}
        {right && <span className="qfoldact">{right}</span>}
      </div>
      {open && (
        <div className="qfoldbody" id={`fold-${id}`}>
          {children}
        </div>
      )}
    </section>
  );
}

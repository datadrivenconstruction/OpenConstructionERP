// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DocumentExportMenu - one control for "give me this as a document".
 *
 * A split button. The main half downloads the first document straight away,
 * in the language the interface is in, so the usual case is one click. The
 * narrow half opens a menu with every document the screen offers and a
 * document-language choice: a site team that works in one language sends
 * papers to a consultant who reads another, and the two are not the same
 * setting.
 *
 * The control owns the pending state and the failure toast, so a refused
 * download always says what the server said and never ends in silence. The
 * panel is portaled with fixed coordinates because it is mounted inside page
 * headers, drawers and expandable rows, several of which clip their overflow.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ChevronDown, Download, FileDown, FileSpreadsheet, FileText, Loader2 } from 'lucide-react';

import {
  REGISTER_DOCUMENT_LOCALES,
  defaultDocumentLocale,
  documentLocaleName,
} from '@/shared/lib/documentExport';
import { useToastStore } from '@/stores/useToastStore';

export interface DocumentExportItem {
  /** Stable id, used for the pending state and the test id. */
  id: string;
  /** Translated label of the menu entry. */
  label: string;
  /** Picks the icon. `other` is for a download that is neither. */
  kind: 'pdf' | 'xlsx' | 'other';
  /** Translated heading the entry is listed under, when the menu has several documents. */
  group?: string;
  disabled?: boolean;
  /** Start the download in the given document language. Reject to report a failure. */
  run: (locale: string) => Promise<void> | void;
}

export interface DocumentExportMenuProps {
  /** Translated label of the button. */
  label: string;
  /** The documents on offer. The first one is what the main half downloads, unless `primaryId` says otherwise. */
  items: DocumentExportItem[];
  /** Id of the entry the main half downloads. */
  primaryId?: string;
  /** Languages the documents exist in. */
  locales?: readonly string[];
  /** When set the control is disabled and this is its tooltip. */
  disabledReason?: string;
  /** Translated note under the entries, e.g. that filters are not applied. */
  note?: string;
  /** Translated title of a toast shown when a download has been handed to the browser. */
  successTitle?: string;
  /** Translated title of the failure toast; "Export failed" by default. */
  failedTitle?: string;
  /** Icon of the main half; a download arrow by default. */
  icon?: ReactNode;
  size?: 'sm' | 'md';
  className?: string;
  /** Test id of the main half; the other parts derive theirs from it. */
  testId?: string;
  /** `data-guide` anchor of the main half, for a module guide spotlight. */
  guide?: string;
}

const ITEM_ICONS = { pdf: FileDown, xlsx: FileSpreadsheet, other: FileText } as const;

const SIZE_STYLES = {
  sm: { main: 'h-7 px-2.5 text-xs gap-1.5', more: 'h-7 w-6', icon: 14 },
  md: { main: 'h-8 px-3.5 text-sm gap-1.5', more: 'h-8 w-7', icon: 14 },
} as const;

const HALF_STYLES = clsx(
  'inline-flex items-center justify-center font-medium whitespace-nowrap select-none',
  'bg-surface-primary text-content-primary border border-border shadow-xs',
  'hover:bg-surface-secondary active:bg-surface-tertiary transition-colors',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
  'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-surface-primary',
);

export function DocumentExportMenu({
  label,
  items,
  primaryId,
  locales = REGISTER_DOCUMENT_LOCALES,
  disabledReason,
  note,
  successTitle,
  failedTitle,
  icon,
  size = 'sm',
  className,
  testId = 'document-export',
  guide,
}: DocumentExportMenuProps) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  // Null until the reader picks a language, so the default keeps following the
  // interface language when that changes while the screen is open.
  const [pickedLocale, setPickedLocale] = useState<string | null>(null);
  const locale =
    pickedLocale && locales.includes(pickedLocale)
      ? pickedLocale
      : defaultDocumentLocale(locales, i18n.language || null);

  const moreRef = useRef<HTMLButtonElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const languageLabelId = useId();

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const compute = () => {
      const el = wrapRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setPos({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) });
    };
    compute();
    window.addEventListener('resize', compute);
    window.addEventListener('scroll', compute, true);
    return () => {
      window.removeEventListener('resize', compute);
      window.removeEventListener('scroll', compute, true);
    };
  }, [open]);

  // The panel lives in a portal, so "outside" has to be measured against both
  // the control and the panel.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (wrapRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    // Captured, and stopped here: the control is mounted inside drawers that
    // close on Escape themselves, and one Escape should close one thing.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setOpen(false);
      moreRef.current?.focus();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  const start = useCallback(
    async (item: DocumentExportItem, inLocale: string) => {
      setOpen(false);
      setPendingId(item.id);
      try {
        await item.run(inLocale);
        if (successTitle) addToast({ type: 'success', title: successTitle });
      } catch (err) {
        addToast({
          type: 'error',
          title: failedTitle ?? t('common.export_failed', { defaultValue: 'Export failed' }),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setPendingId(null);
      }
    },
    [addToast, successTitle, failedTitle, t],
  );

  const primary = items.find((item) => item.id === primaryId) ?? items[0];
  const busy = pendingId !== null;
  const disabled = Boolean(disabledReason) || !primary;
  const sizes = SIZE_STYLES[size];
  const mainTitle = disabledReason
    ? disabledReason
    : primary
      ? t('doc_export.primary_hint', {
          defaultValue: '{{document}}: {{format}}, {{language}}',
          document: primary.group ?? label,
          format: primary.label,
          language: documentLocaleName(locale),
        })
      : undefined;

  return (
    <div
      ref={wrapRef}
      className={clsx('inline-flex shrink-0 items-stretch', className)}
      // The control sits inside clickable rows; a click on it is never a click on the row.
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        className={clsx(HALF_STYLES, sizes.main, 'rounded-l-md border-r-0')}
        disabled={disabled || busy || primary?.disabled}
        title={mainTitle}
        onClick={() => primary && void start(primary, locale)}
        data-testid={testId}
        data-guide={guide}
      >
        <span className="shrink-0">
          {busy ? <Loader2 size={sizes.icon} className="animate-spin" /> : icon ?? <Download size={sizes.icon} />}
        </span>
        <span>{label}</span>
      </button>
      <button
        ref={moreRef}
        type="button"
        className={clsx(HALF_STYLES, sizes.more, 'rounded-r-md')}
        disabled={disabled || busy}
        title={disabledReason}
        aria-label={t('doc_export.more', { defaultValue: 'Format and language' })}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        data-testid={`${testId}-more`}
      >
        <ChevronDown size={13} />
      </button>
      {open &&
        pos &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label={label}
            style={{ position: 'fixed', top: pos.top, right: pos.right, zIndex: 1000 }}
            className="w-64 rounded-lg border border-border-light bg-surface-elevated py-1 shadow-md animate-fade-in"
            data-testid={`${testId}-menu`}
            onClick={(e) => e.stopPropagation()}
          >
            {locales.length > 1 && (
              <div className="border-b border-border-light px-3 pb-2.5 pt-2">
                <p id={languageLabelId} className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('doc_export.language', { defaultValue: 'Document language' })}
                </p>
                <div role="radiogroup" aria-labelledby={languageLabelId} className="flex gap-1">
                  {locales.map((code) => (
                    <button
                      key={code}
                      type="button"
                      role="radio"
                      aria-checked={code === locale}
                      lang={code}
                      onClick={() => setPickedLocale(code)}
                      className={clsx(
                        'flex-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors',
                        code === locale
                          ? 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                          : 'border-border-light text-content-secondary hover:bg-surface-secondary',
                      )}
                      data-testid={`${testId}-lang-${code}`}
                    >
                      {documentLocaleName(code)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {items.map((item, index) => {
              const Icon = ITEM_ICONS[item.kind];
              // Entries keep the order they were given in; a heading is
              // printed whenever the group changes.
              const heading = item.group && item.group !== items[index - 1]?.group ? item.group : null;
              return (
                <div key={item.id}>
                  {heading && (
                    <p className="px-3 pb-0.5 pt-2 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                      {heading}
                    </p>
                  )}
                  <button
                    type="button"
                    role="menuitem"
                    disabled={item.disabled}
                    onClick={() => void start(item, locale)}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-content-primary transition-colors hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-40"
                    data-testid={`${testId}-item-${item.id}`}
                  >
                    <Icon size={15} className="shrink-0 text-content-tertiary" />
                    {item.label}
                  </button>
                </div>
              );
            })}
            {note && (
              <p className="border-t border-border-light px-3 pb-1.5 pt-2 text-2xs leading-snug text-content-tertiary">
                {note}
              </p>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}

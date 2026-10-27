// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The source document beside the extracted values. A PDF or scan shows the
 * rendered page with a box over the selected value; an Excel sheet, an email or
 * pasted text shows its lines with the selected one highlighted.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchPageImage, type Anchor, type Quote } from './api';
import { sameAnchor } from './format';

export function DocumentPane({ quote, anchor }: { quote: Quote; anchor: Anchor | null }) {
  const { t } = useTranslation();
  const pages = quote.document.pages ?? [];
  const [page, setPage] = useState(1);
  const [src, setSrc] = useState<string | null>(null);
  const highlighted = useRef<HTMLLIElement | null>(null);
  const visual = quote.has_file && pages.length > 0 && (quote.source_kind === 'pdf' || quote.source_kind === 'scan');

  useEffect(() => {
    if (anchor?.page) setPage(anchor.page);
  }, [anchor]);

  useEffect(() => {
    if (!visual) return undefined;
    let url: string | null = null;
    let cancelled = false;
    fetchPageImage(quote.id, page)
      .then((u) => {
        url = u;
        if (!cancelled) setSrc(u);
      })
      .catch(() => setSrc(null));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [quote.id, page, visual]);

  useEffect(() => {
    highlighted.current?.scrollIntoView?.({ block: 'center' });
  }, [anchor]);

  if (visual) {
    const size = pages.find((p) => p.page === page) ?? pages[0]!;
    const box = anchor?.page === page ? anchor.bbox : undefined;
    return (
      <div className="flex flex-col gap-2" data-testid="quote-document">
        <div className="flex items-center gap-2 text-xs text-content-secondary">
          <button
            type="button"
            className="rounded border px-2 py-0.5 disabled:opacity-40"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            {t('quote_capture.prev_page', 'Previous')}
          </button>
          <span>{t('quote_capture.page_of', 'Page {{page}} of {{count}}', { page, count: pages.length })}</span>
          <button
            type="button"
            className="rounded border px-2 py-0.5 disabled:opacity-40"
            disabled={page >= pages.length}
            onClick={() => setPage((p) => p + 1)}
          >
            {t('quote_capture.next_page', 'Next')}
          </button>
        </div>
        <div className="relative w-full overflow-hidden rounded border bg-white">
          {src ? (
            <img src={src} alt={t('quote_capture.page_image', 'Quote page')} className="block w-full" />
          ) : (
            <div className="p-6 text-sm text-content-secondary">{t('quote_capture.loading_page', 'Loading page...')}</div>
          )}
          {box && (
            <div
              data-testid="quote-anchor-box"
              className="pointer-events-none absolute rounded-sm border-2 border-amber-500 bg-amber-300/25"
              style={{
                left: `${(box[0] / size.width) * 100}%`,
                top: `${(box[1] / size.height) * 100}%`,
                width: `${((box[2] - box[0]) / size.width) * 100}%`,
                height: `${((box[3] - box[1]) / size.height) * 100}%`,
              }}
            />
          )}
        </div>
      </div>
    );
  }

  const lines = quote.document.lines ?? [];
  return (
    <ol className="max-h-[70vh] overflow-auto rounded border p-2 font-mono text-xs" data-testid="quote-document" dir="auto">
      {lines.length === 0 && <li className="text-content-secondary">{t('quote_capture.no_text', 'No text could be read from this document.')}</li>}
      {lines.map((ln, i) => {
        const on = sameAnchor(ln.anchor, anchor);
        return (
          <li
            key={i}
            ref={on ? highlighted : undefined}
            data-active={on || undefined}
            className={`whitespace-pre-wrap px-1 ${on ? 'rounded bg-amber-200/70 dark:bg-amber-700/50' : ''}`}
          >
            <span className="mr-2 select-none text-content-tertiary">
              {ln.anchor.sheet ? `${ln.anchor.sheet}!${ln.anchor.row}` : ln.anchor.line ?? i + 1}
            </span>
            {ln.text}
          </li>
        );
      })}
    </ol>
  );
}

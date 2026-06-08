/**
 * PdfCompare — professional-grade PDF revision comparison viewer.
 *
 * Three compare modes:
 *  - Overlay (onion-skin): B drawn over A with an opacity slider.
 *  - Difference: A→red, B→blue, shared/unchanged→grey; per-pixel
 *    luminance-threshold diff on offscreen canvases.
 *  - Side-by-side: two panes with synchronised pan & zoom.
 *
 * Reuses the existing pdf.js worker configured in InlinePdfAnnotator
 * (GlobalWorkerOptions.workerSrc set once per module graph — importing
 * pdfjs-dist here is safe; the worker URL is already set).
 */

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
  useLayoutEffect,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import * as pdfjsLib from 'pdfjs-dist';
import {
  ArrowLeft,
  ZoomIn,
  ZoomOut,
  ChevronLeft,
  ChevronRight,
  Layers,
  Diff,
  LayoutPanelLeft,
  ArrowLeftRight,
  Maximize2,
  Loader2,
  AlertCircle,
  FileText,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { Slider } from '@/shared/ui/Slider';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet } from '@/shared/lib/api';

// ── Types ───────────────────────────────────────────────────────────────────

type CompareMode = 'overlay' | 'diff' | 'sidebyside';
const COMPARE_MODE_IDS: readonly CompareMode[] = ['overlay', 'diff', 'sidebyside'];

interface DocItem {
  id: string;
  name: string;
  mime_type: string | null;
  filename: string;
}

interface PanState {
  x: number;
  y: number;
  dragging: boolean;
  startX: number;
  startY: number;
}

// ── Constants ────────────────────────────────────────────────────────────────

const ZOOM_LEVELS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0];
const DIFF_THRESHOLD = 30; // luminance delta to be considered "changed"

// ── PDF loading helper ────────────────────────────────────────────────────────

async function loadPdfFromDocId(documentId: string): Promise<pdfjsLib.PDFDocumentProxy> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api/v1/documents/${documentId}/download/`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  const buf = await res.arrayBuffer();
  return pdfjsLib.getDocument({ data: buf }).promise;
}

// ── usePdfDoc hook ────────────────────────────────────────────────────────────

function usePdfDoc(documentId: string | null) {
  const [doc, setDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const docRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);

  useEffect(() => {
    if (!documentId) {
      setDoc(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDoc(null);

    loadPdfFromDocId(documentId).then(
      (loaded) => {
        if (cancelled) {
          loaded.destroy?.();
          return;
        }
        // Destroy previous doc to release native resources
        docRef.current?.destroy?.();
        docRef.current = loaded;
        setDoc(loaded);
        setLoading(false);
      },
      (err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      },
    );

    return () => {
      cancelled = true;
    };
  }, [documentId]);

  // Destroy on unmount
  useEffect(() => {
    return () => {
      docRef.current?.destroy?.();
    };
  }, []);

  return { doc, loading, error };
}

// ── renderPageToOffscreen ─────────────────────────────────────────────────────

/**
 * Render a PDF page to an OffscreenCanvas at devicePixelRatio for crispness.
 * Returns the canvas (or null if cancelled) plus a cancel function.
 */
function renderPageToOffscreen(
  page: pdfjsLib.PDFPageProxy,
  zoom: number,
): { promise: Promise<OffscreenCanvas | null>; cancel: () => void } {
  let cancelled = false;
  const dpr = window.devicePixelRatio || 1;
  const viewport = page.getViewport({ scale: zoom * dpr });
  const canvas = new OffscreenCanvas(Math.round(viewport.width), Math.round(viewport.height));
  const ctx = canvas.getContext('2d') as OffscreenCanvasRenderingContext2D | null;

  if (!ctx) {
    return {
      promise: Promise.resolve(null),
      cancel: () => {
        cancelled = true;
      },
    };
  }

  const task = page.render({ canvasContext: ctx as unknown as CanvasRenderingContext2D, viewport });

  const promise: Promise<OffscreenCanvas | null> = task.promise.then(
    () => (cancelled ? null : canvas),
    (err: unknown) => {
      if (
        err &&
        typeof err === 'object' &&
        'name' in err &&
        (err as { name: string }).name === 'RenderingCancelledException'
      ) {
        return null;
      }
      throw err;
    },
  );

  return {
    promise,
    cancel: () => {
      cancelled = true;
      task.cancel?.();
    },
  };
}

// ── Per-pane canvas renderer ──────────────────────────────────────────────────

interface PaneCanvasProps {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null;
  page: number;
  zoom: number;
  pan: { x: number; y: number };
  onPanStart: (e: React.MouseEvent) => void;
  onPanMove: (e: React.MouseEvent) => void;
  onPanEnd: () => void;
  label: string;
  docName: string;
  loading?: boolean;
}

function PaneCanvas({
  pdfDoc,
  page,
  zoom,
  pan,
  onPanStart,
  onPanMove,
  onPanEnd,
  label,
  docName,
  loading: externalLoading,
}: PaneCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    let cancel = () => {};
    setRendering(true);
    setRenderError(null);

    pdfDoc.getPage(Math.min(page, pdfDoc.numPages)).then(
      (p) => {
        const { promise, cancel: cancelFn } = renderPageToOffscreen(p, zoom);
        cancel = cancelFn;
        return promise;
      },
      (err: unknown) => {
        setRenderError(String(err));
        setRendering(false);
        return null;
      },
    ).then(
      (offscreen) => {
        if (!offscreen || !canvasRef.current) {
          setRendering(false);
          return;
        }
        const canvas = canvasRef.current;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = offscreen.width;
        canvas.height = offscreen.height;
        canvas.style.width = `${Math.round(offscreen.width / dpr)}px`;
        canvas.style.height = `${Math.round(offscreen.height / dpr)}px`;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(offscreen as unknown as CanvasImageSource, 0, 0);
        }
        setRendering(false);
      },
      (err: unknown) => {
        setRenderError(String(err));
        setRendering(false);
      },
    );

    return () => cancel();
  }, [pdfDoc, page, zoom]);

  const isLoading = externalLoading || rendering;

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* Pane label */}
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border-light bg-surface-secondary/60 shrink-0">
        <FileText size={12} className="text-content-tertiary shrink-0" />
        <span className="text-xs font-semibold text-content-secondary uppercase tracking-wide">
          {label}
        </span>
        <span className="text-xs text-content-tertiary truncate ml-1">{docName}</span>
      </div>
      {/* Canvas scroll area */}
      <div
        className="flex-1 overflow-auto bg-neutral-100 dark:bg-neutral-900 relative cursor-grab active:cursor-grabbing select-none"
        style={{ minHeight: 0 }}
      >
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center z-10 bg-neutral-100/80 dark:bg-neutral-900/80">
            <Loader2 size={24} className="text-oe-blue animate-spin" />
          </div>
        )}
        {renderError && !isLoading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-10 gap-2 p-4 text-center">
            <AlertCircle size={24} className="text-semantic-error" />
            <p className="text-xs text-semantic-error">{renderError}</p>
          </div>
        )}
        <div
          style={{ transform: `translate(${pan.x}px, ${pan.y}px)`, display: 'inline-block' }}
          onMouseDown={onPanStart}
          onMouseMove={onPanMove}
          onMouseUp={onPanEnd}
          onMouseLeave={onPanEnd}
        >
          <canvas
            ref={canvasRef}
            className="shadow-md rounded"
            aria-label={t('pdf_compare.page_canvas_label', {
              defaultValue: 'PDF page {{page}}',
              page,
            })}
          />
        </div>
        {!pdfDoc && !isLoading && (
          <div className="absolute inset-0 flex items-center justify-center text-content-tertiary text-xs">
            {t('pdf_compare.select_doc', { defaultValue: 'Select a document above' })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── DiffCanvas ────────────────────────────────────────────────────────────────

interface DiffCanvasProps {
  docA: pdfjsLib.PDFDocumentProxy | null;
  docB: pdfjsLib.PDFDocumentProxy | null;
  page: number;
  zoom: number;
  pan: { x: number; y: number };
  onPanStart: (e: React.MouseEvent) => void;
  onPanMove: (e: React.MouseEvent) => void;
  onPanEnd: () => void;
  onChangePct: (pct: number) => void;
}

function DiffCanvas({
  docA,
  docB,
  page,
  zoom,
  pan,
  onPanStart,
  onPanMove,
  onPanEnd,
  onChangePct,
}: DiffCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (!docA || !docB || !canvasRef.current) return;

    let cancelA = () => {};
    let cancelB = () => {};
    setRendering(true);
    setRenderError(null);

    const pageA = Math.min(page, docA.numPages);
    const pageB = Math.min(page, docB.numPages);

    Promise.all([docA.getPage(pageA), docB.getPage(pageB)]).then(
      ([pa, pb]) => {
        const { promise: promA, cancel: cA } = renderPageToOffscreen(pa, zoom);
        const { promise: promB, cancel: cB } = renderPageToOffscreen(pb, zoom);
        cancelA = cA;
        cancelB = cB;
        return Promise.all([promA, promB]);
      },
      (err: unknown) => {
        setRenderError(String(err));
        setRendering(false);
        return [null, null] as [null, null];
      },
    ).then(
      ([canvA, canvB]) => {
        if (!canvA || !canvB || !canvasRef.current) {
          setRendering(false);
          return;
        }

        // Compute per-pixel diff
        const w = Math.max(canvA.width, canvB.width);
        const h = Math.max(canvA.height, canvB.height);

        // Helper: get ImageData from an OffscreenCanvas at target size
        const getPixels = (src: OffscreenCanvas): Uint8ClampedArray => {
          const tmp = new OffscreenCanvas(w, h);
          const ctx2 = tmp.getContext('2d') as OffscreenCanvasRenderingContext2D | null;
          if (!ctx2) return new Uint8ClampedArray(w * h * 4);
          ctx2.fillStyle = '#ffffff';
          ctx2.fillRect(0, 0, w, h);
          ctx2.drawImage(src as unknown as CanvasImageSource, 0, 0);
          return ctx2.getImageData(0, 0, w, h).data;
        };

        const dataA = getPixels(canvA);
        const dataB = getPixels(canvB);

        // Build diff image
        const out = new OffscreenCanvas(w, h);
        const outCtx = out.getContext('2d') as OffscreenCanvasRenderingContext2D | null;
        if (!outCtx) return;

        const imgData = outCtx.createImageData(w, h);
        const buf = imgData.data;
        let changedPixels = 0;
        const totalPixels = w * h;

        for (let i = 0; i < totalPixels; i++) {
          const idx = i * 4;
          const rA = dataA[idx]!;
          const gA = dataA[idx + 1]!;
          const bA = dataA[idx + 2]!;
          const rB = dataB[idx]!;
          const gB = dataB[idx + 1]!;
          const bB = dataB[idx + 2]!;

          // Luminance (CCIR 601)
          const lumA = 0.299 * rA + 0.587 * gA + 0.114 * bA;
          const lumB = 0.299 * rB + 0.587 * gB + 0.114 * bB;

          // Treat near-white as background (blank page area)
          const isWhiteA = lumA > 240;
          const isWhiteB = lumB > 240;

          const delta = Math.abs(lumA - lumB);
          const changed = delta > DIFF_THRESHOLD;

          if (changed) changedPixels++;

          if (isWhiteA && isWhiteB) {
            // Both white → transparent/white background
            buf[idx] = 255;
            buf[idx + 1] = 255;
            buf[idx + 2] = 255;
            buf[idx + 3] = 255;
          } else if (changed && !isWhiteA && isWhiteB) {
            // Only in A (removed) → red
            buf[idx] = 239;
            buf[idx + 1] = 68;
            buf[idx + 2] = 68;
            buf[idx + 3] = 220;
          } else if (changed && isWhiteA && !isWhiteB) {
            // Only in B (added) → blue
            buf[idx] = 59;
            buf[idx + 1] = 130;
            buf[idx + 2] = 246;
            buf[idx + 3] = 220;
          } else if (changed) {
            // Both changed — blend: A red + B blue
            buf[idx] = Math.round((rA + rB) / 2);
            buf[idx + 1] = 68;
            buf[idx + 2] = Math.round((bA + bB) / 2);
            buf[idx + 3] = 210;
          } else {
            // Shared/unchanged → desaturated grey
            const grey = Math.round(lumA * 0.4);
            buf[idx] = grey;
            buf[idx + 1] = grey;
            buf[idx + 2] = grey;
            buf[idx + 3] = 200;
          }
        }

        outCtx.putImageData(imgData, 0, 0);
        onChangePct(Math.round((changedPixels / totalPixels) * 100));

        const canvas = canvasRef.current;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = w;
        canvas.height = h;
        canvas.style.width = `${Math.round(w / dpr)}px`;
        canvas.style.height = `${Math.round(h / dpr)}px`;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, w, h);
          ctx.drawImage(out as unknown as CanvasImageSource, 0, 0);
        }
        setRendering(false);
      },
      (err: unknown) => {
        setRenderError(String(err));
        setRendering(false);
      },
    );

    return () => {
      cancelA();
      cancelB();
    };
  }, [docA, docB, page, zoom, onChangePct]);

  return (
    <div
      className="flex-1 overflow-auto bg-neutral-100 dark:bg-neutral-900 relative cursor-grab active:cursor-grabbing select-none"
      style={{ minHeight: 0 }}
    >
      {rendering && (
        <div className="absolute inset-0 flex items-center justify-center z-10 bg-neutral-100/80 dark:bg-neutral-900/80">
          <Loader2 size={24} className="text-oe-blue animate-spin" />
        </div>
      )}
      {renderError && !rendering && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10 gap-2 p-4 text-center">
          <AlertCircle size={24} className="text-semantic-error" />
          <p className="text-xs text-semantic-error">{renderError}</p>
        </div>
      )}
      {(!docA || !docB) && !rendering && !renderError && (
        <div className="absolute inset-0 flex items-center justify-center text-content-tertiary text-xs">
          {t('pdf_compare.select_both', {
            defaultValue: 'Select both documents to compute diff',
          })}
        </div>
      )}
      <div
        style={{ transform: `translate(${pan.x}px, ${pan.y}px)`, display: 'inline-block' }}
        onMouseDown={onPanStart}
        onMouseMove={onPanMove}
        onMouseUp={onPanEnd}
        onMouseLeave={onPanEnd}
      >
        <canvas ref={canvasRef} className="shadow-md rounded" />
      </div>
    </div>
  );
}

// ── OverlayCanvas ─────────────────────────────────────────────────────────────

interface OverlayCanvasProps {
  docA: pdfjsLib.PDFDocumentProxy | null;
  docB: pdfjsLib.PDFDocumentProxy | null;
  page: number;
  zoom: number;
  opacity: number; // 0–100, opacity of B over A
  pan: { x: number; y: number };
  onPanStart: (e: React.MouseEvent) => void;
  onPanMove: (e: React.MouseEvent) => void;
  onPanEnd: () => void;
}

function OverlayCanvas({
  docA,
  docB,
  page,
  zoom,
  opacity,
  pan,
  onPanStart,
  onPanMove,
  onPanEnd,
}: OverlayCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (!docA || !canvasRef.current) return;

    let cancelA = () => {};
    let cancelB = () => {};
    setRendering(true);
    setRenderError(null);

    const pageA = Math.min(page, docA.numPages);
    const pageB = docB ? Math.min(page, docB.numPages) : null;

    const getPageB = pageB !== null && docB ? docB.getPage(pageB) : Promise.resolve(null);

    Promise.all([docA.getPage(pageA), getPageB]).then(
      ([pa, pb]) => {
        const { promise: promA, cancel: cA } = renderPageToOffscreen(pa, zoom);
        cancelA = cA;

        let promB: Promise<OffscreenCanvas | null> = Promise.resolve(null);
        if (pb) {
          const { promise, cancel: cB } = renderPageToOffscreen(pb, zoom);
          promB = promise;
          cancelB = cB;
        }

        return Promise.all([promA, promB]);
      },
      (err: unknown) => {
        setRenderError(String(err));
        setRendering(false);
        return [null, null] as [null, null];
      },
    ).then(
      ([canvA, canvB]) => {
        if (!canvA || !canvasRef.current) {
          setRendering(false);
          return;
        }
        const dpr = window.devicePixelRatio || 1;
        const w = canvA.width;
        const h = canvA.height;

        const canvas = canvasRef.current;
        canvas.width = w;
        canvas.height = h;
        canvas.style.width = `${Math.round(w / dpr)}px`;
        canvas.style.height = `${Math.round(h / dpr)}px`;

        const ctx = canvas.getContext('2d');
        if (!ctx) {
          setRendering(false);
          return;
        }

        ctx.clearRect(0, 0, w, h);
        // Draw A at full opacity
        ctx.globalAlpha = 1;
        ctx.drawImage(canvA as unknown as CanvasImageSource, 0, 0);

        // Draw B at configured opacity
        if (canvB) {
          ctx.globalAlpha = opacity / 100;
          ctx.drawImage(canvB as unknown as CanvasImageSource, 0, 0);
          ctx.globalAlpha = 1;
        }

        setRendering(false);
      },
      (err: unknown) => {
        setRenderError(String(err));
        setRendering(false);
      },
    );

    return () => {
      cancelA();
      cancelB();
    };
  }, [docA, docB, page, zoom, opacity]);

  return (
    <div
      className="flex-1 overflow-auto bg-neutral-100 dark:bg-neutral-900 relative cursor-grab active:cursor-grabbing select-none"
      style={{ minHeight: 0 }}
    >
      {rendering && (
        <div className="absolute inset-0 flex items-center justify-center z-10 bg-neutral-100/80 dark:bg-neutral-900/80">
          <Loader2 size={24} className="text-oe-blue animate-spin" />
        </div>
      )}
      {renderError && !rendering && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10 gap-2 p-4">
          <AlertCircle size={24} className="text-semantic-error" />
          <p className="text-xs text-semantic-error">{renderError}</p>
        </div>
      )}
      {!docA && !rendering && !renderError && (
        <div className="absolute inset-0 flex items-center justify-center text-content-tertiary text-xs">
          {t('pdf_compare.select_doc_a', {
            defaultValue: 'Select document A (old revision)',
          })}
        </div>
      )}
      <div
        style={{ transform: `translate(${pan.x}px, ${pan.y}px)`, display: 'inline-block' }}
        onMouseDown={onPanStart}
        onMouseMove={onPanMove}
        onMouseUp={onPanEnd}
        onMouseLeave={onPanEnd}
      >
        <canvas ref={canvasRef} className="shadow-md rounded" />
      </div>
    </div>
  );
}

// ── usePan hook ───────────────────────────────────────────────────────────────

function usePan() {
  const [pan, setPan] = useState<PanState>({
    x: 0,
    y: 0,
    dragging: false,
    startX: 0,
    startY: 0,
  });
  const panRef = useRef(pan);
  useLayoutEffect(() => {
    panRef.current = pan;
  });

  const onStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setPan((p) => ({ ...p, dragging: true, startX: e.clientX - p.x, startY: e.clientY - p.y }));
  }, []);

  const onMove = useCallback((e: React.MouseEvent) => {
    if (!panRef.current.dragging) return;
    setPan((p) => ({
      ...p,
      x: e.clientX - p.startX,
      y: e.clientY - p.startY,
    }));
  }, []);

  const onEnd = useCallback(() => {
    setPan((p) => ({ ...p, dragging: false }));
  }, []);

  const reset = useCallback(() => {
    setPan({ x: 0, y: 0, dragging: false, startX: 0, startY: 0 });
  }, []);

  return { pan, onStart, onMove, onEnd, reset };
}

// ── Main PdfCompare page ──────────────────────────────────────────────────────

export function PdfComparePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Pre-select from query params (e.g. ?docA=xxx&docB=yyy from MarkupsPage)
  const [selectedDocAId, setSelectedDocAId] = useState<string>(
    searchParams.get('docA') ?? '',
  );
  const [selectedDocBId, setSelectedDocBId] = useState<string>(
    searchParams.get('docB') ?? '',
  );

  const [mode, setMode] = useState<CompareMode>('overlay');
  const onCompareModeKeyDown = useTabKeyboardNav<CompareMode>({
    ids: COMPARE_MODE_IDS,
    activeId: mode,
    onChange: setMode,
    orientation: 'horizontal',
  });
  const [zoom, setZoom] = useState(1.0);
  const [page, setPage] = useState(1);
  const [overlayOpacity, setOverlayOpacity] = useState(50);
  const [changePct, setChangePct] = useState<number | null>(null);

  const panA = usePan();
  const panB = usePan();
  const panMain = usePan();

  const { doc: docA, loading: loadingA, error: errorA } = usePdfDoc(selectedDocAId || null);
  const { doc: docB, loading: loadingB, error: errorB } = usePdfDoc(selectedDocBId || null);

  // Effective page count (clamped to the smaller of the two docs)
  const totalPages = useMemo(() => {
    if (!docA && !docB) return 1;
    if (docA && !docB) return docA.numPages;
    if (!docA && docB) return docB.numPages;
    return Math.min(docA!.numPages, docB!.numPages);
  }, [docA, docB]);

  const maxPages = useMemo(() => {
    if (!docA && !docB) return 1;
    if (docA && !docB) return docA.numPages;
    if (!docA && docB) return docB.numPages;
    return Math.max(docA!.numPages, docB!.numPages);
  }, [docA, docB]);

  // Reset page when docs change
  useEffect(() => {
    setPage(1);
    setChangePct(null);
  }, [selectedDocAId, selectedDocBId]);

  // Reset pans on mode/zoom/page change
  useEffect(() => {
    panA.reset();
    panB.reset();
    panMain.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, zoom, page]);

  const { data: documents = [], isLoading: loadingDocs } = useQuery<DocItem[]>({
    queryKey: ['documents-for-compare', activeProjectId],
    queryFn: () => apiGet<DocItem[]>(`/v1/documents/?project_id=${activeProjectId}`),
    enabled: !!activeProjectId,
    staleTime: 60_000,
  });

  // Only PDF documents
  const pdfDocs = useMemo(
    () =>
      documents.filter(
        (d) =>
          d.mime_type === 'application/pdf' ||
          d.filename?.toLowerCase().endsWith('.pdf'),
      ),
    [documents],
  );

  const docAName = useMemo(
    () => pdfDocs.find((d) => d.id === selectedDocAId)?.name ?? selectedDocAId,
    [pdfDocs, selectedDocAId],
  );
  const docBName = useMemo(
    () => pdfDocs.find((d) => d.id === selectedDocBId)?.name ?? selectedDocBId,
    [pdfDocs, selectedDocBId],
  );

  const zoomIdx = ZOOM_LEVELS.indexOf(zoom);

  const handleZoomIn = useCallback(() => {
    setZoom((z) => {
      const idx = ZOOM_LEVELS.indexOf(z);
      return ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, idx + 1)] ?? z;
    });
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoom((z) => {
      const idx = ZOOM_LEVELS.indexOf(z);
      return ZOOM_LEVELS[Math.max(0, idx - 1)] ?? z;
    });
  }, []);

  const handleSwap = useCallback(() => {
    setSelectedDocAId((a) => {
      const prev = a;
      setSelectedDocBId(a);
      return prev;
    });
    setSelectedDocAId(selectedDocBId);
    setSelectedDocBId(selectedDocAId);
    setChangePct(null);
  }, [selectedDocAId, selectedDocBId]);

  const handleReset = useCallback(() => {
    setZoom(1.0);
    setPage(1);
    setOverlayOpacity(50);
    setChangePct(null);
    panA.reset();
    panB.reset();
    panMain.reset();
  }, [panA, panB, panMain]);

  const MODES: { id: CompareMode; label: string; icon: React.ElementType }[] = [
    { id: 'overlay', label: t('pdf_compare.mode_overlay', { defaultValue: 'Overlay' }), icon: Layers },
    { id: 'diff', label: t('pdf_compare.mode_diff', { defaultValue: 'Difference' }), icon: Diff },
    { id: 'sidebyside', label: t('pdf_compare.mode_side', { defaultValue: 'Side-by-side' }), icon: LayoutPanelLeft },
  ];

  const inputCls =
    'h-8 rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors';

  const selectCls = inputCls + ' pr-7 appearance-none cursor-pointer';

  return (
    <div className="flex flex-col h-screen max-h-screen overflow-hidden bg-surface-primary animate-fade-in">
      {/* ── Top toolbar ────────────────────────────────────────────────── */}
      <div className="shrink-0 px-4 py-2 border-b border-border-light bg-surface-elevated flex items-center gap-2 flex-wrap">
        {/* Back */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate('/markups')}
          icon={<ArrowLeft size={14} />}
          aria-label={t('common.back', { defaultValue: 'Back' })}
        >
          <span className="hidden sm:inline">
            {t('pdf_compare.back_to_markups', { defaultValue: 'Markups' })}
          </span>
        </Button>

        <div className="w-px h-5 bg-border-light" />

        {/* Doc A picker */}
        <div className="flex items-center gap-1.5">
          <span
            className="text-xs font-bold text-semantic-error/80 uppercase"
            title={t('pdf_compare.doc_a_old', { defaultValue: 'Old revision (A)' })}
          >
            A
          </span>
          {loadingDocs ? (
            <Loader2 size={14} className="animate-spin text-content-tertiary" />
          ) : (
            <select
              value={selectedDocAId}
              onChange={(e) => {
                setSelectedDocAId(e.target.value);
                setChangePct(null);
              }}
              className={selectCls + ' max-w-[160px]'}
              aria-label={t('pdf_compare.select_doc_a_label', {
                defaultValue: 'Select document A (old)',
              })}
            >
              <option value="">
                {t('pdf_compare.choose_doc', { defaultValue: '- choose PDF -' })}
              </option>
              {pdfDocs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
          {loadingA && <Loader2 size={12} className="animate-spin text-content-tertiary shrink-0" />}
          {errorA && (
            <span title={errorA}>
              <AlertCircle size={13} className="text-semantic-error" />
            </span>
          )}
        </div>

        {/* Swap button */}
        <button
          onClick={handleSwap}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary transition-colors"
          aria-label={t('pdf_compare.swap', { defaultValue: 'Swap A and B' })}
          title={t('pdf_compare.swap', { defaultValue: 'Swap A and B' })}
        >
          <ArrowLeftRight size={14} />
        </button>

        {/* Doc B picker */}
        <div className="flex items-center gap-1.5">
          <span
            className="text-xs font-bold text-oe-blue uppercase"
            title={t('pdf_compare.doc_b_new', { defaultValue: 'New revision (B)' })}
          >
            B
          </span>
          {loadingDocs ? (
            <Loader2 size={14} className="animate-spin text-content-tertiary" />
          ) : (
            <select
              value={selectedDocBId}
              onChange={(e) => {
                setSelectedDocBId(e.target.value);
                setChangePct(null);
              }}
              className={selectCls + ' max-w-[160px]'}
              aria-label={t('pdf_compare.select_doc_b_label', {
                defaultValue: 'Select document B (new)',
              })}
            >
              <option value="">
                {t('pdf_compare.choose_doc', { defaultValue: '- choose PDF -' })}
              </option>
              {pdfDocs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
          {loadingB && <Loader2 size={12} className="animate-spin text-content-tertiary shrink-0" />}
          {errorB && (
            <span title={errorB}>
              <AlertCircle size={13} className="text-semantic-error" />
            </span>
          )}
        </div>

        <div className="w-px h-5 bg-border-light" />

        {/* Mode selector */}
        <div
          className="inline-flex items-center rounded-lg border border-border-light bg-surface-primary p-0.5"
          role="tablist"
          aria-label={t('pdf_compare.compare_mode', { defaultValue: 'Compare mode' })}
          onKeyDown={onCompareModeKeyDown}
        >
          {MODES.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`pdf-compare-mode-tab-${id}`}
              aria-selected={mode === id}
              aria-controls={`pdf-compare-mode-panel-${id}`}
              tabIndex={mode === id ? 0 : -1}
              onClick={() => setMode(id)}
              className={`flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                mode === id
                  ? 'bg-oe-blue text-white'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
              title={label}
            >
              <Icon size={13} />
              <span className="hidden md:inline">{label}</span>
            </button>
          ))}
        </div>

        <div className="w-px h-5 bg-border-light" />

        {/* Zoom */}
        <button
          onClick={handleZoomOut}
          disabled={zoomIdx <= 0}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40 transition-colors"
          aria-label={t('common.zoom_out', { defaultValue: 'Zoom out' })}
        >
          <ZoomOut size={14} />
        </button>
        <span className="text-2xs text-content-tertiary tabular-nums w-10 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={handleZoomIn}
          disabled={zoomIdx >= ZOOM_LEVELS.length - 1}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40 transition-colors"
          aria-label={t('common.zoom_in', { defaultValue: 'Zoom in' })}
        >
          <ZoomIn size={14} />
        </button>

        <div className="w-px h-5 bg-border-light" />

        {/* Page navigation */}
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40 transition-colors"
          aria-label={t('common.previous_page', { defaultValue: 'Previous page' })}
        >
          <ChevronLeft size={14} />
        </button>
        <span className="text-2xs text-content-secondary tabular-nums">
          {page} / {maxPages}
          {totalPages < maxPages && (
            <span
              className="ml-1 text-amber-500"
              title={t('pdf_compare.page_count_mismatch', {
                defaultValue: 'Documents have different page counts; clamped to {{min}}',
                min: totalPages,
              })}
            >
              *
            </span>
          )}
        </span>
        <button
          onClick={() => setPage((p) => Math.min(maxPages, p + 1))}
          disabled={page >= maxPages}
          className="p-1.5 rounded-md text-content-secondary hover:bg-surface-secondary disabled:opacity-40 transition-colors"
          aria-label={t('common.next_page', { defaultValue: 'Next page' })}
        >
          <ChevronRight size={14} />
        </button>

        {/* Diff change indicator */}
        {mode === 'diff' && changePct !== null && (
          <>
            <div className="w-px h-5 bg-border-light" />
            <span
              className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                changePct > 20
                  ? 'bg-semantic-error/10 text-semantic-error'
                  : changePct > 5
                  ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400'
                  : 'bg-green-100 text-green-700 dark:bg-green-900/20 dark:text-green-400'
              }`}
              title={t('pdf_compare.change_pct_title', {
                defaultValue: 'Percentage of page area that changed',
              })}
            >
              {changePct > 0 ? `~${changePct}%` : t('pdf_compare.no_change', { defaultValue: 'No change' })}
              {' '}
              {t('pdf_compare.changed', { defaultValue: 'changed' })}
            </span>
          </>
        )}

        {/* Spacer + reset */}
        <div className="flex-1" />
        <button
          onClick={handleReset}
          className="text-xs text-content-tertiary hover:text-content-secondary transition-colors"
          title={t('pdf_compare.reset', { defaultValue: 'Reset zoom, page and pan' })}
        >
          <Maximize2 size={14} />
        </button>
      </div>

      {/* ── Overlay opacity slider (only in overlay mode) ──────────────── */}
      {mode === 'overlay' && (
        <div className="shrink-0 px-4 py-2 border-b border-border-light bg-surface-secondary/40 flex items-center gap-4">
          <span className="text-xs font-medium text-content-secondary uppercase tracking-wide shrink-0">
            {t('pdf_compare.opacity_b', { defaultValue: 'B opacity' })}
          </span>
          <div className="flex-1 max-w-xs">
            <Slider
              value={overlayOpacity}
              onChange={setOverlayOpacity}
              min={0}
              max={100}
              step={1}
              format={(v) => `${v}%`}
            />
          </div>
          <div className="flex items-center gap-3 text-2xs text-content-tertiary shrink-0">
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-full border-2 border-neutral-400 bg-white inline-block" />
              A
            </span>
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-full bg-oe-blue inline-block" />
              B
            </span>
          </div>
        </div>
      )}

      {/* ── Diff legend (only in diff mode) ────────────────────────────── */}
      {mode === 'diff' && (
        <div className="shrink-0 px-4 py-1.5 border-b border-border-light bg-surface-secondary/40 flex items-center gap-4 text-2xs text-content-secondary">
          <span className="font-medium uppercase tracking-wide text-content-tertiary">
            {t('pdf_compare.legend', { defaultValue: 'Legend' })}:
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-2 rounded bg-red-400 inline-block" />
            {t('pdf_compare.removed', { defaultValue: 'Removed (A only)' })}
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-2 rounded bg-blue-400 inline-block" />
            {t('pdf_compare.added', { defaultValue: 'Added (B only)' })}
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-2 rounded bg-neutral-400 inline-block" />
            {t('pdf_compare.unchanged', { defaultValue: 'Unchanged' })}
          </span>
        </div>
      )}

      {/* ── Canvas area ────────────────────────────────────────────────── */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {mode === 'sidebyside' ? (
          <>
            <div className="flex-1 flex flex-col border-r border-border-light min-w-0">
              <PaneCanvas
                pdfDoc={docA}
                page={page}
                zoom={zoom}
                pan={panA.pan}
                onPanStart={panA.onStart}
                onPanMove={panA.onMove}
                onPanEnd={panA.onEnd}
                label={t('pdf_compare.label_a', { defaultValue: 'A - Old' })}
                docName={docAName}
                loading={loadingA}
              />
            </div>
            <div className="flex-1 flex flex-col min-w-0">
              <PaneCanvas
                pdfDoc={docB}
                page={page}
                zoom={zoom}
                pan={panB.pan}
                onPanStart={panB.onStart}
                onPanMove={panB.onMove}
                onPanEnd={panB.onEnd}
                label={t('pdf_compare.label_b', { defaultValue: 'B - New' })}
                docName={docBName}
                loading={loadingB}
              />
            </div>
          </>
        ) : mode === 'overlay' ? (
          <div className="flex-1 flex flex-col min-w-0">
            {/* Overlay labels */}
            <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-light bg-surface-secondary/60 shrink-0">
              <FileText size={12} className="text-content-tertiary" />
              <span className="text-xs text-content-tertiary">
                <strong className="text-semantic-error/80">A</strong>: {docAName || t('pdf_compare.none', { defaultValue: 'none' })}
                {' '}+{' '}
                <strong className="text-oe-blue">B</strong>: {docBName || t('pdf_compare.none', { defaultValue: 'none' })}
                {' '}&mdash; {t('pdf_compare.opacity_b_short', { defaultValue: 'B at' })} {overlayOpacity}%
              </span>
            </div>
            <OverlayCanvas
              docA={docA}
              docB={docB}
              page={page}
              zoom={zoom}
              opacity={overlayOpacity}
              pan={panMain.pan}
              onPanStart={panMain.onStart}
              onPanMove={panMain.onMove}
              onPanEnd={panMain.onEnd}
            />
          </div>
        ) : (
          /* diff */
          <div className="flex-1 flex flex-col min-w-0">
            <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-light bg-surface-secondary/60 shrink-0">
              <FileText size={12} className="text-content-tertiary" />
              <span className="text-xs text-content-tertiary">
                <strong className="text-semantic-error/80">A</strong>: {docAName || t('pdf_compare.none', { defaultValue: 'none' })}
                {' '}&rarr;{' '}
                <strong className="text-oe-blue">B</strong>: {docBName || t('pdf_compare.none', { defaultValue: 'none' })}
              </span>
            </div>
            <DiffCanvas
              docA={docA}
              docB={docB}
              page={page}
              zoom={zoom}
              pan={panMain.pan}
              onPanStart={panMain.onStart}
              onPanMove={panMain.onMove}
              onPanEnd={panMain.onEnd}
              onChangePct={setChangePct}
            />
          </div>
        )}
      </div>

      {/* ── Status bar ─────────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center justify-between px-4 py-1 border-t border-border-light bg-surface-secondary/30 text-2xs text-content-tertiary">
        <span>
          {t('pdf_compare.status_hint', {
            defaultValue: 'Drag to pan · Zoom controls above · Keyboard: ← → page navigation',
          })}
        </span>
        {docA && docB && totalPages < maxPages && (
          <span className="text-amber-500">
            {t('pdf_compare.page_count_warning', {
              defaultValue: 'Different page counts - navigating up to {{max}} pages',
              max: maxPages,
            })}
          </span>
        )}
        {(loadingA || loadingB) && (
          <span className="flex items-center gap-1">
            <Loader2 size={11} className="animate-spin" />
            {t('pdf_compare.loading', { defaultValue: 'Loading…' })}
          </span>
        )}
      </div>
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Location" section of a record page (RFI, punch item, inspection, NCR): a small picture of the
 * sheet with the record's pin on it, and a way into the full drawing. Nothing is shown to people
 * without plan room access beyond a one-line hint.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Loader2, MapPin } from 'lucide-react';
import { closePdf, openPdf, type PDFDocumentProxy } from '@/shared/lib/pdfjs';
import { API_BASE, getAuthToken } from '@/shared/lib/api';
import { Badge } from '@/shared/ui';
import { fetchPinsByTarget, type PinTargetKind, type RegistryPin } from './api';
import { PIN_KIND_COLOR, statusBadgeVariant } from './layers';
import { sheetPath } from './pinKinds';

const MINI_WIDTH = 360;
const MAX_SHEETS = 3;

/** One sheet page, drawn small, with the pin on it. */
export function MiniSheet({ pin }: { pin: RegistryPin }) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [ratio, setRatio] = useState(0.7);

  useEffect(() => {
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    setState('loading');
    (async () => {
      try {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/v1/documents/${pin.document_id}/download/`, {
          headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'X-DDC-Client': 'OE/1.0' },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const doc = await openPdf(await res.arrayBuffer()).promise;
        loaded = doc;
        if (cancelled) return;
        const page = await doc.getPage(Math.min(Math.max(1, pin.page), doc.numPages));
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: MINI_WIDTH / base.width });
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        setRatio(viewport.height / viewport.width);
        await page.render({ canvas, viewport }).promise;
        if (!cancelled) setState('ready');
      } catch {
        if (!cancelled) setState('error');
      }
    })();
    return () => {
      cancelled = true;
      closePdf(loaded);
    };
  }, [pin.document_id, pin.page]);

  return (
    <div
      className="relative w-full max-w-sm overflow-hidden rounded-lg border border-border-light bg-white"
      style={{ aspectRatio: `${1 / ratio}` }}
      data-testid="mini-sheet"
    >
      <canvas ref={canvasRef} className="h-full w-full" />
      {state === 'loading' && (
        <span className="absolute inset-0 flex items-center justify-center bg-surface-secondary/60">
          <Loader2 size={20} className="animate-spin text-oe-blue" />
        </span>
      )}
      {state === 'error' && (
        <span className="absolute inset-0 flex items-center justify-center bg-surface-secondary px-3 text-center text-xs text-content-tertiary">
          {t('plan_room.mini_sheet_error', { defaultValue: 'The sheet could not be shown.' })}
        </span>
      )}
      <span
        style={{
          left: `${pin.x * 100}%`,
          top: `${pin.y * 100}%`,
          backgroundColor: PIN_KIND_COLOR[pin.target_kind] ?? PIN_KIND_COLOR.note,
        }}
        className="absolute flex h-6 w-6 -translate-x-1/2 -translate-y-full items-center justify-center rounded-full rounded-bl-none border-2 border-white text-white shadow-md"
        aria-hidden
      >
        <MapPin size={12} />
      </span>
    </div>
  );
}

interface Props {
  projectId: string;
  kind: PinTargetKind;
  recordId: string;
}

export function PinLocationSection({ projectId, kind, recordId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['plan-room-pins', 'by-target', projectId, kind, recordId],
    queryFn: () => fetchPinsByTarget(projectId, kind, recordId),
    enabled: !!projectId && !!recordId,
    retry: false,
  });
  const pins = data?.items ?? [];
  const onSheet = pins.filter((p) => p.document_id);
  const onModel = pins.filter((p) => p.bim_element_id);

  return (
    <section
      aria-label={t('plan_room.location_title', { defaultValue: 'Location' })}
      className="rounded-xl border border-border-light bg-surface-primary p-4"
      data-testid="pin-location-section"
    >
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <MapPin size={14} className="text-content-tertiary" aria-hidden />
        {t('plan_room.location_title', { defaultValue: 'Location' })}
      </h3>

      {isLoading ? (
        <p className="text-xs text-content-tertiary">{t('common.loading', { defaultValue: 'Loading...' })}</p>
      ) : pins.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('plan_room.location_none', { defaultValue: 'Not pinned to a drawing or a model yet.' })}{' '}
          <Link to="/plan-room" className="font-medium text-oe-blue hover:underline">
            {t('plan_room.location_pin_it', { defaultValue: 'Pin it on a drawing' })}
          </Link>
        </p>
      ) : (
        <div className="space-y-3">
          {onSheet.slice(0, MAX_SHEETS).map((pin) => (
            <div key={pin.id} className="space-y-1.5">
              <MiniSheet pin={pin} />
              <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
                <span>{t('plan_room.page_n', { defaultValue: 'Page {{n}}', n: pin.page })}</span>
                {pin.status && (
                  <Badge variant={statusBadgeVariant(pin.status)} size="sm">
                    {pin.status.replace(/_/g, ' ')}
                  </Badge>
                )}
                {pin.revision_state !== 'current' && (
                  <Badge variant="warning" size="sm">
                    {t(`plan_room.rev_${pin.revision_state}`, { defaultValue: pin.revision_state })}
                  </Badge>
                )}
                <Link to={sheetPath(pin.document_id, pin.page)} className="font-medium text-oe-blue hover:underline">
                  {t('plan_room.open_on_drawing', { defaultValue: 'Open on the drawing' })}
                </Link>
              </div>
            </div>
          ))}
          {onSheet.length > MAX_SHEETS && (
            <p className="text-xs text-content-tertiary">
              {t('plan_room.location_more', { defaultValue: '{{n}} more pins', n: onSheet.length - MAX_SHEETS })}
            </p>
          )}
          {onModel.length > 0 && (
            <p className="text-xs text-content-secondary">
              {t('plan_room.location_on_model', {
                defaultValue: 'Pinned on {{n}} model element(s).',
                n: onModel.length,
              })}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

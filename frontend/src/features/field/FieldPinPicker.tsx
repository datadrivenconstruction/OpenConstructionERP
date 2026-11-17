// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pick a drawing and tap where the defect is. Works from the phone's cached sheets with no signal. */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MapPin } from 'lucide-react';
import type { FieldSession } from './fieldApi';
import { clamp01, loadSheets, sheetPicture, type FieldSheet, type PinPlacement } from './pinOnDrawing';

interface Props {
  session: FieldSession;
  value: PinPlacement | null;
  onChange: (next: PinPlacement | null) => void;
}

export function FieldPinPicker({ session, value, onChange }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [sheets, setSheets] = useState<FieldSheet[]>([]);
  const [docId, setDocId] = useState('');
  const [picture, setPicture] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    void loadSheets(session).then((s) => alive && setSheets(s));
    return () => {
      alive = false;
    };
  }, [open, session]);

  const page = value?.page ?? 1;
  useEffect(() => {
    if (!docId) return;
    let alive = true;
    let url: string | null = null;
    setMissing(false);
    void sheetPicture(session, docId, page).then((u) => {
      url = u;
      if (!alive) return;
      setPicture(u);
      setMissing(u === null);
    });
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [session, docId, page]);

  const current = sheets.find((s) => s.document_id === docId);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-12 items-center justify-center gap-2 rounded-xl border border-border bg-surface-primary text-sm font-medium text-content-primary"
      >
        <MapPin size={18} aria-hidden="true" />
        {value
          ? t('field.pin_set', { defaultValue: 'Pinned on a drawing (change)' })
          : t('field.pin_on_drawing', { defaultValue: 'Pin on drawing' })}
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border-light p-3 text-sm" data-testid="field-pin-picker">
      <div className="flex items-center gap-2">
        <select
          value={docId}
          onChange={(e) => {
            setDocId(e.target.value);
            onChange(null);
          }}
          aria-label={t('field.pin_sheet', { defaultValue: 'Drawing' })}
          className="oe-input h-11 flex-1"
        >
          <option value="">{t('field.pin_choose_sheet', { defaultValue: 'Choose a drawing' })}</option>
          {sheets.map((s) => (
            <option key={s.document_id} value={s.document_id}>
              {s.name}
            </option>
          ))}
        </select>
        {current && current.pages > 1 && (
          <input
            type="number"
            min={1}
            max={current.pages}
            value={page}
            onChange={(e) =>
              onChange(value ? { ...value, page: Math.min(current.pages, Math.max(1, Number(e.target.value) || 1)) } : null)
            }
            aria-label={t('field.pin_page', { defaultValue: 'Page' })}
            className="oe-input h-11 w-16"
          />
        )}
      </div>
      {docId && missing && (
        <p className="text-xs text-content-tertiary">
          {t('field.pin_sheet_offline', { defaultValue: 'This drawing is not saved on the phone. Open it once with signal.' })}
        </p>
      )}
      {docId && picture && (
        <div
          className="relative touch-manipulation overflow-hidden rounded-lg border border-border-light"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            onChange({
              documentId: docId,
              page,
              x: clamp01((e.clientX - r.left) / r.width),
              y: clamp01((e.clientY - r.top) / r.height),
            });
          }}
        >
          <img src={picture} alt={current?.name ?? ''} className="block w-full select-none" draggable={false} />
          {value && value.documentId === docId && (
            <span
              style={{ left: `${value.x * 100}%`, top: `${value.y * 100}%` }}
              className="absolute flex h-7 w-7 -translate-x-1/2 -translate-y-full items-center justify-center rounded-full rounded-bl-none border-2 border-white bg-semantic-error text-white shadow-md"
              aria-hidden
            >
              <MapPin size={14} />
            </span>
          )}
        </div>
      )}
      <div className="flex justify-between">
        <button type="button" className="h-10 px-2 text-content-secondary" onClick={() => setOpen(false)}>
          {t('field.pin_done', { defaultValue: 'Done' })}
        </button>
        {value && (
          <button
            type="button"
            className="h-10 px-2 text-semantic-error"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
          >
            {t('field.pin_remove', { defaultValue: 'Remove pin' })}
          </button>
        )}
      </div>
    </div>
  );
}

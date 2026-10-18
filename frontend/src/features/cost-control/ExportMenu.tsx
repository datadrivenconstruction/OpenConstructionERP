// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The four cost documents, each as a PDF for the meeting or a workbook to work
// on: the cost report, the phase comparison, the invoice ledger and the
// forecast documentation (the latest frozen snapshot with its reasons). The
// server writes them in the reader's language.
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, FileSpreadsheet, FileText } from 'lucide-react';

import { Button } from '@/shared/ui';
import { activeLanguageTag, downloadWithAuth } from '@/shared/lib/api';
import { documentExportUrl, type DocumentFormat } from '@/shared/lib/documentExport';
import { useToastStore } from '@/stores/useToastStore';
import { EXPORT_KINDS, type ExportKind } from './api';
import { exportKindLabel } from './labels';

export interface ExportMenuProps {
  projectId: string;
}

export function ExportMenu({ projectId }: ExportMenuProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  const download = async (kind: ExportKind, format: DocumentFormat) => {
    const id = `${kind}-${format}`;
    setBusy(id);
    try {
      await downloadWithAuth(
        documentExportUrl(`/v1/costmodel/projects/${projectId}/cost-control/export/${kind}/`, {
          format,
          locale: activeLanguageTag() ?? undefined,
        }),
        `${kind}.${format}`,
      );
      setOpen(false);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('cost_control.export_failed', { defaultValue: 'Could not create the document' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="secondary"
        size="sm"
        icon={<Download size={14} />}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {t('cost_control.export', { defaultValue: 'Export' })}
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute end-0 z-30 mt-1 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-border-light bg-surface-primary p-1.5 shadow-lg"
        >
          {EXPORT_KINDS.map((kind) => (
            <div key={kind} className="flex items-center gap-2 rounded-lg px-2 py-1.5">
              <span className="min-w-0 flex-1 text-sm leading-snug text-content-primary">{exportKindLabel(t, kind)}</span>
              <button
                type="button"
                role="menuitem"
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
                disabled={busy !== null}
                onClick={() => download(kind, 'pdf')}
              >
                <FileText size={12} />
                {t('cost_control.export_pdf', { defaultValue: 'PDF' })}
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-50"
                disabled={busy !== null}
                onClick={() => download(kind, 'xlsx')}
              >
                <FileSpreadsheet size={12} />
                {t('cost_control.export_xlsx', { defaultValue: 'Excel' })}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

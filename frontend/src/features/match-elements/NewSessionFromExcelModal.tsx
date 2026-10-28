// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "New session from Excel BoQ" modal — implements MAPPING_PROCESS.md
// §4.1.5. User drops an xlsx file, the backend parses it (multi-language
// column detection in excel_import.py), and the resulting BoQ rows
// become a 'boq'-source session whose adapter exposes them to the
// matcher pipeline.

import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, X, FileSpreadsheet, Upload } from 'lucide-react';
import { matchElementsApi, type MatchSession } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

interface Props {
  projectId: string;
  onClose: () => void;
  onCreated: (session: MatchSession) => void;
}

export function NewSessionFromExcelModal({
  projectId,
  onClose,
  onCreated,
}: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const mut = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('No file selected');
      return matchElementsApi.createSessionFromExcel({
        project_id: projectId,
        file,
        name: name.trim() || undefined,
      });
    },
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ['match-sessions', projectId] });
      onCreated(session);
    },
  });

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped && dropped.name.toLowerCase().endsWith('.xlsx')) {
      setFile(dropped);
    }
  };

  const canSubmit = !!file && !mut.isPending;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-xl bg-surface-primary shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 text-emerald-600" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t(
                'match_elements.new_excel.title',
                'New session from Excel BoQ',
              )}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <p className="text-xs text-content-tertiary leading-relaxed">
            {t(
              'match_elements.new_excel.hint',
              'Upload an .xlsx with at least a "Description" column (or its localised equivalent - Beschreibung, Описание, Descripción, 描述, etc.). Optional columns: Qty, Unit, Code, Category. Decimal-comma quantities are recognised.',
            )}
          </p>

          <div>
            <label
              htmlFor="me-excel-name"
              className="block text-xs font-medium text-content-secondary mb-1"
            >
              {t('match_elements.new_excel.name_label', 'Session name (optional)')}
            </label>
            <input
              id="me-excel-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t(
                'match_elements.new_excel.name_placeholder',
                'e.g. Tender BoQ rev 3',
              )}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-1.5 text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
          </div>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-8 cursor-pointer transition ${
              dragOver
                ? 'border-oe-blue bg-oe-blue/5'
                : 'border-border bg-surface-secondary hover:border-oe-blue/40'
            }`}
          >
            <Upload className="w-6 h-6 text-content-quaternary" />
            <div className="text-center">
              {file ? (
                <>
                  <div className="text-sm font-medium text-content-primary truncate max-w-xs">
                    {file.name}
                  </div>
                  <div className="text-xs text-content-tertiary tabular-nums">
                    {fmtFixed(file.size / 1024, 1)} KB
                  </div>
                </>
              ) : (
                <>
                  <div className="text-sm text-content-secondary">
                    {t(
                      'match_elements.new_excel.drop',
                      'Drop your .xlsx here or click to browse',
                    )}
                  </div>
                  <div className="text-xs text-content-quaternary mt-0.5">
                    {t(
                      'match_elements.new_excel.format_hint',
                      '.xlsx only · multi-language headers supported',
                    )}
                  </div>
                </>
              )}
            </div>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={(e) => {
                const picked = e.target.files?.[0] ?? null;
                if (picked) setFile(picked);
              }}
            />
          </div>

          {mut.isError && (
            <div className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-700 dark:bg-rose-900/30 dark:text-rose-200">
              {String((mut.error as Error)?.message ?? mut.error)}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light bg-surface-secondary/50">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-content-secondary hover:text-content-primary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => mut.mutate()}
            disabled={!canSubmit}
            className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue/90 disabled:opacity-50"
          >
            {mut.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {t('match_elements.new_excel.create', 'Upload & create session')}
          </button>
        </div>
      </div>
    </div>
  );
}

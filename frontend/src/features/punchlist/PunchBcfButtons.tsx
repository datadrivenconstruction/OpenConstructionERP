// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Export the punch list as BCF topics, or import topics back.
 *
 * The topic GUID is the punch item id and each photo travels as a viewpoint
 * snapshot, so editing the topics in another BCF tool and importing again
 * updates the same items instead of creating copies.
 */
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FileDown, FileUp, Loader2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { downloadPunchBcf, importPunchBcf, type PunchBcfImportReport } from './api';

export function PunchBcfButtons({ projectId, selectedIds }: { projectId: string; selectedIds?: string[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const inputRef = useRef<HTMLInputElement>(null);

  const exportMut = useMutation({
    mutationFn: () => downloadPunchBcf(projectId, selectedIds && selectedIds.length > 0 ? selectedIds : undefined),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.export_failed', { defaultValue: 'Export failed' }),
        message: e.message,
      }),
  });

  const importMut = useMutation({
    mutationFn: (file: File) => importPunchBcf(projectId, file),
    onSuccess: (report: PunchBcfImportReport) => {
      qc.invalidateQueries({ queryKey: ['punchlist'] });
      qc.invalidateQueries({ queryKey: ['punchlist-summary'] });
      addToast({
        type: report.status === 'errors' ? 'error' : report.status === 'warnings' ? 'warning' : 'success',
        title: t('punch.bcf_import_done', {
          defaultValue: 'BCF imported: {{created}} new, {{updated}} updated, {{photos}} photos',
          created: report.created,
          updated: report.updated,
          photos: report.photos_added,
        }),
        message: report.issues.length
          ? report.issues
              .slice(0, 3)
              .map((i) => i.message)
              .join(' · ')
          : undefined,
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('punch.bcf_import_failed', { defaultValue: 'BCF import failed' }),
        message: e.message,
      }),
  });

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => exportMut.mutate()}
        disabled={exportMut.isPending}
        data-testid="punchlist-export-bcf"
        title={t('punch.bcf_export_hint', {
          defaultValue: 'Export as BCF topics; importing the file back updates the same items',
        })}
        icon={exportMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <FileDown size={14} />}
      >
        {t('punch.bcf_export', { defaultValue: 'Export BCF' })}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept=".bcf,.bcfzip,application/zip"
        className="sr-only"
        data-testid="punchlist-import-bcf-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) importMut.mutate(file);
          e.target.value = '';
        }}
      />
      <Button
        variant="secondary"
        size="sm"
        onClick={() => inputRef.current?.click()}
        disabled={importMut.isPending}
        data-testid="punchlist-import-bcf"
        icon={importMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} />}
      >
        {t('punch.bcf_import', { defaultValue: 'Import BCF' })}
      </Button>
    </>
  );
}

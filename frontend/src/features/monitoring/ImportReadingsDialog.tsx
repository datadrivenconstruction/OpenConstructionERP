// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Import readings in two steps: pick the file and read the preview. Only the
 * Import button saves anything; new points are created from the file.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { importReadings, previewReadings, type ImportProblem } from './api';

const MAX_BYTES = 5 * 1024 * 1024;

interface Props {
  open: boolean;
  projectId: string;
  onClose: () => void;
}

function Problems({ items, total }: { items: ImportProblem[]; total: number }) {
  const { t } = useTranslation();
  if (total === 0) return null;
  return (
    <div className="rounded-lg border border-semantic-warning/40 p-3 text-sm" data-testid="mon-import-problems">
      <div className="font-semibold">
        {t('survey.monitoring.import.problems', { defaultValue: '{{count}} rows need a look', count: total })}
      </div>
      <ul className="mt-1 max-h-40 space-y-0.5 overflow-auto text-xs text-content-secondary">
        {items.map((p, i) => (
          <li key={i}>
            {t('survey.monitoring.import.line', { defaultValue: 'Line {{line}}', line: p.line })}
            {p.point_id ? ` (${p.point_id})` : ''}: {p.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ImportReadingsDialog({ open, projectId, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [text, setText] = useState('');
  const [filename, setFilename] = useState('');

  const preview = useQuery({
    queryKey: ['monitoring', 'preview', projectId, text],
    queryFn: () => previewReadings(projectId, text),
    enabled: open && text.length > 0,
    retry: false,
  });
  const run = useMutation({
    mutationFn: () => importReadings(projectId, text, filename, i18n.language),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['monitoring'] });
      addToast({
        type: r.alerts.length > 0 ? 'warning' : 'success',
        title: t('survey.monitoring.import.done', {
          defaultValue: '{{count}} readings imported',
          count: r.readings_added,
        }),
      });
      close();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const close = () => {
    setText('');
    setFilename('');
    onClose();
  };
  const onFile = async (file: File) => {
    if (file.size > MAX_BYTES) {
      addToast({ type: 'error', title: t('survey.import.too_big', { defaultValue: 'The file is larger than 5 MB.' }) });
      return;
    }
    setText(await file.text());
    setFilename(file.name);
  };

  const p = preview.data;
  const footer = (
    <div className="flex justify-end gap-2">
      <Button variant="ghost" onClick={close} disabled={run.isPending}>
        {t('common.cancel', { defaultValue: 'Cancel' })}
      </Button>
      <Button
        variant="primary"
        icon={<Upload size={16} />}
        disabled={!p || p.readings - p.already_imported <= 0 || run.isPending}
        loading={run.isPending}
        onClick={() => run.mutate()}
        data-testid="mon-import-run"
      >
        {t('common.import', { defaultValue: 'Import' })}
      </Button>
    </div>
  );

  return (
    <WideModal
      open={open}
      onClose={close}
      busy={run.isPending}
      size="lg"
      title={t('survey.monitoring.action.import_readings', { defaultValue: 'Import readings' })}
      subtitle={filename || undefined}
      footer={footer}
    >
      <div className="space-y-4">
        <p className="text-sm text-content-secondary">
          {t('survey.monitoring.import.hint', {
            defaultValue: 'A CSV with a header: point, date, and Z (or E, N, Z, or value). Dates as 2026-10-09 or 09.10.2026.',
          })}
        </p>
        <input
          type="file"
          accept=".csv,.txt,text/csv,text/plain"
          className="oe-input w-full"
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
          data-testid="mon-import-file"
        />
        {preview.isError && <div className="text-sm text-semantic-error">{getErrorMessage(preview.error)}</div>}
        {p && (
          <div className="space-y-3" data-testid="mon-import-preview">
            <div className="text-sm">
              {t('survey.monitoring.import.summary', {
                defaultValue: '{{rows}} rows read, {{readings}} readings in {{epochs}} epochs',
                rows: p.rows_read,
                readings: p.readings,
                epochs: p.epochs.length,
              })}
            </div>
            {p.new_points.length > 0 && (
              <div className="text-sm text-content-secondary">
                {t('survey.monitoring.import.new_points', { defaultValue: 'New points: {{list}}', list: p.new_points.join(', ') })}
              </div>
            )}
            {p.already_imported > 0 && (
              <div className="text-sm text-content-secondary">
                {t('survey.monitoring.import.already', {
                  defaultValue: '{{count}} readings are already saved and will be skipped',
                  count: p.already_imported,
                })}
              </div>
            )}
            <Problems items={p.problems} total={p.problem_count} />
          </div>
        )}
      </div>
    </WideModal>
  );
}

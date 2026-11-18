// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Import design stakes into a request: a CSV of points (E/N or chainage/offset)
 * or a LandXML file with CgPoints and/or an alignment. Preview first; only
 * Import saves.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { importDesign, previewDesign, type DesignImportInput, type DesignPreview } from './api';
import { fmtCoord } from './verdict';
import { fmtFixed } from '@/shared/lib/formatters';

export function DesignImportDialog({ open, requestId, onClose }: { open: boolean; requestId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [input, setInput] = useState<DesignImportInput | null>(null);
  const [preview, setPreview] = useState<DesignPreview | null>(null);

  const read = useMutation({
    mutationFn: (body: DesignImportInput) => previewDesign(requestId, body),
    onSuccess: setPreview,
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const save = useMutation({
    mutationFn: () => importDesign(requestId, input!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['setting-out'] });
      setInput(null);
      setPreview(null);
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    const body: DesignImportInput = {
      text,
      filename: file.name,
      file_format: /\.xml$/i.test(file.name) || text.trimStart().startsWith('<') ? 'landxml' : 'csv',
    };
    setInput(body);
    read.mutate(body);
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      title={t('survey.setting_out.action.import_design', { defaultValue: 'Import design' })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" disabled={!preview || save.isPending} onClick={() => save.mutate()}>
            {t('survey.setting_out.action.import', { defaultValue: 'Import' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-content-secondary">
          {t('survey.setting_out.import_hint', {
            defaultValue: 'CSV with point, E, N, Z, or point, chainage, offset; or LandXML with points and an alignment.',
          })}
        </p>
        <input type="file" accept=".csv,.txt,.xml" onChange={(e) => onFile(e.target.files?.[0])}
          aria-label={t('survey.setting_out.action.import_design', { defaultValue: 'Import design' })} />
        {preview && (
          <div className="space-y-2">
            <div className="text-sm" data-testid="design-preview-count">
              {t('survey.import.rows_read', { rows: preview.rows_read, count: preview.problem_count })}
              {preview.alignment && (
                <span className="text-content-secondary">
                  {' · '}
                  {t('survey.setting_out.alignment_found', {
                    defaultValue: 'Alignment {{name}}, {{length}} m',
                    name: preview.alignment.name,
                    length: fmtFixed(preview.alignment.length, 3),
                  })}
                </span>
              )}
            </div>
            {preview.problems.length > 0 && (
              <ul className="text-sm text-semantic-warning list-disc ps-5">
                {preview.problems.map((p, i) => (
                  <li key={i}>{p.line ? `${p.line}: ` : ''}{p.point_id ? <bdi dir="ltr">{p.point_id} </bdi> : null}{p.message}</li>
                ))}
              </ul>
            )}
            {preview.points.length > 0 && (
              <table className="oe-table w-full text-sm">
                <thead>
                  <tr>
                    <th>{t('survey.setting_out.col.point', { defaultValue: 'Point' })}</th>
                    <th className="text-right">E (m)</th>
                    <th className="text-right">N (m)</th>
                    <th className="text-right">{t('survey.setting_out.col.chainage', { defaultValue: 'Chainage (m)' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.points.map((p) => (
                    <tr key={p.point_id}>
                      <td><bdi dir="ltr" className="font-mono">{p.point_id}</bdi></td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(p.e)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(p.n)}</bdi></td>
                      <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtCoord(p.chainage)}</bdi></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </WideModal>
  );
}

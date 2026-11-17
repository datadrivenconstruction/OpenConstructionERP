// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Import parcels or a work zone from GeoJSON or a zipped Shapefile. Step 1
 * picks the file, step 2 is the preview; only Import saves anything.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, QuantityDisplay, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { importFile, previewImport, type ImportBody, type ImportPreview, type ImportTarget } from './api';
import { importBodyFor } from './parcelFormat';

interface Props {
  open: boolean;
  projectId: string;
  initialTarget?: ImportTarget;
  onClose: () => void;
}

export function ParcelImportDialog({ open, projectId, initialTarget = 'parcels', onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [target, setTarget] = useState<ImportTarget>(initialTarget);
  const [body, setBody] = useState<ImportBody | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [error, setError] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [sourceEpsg, setSourceEpsg] = useState('');
  const [replace, setReplace] = useState(false);

  const reset = () => {
    setBody(null);
    setPreview(null);
    setError('');
  };
  const close = () => {
    reset();
    onClose();
  };

  const withOptions = (b: ImportBody): ImportBody => ({
    ...b,
    target,
    source_epsg: sourceEpsg ? Number(sourceEpsg) : null,
    on_existing: replace ? 'replace' : 'skip',
  });

  const runPreview = useMutation({
    mutationFn: (b: ImportBody) => previewImport(projectId, withOptions(b)),
    onSuccess: (p) => setPreview(p),
    onError: (e) => setError(getErrorMessage(e)),
  });
  const commit = useMutation({
    mutationFn: () => importFile(projectId, withOptions(body!)),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['land-parcels'] });
      addToast({
        type: 'success',
        title:
          target === 'work_zone'
            ? t('survey.parcels.import.done_zone', { defaultValue: 'Work zone imported' })
            : t('survey.parcels.import.done', { defaultValue: '{{count}} parcels imported', count: r.created + r.replaced }),
      });
      close();
    },
    onError: (e) => setError(getErrorMessage(e)),
  });

  const onFile = async (file: File | undefined) => {
    reset();
    if (!file) return;
    try {
      const b = await importBodyFor(file, target);
      setBody(b);
      runPreview.mutate(b);
    } catch {
      setError(t('survey.parcels.import.unsupported', { defaultValue: 'Use a .geojson file or a Shapefile as .zip.' }));
    }
  };

  const title = t('survey.parcels.btn.import', { defaultValue: 'Import parcels' });
  return (
    <WideModal
      open={open}
      onClose={close}
      title={title}
      size="xl"
      testId="parcels-import-dialog"
      busy={runPreview.isPending || commit.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={close}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!preview || preview.features.length === 0 || commit.isPending}
            onClick={() => commit.mutate()}
            data-testid="parcels-import-commit"
          >
            {t('survey.parcels.import.commit', { defaultValue: 'Import' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <fieldset className="flex flex-wrap gap-4 text-sm">
          <legend className="oe-label">{t('survey.parcels.import.what', { defaultValue: 'What the file holds' })}</legend>
          {(['parcels', 'work_zone'] as ImportTarget[]).map((v) => (
            <label key={v} className="inline-flex items-center gap-2">
              <input
                type="radio"
                name="parcel-import-target"
                checked={target === v}
                onChange={() => {
                  setTarget(v);
                  reset();
                }}
              />
              {v === 'parcels'
                ? t('survey.parcels.import.target_parcels', { defaultValue: 'Parcels' })
                : t('survey.parcels.import.target_zone', { defaultValue: 'Work zone' })}
            </label>
          ))}
        </fieldset>

        <label className="block">
          <span className="oe-label">{t('survey.parcels.import.file', { defaultValue: 'File (GeoJSON or Shapefile .zip)' })}</span>
          <input
            type="file"
            accept=".geojson,.json,.zip"
            className="oe-input w-full"
            data-testid="parcels-import-file"
            title={t('survey.parcels.tip.file', {
              defaultValue: 'A GeoJSON file, or a Shapefile zipped with its .shp, .shx, .dbf and .prj files.',
            })}
            onChange={(e) => void onFile(e.target.files?.[0])}
          />
        </label>

        <details open={advanced} onToggle={(e) => setAdvanced((e.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-sm text-content-secondary">
            {t('survey.action.advanced', { defaultValue: 'Advanced options' })}
          </summary>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="oe-label">{t('survey.parcels.import.source_epsg', { defaultValue: 'File EPSG (when the file does not say)' })}</span>
              <input
                className="oe-input w-full"
                inputMode="numeric"
                value={sourceEpsg}
                onChange={(e) => setSourceEpsg(e.target.value.replace(/\D/g, ''))}
                title={t('survey.parcels.tip.source_epsg', {
                  defaultValue: 'EPSG code the coordinates were written in. Leave empty to use the code the file declares.',
                })}
              />
            </label>
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              {t('survey.parcels.import.replace', { defaultValue: 'Replace boundaries of parcels that already exist' })}
            </label>
          </div>
          {body && (
            <Button size="sm" variant="secondary" className="mt-2" onClick={() => runPreview.mutate(body)}>
              {t('survey.parcels.import.refresh', { defaultValue: 'Read again' })}
            </Button>
          )}
        </details>

        {error && (
          <p role="alert" className="text-sm text-semantic-error">
            {error}
          </p>
        )}

        {preview && (
          <div className="space-y-2" data-testid="parcels-import-preview">
            <p className="text-sm font-medium">
              {t('survey.parcels.import.read', {
                defaultValue: '{{rows}} features read, {{count}} problems',
                rows: preview.features_read,
                count: preview.problem_count,
              })}
              {' · '}
              <QuantityDisplay value={preview.total_area} unit="m²" precision={2} />
            </p>
            {preview.transform && (
              <p className="text-sm text-semantic-warning">
                {t('survey.parcels.import.transform', {
                  defaultValue: 'Coordinates will be converted: {{transform}}. Check both codes before you import.',
                  transform: preview.transform,
                })}
              </p>
            )}
            {preview.problems.length > 0 && (
              <ul className="text-sm text-content-secondary list-disc ps-5">
                {preview.problems.map((p, i) => (
                  <li key={i}>
                    #{p.index + 1}: {p.detail}
                  </li>
                ))}
              </ul>
            )}
            <div className="overflow-x-auto">
              <table className="oe-table w-full text-sm">
                <thead>
                  <tr>
                    <th>{t('survey.parcels.col.parcel_id', { defaultValue: 'Parcel ID' })}</th>
                    <th className="text-right">{t('survey.parcels.col.legal', { defaultValue: 'Legal area' })}</th>
                    <th className="text-right">{t('survey.parcels.col.computed', { defaultValue: 'Computed' })}</th>
                    <th className="text-right">{t('survey.parcels.import.vertices', { defaultValue: 'Points' })}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {preview.features.slice(0, 20).map((f) => (
                    <tr key={f.index}>
                      <td><bdi dir="ltr" className="font-mono">{f.ref}</bdi></td>
                      <td className="text-right">{f.legal_area ? <QuantityDisplay value={f.legal_area} unit="m²" precision={2} /> : '-'}</td>
                      <td className="text-right"><QuantityDisplay value={f.computed_area} unit="m²" precision={2} /></td>
                      <td className="text-right">{f.vertices}</td>
                      <td className="text-xs text-content-tertiary">
                        {f.exists && t('survey.parcels.import.exists', { defaultValue: 'already on the schedule' })}
                        {!f.closed && ` ${t('survey.parcels.import.open_ring', { defaultValue: 'ring not closed' })}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </WideModal>
  );
}

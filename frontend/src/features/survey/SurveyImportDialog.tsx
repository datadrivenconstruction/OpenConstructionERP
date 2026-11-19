// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Import points in three steps: file, columns, preview. The guesses carry a
 * confidence and can be changed; only the Import button saves anything.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { Button, ConfidenceBadge, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  POINT_KINDS,
  importPoints,
  previewImport,
  type DuplicatePolicy,
  type FootDefinition,
  type ImportBody,
  type ImportPreview,
  type PointKind,
} from './api';
import {
  COLUMN_FIELDS,
  DELIMITERS,
  PRESET_NAMES,
  chooseColumn,
  columnsForPreset,
  delimiterLabelKey,
  detectDelimiter,
  fileFormatFor,
  selfDescribing,
  guessPreset,
  looksLikeHeader,
  mappingProblems,
  presetOf,
  sampleRows,
  type ColumnField,
  type Guess,
  type PresetName,
} from './importMapping';
import { fmtFixed } from '@/shared/lib/formatters';

const LABEL = 'oe-label';
const INPUT = 'oe-input w-full';
const MAX_BYTES = 5 * 1024 * 1024;

interface Props {
  open: boolean;
  projectId: string;
  projectEpsg: number | null;
  onClose: () => void;
}

type Step = 1 | 2 | 3;

const fmt = (v: number | null) => (v == null ? '' : fmtFixed(v, 3));

export function SurveyImportDialog({ open, projectId, projectEpsg, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [step, setStep] = useState<Step>(1);
  const [text, setText] = useState('');
  const [filename, setFilename] = useState('');
  const [delimiter, setDelimiter] = useState<Guess<string>>({ value: ',', confidence: 0 });
  const [preset, setPreset] = useState<Guess<PresetName>>({ value: 'PENZD', confidence: 0 });
  const [columns, setColumns] = useState<ColumnField[]>([]);
  const [hasHeader, setHasHeader] = useState(false);
  const [kind, setKind] = useState<PointKind>('topo');
  const [sourceEpsg, setSourceEpsg] = useState('');
  const [meta, setMeta] = useState({ name: '', instrument: '', surveyed_by: '', survey_date: '' });
  const [policy, setPolicy] = useState<DuplicatePolicy>('keep_first');
  const [foot, setFoot] = useState<FootDefinition>('');
  const [coords, setCoords] = useState<'grid' | 'local'>('grid');
  const [preview, setPreview] = useState<ImportPreview | null>(null);

  const format = fileFormatFor(filename, text);
  const direct = selfDescribing(format);
  const rows = useMemo(() => (text ? sampleRows(text, delimiter.value) : []), [text, delimiter.value]);
  const colCount = Math.max(0, ...rows.map((r) => r.length));
  const problems = direct ? [] : mappingProblems(columns);

  const reset = () => {
    setStep(1);
    setText('');
    setFilename('');
    setPreview(null);
    setPolicy('keep_first');
  };
  const close = () => {
    reset();
    onClose();
  };

  const onFile = async (file: File) => {
    if (file.size > MAX_BYTES) {
      addToast({ type: 'error', title: t('survey.import.too_big', { defaultValue: 'The file is larger than 5 MB.' }) });
      return;
    }
    const body = await file.text();
    setText(body);
    setFilename(file.name);
    setMeta((m) => ({ ...m, name: m.name || file.name.replace(/\.[^.]+$/, '') }));
    const d = detectDelimiter(body);
    setDelimiter(d);
    const sample = sampleRows(body, d.value);
    const header = looksLikeHeader(sample);
    setHasHeader(header);
    const g = guessPreset(sample);
    setPreset(g);
    setColumns(columnsForPreset(g.value, Math.max(0, ...sample.map((r) => r.length))));
    if (/^cp|control/i.test(file.name)) setKind('control');
    setSourceEpsg(fileFormatFor(file.name) === 'geojson' ? '' : projectEpsg != null ? String(projectEpsg) : '');
  };

  const body = (dup: DuplicatePolicy = policy): ImportBody => ({
    text,
    file_format: format,
    filename,
    delimiter: delimiter.value,
    columns,
    has_header: hasHeader,
    default_kind: kind,
    source_epsg: sourceEpsg.trim() ? Number(sourceEpsg) : null,
    name: meta.name || filename,
    instrument: meta.instrument,
    surveyed_by: meta.surveyed_by,
    survey_date: meta.survey_date || null,
    duplicate_policy: dup,
    foot_definition: foot,
    coords,
  });

  const runPreview = useMutation({
    mutationFn: (dup?: DuplicatePolicy) => previewImport(projectId, body(dup)),
    onSuccess: (p) => {
      setPreview(p);
      setStep(3);
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const runImport = useMutation({
    mutationFn: () => importPoints(projectId, body()),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['survey'] });
      addToast({
        type: 'success',
        title: t('survey.import.done', { defaultValue: '{{count}} points imported', count: r.imported }),
      });
      close();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const fieldLabel = (f: ColumnField) =>
    f === ''
      ? t('survey.import.field_skip', { defaultValue: 'Do not import' })
      : t(`survey.field.${f}`, { defaultValue: f });

  const footer = (
    <div className="flex justify-between gap-2">
      <span className="text-xs text-content-tertiary self-center">
        {t('survey.import.step', { defaultValue: 'Step {{n}} of 3', n: step })}
      </span>
      <div className="flex gap-2">
        {step > 1 && (
          <Button variant="secondary" onClick={() => setStep((s) => (s === 3 && direct ? 1 : ((s - 1) as Step)))}>
            {t('common.back', { defaultValue: 'Back' })}
          </Button>
        )}
        {step === 1 && (
          <Button variant="primary" disabled={!text} onClick={() => (direct ? runPreview.mutate(undefined) : setStep(2))}>
            {t('common.next', { defaultValue: 'Next' })}
          </Button>
        )}
        {step === 2 && (
          <Button variant="primary" disabled={problems.length > 0} loading={runPreview.isPending} onClick={() => runPreview.mutate(undefined)}>
            {t('survey.import.preview', { defaultValue: 'Preview' })}
          </Button>
        )}
        {step === 3 && (
          <Button
            variant="primary"
            disabled={!preview || preview.points_to_import === 0}
            loading={runImport.isPending}
            onClick={() => runImport.mutate()}
            data-testid="survey-import-commit"
          >
            {t('survey.action.import_points', { defaultValue: 'Import points' })}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <WideModal
      open={open}
      onClose={close}
      busy={runImport.isPending}
      size="xl"
      title={t('survey.action.import_points', { defaultValue: 'Import points' })}
      subtitle={filename || undefined}
      footer={footer}
    >
      {step === 1 && (
        <div className="space-y-4">
          <label className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border-light p-8 text-sm cursor-pointer hover:bg-surface-secondary">
            <Upload size={20} aria-hidden />
            <span>{filename || t('survey.import.drop_formats', { defaultValue: 'Choose a CSV, TXT, GeoJSON, GSI-8/16, JobXML or LandXML file' })}</span>
            <input
              type="file"
              accept=".csv,.txt,.pts,.xyz,.geojson,.json,.gsi,.xml,.jxl"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onFile(f);
              }}
            />
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="survey-imp-name">{t('survey.import.set_name', { defaultValue: 'Point set name' })}</label>
              <input id="survey-imp-name" className={INPUT} value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} />
            </div>
            <div>
              <label className={LABEL} htmlFor="survey-imp-epsg">{t('survey.import.source_epsg', { defaultValue: 'Coordinate system of the file (EPSG)' })}</label>
              <input
                id="survey-imp-epsg"
                className={INPUT}
                inputMode="numeric"
                value={sourceEpsg}
                placeholder={format === 'geojson' ? '4326' : ''}
                title={t('survey.import.source_epsg_tip', { defaultValue: 'The system the instrument recorded in. A different one from the project is converted, and the preview says so.' })}
                onChange={(e) => setSourceEpsg(e.target.value)}
              />
            </div>
            {format !== 'geojson' && (
              <div>
                <label className={LABEL} htmlFor="survey-imp-foot">{t('survey.import.foot', { defaultValue: 'Foot, when the file is in feet' })}</label>
                <select id="survey-imp-foot" className={INPUT} value={foot} onChange={(e) => setFoot(e.target.value as FootDefinition)}>
                  <option value="">{t('survey.import.foot_auto', { defaultValue: 'As the project, ask if unclear' })}</option>
                  <option value="ft">{t('survey.import.foot_intl', { defaultValue: 'International foot (0.3048 m)' })}</option>
                  <option value="ftUS">{t('survey.import.foot_us', { defaultValue: 'US survey foot (1200/3937 m)' })}</option>
                </select>
              </div>
            )}
            {format !== 'geojson' && (
              <div>
                <label className={LABEL} htmlFor="survey-imp-coords">{t('survey.import.coords', { defaultValue: 'Coordinates in the file' })}</label>
                <select id="survey-imp-coords" className={INPUT} value={coords} onChange={(e) => setCoords(e.target.value as 'grid' | 'local')}>
                  <option value="grid">{t('survey.import.coords_grid', { defaultValue: 'National or project grid' })}</option>
                  <option value="local">{t('survey.import.coords_local', { defaultValue: 'Site grid (through the local grid tie)' })}</option>
                </select>
              </div>
            )}
            <div>
              <label className={LABEL} htmlFor="survey-imp-kind">{t('survey.import.kind', { defaultValue: 'Point kind' })}</label>
              <select id="survey-imp-kind" className={INPUT} value={kind} onChange={(e) => setKind(e.target.value as PointKind)}>
                {POINT_KINDS.map((k) => (
                  <option key={k} value={k}>{t(`survey.kind.${k}`, { defaultValue: k })}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="survey-imp-date">{t('survey.import.date', { defaultValue: 'Survey date' })}</label>
              <input id="survey-imp-date" type="date" className={INPUT} value={meta.survey_date} onChange={(e) => setMeta({ ...meta, survey_date: e.target.value })} />
            </div>
            <div>
              <label className={LABEL} htmlFor="survey-imp-instr">{t('survey.import.instrument', { defaultValue: 'Instrument' })}</label>
              <input id="survey-imp-instr" className={INPUT} value={meta.instrument} onChange={(e) => setMeta({ ...meta, instrument: e.target.value })} />
            </div>
            <div>
              <label className={LABEL} htmlFor="survey-imp-by">{t('survey.import.surveyed_by', { defaultValue: 'Surveyed by' })}</label>
              <input id="survey-imp-by" className={INPUT} value={meta.surveyed_by} onChange={(e) => setMeta({ ...meta, surveyed_by: e.target.value })} />
            </div>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={LABEL} htmlFor="survey-imp-delim">{t('survey.import.delimiter', { defaultValue: 'Delimiter' })}</label>
              <div className="flex items-center gap-2">
                <select
                  id="survey-imp-delim"
                  className={INPUT}
                  value={delimiter.value}
                  onChange={(e) => {
                    const d = e.target.value;
                    setDelimiter({ value: d, confidence: 1 });
                    const sample = sampleRows(text, d);
                    setColumns(columnsForPreset(preset.value, Math.max(0, ...sample.map((r) => r.length))));
                  }}
                >
                  {DELIMITERS.map((d) => (
                    <option key={d} value={d}>{t(`survey.delimiter.${delimiterLabelKey(d)}`, { defaultValue: delimiterLabelKey(d) })}</option>
                  ))}
                </select>
                <ConfidenceBadge score={delimiter.confidence} size="sm" />
              </div>
            </div>
            <div>
              <label className={LABEL} htmlFor="survey-imp-preset">{t('survey.import.preset', { defaultValue: 'Column order' })}</label>
              <div className="flex items-center gap-2">
                <select
                  id="survey-imp-preset"
                  className={INPUT}
                  value={presetOf(columns) ?? ''}
                  title={t('survey.import.preset_tip', { defaultValue: 'P point, N northing, E easting, Z height, D code. Some countries call north X.' })}
                  onChange={(e) => {
                    const p = e.target.value as PresetName;
                    setPreset({ value: p, confidence: 1 });
                    setColumns(columnsForPreset(p, colCount));
                  }}
                >
                  <option value="" disabled>{t('survey.import.preset_custom', { defaultValue: 'Custom' })}</option>
                  {PRESET_NAMES.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
                <ConfidenceBadge score={preset.confidence} size="sm" />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm self-end pb-2">
              <input type="checkbox" checked={hasHeader} onChange={(e) => setHasHeader(e.target.checked)} />
              {t('survey.import.has_header', { defaultValue: 'First row holds column names' })}
            </label>
          </div>
          <div className="overflow-x-auto">
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  {Array.from({ length: colCount }, (_, i) => (
                    <th key={i}>
                      <select
                        className="oe-input text-xs"
                        aria-label={t('survey.import.column_n', { defaultValue: 'Column {{n}}', n: i + 1 })}
                        value={columns[i] ?? ''}
                        onChange={(e) => setColumns(chooseColumn(columns, i, e.target.value as ColumnField))}
                      >
                        {(['', ...COLUMN_FIELDS] as ColumnField[]).map((f) => (
                          <option key={f || 'skip'} value={f}>{fieldLabel(f)}</option>
                        ))}
                      </select>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, ri) => (
                  <tr key={ri} className={hasHeader && ri === 0 ? 'text-content-tertiary' : undefined}>
                    {Array.from({ length: colCount }, (_, i) => (
                      <td key={i}><bdi dir="ltr" className="font-mono">{r[i] ?? ''}</bdi></td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {problems.length > 0 && (
            <p className="text-sm text-semantic-error">
              {t('survey.import.need_en', { defaultValue: 'Choose which columns hold E and N.' })}
            </p>
          )}
        </div>
      )}

      {step === 3 && preview && (
        <div className="space-y-4">
          <p className="text-sm font-medium" data-testid="survey-import-count">
            {t('survey.import.rows_read', { defaultValue: '{{rows}} rows read, {{count}} problems', rows: preview.rows_read, count: preview.problem_count })}
          </p>
          {preview.will_transform && (
            <p className="text-sm text-semantic-warning">
              {t('survey.import.will_transform', {
                defaultValue: 'Points will be converted from EPSG {{from}} to the project system EPSG {{to}}.',
                from: preview.source_epsg,
                to: preview.target_epsg,
              })}
            </p>
          )}
          {preview.unit_converted && (
            <p className="text-sm" data-testid="survey-import-unit">
              {t('survey.import.unit_converted', {
                defaultValue: 'The file is in {{from}}; values are converted to the project unit {{to}}.',
                from: preview.file_unit,
                to: preview.project_unit,
              })}
            </p>
          )}
          {preview.local_grid_applied && (
            <p className="text-sm">{t('survey.import.local_applied', { defaultValue: 'Site grid coordinates go through the local grid tie.' })}</p>
          )}
          {!!preview.missing_grids?.length && (
            <p className="text-sm text-semantic-warning">
              {t('survey.import.geoid_missing', {
                defaultValue: 'Geoid grid {{grids}} is not installed: heights are kept as measured.',
                grids: preview.missing_grids.join(', '),
              })}
            </p>
          )}
          {preview.detected_crs && (
            <p className="flex items-center gap-2 text-sm">
              {t('survey.import.detected', { defaultValue: 'The coordinates look like EPSG {{code}}. Set it as the project system if that is right.', code: preview.detected_crs.epsg })}
              {preview.detected_crs.confidence != null && <ConfidenceBadge score={preview.detected_crs.confidence} showScore size="sm" />}
            </p>
          )}
          {preview.problems.length > 0 && (
            <ul className="space-y-1 text-sm">
              {preview.problems.slice(0, 20).map((p, i) => (
                <li key={i} className="flex gap-2">
                  <span className="font-mono text-xs text-semantic-error">{p.rule_id}</span>
                  <span>{t('survey.import.problem_line', { defaultValue: 'Line {{line}}', line: p.line })}</span>
                  {p.point_id && <bdi dir="ltr" className="font-mono">{p.point_id}</bdi>}
                  <span className="text-content-secondary">{p.message || p.detail}</span>
                </li>
              ))}
            </ul>
          )}
          {(preview.problems.some((p) => p.rule_id === 'SRV-003') || preview.existing_conflicts > 0) && (
            <fieldset className="flex flex-wrap gap-4 text-sm">
              <legend className="oe-label">{t('survey.import.duplicates', { defaultValue: 'Same point ID twice' })}</legend>
              {(['keep_first', 'keep_last', 'skip'] as DuplicatePolicy[]).map((p) => (
                <label key={p} className="flex items-center gap-2">
                  <input type="radio" name="survey-dup" checked={policy === p} onChange={() => { setPolicy(p); runPreview.mutate(p); }} />
                  {t(`survey.duplicate.${p}`, { defaultValue: p })}
                </label>
              ))}
            </fieldset>
          )}
          <p className="text-sm">
            {t('survey.import.to_import', { defaultValue: '{{count}} points will be imported.', count: preview.points_to_import })}
          </p>
          <div className="overflow-x-auto">
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  <th>{t('survey.field.point_id', { defaultValue: 'ID' })}</th>
                  <th>{t('survey.field.code', { defaultValue: 'Code' })}</th>
                  <th>{t('survey.field.kind', { defaultValue: 'Kind' })}</th>
                  <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.field.e', { defaultValue: 'E (m)' })}</th>
                  <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.field.n', { defaultValue: 'N (m)' })}</th>
                  <th className="text-right" title={t('survey.unit.metre', { defaultValue: 'metres' })}>{t('survey.field.z', { defaultValue: 'Z (m)' })}</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 20).map((r) => (
                  <tr key={r.line}>
                    <td><bdi dir="ltr" className="font-mono">{r.point_id}</bdi></td>
                    <td>{r.code}</td>
                    <td>{t(`survey.kind.${r.kind}`, { defaultValue: r.kind })}</td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmt(r.e)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmt(r.n)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmt(r.z)}</bdi></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </WideModal>
  );
}

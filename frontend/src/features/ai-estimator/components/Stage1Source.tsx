// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Stage 1 - Understand source. Two faces:
//  (a) intake (before a run exists): pick ANY source - text, files,
//      BIM/CAD model, project documents - and start the run.
//  (b) confirm (after stage 1 ran): review the auto-detected source type
//      with a confidence badge and edit catalogue / region / currency /
//      group-by before grouping (human-confirm checkpoint #1).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  Pencil,
  Upload,
  Boxes,
  FileText,
  X,
  Sparkles,
  CheckCircle2,
} from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { BIMModelPicker } from '@/shared/ui/BIMModelPicker';
import { scoreColor, scorePercent } from '../helpers';
import { useScoreThresholds } from '../meta';
import {
  SOURCE_TABS,
  type CatalogueOption,
  type DetectedSource,
  type RunRead,
  type SourceTabDef,
  type SuggestedConfig,
} from '../api';

/** Humanise a construction-stage enum value ("06_Superstructure") into a
 *  readable default ("Superstructure") used when no translation exists. */
function humanizeStage(value: string): string {
  const withoutPrefix = value.replace(/^\d+[_-]?/, '');
  return withoutPrefix.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').trim();
}

/** The four intake-tab ids (UI-level). */
export type SourceTabId = SourceTabDef['id'];

const TAB_ICON: Record<SourceTabId, React.ReactNode> = {
  text: <Pencil className="h-5 w-5" />,
  files: <Upload className="h-5 w-5" />,
  bim_model: <Boxes className="h-5 w-5" />,
  documents: <FileText className="h-5 w-5" />,
};

interface BimModel {
  id: string;
  name: string;
  model_format: string | null;
  element_count: number;
  storey_count: number;
  status: string;
  created_at: string | null;
}

interface ProjectDoc {
  id: string;
  name: string;
}

export interface Stage1IntakeProps {
  projectId: string | null;
  sourceKind: SourceTabId;
  onSourceKind: (k: SourceTabId) => void;
  text: string;
  onText: (v: string) => void;
  files: File[];
  onFiles: (f: File[]) => void;
  bimModels: BimModel[];
  bimModelsLoading: boolean;
  selectedModelId: string | null;
  onSelectModel: (id: string) => void;
  documents: ProjectDoc[];
  selectedDocIds: string[];
  onToggleDoc: (id: string) => void;
  canStart: boolean;
  starting: boolean;
  onStart: () => void;
}

/** Pre-run intake screen. */
export function Stage1Intake(props: Stage1IntakeProps) {
  const { t } = useTranslation();
  const {
    projectId,
    sourceKind,
    onSourceKind,
    text,
    onText,
    files,
    onFiles,
    bimModels,
    bimModelsLoading,
    selectedModelId,
    onSelectModel,
    documents,
    selectedDocIds,
    onToggleDoc,
    canStart,
    starting,
    onStart,
  } = props;

  const [dragOver, setDragOver] = useState(false);

  return (
    <div className="space-y-5">
      <p className="text-sm text-content-secondary">
        {t('aiest.intake.help', {
          defaultValue:
            'Bring any source. The agent detects the format, reads it into elements, groups quantities and finds exact catalogue rates. Rates always come from the cost database, never invented.',
        })}
      </p>

      {/* Source-kind tab grid */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {SOURCE_TABS.map((tab) => {
          const active = tab.id === sourceKind;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => onSourceKind(tab.id)}
              className={clsx(
                'flex flex-col gap-1.5 rounded-xl border p-3 text-left transition-all',
                active
                  ? 'border-oe-blue bg-oe-blue/5 ring-1 ring-oe-blue/30'
                  : 'border-border-light hover:border-border hover:bg-surface-muted',
              )}
            >
              <span className={clsx('text-content-primary', active && 'text-oe-blue')}>
                {TAB_ICON[tab.id]}
              </span>
              <span className="text-sm font-medium text-content-primary">
                {t(tab.labelKey, { defaultValue: tab.labelFallback })}
              </span>
              <span className="text-xs leading-snug text-content-tertiary">
                {t(tab.descKey, { defaultValue: tab.descFallback })}
              </span>
            </button>
          );
        })}
      </div>

      {/* Per-kind input */}
      <div>
        {sourceKind === 'text' && (
          <textarea
            value={text}
            onChange={(e) => onText(e.target.value)}
            rows={6}
            placeholder={t('aiest.intake.text_placeholder', {
              defaultValue:
                'Describe the scope, e.g. "Two-storey office, 1200 m2 GFA, reinforced concrete frame, brick facade, suspended ceilings, full MEP fit-out."',
            })}
            className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
          />
        )}

        {sourceKind === 'files' && (
          <div>
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                onFiles([...files, ...Array.from(e.dataTransfer.files)]);
              }}
              className={clsx(
                'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
                dragOver
                  ? 'border-oe-blue bg-oe-blue/5'
                  : 'border-border-light hover:border-border hover:bg-surface-muted',
              )}
            >
              <Upload className="h-7 w-7 text-content-tertiary" />
              <span className="text-sm font-medium text-content-primary">
                {t('aiest.intake.drop_files', {
                  defaultValue: 'Drop files here or click to browse',
                })}
              </span>
              <span className="text-xs text-content-tertiary">
                {t('aiest.intake.file_hint', {
                  defaultValue: 'DWG, PDF, Excel, GAEB XML, IFC, photos',
                })}
              </span>
              <input
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) onFiles([...files, ...Array.from(e.target.files)]);
                }}
              />
            </label>
            {files.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {files.map((f, i) => (
                  <li
                    key={`${f.name}-${i}`}
                    className="flex items-center justify-between rounded-lg border border-border-light bg-surface-muted px-3 py-1.5 text-xs"
                  >
                    <span className="truncate text-content-primary">{f.name}</span>
                    <button
                      type="button"
                      onClick={() => onFiles(files.filter((_, idx) => idx !== i))}
                      className="ml-2 shrink-0 text-content-tertiary hover:text-rose-500"
                      aria-label={t('common.remove', { defaultValue: 'Remove' })}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {sourceKind === 'bim_model' && (
          <BIMModelPicker
            models={bimModels}
            activeModelId={selectedModelId}
            onSelect={onSelectModel}
            isLoading={bimModelsLoading}
            uploadHref={projectId ? `/bim?project=${projectId}` : '/bim'}
            emptyMessage={t('aiest.intake.no_models', {
              defaultValue: 'No converted models in this project yet.',
            })}
          />
        )}

        {sourceKind === 'documents' && (
          <div className="rounded-xl border border-border-light">
            {documents.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-content-tertiary">
                {t('aiest.intake.no_documents', {
                  defaultValue: 'No documents in this project.',
                })}{' '}
                <Link className="font-medium text-oe-blue hover:underline" to="/files">
                  {t('aiest.intake.go_to_files', { defaultValue: 'Open project files' })}
                </Link>
              </p>
            ) : (
              <ul className="max-h-64 divide-y divide-border-light overflow-y-auto">
                {documents.map((d) => {
                  const checked = selectedDocIds.includes(d.id);
                  return (
                    <li key={d.id}>
                      <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm hover:bg-surface-muted">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => onToggleDoc(d.id)}
                          className="accent-oe-blue"
                        />
                        <FileText className="h-4 w-4 shrink-0 text-content-tertiary" />
                        <span className="truncate text-content-primary">{d.name}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>

      <Button
        variant="primary"
        size="lg"
        icon={<Sparkles className="h-4 w-4" />}
        loading={starting}
        disabled={!canStart}
        onClick={onStart}
      >
        {t('aiest.intake.start', { defaultValue: 'Start AI estimate' })}
      </Button>
    </div>
  );
}

// ── Confirm checkpoint #1 ─────────────────────────────────────────────

export interface Stage1ConfirmProps {
  run: RunRead;
  detected: DetectedSource;
  config: SuggestedConfig;
  catalogues: CatalogueOption[];
  /** Allowed construction-stage values (server-driven via GET /meta). Empty
   *  while the endpoint is unavailable - the select then offers only "All
   *  stages" plus any value already on the run, never a free-text field. */
  constructionStages: string[];
  onChange: (patch: Partial<SuggestedConfig> & { detected_source_type?: string }) => void;
  edits: Partial<SuggestedConfig> & { detected_source_type?: string };
}

const CURRENCY_OPTIONS = [
  'EUR', 'USD', 'GBP', 'CHF', 'PLN', 'CZK', 'CAD', 'AUD', 'JPY', 'CNY',
  'BRL', 'INR', 'ZAR', 'TRY', 'AED', 'SAR', 'NOK', 'SEK', 'DKK', 'RUB',
];

/** Post-stage-1 review/edit of detected source + config. */
export function Stage1Confirm(props: Stage1ConfirmProps) {
  const { t } = useTranslation();
  const { detected, config, catalogues, constructionStages, onChange, edits } = props;
  const thresholds = useScoreThresholds();

  const effCatalogue = edits.catalogue_id ?? config.catalogue_id ?? '';
  const effRegion = edits.region ?? config.region ?? '';
  const effCurrency = edits.currency ?? config.currency ?? '';
  const effStage = edits.construction_stage ?? config.construction_stage ?? '';
  // Tolerate older / partial run payloads where array fields are null: the
  // backend types them as lists but pre-existing rows may omit them.
  const groupBy = Array.isArray(edits.group_by)
    ? edits.group_by
    : Array.isArray(config.group_by)
      ? config.group_by
      : [];
  const disciplines = Array.isArray(detected.disciplines) ? detected.disciplines : [];

  // The select offers the server-driven stages plus, defensively, any stage
  // already set on this run (so an existing value is never silently dropped
  // when the meta list is stale or empty).
  const stageOptions = (() => {
    const out: string[] = [];
    const seen = new Set<string>();
    const push = (s: string | null | undefined) => {
      if (!s) return;
      if (seen.has(s)) return;
      seen.add(s);
      out.push(s);
    };
    (Array.isArray(constructionStages) ? constructionStages : []).forEach(push);
    push(config.construction_stage);
    push(effStage || null);
    return out;
  })();

  // De-duplicated currency menu seeded from the suggested currency + the
  // catalogue currencies, then common globals. Never blends - one
  // currency selected.
  const currencyMenu: string[] = (() => {
    const out: string[] = [];
    const seen = new Set<string>();
    const push = (c: string | null | undefined) => {
      if (!c) return;
      const k = c.trim().toUpperCase();
      if (!k || seen.has(k)) return;
      seen.add(k);
      out.push(k);
    };
    push(config.currency);
    catalogues.forEach((c) => push(c.currency));
    CURRENCY_OPTIONS.forEach(push);
    return out;
  })();

  return (
    <div className="space-y-5">
      {/* Detected source card */}
      <Card padding="md" className="border-emerald-200/60 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-900/10">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-content-primary">
                {t('aiest.confirm1.detected', { defaultValue: 'Detected source' })}:{' '}
                <span className="uppercase">{detected.type}</span>
              </span>
              <span
                className={clsx(
                  'rounded px-1.5 py-0.5 text-[10px] font-bold',
                  scoreColor(detected.confidence, thresholds),
                )}
              >
                {scorePercent(detected.confidence)}
              </span>
            </div>
            {detected.summary && (
              <p className="mt-1 text-xs text-content-secondary">{detected.summary}</p>
            )}
            {disciplines.length > 0 && (
              <p className="mt-1 text-xs text-content-tertiary">{disciplines.join(', ')}</p>
            )}
          </div>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('aiest.confirm1.catalogue', { defaultValue: 'Cost catalogue' })}
          </label>
          <select
            value={effCatalogue}
            onChange={(e) => onChange({ catalogue_id: e.target.value || null })}
            className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm"
          >
            <option value="">
              {t('aiest.confirm1.catalogue_auto', {
                defaultValue: 'Auto (from region: {{region}})',
                region: effRegion || '-',
              })}
            </option>
            {catalogues.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} · {c.currency}
              </option>
            ))}
          </select>
          {catalogues.length === 0 && (
            <p className="mt-1 text-xs text-amber-600">
              {t('aiest.confirm1.no_catalogue', {
                defaultValue:
                  'No catalogues loaded. Install one from CAD Match → Cost to ground rates.',
              })}
            </p>
          )}
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('aiest.confirm1.currency', { defaultValue: 'Currency' })}
          </label>
          <select
            value={effCurrency}
            onChange={(e) => onChange({ currency: e.target.value || null })}
            className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm"
          >
            <option value="">{t('common.auto', { defaultValue: 'Auto' })}</option>
            {currencyMenu.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('aiest.confirm1.currency_hint', {
              defaultValue:
                'Rates are filtered to this currency. The catalogue currency is never converted into a wrong number.',
            })}
          </p>
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('aiest.confirm1.region', { defaultValue: 'Region' })}
          </label>
          <input
            type="text"
            value={effRegion}
            onChange={(e) => onChange({ region: e.target.value || null })}
            placeholder={t('aiest.confirm1.region_placeholder', { defaultValue: 'e.g. de, us' })}
            className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label
            htmlFor="aiest-construction-stage"
            className="mb-1.5 block text-sm font-medium text-content-primary"
          >
            {t('aiest.confirm1.stage', { defaultValue: 'Construction stage' })}
          </label>
          <select
            id="aiest-construction-stage"
            value={effStage}
            onChange={(e) => onChange({ construction_stage: e.target.value || null })}
            className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm"
          >
            <option value="">{t('aiest.stage_all', { defaultValue: 'All stages' })}</option>
            {stageOptions.map((s) => (
              <option key={s} value={s}>
                {t(`aiest.stage_${s}`, { defaultValue: humanizeStage(s) })}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* group_by chips */}
      <div>
        <span className="mb-1.5 block text-sm font-medium text-content-primary">
          {t('aiest.confirm1.group_by', { defaultValue: 'Group elements by' })}
        </span>
        {groupBy.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('aiest.confirm1.group_by_default', {
              defaultValue: 'Using the auto-suggested grouping keys.',
            })}
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {groupBy.map((key) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-full border border-oe-blue/30 bg-oe-blue/5 px-2.5 py-1 text-xs font-medium text-oe-blue"
              >
                {key}
                <button
                  type="button"
                  onClick={() => onChange({ group_by: groupBy.filter((k) => k !== key) })}
                  aria-label={t('common.remove', { defaultValue: 'Remove' })}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

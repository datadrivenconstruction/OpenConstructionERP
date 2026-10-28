// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<InspectorPanel>` — right-side contextual editor (320 px, collapsible).
 *
 * Two context modes shown via a labelled status pill (03_ux_visual §2.4):
 *   1. **Node** (a single node selected) — a friendly form generated from the
 *      node-type's `params_schema` (string / number / boolean / enum), each
 *      field with a localized label + helper. Not raw JSON.
 *   2. **Pipeline** (nothing / many selected) — name, description, project
 *      binding, published toggle, plus a plain-language summary stub.
 *
 * The mode is driven by the canvas selection, not by clicking here, so an
 * ARIA `tablist` would be a focus trap. The visible pill below is rendered
 * as a passive status indicator.
 *
 * All strings via `t(...)`. Logical props for RTL. Footer: Duplicate / Delete.
 */
import { ChevronRight, Copy, Trash2 } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ConfirmDialog } from '@/shared/ui';

import { getCategoryTokens } from '../tokens';
import {
  selectSingleSelected,
  usePipelineStore,
} from '../usePipelineStore';
import type { NodeTypeDef } from '../api';

export interface InspectorPanelProps {
  nodeTypes: NodeTypeDef[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /**
   * Plain-language summary of the whole pipeline, produced by the page's
   * "Explain this pipeline" action. When set, it replaces the placeholder
   * hint in the pipeline-mode summary slot.
   */
  summary?: string | null;
  testId?: string;
}

interface SchemaField {
  key: string;
  type: 'string' | 'number' | 'boolean' | 'enum';
  enum?: string[];
  required?: boolean;
  title?: string;
  description?: string;
}

/** Best-effort: turn a JSON-Schema-ish `params_schema` into flat fields. */
function fieldsFromSchema(
  schema: Record<string, unknown> | undefined,
): SchemaField[] {
  if (!schema || typeof schema !== 'object') return [];
  const props = (schema.properties ?? schema) as Record<string, unknown>;
  if (!props || typeof props !== 'object') return [];
  const required = Array.isArray(schema.required)
    ? (schema.required as string[])
    : [];
  const out: SchemaField[] = [];
  for (const [key, raw] of Object.entries(props)) {
    if (!raw || typeof raw !== 'object') continue;
    const def = raw as Record<string, unknown>;
    const enumVals = Array.isArray(def.enum)
      ? (def.enum as string[])
      : undefined;
    let type: SchemaField['type'] = 'string';
    if (enumVals) type = 'enum';
    else if (def.type === 'number' || def.type === 'integer') type = 'number';
    else if (def.type === 'boolean') type = 'boolean';
    out.push({
      key,
      type,
      enum: enumVals,
      required: required.includes(key),
      title: typeof def.title === 'string' ? def.title : undefined,
      description:
        typeof def.description === 'string' ? def.description : undefined,
    });
  }
  return out;
}

export function InspectorPanel({
  nodeTypes,
  collapsed,
  onToggleCollapsed,
  summary,
  testId,
}: InspectorPanelProps) {
  const { t } = useTranslation();
  const selected = usePipelineStore(selectSingleSelected);
  const meta = usePipelineStore((s) => s.meta);
  const setNodeParams = usePipelineStore((s) => s.setNodeParams);
  const removeNode = usePipelineStore((s) => s.removeNode);
  const copySelection = usePipelineStore((s) => s.copySelection);
  const pasteClipboard = usePipelineStore((s) => s.pasteClipboard);
  const patchMeta = usePipelineStore((s) => s.patchMeta);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const confirmDelete = useCallback(() => {
    if (selected) removeNode(selected.id);
    setConfirmDeleteOpen(false);
  }, [removeNode, selected]);

  const def = useMemo(
    () => nodeTypes.find((d) => d.type === selected?.type),
    [nodeTypes, selected?.type],
  );
  const fields = useMemo(
    () => fieldsFromSchema(def?.params_schema),
    [def?.params_schema],
  );

  const setParam = useCallback(
    (key: string, value: unknown) => {
      if (!selected) return;
      setNodeParams(selected.id, { ...selected.params, [key]: value });
    },
    [selected, setNodeParams],
  );

  const duplicate = useCallback(() => {
    copySelection();
    pasteClipboard();
  }, [copySelection, pasteClipboard]);

  if (collapsed) {
    return (
      <aside
        data-testid={testId ?? 'pipeline-inspector'}
        data-collapsed="true"
        className="flex h-full w-11 shrink-0 flex-col items-center border-s border-border bg-surface-secondary py-2"
      >
        <button
          type="button"
          aria-label={t('pipeline.inspector.expand', {
            defaultValue: 'Expand inspector',
          })}
          onClick={onToggleCollapsed}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-surface-tertiary"
        >
          <ChevronRight
            size={16}
            aria-hidden="true"
            className="scale-x-[-1] rtl:scale-x-100"
          />
        </button>
      </aside>
    );
  }

  const mode: 'node' | 'pipeline' = selected ? 'node' : 'pipeline';

  return (
    <aside
      data-testid={testId ?? 'pipeline-inspector'}
      data-collapsed="false"
      className="flex h-full w-[320px] shrink-0 flex-col border-s border-border bg-surface-secondary"
      aria-label={t('pipeline.inspector.aria', { defaultValue: 'Inspector' })}
    >
      <ConfirmDialog
        open={confirmDeleteOpen && Boolean(selected)}
        onConfirm={confirmDelete}
        onCancel={() => setConfirmDeleteOpen(false)}
        variant="danger"
        title={t('pipeline.inspector.delete_confirm_title', {
          defaultValue: 'Delete this step?',
        })}
        message={t('pipeline.inspector.delete_confirm_body', {
          defaultValue:
            'This removes the step from the canvas. Any connections into or out of it are removed too.',
        })}
        confirmLabel={t('pipeline.inspector.delete', { defaultValue: 'Delete' })}
      />
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        {/* Context indicator (NOT a tablist — the mode is driven by the
            canvas selection, not by clicking here; a non-operable ARIA
            tablist is an a11y trap, so this is a labelled status). */}
        <span
          data-testid="pipeline-inspector-mode"
          className="inline-flex items-center gap-1.5 rounded bg-oe-blue/10 px-2 py-1 text-xs font-medium text-oe-blue"
        >
          {mode === 'node'
            ? t('pipeline.inspector.context_node', {
                defaultValue: 'Editing step',
              })
            : t('pipeline.inspector.context_pipeline', {
                defaultValue: 'Editing pipeline',
              })}
        </span>
        <button
          type="button"
          aria-label={t('pipeline.inspector.collapse', {
            defaultValue: 'Collapse inspector',
          })}
          onClick={onToggleCollapsed}
          className="flex h-6 w-6 items-center justify-center rounded hover:bg-surface-tertiary"
        >
          <ChevronRight
            size={14}
            aria-hidden="true"
            className="rtl:scale-x-[-1]"
          />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {mode === 'node' && selected ? (
          <div className="space-y-4" data-testid="pipeline-inspector-node">
            <div>
              <div className="flex items-center gap-2">
                {(() => {
                  const Icon = getCategoryTokens(selected.category).Icon;
                  return (
                    <Icon
                      size={16}
                      aria-hidden="true"
                      className={getCategoryTokens(selected.category).classes.icon}
                    />
                  );
                })()}
                <h3 className="text-sm font-semibold text-content-primary">
                  {selected.title}
                </h3>
              </div>
              <p className="mt-1 text-xs text-content-tertiary">
                {def?.description ||
                  t(`pipeline.nodetype.${selected.type}.desc`, {
                    defaultValue: selected.type,
                  })}
              </p>
            </div>

            {fields.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('pipeline.inspector.no_params', {
                  defaultValue: 'This step has no settings to configure.',
                })}
              </p>
            ) : (
              <div className="space-y-3">
                {fields.map((f) => {
                  const value = selected.params[f.key];
                  const fieldLabel =
                    f.title ||
                    t(`pipeline.param.${selected.type}.${f.key}`, {
                      defaultValue: f.key,
                    });
                  const help =
                    f.description ||
                    t(`pipeline.param.${selected.type}.${f.key}.help`, {
                      defaultValue: '',
                    });
                  return (
                    <div key={f.key}>
                      <label className="mb-1 block text-xs font-medium text-content-secondary">
                        {fieldLabel}
                        {f.required && (
                          <span
                            className="ms-1 text-semantic-error"
                            aria-hidden="true"
                          >
                            *
                          </span>
                        )}
                      </label>
                      {f.type === 'boolean' ? (
                        <label className="inline-flex items-center gap-2 text-xs text-content-secondary">
                          <input
                            type="checkbox"
                            checked={Boolean(value)}
                            onChange={(e) =>
                              setParam(f.key, e.target.checked)
                            }
                            data-testid={`pipeline-param-${f.key}`}
                          />
                          {t('pipeline.inspector.enabled', {
                            defaultValue: 'Enabled',
                          })}
                        </label>
                      ) : f.type === 'enum' ? (
                        <select
                          value={String(value ?? '')}
                          onChange={(e) => setParam(f.key, e.target.value)}
                          data-testid={`pipeline-param-${f.key}`}
                          className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                        >
                          <option value="">
                            {t('pipeline.inspector.choose', {
                              defaultValue: 'Choose…',
                            })}
                          </option>
                          {f.enum?.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={f.type === 'number' ? 'number' : 'text'}
                          value={
                            value === undefined || value === null
                              ? ''
                              : String(value)
                          }
                          onChange={(e) =>
                            setParam(
                              f.key,
                              f.type === 'number'
                                ? e.target.value === ''
                                  ? ''
                                  : Number(e.target.value)
                                : e.target.value,
                            )
                          }
                          data-testid={`pipeline-param-${f.key}`}
                          className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                        />
                      )}
                      {help && (
                        <p className="mt-1 text-2xs text-content-tertiary">
                          {help}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <div className="flex items-center gap-2 border-t border-border pt-3">
              <button
                type="button"
                onClick={duplicate}
                data-testid="pipeline-inspector-duplicate"
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-xs font-medium hover:bg-surface-tertiary"
              >
                <Copy size={13} aria-hidden="true" />
                {t('pipeline.inspector.duplicate', {
                  defaultValue: 'Duplicate',
                })}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDeleteOpen(true)}
                data-testid="pipeline-inspector-delete"
                className="inline-flex items-center gap-1.5 rounded-md border border-semantic-error/40 bg-semantic-error-bg px-2.5 py-1.5 text-xs font-medium text-semantic-error hover:opacity-90"
              >
                <Trash2 size={13} aria-hidden="true" />
                {t('pipeline.inspector.delete', { defaultValue: 'Delete' })}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4" data-testid="pipeline-inspector-pipeline">
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                {t('pipeline.inspector.name', { defaultValue: 'Name' })}
              </label>
              <input
                type="text"
                value={meta.name}
                onChange={(e) => patchMeta({ name: e.target.value })}
                data-testid="pipeline-meta-name"
                placeholder={t('pipeline.inspector.name_ph', {
                  defaultValue: 'My automation',
                })}
                className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                {t('pipeline.inspector.description', {
                  defaultValue: 'Description',
                })}
              </label>
              <textarea
                value={meta.description}
                onChange={(e) => patchMeta({ description: e.target.value })}
                data-testid="pipeline-meta-description"
                rows={3}
                className="w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              />
            </div>
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input
                type="checkbox"
                checked={meta.isPublished}
                onChange={(e) => patchMeta({ isPublished: e.target.checked })}
                data-testid="pipeline-meta-published"
              />
              {t('pipeline.inspector.published', {
                defaultValue: 'Published (can be triggered)',
              })}
            </label>
            <div
              data-testid="pipeline-inspector-summary"
              className="space-y-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-2.5 text-xs text-content-secondary"
            >
              {summary ? (
                summary.split('\n').map((line, i) => (
                  <p key={i} className={line ? '' : 'h-1'}>
                    {line}
                  </p>
                ))
              ) : (
                t('pipeline.inspector.summary_stub', {
                  defaultValue:
                    'A plain-language summary of what this pipeline does will appear here. Use "Explain this pipeline" for the full story.',
                })
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

export default InspectorPanel;

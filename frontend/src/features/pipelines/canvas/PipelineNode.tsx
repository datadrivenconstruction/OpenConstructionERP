// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PipelineNode>` - a single pipeline node rendered as an xyflow node card.
 *
 * The card resolves its identity from `node.category` via `getCategoryTokens()`
 * and reads as a solid, modern node-editor card rather than a floating label:
 *   - a solid CATEGORY-COLORED HEADER (icon + inline-editable title + a quiet
 *     category label + help/expand controls; header text clears WCAG-AA),
 *   - a surfaced BODY that lays inputs down the logical-start edge and outputs
 *     down the logical-end edge (each = a type-colored glyph aligned to its
 *     Handle + the port label; two columns when the node has both), plus a
 *     compact "label: value" param preview (or a one-line description when the
 *     step has no params), and
 *   - a bottom STATUS strip that mirrors the live run state (idle shows nothing;
 *     running/done/error pair an icon with color so state is never color-alone).
 *
 * Contracts preserved: each Handle id === the port id, inputs are `target`
 * handles on the logical-start edge and outputs are `source` handles on the
 * logical-end edge, and inline rename / selection / drag / run overlay all keep
 * working against the same store actions and `CanvasNode` shape.
 */
import { Handle, Position, type NodeProps } from '@xyflow/react';
import clsx from 'clsx';
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleSlash,
  Clock,
  Info,
  Loader2,
  PauseCircle,
  XCircle,
  type LucideProps,
} from 'lucide-react';
import {
  useCallback,
  useMemo,
  useState,
  type ComponentType,
  type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';

import { useIsRTL } from '@/shared/hooks/useIsRTL';

import { PortGlyph } from '../components/PortGlyph';
import { getCategoryTokens, getPortTokens } from '../tokens';
import {
  usePipelineStore,
  type CanvasNode,
  type PipelinePort,
} from '../usePipelineStore';
import { useNodeTypes, type NodeTypeDef, type RunStatus } from '../api';

export interface PipelineNodeData extends Record<string, unknown> {
  node: CanvasNode;
}

export type PipelineNodeProps = NodeProps;

/** Max params rendered in the collapsed preview before a "+N more" line. */
const MAX_PREVIEW_PARAMS = 3;

/** Map a run status → {icon, tinted-strip classes, animation flags}. */
function runVisual(status: RunStatus | undefined): {
  Icon: ComponentType<LucideProps> | null;
  cls: string;
  spin?: boolean;
  pulse?: boolean;
} {
  switch (status) {
    case 'queued':
      return {
        Icon: Clock,
        cls: 'bg-semantic-info-bg text-semantic-info',
        pulse: true,
      };
    case 'running':
      return {
        Icon: Loader2,
        cls: 'bg-semantic-info-bg text-semantic-info',
        spin: true,
      };
    case 'done':
    case 'success':
      return {
        Icon: CheckCircle2,
        cls: 'bg-semantic-success-bg text-semantic-success',
      };
    case 'error':
    case 'failed':
      return {
        Icon: XCircle,
        cls: 'bg-semantic-error-bg text-semantic-error',
      };
    case 'paused':
      return {
        Icon: PauseCircle,
        cls: 'bg-semantic-warning-bg text-semantic-warning',
      };
    case 'cancelled':
      return {
        Icon: CircleSlash,
        cls: 'bg-surface-tertiary text-content-tertiary',
      };
    default:
      return { Icon: null, cls: '' };
  }
}

/** Human label for a param key, taken from the node-type's params_schema. */
function paramLabel(
  schema: Record<string, unknown> | undefined,
  key: string,
): string {
  if (!schema) return key;
  const props =
    schema.properties && typeof schema.properties === 'object'
      ? (schema.properties as Record<string, unknown>)
      : schema;
  const entry = props[key];
  if (entry && typeof entry === 'object' && 'title' in entry) {
    const title = (entry as { title?: unknown }).title;
    if (typeof title === 'string' && title.trim()) return title;
  }
  return key;
}

/** Compact one-line rendering of a param value. */
function formatParamValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (Array.isArray(value)) return value.map((v) => String(v)).join(', ');
  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export function PipelineNode({ id, data, selected }: PipelineNodeProps) {
  const { t } = useTranslation();
  const isRTL = useIsRTL();
  const node = (data as PipelineNodeData | undefined)?.node;
  const setNodeTitle = usePipelineStore((s) => s.setNodeTitle);
  const toggleExpanded = usePipelineStore((s) => s.toggleNodeExpanded);
  const runNodeState = usePipelineStore((s) =>
    node ? s.run.nodeStates[node.id] : undefined,
  );
  const { data: nodeTypes } = useNodeTypes();

  const [editingTitle, setEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState(node?.title ?? '');
  const [showHelp, setShowHelp] = useState(false);

  const tokens = useMemo(
    () => (node ? getCategoryTokens(node.category) : null),
    [node],
  );
  const def = useMemo<NodeTypeDef | undefined>(
    () => (node ? nodeTypes?.find((d) => d.type === node.type) : undefined),
    [nodeTypes, node],
  );

  const commitTitle = useCallback(() => {
    if (!node) return;
    const next = draftTitle.trim() || node.title;
    if (next !== node.title) setNodeTitle(node.id, next);
    setEditingTitle(false);
  }, [node, draftTitle, setNodeTitle]);

  const handleTitleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        commitTitle();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        setDraftTitle(node?.title ?? '');
        setEditingTitle(false);
      }
    },
    [node?.title, commitTitle],
  );

  if (!node || !tokens) return null;

  const Icon = tokens.Icon;
  const inputSide = isRTL ? Position.Right : Position.Left;
  const outputSide = isRTL ? Position.Left : Position.Right;
  const hasInputs = node.inputs.length > 0;
  const hasOutputs = node.outputs.length > 0;
  const hasPorts = hasInputs || hasOutputs;
  const isAi = node.category === 'ai';

  const paramEntries = Object.entries(node.params).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  );
  const visibleParams = node.expanded
    ? paramEntries
    : paramEntries.slice(0, MAX_PREVIEW_PARAMS);
  const hiddenParamCount = paramEntries.length - visibleParams.length;

  const description = def?.description?.trim();
  const descText =
    description ||
    t(`pipeline.nodehelp.${node.type}`, {
      defaultValue: t('pipeline.node.no_params', {
        defaultValue: 'No settings needed. Connect it and press Run.',
      }),
    });

  const rv = runVisual(runNodeState?.status);
  const hasStatus = Boolean(runNodeState && rv.Icon);
  const tookMs = runNodeState?.took_ms;

  const categoryLabel = t(tokens.labelKey, { defaultValue: tokens.labelDefault });
  const portTypeLong = (dt: string): string =>
    t(getPortTokens(dt).labelKey, {
      defaultValue: getPortTokens(dt).labelDefault,
    });

  const renderInput = (port: PipelinePort) => (
    <div key={port.id} className="relative flex h-7 items-center">
      <Handle
        type="target"
        position={inputSide}
        id={port.id}
        data-testid={`pipeline-node-input-${id}-${port.id}`}
        title={t('pipeline.port.tooltip_input', {
          defaultValue:
            'Input "{{label}}" accepts {{type}}. Drag a matching output here to connect it.',
          label: port.label,
          type: portTypeLong(port.dataType),
        })}
        aria-label={t('pipeline.port.aria_input', {
          defaultValue: 'input: {{label}}, type {{type}}',
          label: port.label,
          type: portTypeLong(port.dataType),
        })}
        style={{
          background: '#fff',
          border: `2px solid ${getPortTokens(port.dataType).color}`,
          width: 11,
          height: 11,
        }}
      />
      <span className="flex min-w-0 items-center gap-1.5 ps-2.5 pe-1">
        <PortGlyph type={port.dataType} />
        <span className="truncate text-xs font-medium text-content-primary">
          {port.label}
        </span>
      </span>
    </div>
  );

  const renderOutput = (port: PipelinePort) => (
    <div key={port.id} className="relative flex h-7 items-center justify-end">
      <span className="flex min-w-0 items-center justify-end gap-1.5 ps-1 pe-2.5">
        <span className="truncate text-xs font-medium text-content-primary">
          {port.label}
        </span>
        <PortGlyph type={port.dataType} />
      </span>
      <Handle
        type="source"
        position={outputSide}
        id={port.id}
        data-testid={`pipeline-node-output-${id}-${port.id}`}
        title={t('pipeline.port.tooltip_output', {
          defaultValue:
            'Output "{{label}}" sends {{type}}. Drag from here to a matching input.',
          label: port.label,
          type: portTypeLong(port.dataType),
        })}
        aria-label={t('pipeline.port.aria_output', {
          defaultValue: 'output: {{label}}, type {{type}}',
          label: port.label,
          type: portTypeLong(port.dataType),
        })}
        style={{
          background: '#fff',
          border: `2px solid ${getPortTokens(port.dataType).color}`,
          width: 11,
          height: 11,
        }}
      />
    </div>
  );

  return (
    <div
      data-testid={`pipeline-node-${id}`}
      data-node-category={node.category}
      data-node-type={node.type}
      data-node-selected={selected ? 'true' : 'false'}
      className={clsx(
        'w-56 rounded-xl border border-border bg-surface-primary text-content-primary shadow-sm',
        'transition-shadow duration-150 hover:shadow-md',
        selected && clsx('shadow-md ring-2', tokens.classes.ring),
      )}
    >
      {/* Header - solid category color, editable title + quiet category name */}
      <div
        className={clsx(
          'flex items-center gap-1.5 rounded-t-xl px-2.5 py-1.5',
          tokens.classes.header,
          tokens.classes.headerText,
        )}
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center">
          <Icon size={16} aria-hidden="true" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          {editingTitle ? (
            <input
              type="text"
              data-testid={`pipeline-node-title-input-${id}`}
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={handleTitleKeyDown}
              autoFocus
              aria-label={t('pipeline.node.rename', {
                defaultValue: 'Rename node',
              })}
              className="h-6 w-full rounded border-0 bg-white/95 px-1 text-sm font-semibold text-slate-900 focus:outline-none focus:ring-2 focus:ring-white/60"
            />
          ) : (
            <button
              type="button"
              data-testid={`pipeline-node-title-${id}`}
              onDoubleClick={() => {
                setDraftTitle(node.title);
                setEditingTitle(true);
              }}
              className="truncate text-start text-sm font-semibold hover:underline"
              title={t('pipeline.node.rename_hint', {
                defaultValue: 'Double-click to rename',
              })}
            >
              {node.title}
            </button>
          )}
          <span
            className={clsx(
              'truncate text-2xs font-semibold uppercase tracking-wide',
              tokens.classes.headerSubtle,
            )}
          >
            {categoryLabel}
          </span>
        </div>
        {isAi && (
          <span
            className="shrink-0 rounded bg-white/25 px-1 text-2xs font-bold"
            title={t('pipeline.node.ai_confidence', {
              defaultValue: 'AI suggestion - review the confidence score',
            })}
          >
            {t('pipeline.node.ai_badge', { defaultValue: 'AI' })}
          </span>
        )}
        <button
          type="button"
          aria-label={t('pipeline.node.help', {
            defaultValue: 'What this node does',
          })}
          aria-expanded={showHelp}
          onClick={() => setShowHelp((v) => !v)}
          className={clsx(
            'flex h-5 w-5 shrink-0 items-center justify-center rounded',
            tokens.classes.headerHover,
          )}
        >
          <Info size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label={
            node.expanded
              ? t('pipeline.node.collapse', { defaultValue: 'Collapse' })
              : t('pipeline.node.expand', { defaultValue: 'Expand' })
          }
          data-testid={`pipeline-node-toggle-${id}`}
          onClick={() => toggleExpanded(node.id)}
          className={clsx(
            'flex h-5 w-5 shrink-0 items-center justify-center rounded',
            tokens.classes.headerHover,
          )}
        >
          {node.expanded ? (
            <ChevronDown size={14} aria-hidden="true" />
          ) : (
            <ChevronRight
              size={14}
              aria-hidden="true"
              className="rtl:scale-x-[-1]"
            />
          )}
        </button>
      </div>

      {/* Per-node help - what it does (localized, plain language) */}
      {showHelp && (
        <p
          data-testid={`pipeline-node-help-${id}`}
          className="border-b border-border px-2.5 py-1.5 text-xs leading-relaxed text-content-secondary"
        >
          {t(`pipeline.nodehelp.${node.type}`, {
            defaultValue:
              description ||
              t('pipeline.node.help_generic', {
                defaultValue:
                  'Configure this step in the Inspector. It receives data from the connected step before it and passes its result on.',
              }),
          })}
        </p>
      )}

      {/* Port rows - inputs down the logical-start edge, outputs down the
          logical-end edge (a two-column body when the node has both). Each
          Handle keeps id === port.id so existing edges reconnect. */}
      {hasPorts && (
        <div className="flex items-start">
          {hasInputs && (
            <div className="flex flex-1 flex-col py-1.5">
              {node.inputs.map(renderInput)}
            </div>
          )}
          {hasOutputs && (
            <div className="flex flex-1 flex-col py-1.5">
              {node.outputs.map(renderOutput)}
            </div>
          )}
        </div>
      )}

      {/* Param preview ("label: value") or, when there are none, a one-liner
          describing what the step does. */}
      <div
        className={clsx(
          'px-2.5',
          hasPorts ? 'border-t border-border pt-1.5' : 'pt-2',
          hasStatus ? 'pb-1.5' : 'pb-2',
        )}
      >
        {paramEntries.length > 0 ? (
          <div data-testid={`pipeline-node-params-${id}`} className="space-y-0.5">
            {visibleParams.map(([key, value]) => (
              <div
                key={key}
                className="flex min-w-0 items-baseline gap-1 text-xs"
              >
                <span className="shrink-0 font-medium text-content-secondary">
                  {paramLabel(def?.params_schema, key)}:
                </span>
                <span className="min-w-0 truncate text-content-primary">
                  {formatParamValue(value)}
                </span>
              </div>
            ))}
            {hiddenParamCount > 0 && (
              <div className="text-2xs italic text-content-tertiary">
                {t('pipeline.node.more_params', {
                  defaultValue: '+{{count}} more',
                  count: hiddenParamCount,
                })}
              </div>
            )}
          </div>
        ) : (
          <p className="line-clamp-2 text-xs leading-snug text-content-secondary">
            {descText}
          </p>
        )}
      </div>

      {/* Live status strip - icon + text + color so state never relies on
          color alone. Idle nodes render no strip. */}
      {hasStatus && rv.Icon && (
        <div
          data-testid={`pipeline-node-status-${id}`}
          className={clsx(
            'flex items-center gap-1.5 rounded-b-xl px-2.5 py-1.5 text-xs font-medium',
            rv.cls,
            rv.pulse && 'animate-pulse',
          )}
          aria-live="polite"
        >
          <rv.Icon
            size={13}
            aria-hidden="true"
            className={rv.spin ? 'animate-spin' : undefined}
          />
          <span className="truncate">
            {t(`pipeline.runstatus.${runNodeState?.status ?? ''}`, {
              defaultValue: String(runNodeState?.status ?? ''),
            })}
          </span>
          {typeof tookMs === 'number' && (
            <span className="ms-auto shrink-0 tabular-nums opacity-80">
              {t('pipeline.node.took_ms', {
                defaultValue: '{{ms}} ms',
                ms: tookMs,
              })}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export default PipelineNode;

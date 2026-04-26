/**
 * `<BlockNode>` — single block rendered as an xyflow node.
 *
 * Composition rules:
 *   - Outer wrapper carries the block color and selected state via Tailwind.
 *   - Header line: icon + editable title + expand/collapse caret.
 *   - Param chips: short read-only summary of `block.params`. Clicking the
 *     caret toggles the expanded state (full inspector lives in EAC-3.x).
 *   - Slot handles: one xyflow `<Handle>` per slot, positioned left for
 *     inputs and right for outputs.
 *
 * The component reads/writes through `useBlockCanvasStore` actions so the
 * canvas remains the single source of truth; `props` only carry what xyflow
 * passes (`id`, `data`, `selected`).
 */
import { Handle, Position, type NodeProps } from '@xyflow/react';
import clsx from 'clsx';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useCallback, useMemo, useState, type KeyboardEvent } from 'react';

import { getBlockTokens } from '../tokens';
import type { SlotDataType, SlotDefinition } from './dnd';
import { useBlockCanvasStore, type CanvasBlock } from './useBlockCanvasStore';

export interface BlockNodeData extends Record<string, unknown> {
  block: CanvasBlock;
}

export type BlockNodeProps = NodeProps;

/** Tailwind text colour per slot type — used for the small slot label. */
const SLOT_TYPE_TEXT_COLOR: Record<SlotDataType, string> = {
  selector: 'text-gray-600 dark:text-gray-300',
  predicate: 'text-green-700 dark:text-green-300',
  attribute: 'text-purple-700 dark:text-purple-300',
  constraint: 'text-blue-700 dark:text-blue-300',
  variable: 'text-yellow-700 dark:text-yellow-300',
  number: 'text-cyan-700 dark:text-cyan-300',
  string: 'text-pink-700 dark:text-pink-300',
  boolean: 'text-teal-700 dark:text-teal-300',
  any: 'text-slate-500 dark:text-slate-400',
};

export function BlockNode({ id, data, selected }: BlockNodeProps) {
  const block = (data as BlockNodeData | undefined)?.block;
  const setBlockTitle = useBlockCanvasStore((s) => s.setBlockTitle);
  const toggleBlockExpanded = useBlockCanvasStore((s) => s.toggleBlockExpanded);

  const [editingTitle, setEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState(block?.title ?? '');

  // Memoise the slot partition because a block typically renders 50–100
  // times per drag, and the array filter is the hottest line.
  const { inputs, outputs } = useMemo(() => {
    const inputs: SlotDefinition[] = [];
    const outputs: SlotDefinition[] = [];
    for (const slot of block?.slots ?? []) {
      (slot.direction === 'input' ? inputs : outputs).push(slot);
    }
    return { inputs, outputs };
  }, [block?.slots]);

  const tokens = useMemo(() => (block ? getBlockTokens(block.color) : null), [block?.color]);

  const commitTitle = useCallback(() => {
    if (!block) return;
    const next = draftTitle.trim() || block.title;
    if (next !== block.title) {
      setBlockTitle(block.id, next);
    }
    setEditingTitle(false);
  }, [block, draftTitle, setBlockTitle]);

  const handleTitleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        commitTitle();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        setDraftTitle(block?.title ?? '');
        setEditingTitle(false);
      }
    },
    [block?.title, commitTitle],
  );

  if (!block || !tokens) {
    return null;
  }

  const Icon = tokens.Icon;
  const paramChips = Object.entries(block.params).filter(([, value]) => value !== undefined && value !== null);

  return (
    <div
      data-testid={`eac-block-node-${id}`}
      data-block-color={block.color}
      data-block-selected={selected ? 'true' : 'false'}
      className={clsx(
        'relative min-w-[200px] max-w-[320px] rounded-lg border-2 px-3 py-2 text-sm shadow-sm',
        'transition-colors',
        selected ? tokens.classes.bgSelected : tokens.classes.bg,
        selected ? tokens.classes.borderSelected : tokens.classes.border,
        tokens.classes.text,
      )}
    >
      {/* Header — icon + editable title + expand caret */}
      <div className="flex items-center gap-2">
        <span className={clsx('flex h-5 w-5 shrink-0 items-center justify-center', tokens.classes.icon)}>
          <Icon size={16} aria-hidden="true" />
        </span>
        {editingTitle ? (
          <input
            type="text"
            data-testid={`eac-block-node-title-input-${id}`}
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            onBlur={commitTitle}
            onKeyDown={handleTitleKeyDown}
            autoFocus
            className="h-6 w-full rounded border border-border bg-white px-1 text-sm dark:bg-gray-900"
          />
        ) : (
          <button
            type="button"
            data-testid={`eac-block-node-title-${id}`}
            onDoubleClick={() => {
              setDraftTitle(block.title);
              setEditingTitle(true);
            }}
            className="truncate text-left font-medium hover:underline"
            title="Double-click to rename"
          >
            {block.title}
          </button>
        )}
        <button
          type="button"
          aria-label={block.expanded ? 'Collapse parameters' : 'Expand parameters'}
          data-testid={`eac-block-node-toggle-${id}`}
          onClick={() => toggleBlockExpanded(block.id)}
          className={clsx(
            'ml-auto flex h-5 w-5 shrink-0 items-center justify-center rounded',
            'hover:bg-black/5 dark:hover:bg-white/10',
            tokens.classes.icon,
          )}
        >
          {block.expanded ? (
            <ChevronDown size={14} aria-hidden="true" />
          ) : (
            <ChevronRight size={14} aria-hidden="true" />
          )}
        </button>
      </div>

      {/* Parameter chips — collapsed = short summary, expanded = full table */}
      {paramChips.length > 0 && (
        <div
          data-testid={`eac-block-node-params-${id}`}
          className={clsx('mt-1 flex flex-wrap gap-1 text-xs', tokens.classes.textSubtle)}
        >
          {(block.expanded ? paramChips : paramChips.slice(0, 3)).map(([key, value]) => (
            <span
              key={key}
              className="inline-flex items-center rounded bg-black/5 px-1.5 py-0.5 dark:bg-white/10"
            >
              <span className="font-medium">{key}</span>
              <span className="mx-1">:</span>
              <span className="truncate max-w-[120px]">{String(value)}</span>
            </span>
          ))}
          {!block.expanded && paramChips.length > 3 && (
            <span className="inline-flex items-center px-1 text-xs italic">
              +{paramChips.length - 3} more
            </span>
          )}
        </div>
      )}

      {/* Slot rows — input handles on the left, output handles on the right */}
      <div className="mt-2 space-y-1">
        {Math.max(inputs.length, outputs.length) > 0 &&
          Array.from({ length: Math.max(inputs.length, outputs.length) }).map((_, idx) => {
            const input = inputs[idx];
            const output = outputs[idx];
            return (
              <div key={idx} className="relative flex items-center justify-between text-xs">
                <span className={clsx('flex items-center gap-1', input ? SLOT_TYPE_TEXT_COLOR[input.dataType] : '')}>
                  {input && (
                    <>
                      <Handle
                        type="target"
                        position={Position.Left}
                        id={input.id}
                        data-testid={`eac-block-node-input-${id}-${input.id}`}
                        style={{ background: '#fff', border: '1px solid #94a3b8', width: 8, height: 8 }}
                      />
                      <span>{input.label}</span>
                    </>
                  )}
                </span>
                <span className={clsx('flex items-center gap-1', output ? SLOT_TYPE_TEXT_COLOR[output.dataType] : '')}>
                  {output && (
                    <>
                      <span>{output.label}</span>
                      <Handle
                        type="source"
                        position={Position.Right}
                        id={output.id}
                        data-testid={`eac-block-node-output-${id}-${output.id}`}
                        style={{ background: '#fff', border: '1px solid #94a3b8', width: 8, height: 8 }}
                      />
                    </>
                  )}
                </span>
              </div>
            );
          })}
      </div>
    </div>
  );
}

export default BlockNode;

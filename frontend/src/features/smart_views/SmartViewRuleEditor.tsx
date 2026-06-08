// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SmartViewRuleEditor — visual rule builder.
//
// Layout (top → bottom):
//   1. Name / Description / Default action  (the "head" of the view)
//   2. Drag-orderable list of rules         (the rule "body")
//   3. "Add rule" affordance                (appends a sensible default)
//   4. Sticky footer with Cancel / Save     (delegates POST vs PUT)
//
// Rules are kept in local state and only POST'd / PUT'd on Save — this
// matches a BIM coordination tool's "edit as draft, commit as one" UX and lets a
// user iterate freely without spamming the API.

import { useState, useMemo, useEffect, type ChangeEvent, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2, Plus, GripVertical, AlertCircle } from 'lucide-react';
import clsx from 'clsx';
import { Button, WideModal, Input } from '@/shared/ui';
import { Slider } from '@/shared/ui/Slider';
import {
  COMMON_IFC_CLASSES,
  type SmartViewAction,
  type SmartViewActionArgs,
  type SmartViewCreatePayload,
  type SmartViewDefaultAction,
  type SmartViewOperator,
  type SmartViewResponse,
  type SmartViewRule,
  type SmartViewScopeType,
  type SmartViewSelector,
} from './types';
import { createSmartView, updateSmartView } from './api';

/* ── Constants ────────────────────────────────────────────────────────── */

const OPERATORS: SmartViewOperator[] = [
  'eq',
  'neq',
  'contains',
  'regex',
  'gt',
  'lt',
  'in',
  'exists',
  'between',
];

const ACTIONS: SmartViewAction[] = [
  'show',
  'hide',
  'color',
  'transparent',
  'isolate',
];

/* ── Helpers ──────────────────────────────────────────────────────────── */

let _idCounter = 0;
function generateRuleId(): string {
  // Deterministic in tests (suite resets state on remount), opaque in
  // production. Crypto-randomness isn't needed — uniqueness within a
  // single view is enough.
  _idCounter += 1;
  const ts = Date.now().toString(36);
  return `r_${ts}_${_idCounter}`;
}

function makeDefaultRule(order: number): SmartViewRule {
  return {
    id: generateRuleId(),
    selector: {
      ifc_class: 'IfcWall',
      property: null,
      operator: null,
      value: null,
    },
    action: 'show',
    action_args: {},
    order,
  };
}

/** Stringify a stored selector.value for the editor's text input.
 *  ``null`` becomes ''; arrays become 'a, b, c'; numbers become their
 *  string form. */
function valueToString(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (Array.isArray(v)) return v.map(String).join(', ');
  return String(v);
}

/** Inverse of {@link valueToString} — parse the input back into the
 *  shape the backend expects for the chosen operator. */
function parseValueForOperator(raw: string, op: SmartViewOperator | null): unknown {
  if (op === null) return null;
  if (op === 'exists') return null;
  const trimmed = raw.trim();
  if (op === 'gt' || op === 'lt') {
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : trimmed; // leave raw on bad input; backend will 422
  }
  if (op === 'in') {
    return trimmed
      ? trimmed.split(',').map((p) => {
          const s = p.trim();
          const n = Number(s);
          return Number.isFinite(n) && s !== '' ? n : s;
        })
      : [];
  }
  if (op === 'between') {
    const parts = trimmed.split(',').map((p) => p.trim());
    if (parts.length !== 2) return trimmed;
    const a = Number(parts[0]);
    const b = Number(parts[1]);
    return [Number.isFinite(a) ? a : parts[0], Number.isFinite(b) ? b : parts[1]];
  }
  return trimmed;
}

/* ── Props ────────────────────────────────────────────────────────────── */

export interface SmartViewRuleEditorProps {
  open: boolean;
  onClose: () => void;
  /** When provided we update; when null we create. */
  initialView?: SmartViewResponse | null;
  /** Scope for newly-created views. Ignored when updating. */
  scopeType: SmartViewScopeType;
  scopeId: string;
  /** Fired after a successful save with the server's response. */
  onSaved?: (view: SmartViewResponse) => void;
}

/* ── Component ────────────────────────────────────────────────────────── */

export function SmartViewRuleEditor({
  open,
  onClose,
  initialView = null,
  scopeType,
  scopeId,
  onSaved,
}: SmartViewRuleEditorProps) {
  const { t } = useTranslation();

  // Reset local state every time the editor is opened. We key off
  // ``initialView?.id ?? open`` via useMemo so the form clears cleanly
  // when the modal goes from open → close → open with no initial view.
  const seed = useMemo(() => {
    if (initialView) {
      return {
        name: initialView.name,
        description: initialView.description ?? '',
        defaultAction: (initialView.default_action as SmartViewDefaultAction) ?? 'show_all',
        rules: initialView.rules.map((r) => ({ ...r, action_args: { ...r.action_args } })),
      };
    }
    return {
      name: '',
      description: '',
      defaultAction: 'show_all' as SmartViewDefaultAction,
      rules: [] as SmartViewRule[],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialView, open]);

  const [name, setName] = useState(seed.name);
  const [description, setDescription] = useState(seed.description);
  const [defaultAction, setDefaultAction] = useState<SmartViewDefaultAction>(
    seed.defaultAction,
  );
  const [rules, setRules] = useState<SmartViewRule[]>(seed.rules);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  // Reset whenever ``seed`` identity flips (i.e. modal re-opened, or a
  // different view was selected for editing). Mirrors the same pattern
  // every other "edit-in-place" modal in the codebase uses.
  useEffect(() => {
    setName(seed.name);
    setDescription(seed.description);
    setDefaultAction(seed.defaultAction);
    setRules(seed.rules);
    setNameError(null);
    setError(null);
  }, [seed]);

  if (!open) return null;

  const isEdit = Boolean(initialView?.id);

  /* ── Rule mutations ───────────────────────────────────────────────── */

  function patchRule(idx: number, patch: Partial<SmartViewRule>): void {
    setRules((prev) =>
      prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)),
    );
  }

  function patchSelector(idx: number, patch: Partial<SmartViewSelector>): void {
    setRules((prev) =>
      prev.map((r, i) =>
        i === idx ? { ...r, selector: { ...r.selector, ...patch } } : r,
      ),
    );
  }

  function patchActionArgs(idx: number, patch: Partial<SmartViewActionArgs>): void {
    setRules((prev) =>
      prev.map((r, i) =>
        i === idx ? { ...r, action_args: { ...r.action_args, ...patch } } : r,
      ),
    );
  }

  function addRule(): void {
    setRules((prev) => [...prev, makeDefaultRule(prev.length)]);
  }

  function deleteRule(idx: number): void {
    setRules((prev) =>
      prev
        .filter((_, i) => i !== idx)
        // Re-index ``order`` so it always equals the array position. The
        // backend tolerates gaps, but consistent indices make tests &
        // debugging easier to read.
        .map((r, i) => ({ ...r, order: i })),
    );
  }

  function moveRule(from: number, to: number): void {
    if (from === to) return;
    setRules((prev) => {
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      if (!moved) return prev;
      next.splice(to, 0, moved);
      return next.map((r, i) => ({ ...r, order: i }));
    });
  }

  /* ── Drag-drop (HTML5, no deps) ───────────────────────────────────── */

  function handleDragStart(e: DragEvent<HTMLDivElement>, idx: number): void {
    setDragIndex(idx);
    // Required for Firefox to start the drag at all.
    e.dataTransfer.effectAllowed = 'move';
    try {
      e.dataTransfer.setData('text/plain', String(idx));
    } catch {
      // Some test envs throw on setData — silently ignored.
    }
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>): void {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }

  function handleDrop(e: DragEvent<HTMLDivElement>, toIdx: number): void {
    e.preventDefault();
    if (dragIndex === null) return;
    moveRule(dragIndex, toIdx);
    setDragIndex(null);
  }

  /* ── Save ─────────────────────────────────────────────────────────── */

  async function handleSave(): Promise<void> {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setNameError(
        t('smartViews.error_name_required', {
          defaultValue: 'Please give this view a name.',
        }),
      );
      return;
    }
    setNameError(null);
    setError(null);
    setSaving(true);
    try {
      let saved: SmartViewResponse;
      if (initialView?.id) {
        saved = await updateSmartView(initialView.id, {
          name: trimmedName,
          description: description.trim() || null,
          rules,
          default_action: defaultAction,
        });
      } else {
        const payload: SmartViewCreatePayload = {
          name: trimmedName,
          description: description.trim() || null,
          rules,
          default_action: defaultAction,
          scope_type: scopeType,
          scope_id: scopeId,
        };
        saved = await createSmartView(payload);
      }
      onSaved?.(saved);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  /* ── Render ───────────────────────────────────────────────────────── */

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={
        isEdit
          ? t('smartViews.edit', { defaultValue: 'Edit' })
          : t('smartViews.new', { defaultValue: 'New view' })
      }
      size="xl"
      busy={saving}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            {t('smartViews.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            loading={saving}
            data-testid="smart-view-save"
          >
            {t('smartViews.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4" data-testid="smart-view-editor">
        {/* Head */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Input
            label={t('smartViews.name', { defaultValue: 'Name' })}
            value={name}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setName(e.target.value)}
            error={nameError ?? undefined}
            data-testid="smart-view-name-input"
            autoFocus
          />
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="smart-view-default-action"
              className="text-sm font-medium text-content-primary"
            >
              {t('smartViews.default_action', { defaultValue: 'Default action' })}
            </label>
            <select
              id="smart-view-default-action"
              className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm"
              value={defaultAction}
              onChange={(e) =>
                setDefaultAction(e.target.value as SmartViewDefaultAction)
              }
              data-testid="smart-view-default-action"
            >
              <option value="show_all">
                {t('smartViews.default_show_all', { defaultValue: 'Show all' })}
              </option>
              <option value="hide_all">
                {t('smartViews.default_hide_all', { defaultValue: 'Hide all' })}
              </option>
            </select>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="smart-view-description"
            className="text-sm font-medium text-content-primary"
          >
            {t('smartViews.description', { defaultValue: 'Description' })}
          </label>
          <textarea
            id="smart-view-description"
            className="min-h-[64px] w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            data-testid="smart-view-description-input"
          />
        </div>

        {/* Rules list */}
        <div className="flex flex-col gap-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('smartViews.rules_section', { defaultValue: 'Rules' })}
          </div>
          {rules.length === 0 && (
            <div className="rounded-lg border border-dashed border-border-light bg-surface-secondary/50 px-4 py-6 text-center text-sm text-content-tertiary">
              {t('smartViews.no_rules_yet', {
                defaultValue: 'No rules yet - add one below.',
              })}
            </div>
          )}
          {rules.map((rule, idx) => (
            <RuleRow
              key={rule.id}
              rule={rule}
              index={idx}
              onPatchRule={(patch) => patchRule(idx, patch)}
              onPatchSelector={(patch) => patchSelector(idx, patch)}
              onPatchActionArgs={(patch) => patchActionArgs(idx, patch)}
              onDelete={() => deleteRule(idx)}
              onDragStart={(e) => handleDragStart(e, idx)}
              onDragOver={handleDragOver}
              onDrop={(e) => handleDrop(e, idx)}
              isDragSource={dragIndex === idx}
            />
          ))}
          <button
            type="button"
            onClick={addRule}
            className="flex items-center gap-2 self-start rounded-lg border border-dashed border-oe-blue/40 px-3 py-1.5 text-sm text-oe-blue hover:bg-oe-blue/5"
            data-testid="smart-view-add-rule"
          >
            <Plus size={14} />
            {t('smartViews.rule_add', { defaultValue: 'Add rule' })}
          </button>
        </div>

        {error && (
          <div
            className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/40 px-3 py-2 text-sm text-semantic-error"
            data-testid="smart-view-save-error"
          >
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>
    </WideModal>
  );
}

/* ── RuleRow — one editable row ──────────────────────────────────────── */

interface RuleRowProps {
  rule: SmartViewRule;
  index: number;
  onPatchRule: (patch: Partial<SmartViewRule>) => void;
  onPatchSelector: (patch: Partial<SmartViewSelector>) => void;
  onPatchActionArgs: (patch: Partial<SmartViewActionArgs>) => void;
  onDelete: () => void;
  onDragStart: (e: DragEvent<HTMLDivElement>) => void;
  onDragOver: (e: DragEvent<HTMLDivElement>) => void;
  onDrop: (e: DragEvent<HTMLDivElement>) => void;
  isDragSource: boolean;
}

function RuleRow({
  rule,
  index,
  onPatchRule,
  onPatchSelector,
  onPatchActionArgs,
  onDelete,
  onDragStart,
  onDragOver,
  onDrop,
  isDragSource,
}: RuleRowProps) {
  const { t } = useTranslation();
  const op = rule.selector.operator;
  const action = rule.action;

  const valueInputType: 'text' | 'number' | 'hidden' | 'list' = (() => {
    if (op === null || op === 'exists') return 'hidden';
    if (op === 'gt' || op === 'lt') return 'number';
    if (op === 'in' || op === 'between') return 'list';
    return 'text';
  })();

  const valueAsString = valueToString(rule.selector.value);

  return (
    <div
      className={clsx(
        'rounded-xl border border-border-light bg-surface-elevated p-3',
        'flex flex-col gap-2',
        isDragSource && 'opacity-60',
      )}
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      data-testid={`smart-view-rule-${index}`}
    >
      <div className="flex items-center gap-2">
        <div
          className="cursor-grab text-content-tertiary"
          title={t('smartViews.drag_to_reorder', { defaultValue: 'Drag to reorder' })}
        >
          <GripVertical size={16} />
        </div>
        <span className="text-xs font-medium text-content-tertiary tabular-nums">
          #{index + 1}
        </span>
        <span className="text-xs text-content-tertiary">
          {t('smartViews.rule_order', { defaultValue: 'order' })} {rule.order}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onDelete}
          className="text-content-tertiary hover:text-semantic-error"
          aria-label={t('smartViews.delete', { defaultValue: 'Delete' })}
          data-testid={`smart-view-rule-delete-${index}`}
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
        {/* IFC class with datalist autocomplete */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-content-tertiary">
            {t('smartViews.rule_selector_ifc_class', { defaultValue: 'IFC class' })}
          </label>
          <input
            list={`ifc-classes-${index}`}
            className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
            value={rule.selector.ifc_class ?? ''}
            onChange={(e) =>
              onPatchSelector({ ifc_class: e.target.value || null })
            }
            data-testid={`smart-view-rule-ifc-${index}`}
          />
          <datalist id={`ifc-classes-${index}`}>
            {COMMON_IFC_CLASSES.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>

        {/* Property */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-content-tertiary">
            {t('smartViews.rule_selector_property', { defaultValue: 'Property' })}
          </label>
          <input
            className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
            value={rule.selector.property ?? ''}
            onChange={(e) =>
              onPatchSelector({ property: e.target.value || null })
            }
            data-testid={`smart-view-rule-property-${index}`}
          />
        </div>

        {/* Operator */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-content-tertiary">
            {t('smartViews.rule_selector_operator', { defaultValue: 'Operator' })}
          </label>
          <select
            className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
            value={op ?? ''}
            onChange={(e) => {
              const next = e.target.value === '' ? null : (e.target.value as SmartViewOperator);
              // Reset value when switching to ``exists`` (it ignores
              // value) or when toggling between scalar/list shapes —
              // otherwise the backend rejects the saved rule with 422.
              const nextValue = next === 'exists' ? null : rule.selector.value;
              onPatchSelector({ operator: next, value: nextValue });
            }}
            data-testid={`smart-view-rule-operator-${index}`}
          >
            <option value="">—</option>
            {OPERATORS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>

        {/* Value — type morphs by operator */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-content-tertiary">
            {t('smartViews.rule_selector_value', { defaultValue: 'Value' })}
          </label>
          {valueInputType === 'hidden' ? (
            <div
              className="h-9 rounded-lg border border-dashed border-border-light bg-surface-secondary/40 px-2 text-xs text-content-tertiary flex items-center"
              data-testid={`smart-view-rule-value-disabled-${index}`}
            >
              {t('smartViews.value_disabled', { defaultValue: 'n/a' })}
            </div>
          ) : valueInputType === 'number' ? (
            <input
              type="number"
              className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
              value={valueAsString}
              onChange={(e) =>
                onPatchSelector({
                  value: parseValueForOperator(e.target.value, op),
                })
              }
              data-testid={`smart-view-rule-value-${index}`}
            />
          ) : (
            <input
              type="text"
              placeholder={
                valueInputType === 'list'
                  ? t('smartViews.value_placeholder_list', {
                      defaultValue: 'a, b, c',
                    })
                  : ''
              }
              className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
              value={valueAsString}
              onChange={(e) =>
                onPatchSelector({
                  value: parseValueForOperator(e.target.value, op),
                })
              }
              data-testid={`smart-view-rule-value-${index}`}
            />
          )}
        </div>
      </div>

      {/* Action row */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-content-tertiary">
          {t('smartViews.rule_action', { defaultValue: 'Action' })}
        </label>
        <select
          className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
          value={action}
          onChange={(e) =>
            onPatchRule({ action: e.target.value as SmartViewAction })
          }
          data-testid={`smart-view-rule-action-${index}`}
        >
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        {/* Color picker — only when action='color' */}
        {action === 'color' && (
          <div
            className="flex items-center gap-1.5"
            data-testid={`smart-view-rule-color-${index}`}
          >
            <input
              type="color"
              className="h-9 w-9 rounded-md border border-border bg-surface-primary p-0"
              value={rule.action_args.color ?? '#3b82f6'}
              onChange={(e) =>
                onPatchActionArgs({ color: e.target.value })
              }
              aria-label={t('smartViews.color_picker', { defaultValue: 'Color' })}
            />
            <input
              type="text"
              className="h-9 w-24 rounded-lg border border-border bg-surface-primary px-2 text-sm font-mono"
              value={rule.action_args.color ?? ''}
              onChange={(e) =>
                onPatchActionArgs({ color: e.target.value })
              }
              placeholder="#RRGGBB"
              data-testid={`smart-view-rule-color-hex-${index}`}
            />
          </div>
        )}

        {/* Opacity slider — only when action='transparent' */}
        {action === 'transparent' && (
          <div
            className="flex items-center gap-2 flex-1 min-w-[180px]"
            data-testid={`smart-view-rule-opacity-${index}`}
          >
            <Slider
              value={rule.action_args.opacity ?? 0.5}
              onChange={(v) => onPatchActionArgs({ opacity: v })}
              min={0}
              max={1}
              step={0.05}
              format={(v) => `${Math.round(v * 100)}%`}
            />
          </div>
        )}

        {/* Auto-color toggle — relevant for color + isolate. */}
        {(action === 'color' || action === 'isolate') && (
          <label className="flex items-center gap-1.5 text-xs text-content-secondary">
            <input
              type="checkbox"
              checked={Boolean(rule.action_args.color_by_property)}
              onChange={(e) =>
                onPatchActionArgs({
                  color_by_property: e.target.checked
                    ? rule.action_args.color_by_property ?? rule.selector.property ?? ''
                    : null,
                })
              }
              data-testid={`smart-view-rule-colorby-toggle-${index}`}
            />
            {t('smartViews.rule_action_color_by', {
              defaultValue: 'Auto-colour by property',
            })}
          </label>
        )}

        {rule.action_args.color_by_property !== null &&
          rule.action_args.color_by_property !== undefined && (
            <input
              type="text"
              className="h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm"
              value={rule.action_args.color_by_property}
              onChange={(e) =>
                onPatchActionArgs({ color_by_property: e.target.value })
              }
              placeholder={t('smartViews.rule_selector_property', {
                defaultValue: 'Property',
              })}
              data-testid={`smart-view-rule-colorby-input-${index}`}
            />
          )}
      </div>
    </div>
  );
}

export default SmartViewRuleEditor;

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// TemplateBuilder - compose (or edit) a reusable form / checklist template from
// ordered fields. Client-side integrity mirrors the backend so problems show
// live; the backend re-validates on save and is the source of truth.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  GripVertical,
  X,
  AlertTriangle,
  Asterisk,
  Copy,
  Eye,
  EyeOff,
  Settings2,
  GitBranch,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Badge, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import {
  createTemplate,
  updateTemplate,
  type ConditionExpr,
  type ConditionOp,
  type FieldIssue,
  type FormFieldDef,
  type TemplateCategory,
  type TemplateDetail,
  type TemplateUpdatePayload,
} from './api';
import {
  FIELD_TYPES,
  fieldMeta,
  CHOICE_TYPES,
  LAYOUT_TYPES,
  TEXT_TYPES,
  PLACEHOLDER_TYPES,
  CONDITION_OPS,
  CONDITION_OP_LABELS,
  VALUELESS_OPS,
  CATEGORY_ORDER,
  CATEGORY_LABELS,
  DEFAULT_RATING_SCALE,
  ensureFieldKeys,
  validateTemplateFields,
  parseFormula,
  type FieldTypeMeta,
} from './fieldTypes';
import { FormPreview } from './FormPreview';
import { fmtList } from '@/shared/lib/formatters';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

type EditableField = FormFieldDef & { _id: string };

let _seq = 0;
function nextId(): string {
  _seq += 1;
  return `f${_seq}_${Math.random().toString(36).slice(2, 7)}`;
}

function blankField(type: FormFieldDef['type']): EditableField {
  const meta = fieldMeta(type);
  return {
    _id: nextId(),
    key: '',
    type,
    label: '',
    required: false,
    help_text: '',
    options: meta.hasOptions ? ['Option 1', 'Option 2'] : [],
    unit: null,
    max_rating: meta.hasRating ? DEFAULT_RATING_SCALE : null,
    placeholder: null,
    default: null,
    min: null,
    max: null,
    min_length: null,
    pattern: null,
    formula: type === 'formula' ? '' : null,
    visible_if: null,
    required_if: null,
  };
}

function toEditable(fields: FormFieldDef[]): EditableField[] {
  return fields.map((f) => ({
    _id: nextId(),
    key: f.key,
    type: f.type,
    label: f.label,
    required: f.required,
    help_text: f.help_text ?? '',
    options: f.options ?? [],
    unit: f.unit ?? null,
    max_rating: f.max_rating ?? (fieldMeta(f.type).hasRating ? DEFAULT_RATING_SCALE : null),
    placeholder: f.placeholder ?? null,
    default: f.default ?? null,
    min: f.min ?? null,
    max: f.max ?? null,
    min_length: f.min_length ?? null,
    pattern: f.pattern ?? null,
    formula: f.formula ?? null,
    visible_if: f.visible_if ?? null,
    required_if: f.required_if ?? null,
  }));
}

/**
 * Turn the editor state into the field list and tag list the API expects.
 * Lives at module scope so an edit can run it a second time over the template
 * as it was loaded and get the baseline to diff against, which keeps the two
 * from drifting apart.
 */
function buildTemplatePayload(fields: EditableField[], tagsText: string) {
  const cleaned = ensureFieldKeys(
    fields.map((f) => ({
      key: f.key,
      type: f.type,
      label: f.label.trim(),
      required: LAYOUT_TYPES.has(f.type) ? false : f.required,
      help_text: (f.help_text ?? '').trim() || null,
      options: CHOICE_TYPES.has(f.type) ? (f.options ?? []).map((o) => o.trim()).filter(Boolean) : [],
      unit: f.type === 'number' ? (f.unit ?? null) : null,
      max_rating: f.type === 'rating' ? (f.max_rating ?? DEFAULT_RATING_SCALE) : null,
      // Per-field config + branching logic - the backend normaliser keeps only
      // the keys that apply to each field type, so passing them all is safe.
      placeholder: f.placeholder ?? null,
      default: f.default ?? null,
      min: f.min ?? null,
      max: f.max ?? null,
      min_length: f.min_length ?? null,
      pattern: (f.pattern ?? '').trim() || null,
      formula: f.type === 'formula' ? (f.formula ?? '').trim() || null : null,
      visible_if: cleanRule(f.visible_if),
      required_if: cleanRule(f.required_if),
    })),
  );
  const tags = tagsText
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  return { cleaned, tags };
}

export interface TemplateBuilderProps {
  open: boolean;
  onClose: () => void;
  /** When set, edit this template; otherwise create a new one. */
  initial?: TemplateDetail | null;
  /** Active project - a new template can be pinned to it or kept global. */
  projectId?: string | null;
  onSaved: (template: TemplateDetail) => void;
}

export function TemplateBuilder({ open, onClose, initial, projectId, onSaved }: TemplateBuilderProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [category, setCategory] = useState<TemplateCategory>(initial?.category ?? 'custom');
  const [scope, setScope] = useState<'global' | 'project'>(
    initial ? (initial.project_id ? 'project' : 'global') : 'global',
  );
  const [tagsText, setTagsText] = useState((initial?.tags ?? []).join(', '));
  const [fields, setFields] = useState<EditableField[]>(initial ? toEditable(initial.fields) : []);
  const [showPalette, setShowPalette] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  const issues = useMemo(() => validateTemplateFields(fields), [fields]);
  const isEdit = !!initial;

  const patch = (id: string, changes: Partial<EditableField>) =>
    setFields((prev) => prev.map((f) => (f._id === id ? { ...f, ...changes } : f)));

  const addField = (type: FormFieldDef['type']) => {
    setFields((prev) => [...prev, blankField(type)]);
    setShowPalette(false);
  };

  const removeField = (id: string) => setFields((prev) => prev.filter((f) => f._id !== id));

  const duplicateField = (id: string) =>
    setFields((prev) => {
      const idx = prev.findIndex((f) => f._id === id);
      if (idx < 0) return prev;
      const src = prev[idx]!;
      const copy: EditableField = { ...src, _id: nextId(), key: '' };
      const next = [...prev];
      next.splice(idx + 1, 0, copy);
      return next;
    });

  const move = (id: string, dir: -1 | 1) =>
    setFields((prev) => {
      const idx = prev.findIndex((f) => f._id === id);
      const target = idx + dir;
      if (idx < 0 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      const a = next[idx];
      const b = next[target];
      if (!a || !b) return prev;
      next[idx] = b;
      next[target] = a;
      return next;
    });

  const buildPayload = () => buildTemplatePayload(fields, tagsText);

  // Field definitions as the filler will see them, for the live preview. Keys are
  // filled from labels exactly like on save, so a formula / condition referencing
  // another field resolves in the preview too.
  const previewFields = useMemo(() => buildPayload().cleaned as FormFieldDef[], [fields]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveMut = useMutation({
    mutationFn: async (): Promise<TemplateDetail> => {
      const { cleaned, tags } = buildPayload();
      if (isEdit && initial) {
        // Only what the user actually edited goes back. Renaming a template
        // used to resend its whole field list as this editor had loaded it, so
        // a question a colleague had added in the meantime was silently
        // dropped. The update route dumps with `exclude_unset=True`, so an
        // omitted field is left alone. The baseline runs the same builder over
        // the template as it arrived, and the two lists are compared by content
        // because a fresh array is produced on every save.
        const base = buildTemplatePayload(
          toEditable(initial.fields),
          (initial.tags ?? []).join(', '),
        );
        const body: TemplateUpdatePayload = {};
        if (name !== (initial.name ?? '')) body.name = name.trim();
        if (description !== (initial.description ?? '')) {
          body.description = description.trim() || null;
        }
        if (category !== (initial.category ?? 'custom')) body.category = category;
        if (JSON.stringify(cleaned) !== JSON.stringify(base.cleaned)) {
          body.fields = cleaned as FormFieldDef[];
        }
        if (JSON.stringify(tags) !== JSON.stringify(base.tags)) body.tags = tags;
        return updateTemplate(initial.id, body);
      }
      return createTemplate({
        project_id: scope === 'project' ? (projectId ?? null) : null,
        name: name.trim(),
        description: description.trim() || null,
        category,
        status: 'published',
        fields: cleaned,
        tags,
      });
    },
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ['forms', 'templates'] });
      qc.invalidateQueries({ queryKey: ['forms', 'categories'] });
      addToast({
        type: 'success',
        title: isEdit
          ? t('forms.template_updated', { defaultValue: 'Template updated' })
          : t('forms.template_created', { defaultValue: 'Template created' }),
      });
      onSaved(saved);
    },
    onError: (e: unknown) => {
      // Surface backend field issues when present (422 with detail.issues).
      const serverIssues = extractIssues(e);
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: serverIssues.length ? serverIssues[0]!.message : getErrorMessage(e),
      });
    },
  });

  const canSave = name.trim().length > 0 && issues.length === 0 && !saveMut.isPending;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="xl"
      busy={saveMut.isPending}
      title={
        isEdit
          ? t('forms.edit_template', { defaultValue: 'Edit template' })
          : t('forms.new_template', { defaultValue: 'New template' })
      }
      subtitle={t('forms.builder_subtitle', {
        defaultValue: 'Compose a reusable form or checklist from ordered fields.',
      })}
      footer={
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 text-xs text-content-tertiary">
            {issues.length > 0 ? (
              <span className="inline-flex items-center gap-1.5 text-semantic-warning">
                <AlertTriangle size={14} />
                {t('forms.issues_count', {
                  defaultValue: '{{count}} issue(s) to fix',
                  count: issues.length,
                })}
              </span>
            ) : (
              <span>
                {t('forms.field_count', { defaultValue: '{{count}} field(s)', count: fields.length })}
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="secondary" onClick={onClose} disabled={saveMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button onClick={() => saveMut.mutate()} loading={saveMut.isPending} disabled={!canSave}>
              {isEdit
                ? t('common.save', { defaultValue: 'Save' })
                : t('forms.create_template', { defaultValue: 'Create template' })}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-5">
        {/* Template meta */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-content-secondary">
              {t('forms.template_name', { defaultValue: 'Template name' })}
            </span>
            <input
              className={inputCls}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('forms.template_name_ph', { defaultValue: 'e.g. Site safety induction' })}
              autoFocus
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-content-secondary">
              {t('forms.category', { defaultValue: 'Category' })}
            </span>
            <select
              className={inputCls}
              value={category}
              onChange={(e) => setCategory(e.target.value as TemplateCategory)}
            >
              {CATEGORY_ORDER.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABELS[c]}
                </option>
              ))}
            </select>
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-xs font-medium text-content-secondary">
              {t('forms.description', { defaultValue: 'Description' })}
            </span>
            <input
              className={inputCls}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('forms.description_ph', { defaultValue: 'What is this form for?' })}
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-xs font-medium text-content-secondary">
              {t('forms.tags', { defaultValue: 'Tags (comma separated)' })}
            </span>
            <input
              className={inputCls}
              value={tagsText}
              onChange={(e) => setTagsText(e.target.value)}
              placeholder="safety, induction"
            />
          </label>
          {!isEdit && projectId && (
            <div className="sm:col-span-2">
              <span className="mb-1 block text-xs font-medium text-content-secondary">
                {t('forms.availability', { defaultValue: 'Availability' })}
              </span>
              <div className="flex flex-wrap gap-2">
                <ScopeChip
                  active={scope === 'global'}
                  onClick={() => setScope('global')}
                  label={t('forms.scope_global', { defaultValue: 'All projects (library)' })}
                />
                <ScopeChip
                  active={scope === 'project'}
                  onClick={() => setScope('project')}
                  label={t('forms.scope_project', { defaultValue: 'This project only' })}
                />
              </div>
            </div>
          )}
        </div>

        {/* Fields + live preview */}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('forms.fields', { defaultValue: 'Fields' })}
              </h3>
              <button
                type="button"
                onClick={() => setShowPreview((v) => !v)}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary lg:hidden"
              >
                {showPreview ? <EyeOff size={13} /> : <Eye size={13} />}
                {showPreview
                  ? t('forms.hide_preview', { defaultValue: 'Hide preview' })
                  : t('forms.show_preview', { defaultValue: 'Preview' })}
              </button>
            </div>

            {fields.length === 0 && (
              <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-content-tertiary">
                {t('forms.no_fields_yet', { defaultValue: 'No fields yet. Add your first field below.' })}
              </div>
            )}

            {fields.map((field, idx) => (
              <FieldCard
                key={field._id}
                field={field}
                index={idx}
                total={fields.length}
                allFields={fields}
                onPatch={(changes) => patch(field._id, changes)}
                onRemove={() => removeField(field._id)}
                onDuplicate={() => duplicateField(field._id)}
                onMove={(dir) => move(field._id, dir)}
              />
            ))}

            {/* Add-field palette */}
            <div className="relative">
              <Button
                variant="secondary"
                icon={<Plus size={15} />}
                onClick={() => setShowPalette((v) => !v)}
              >
                {t('forms.add_field', { defaultValue: 'Add field' })}
              </Button>
              {showPalette && (
                <div className="absolute z-10 mt-2 grid w-full max-w-2xl grid-cols-2 gap-1 rounded-xl border border-border bg-surface-elevated p-2 shadow-xl sm:grid-cols-3">
                  {FIELD_TYPES.map((m) => (
                    <PaletteButton key={m.type} meta={m} onClick={() => addField(m.type)} />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Live preview - always shown on large screens, toggled on small */}
          <div className={clsx('lg:block', showPreview ? 'block' : 'hidden')}>
            <div className="sticky top-2">
              <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                <Eye size={13} />
                {t('forms.live_preview', { defaultValue: 'Live preview' })}
              </div>
              <div className="max-h-[60vh] overflow-y-auto rounded-xl border border-border bg-surface-secondary p-3">
                <FormPreview fields={previewFields} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </WideModal>
  );
}

/* -- Sub-components -------------------------------------------------------- */

function ScopeChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'inline-flex h-8 items-center rounded-full border px-3 text-xs font-medium transition-colors',
        active
          ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
          : 'border-border text-content-secondary hover:bg-surface-secondary',
      )}
    >
      {label}
    </button>
  );
}

function PaletteButton({ meta, onClick }: { meta: FieldTypeMeta; onClick: () => void }) {
  const Icon = meta.icon;
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-start gap-2 rounded-lg border border-transparent p-2 text-left hover:border-border hover:bg-surface-secondary"
    >
      <Icon size={16} className="mt-0.5 shrink-0 text-oe-blue" />
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-content-primary">{meta.label}</span>
        <span className="block truncate text-xs text-content-tertiary">{meta.hint}</span>
      </span>
    </button>
  );
}

interface FieldCardProps {
  field: EditableField;
  index: number;
  total: number;
  allFields: EditableField[];
  onPatch: (changes: Partial<EditableField>) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  onMove: (dir: -1 | 1) => void;
}

function FieldCard({ field, index, total, allFields, onPatch, onRemove, onDuplicate, onMove }: FieldCardProps) {
  const { t } = useTranslation();
  const [showConfig, setShowConfig] = useState(false);
  const [showLogic, setShowLogic] = useState(false);
  const meta = fieldMeta(field.type);
  const Icon = meta.icon;
  const isLayout = LAYOUT_TYPES.has(field.type);
  const isFormula = field.type === 'formula';

  // Other fields this one may reference in a condition or formula, with their
  // real (deduped) keys, resolved exactly like on save.
  const refs = useMemo(() => {
    const keyed = ensureFieldKeys(allFields);
    return keyed
      .map((f, i) => ({ key: f.key, label: f.label || f.key, type: f.type, i }))
      .filter((r) => r.i !== index && !LAYOUT_TYPES.has(r.type));
  }, [allFields, index]);

  const hasLogic = !!(field.visible_if || field.required_if);
  const hasConfig =
    !!(field.placeholder || field.default != null || field.min != null || field.max != null ||
      field.min_length != null || (field.pattern && field.pattern.trim()));

  return (
    <div
      className={clsx(
        'rounded-xl border border-border bg-surface-primary p-3',
        isLayout && 'bg-surface-secondary',
      )}
    >
      <div className="flex items-start gap-2">
        <GripVertical size={16} className="mt-2.5 shrink-0 text-content-quaternary" aria-hidden />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="neutral" size="sm">
              <Icon size={12} className="mr-1" />
              {meta.label}
            </Badge>
            {!isLayout && !isFormula && (
              <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-content-secondary">
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(e) => onPatch({ required: e.target.checked })}
                  className="h-3.5 w-3.5 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                />
                <Asterisk size={11} className="text-semantic-error" />
                {t('forms.required', { defaultValue: 'Required' })}
              </label>
            )}
            {hasLogic && (
              <Badge variant="blue" size="sm">
                <GitBranch size={11} className="mr-1" />
                {t('forms.has_logic', { defaultValue: 'Logic' })}
              </Badge>
            )}
          </div>

          <input
            className={inputCls}
            value={field.label}
            onChange={(e) => onPatch({ label: e.target.value })}
            placeholder={
              isLayout
                ? t('forms.section_title_ph', { defaultValue: 'Section title' })
                : t('forms.question_ph', { defaultValue: 'Question / label' })
            }
          />

          {!isLayout && (
            <input
              className={clsx(inputCls, 'h-8 text-xs')}
              value={field.help_text ?? ''}
              onChange={(e) => onPatch({ help_text: e.target.value })}
              placeholder={t('forms.help_text_ph', { defaultValue: 'Help text (optional)' })}
            />
          )}

          {CHOICE_TYPES.has(field.type) && (
            <OptionsEditor
              options={field.options ?? []}
              onChange={(options) => onPatch({ options })}
            />
          )}

          {field.type === 'number' && (
            <div className="flex flex-wrap items-center gap-2">
              <input
                className={clsx(inputCls, 'h-8 max-w-[10rem] text-xs')}
                value={field.unit ?? ''}
                onChange={(e) => onPatch({ unit: e.target.value || null })}
                placeholder={t('forms.unit_ph', { defaultValue: 'Unit (e.g. mm, m3)' })}
              />
              <NumBound
                label={t('forms.min', { defaultValue: 'Min' })}
                value={field.min}
                onChange={(v) => onPatch({ min: v })}
              />
              <NumBound
                label={t('forms.max', { defaultValue: 'Max' })}
                value={field.max}
                onChange={(v) => onPatch({ max: v })}
              />
            </div>
          )}

          {field.type === 'rating' && (
            <label className="inline-flex items-center gap-2 text-xs text-content-secondary">
              {t('forms.rating_scale', { defaultValue: 'Scale 1 to' })}
              <input
                type="number"
                min={2}
                max={10}
                className={clsx(inputCls, 'h-8 w-20 text-xs')}
                value={field.max_rating ?? DEFAULT_RATING_SCALE}
                onChange={(e) => onPatch({ max_rating: Number(e.target.value) || DEFAULT_RATING_SCALE })}
              />
            </label>
          )}

          {isFormula && <FormulaEditor field={field} refs={refs} onPatch={onPatch} />}

          {/* Expanders: capture settings + conditional logic */}
          {!isLayout && (
            <div className="flex flex-wrap gap-3 pt-0.5">
              {!isFormula && (
                <ExpanderToggle
                  active={showConfig}
                  dot={hasConfig}
                  icon={<Settings2 size={12} />}
                  label={t('forms.field_settings', { defaultValue: 'Settings' })}
                  onClick={() => setShowConfig((v) => !v)}
                />
              )}
              <ExpanderToggle
                active={showLogic}
                dot={hasLogic}
                icon={<GitBranch size={12} />}
                label={t('forms.field_logic', { defaultValue: 'Logic' })}
                onClick={() => setShowLogic((v) => !v)}
              />
            </div>
          )}

          {showConfig && !isFormula && (
            <FieldConfig field={field} onPatch={onPatch} />
          )}

          {showLogic && (
            <div className="space-y-2 rounded-lg border border-border-light bg-surface-secondary p-2.5">
              <ConditionEditor
                title={t('forms.visible_when', { defaultValue: 'Show this field only when' })}
                rule={field.visible_if ?? null}
                refs={refs}
                onChange={(r) => onPatch({ visible_if: r })}
              />
              {!isFormula && (
                <ConditionEditor
                  title={t('forms.required_when', { defaultValue: 'Make it required only when' })}
                  rule={field.required_if ?? null}
                  refs={refs}
                  onChange={(r) => onPatch({ required_if: r })}
                />
              )}
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-center gap-0.5">
          <IconBtn label="Move up" disabled={index === 0} onClick={() => onMove(-1)}>
            <ArrowUp size={14} />
          </IconBtn>
          <IconBtn label="Move down" disabled={index === total - 1} onClick={() => onMove(1)}>
            <ArrowDown size={14} />
          </IconBtn>
          <IconBtn label="Duplicate field" onClick={onDuplicate}>
            <Copy size={14} />
          </IconBtn>
          <IconBtn label="Remove field" danger onClick={onRemove}>
            <Trash2 size={14} />
          </IconBtn>
        </div>
      </div>
    </div>
  );
}

/* -- Field config (placeholder / default / length / pattern) --------------- */

interface FieldConfigProps {
  field: EditableField;
  onPatch: (changes: Partial<EditableField>) => void;
}

function FieldConfig({ field, onPatch }: FieldConfigProps) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border border-border-light bg-surface-secondary p-2.5 sm:grid-cols-2">
      {PLACEHOLDER_TYPES.has(field.type) && (
        <ConfigRow label={t('forms.placeholder', { defaultValue: 'Placeholder' })}>
          <input
            className={clsx(inputCls, 'h-8 text-xs')}
            value={field.placeholder ?? ''}
            onChange={(e) => onPatch({ placeholder: e.target.value || null })}
          />
        </ConfigRow>
      )}
      {TEXT_TYPES.has(field.type) && (
        <>
          <ConfigRow label={t('forms.min_length', { defaultValue: 'Min length' })}>
            <input
              type="number"
              min={0}
              className={clsx(inputCls, 'h-8 text-xs')}
              value={field.min_length ?? ''}
              onChange={(e) =>
                onPatch({ min_length: e.target.value === '' ? null : Math.max(0, Number(e.target.value)) })
              }
            />
          </ConfigRow>
          <ConfigRow label={t('forms.pattern', { defaultValue: 'Pattern (regex)' })}>
            <input
              className={clsx(inputCls, 'h-8 font-mono text-xs')}
              value={field.pattern ?? ''}
              onChange={(e) => onPatch({ pattern: e.target.value || null })}
              placeholder="\\d{4}"
            />
          </ConfigRow>
        </>
      )}
      {field.type !== 'photo' && field.type !== 'signature' && (
        <ConfigRow label={t('forms.default_value', { defaultValue: 'Default value' })}>
          <DefaultValueInput field={field} onPatch={onPatch} />
        </ConfigRow>
      )}
    </div>
  );
}

function ConfigRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[11px] font-medium text-content-tertiary">{label}</span>
      {children}
    </label>
  );
}

/** A default-value control shaped to the field type (bool / choice / text). */
function DefaultValueInput({ field, onPatch }: FieldConfigProps) {
  const cls = clsx(inputCls, 'h-8 text-xs');
  if (field.type === 'checkbox') {
    return (
      <select
        className={cls}
        value={field.default === true ? 'true' : 'false'}
        onChange={(e) => onPatch({ default: e.target.value === 'true' })}
      >
        <option value="false">Unticked</option>
        <option value="true">Ticked</option>
      </select>
    );
  }
  if (field.type === 'single_choice') {
    return (
      <select
        className={cls}
        value={typeof field.default === 'string' ? field.default : ''}
        onChange={(e) => onPatch({ default: e.target.value || null })}
      >
        <option value="">-</option>
        {(field.options ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === 'pass_fail_na') {
    return (
      <select
        className={cls}
        value={typeof field.default === 'string' ? field.default : ''}
        onChange={(e) => onPatch({ default: e.target.value || null })}
      >
        <option value="">-</option>
        <option value="pass">Pass</option>
        <option value="fail">Fail</option>
        <option value="na">N/A</option>
      </select>
    );
  }
  return (
    <input
      className={cls}
      type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
      value={
        field.default == null
          ? ''
          : Array.isArray(field.default)
            ? field.default.join(', ')
            : String(field.default)
      }
      onChange={(e) => onPatch({ default: e.target.value || null })}
    />
  );
}

function NumBound({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
}) {
  return (
    <label className="inline-flex items-center gap-1 text-xs text-content-tertiary">
      {label}
      <input
        type="number"
        className={clsx(inputCls, 'h-8 w-20 text-xs')}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    </label>
  );
}

/* -- Formula editor -------------------------------------------------------- */

interface FormulaEditorProps {
  field: EditableField;
  refs: { key: string; label: string }[];
  onPatch: (changes: Partial<EditableField>) => void;
}

function FormulaEditor({ field, refs, onPatch }: FormulaEditorProps) {
  const { t } = useTranslation();
  const expr = field.formula ?? '';
  const parsed = useMemo(() => (expr.trim() ? parseFormula(expr) : null), [expr]);
  const known = new Set(refs.map((r) => r.key));
  const badRefs = parsed?.ok ? parsed.vars.filter((v) => !known.has(v)) : [];

  return (
    <div className="space-y-1.5 rounded-lg border border-border-light bg-surface-secondary p-2.5">
      <input
        className={clsx(inputCls, 'h-9 font-mono text-xs')}
        value={expr}
        onChange={(e) => onPatch({ formula: e.target.value })}
        placeholder={t('forms.formula_ph', { defaultValue: 'e.g. length * width' })}
      />
      <div className="flex items-center gap-1 text-[11px]">
        <span className="text-content-tertiary">{t('forms.unit', { defaultValue: 'Unit' })}:</span>
        <input
          className={clsx(inputCls, 'h-7 max-w-[8rem] text-xs')}
          value={field.unit ?? ''}
          onChange={(e) => onPatch({ unit: e.target.value || null })}
          placeholder="m2"
        />
      </div>
      {parsed && !parsed.ok && (
        <p className="text-[11px] text-semantic-error">
          {t('forms.formula_invalid', { defaultValue: 'Invalid formula' })}: {parsed.error}
        </p>
      )}
      {badRefs.length > 0 && (
        <p className="text-[11px] text-semantic-error">
          {t('forms.formula_unknown', { defaultValue: 'Unknown field(s)' })}: {fmtList(badRefs)}
        </p>
      )}
      {refs.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-0.5">
          <span className="text-[11px] text-content-tertiary">
            {t('forms.insert_field', { defaultValue: 'Insert' })}:
          </span>
          {refs.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => onPatch({ formula: `${expr}${expr && !expr.endsWith(' ') ? ' ' : ''}${r.key}` })}
              className="rounded border border-border bg-surface-primary px-1.5 py-0.5 font-mono text-[11px] text-oe-blue hover:bg-oe-blue-subtle"
            >
              {r.key}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* -- Conditional rule editor ----------------------------------------------- */

interface ConditionEditorProps {
  title: string;
  rule: ConditionExpr | null;
  refs: { key: string; label: string }[];
  onChange: (rule: ConditionExpr | null) => void;
}

function ConditionEditor({ title, rule, refs, onChange }: ConditionEditorProps) {
  const { t } = useTranslation();
  const isGroup = !!(rule && (rule.all || rule.any));
  const leaf = rule && !isGroup ? rule : null;

  if (isGroup) {
    return (
      <div className="text-[11px] text-content-tertiary">
        <span className="font-medium text-content-secondary">{title}</span>{' '}
        {t('forms.advanced_rule', { defaultValue: 'an advanced rule (kept as-is).' })}{' '}
        <button type="button" onClick={() => onChange(null)} className="text-oe-blue hover:underline">
          {t('common.clear', { defaultValue: 'Clear' })}
        </button>
      </div>
    );
  }

  const op = leaf?.op ?? 'eq';
  const needsValue = !VALUELESS_OPS.has(op);
  const isListOp = op === 'in' || op === 'not_in';

  const setLeaf = (patch: Partial<ConditionExpr>) => {
    const next: ConditionExpr = { field: leaf?.field, op: leaf?.op ?? 'eq', value: leaf?.value, ...patch };
    if (!next.field || !next.op) {
      onChange(null);
      return;
    }
    onChange(next);
  };

  return (
    <div className="space-y-1.5">
      <span className="block text-[11px] font-medium text-content-secondary">{title}</span>
      {!leaf ? (
        refs.length === 0 ? (
          <p className="text-[11px] text-content-tertiary">
            {t('forms.logic_needs_fields', { defaultValue: 'Add another field first to build a rule.' })}
          </p>
        ) : (
          <button
            type="button"
            onClick={() => setLeaf({ field: refs[0]!.key, op: 'not_empty' })}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-oe-blue hover:underline"
          >
            <Plus size={11} />
            {t('forms.add_condition', { defaultValue: 'Add a condition' })}
          </button>
        )
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <select
            className={clsx(inputCls, 'h-8 max-w-[10rem] text-xs')}
            value={leaf.field ?? ''}
            onChange={(e) => setLeaf({ field: e.target.value })}
          >
            {refs.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
          <select
            className={clsx(inputCls, 'h-8 max-w-[9rem] text-xs')}
            value={op}
            onChange={(e) => setLeaf({ op: e.target.value as ConditionOp })}
          >
            {CONDITION_OPS.map((o) => (
              <option key={o} value={o}>
                {CONDITION_OP_LABELS[o]}
              </option>
            ))}
          </select>
          {needsValue && (
            <input
              className={clsx(inputCls, 'h-8 max-w-[9rem] text-xs')}
              value={
                leaf.value == null ? '' : Array.isArray(leaf.value) ? leaf.value.join(', ') : String(leaf.value)
              }
              onChange={(e) =>
                setLeaf({ value: isListOp ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean) : e.target.value })
              }
              placeholder={isListOp ? 'a, b, c' : t('forms.value', { defaultValue: 'value' })}
            />
          )}
          <button
            type="button"
            aria-label={t('forms.clear_condition', { defaultValue: 'Clear condition' })}
            onClick={() => onChange(null)}
            className="text-content-tertiary hover:text-semantic-error"
          >
            <X size={13} />
          </button>
        </div>
      )}
    </div>
  );
}

function ExpanderToggle({
  active,
  dot,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  dot?: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1 text-[11px] font-medium transition-colors',
        active ? 'text-oe-blue' : 'text-content-tertiary hover:text-content-secondary',
      )}
    >
      {icon}
      {label}
      {dot && <span className="ml-0.5 h-1.5 w-1.5 rounded-full bg-oe-blue" />}
    </button>
  );
}

/* -- Rule cleanup (drops an incomplete rule to null on save) --------------- */

function cleanRule(rule: ConditionExpr | null | undefined): ConditionExpr | null {
  if (!rule || typeof rule !== 'object') return null;
  if (Array.isArray(rule.all) || Array.isArray(rule.any)) return rule; // keep advanced groups verbatim
  if (!rule.field || !rule.op) return null;
  const valueless = VALUELESS_OPS.has(rule.op);
  return {
    field: rule.field,
    op: rule.op,
    ...(valueless ? {} : { value: rule.value ?? null }),
  };
}

function OptionsEditor({ options, onChange }: { options: string[]; onChange: (next: string[]) => void }) {
  const { t } = useTranslation();
  const set = (i: number, value: string) => onChange(options.map((o, idx) => (idx === i ? value : o)));
  const remove = (i: number) => onChange(options.filter((_, idx) => idx !== i));
  const add = () => onChange([...options, `Option ${options.length + 1}`]);
  return (
    <div className="space-y-1.5">
      {options.map((opt, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <input
            className={clsx(inputCls, 'h-8 text-xs')}
            value={opt}
            onChange={(e) => set(i, e.target.value)}
            placeholder={t('forms.option_ph', { defaultValue: 'Option label' })}
          />
          <IconBtn label="Remove option" onClick={() => remove(i)} disabled={options.length <= 1}>
            <X size={13} />
          </IconBtn>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
      >
        <Plus size={12} />
        {t('forms.add_option', { defaultValue: 'Add option' })}
      </button>
    </div>
  );
}

function IconBtn({
  children,
  label,
  onClick,
  disabled,
  danger,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        'inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors',
        'disabled:opacity-30 disabled:pointer-events-none',
        danger
          ? 'text-semantic-error hover:bg-semantic-error-bg'
          : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
      )}
    >
      {children}
    </button>
  );
}

/* -- Helpers --------------------------------------------------------------- */

function extractIssues(err: unknown): FieldIssue[] {
  if (err instanceof ApiError && err.body && typeof err.body === 'object') {
    const detail = (err.body as { detail?: unknown }).detail;
    if (detail && typeof detail === 'object' && Array.isArray((detail as { issues?: unknown }).issues)) {
      return (detail as { issues: FieldIssue[] }).issues;
    }
  }
  return [];
}

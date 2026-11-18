// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The settings of one layout block: its wording per language, its content
 * (fields, columns, totals, signers, clause), the condition it prints under
 * and its style. Locked parts show a lock with the reason instead of a remove
 * or hide control.
 */
import { useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Eye, EyeOff, Lock, Plus, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { fmtList } from '@/shared/lib/formatters';

import type {
  BlockCondition,
  Clause,
  FieldEntry,
  LayoutBlock,
  LayoutLocks,
  LayoutSpecInfo,
  Signer,
  TableColumn,
  TotalRow,
} from './layoutApi';
import { columnLock, fieldLock, moveItem, setText, tableColumns, textIn, unknownFields } from './layoutModel';

export const INPUT =
  'h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue disabled:opacity-60';
const LABEL = 'mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary';
const ICON_BTN =
  'inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue disabled:opacity-30';

export interface BlockEditorProps {
  block: LayoutBlock;
  spec: LayoutSpecInfo;
  locale: string;
  primary: string;
  locks: LayoutLocks;
  clauses: Clause[];
  samples: Record<string, string>;
  readOnly: boolean;
  onChange: (patch: Partial<LayoutBlock>) => void;
}

export function LockBadge({ reason }: { reason: string }) {
  const { t } = useTranslation();
  const text = t('doc_layout.locked_reason', { defaultValue: 'Required by {{source}}', source: reason });
  return (
    <span className="inline-flex h-7 w-7 items-center justify-center text-content-tertiary" title={text} aria-label={text}>
      <Lock size={13} />
    </span>
  );
}

/** A select that inserts `{{field}}`, listing each field with its value on the current record. */
export function MergeFieldPicker({
  spec,
  samples,
  onPick,
  disabled,
}: {
  spec: LayoutSpecInfo;
  samples: Record<string, string>;
  onPick: (path: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const groups = useMemo(() => {
    const out = new Map<string, LayoutSpecInfo['fields']>();
    for (const f of spec.fields) out.set(f.group, [...(out.get(f.group) ?? []), f]);
    return [...out.entries()];
  }, [spec.fields]);
  return (
    <select
      className={clsx(INPUT, 'h-7 w-auto max-w-[16rem] text-xs')}
      value=""
      disabled={disabled}
      aria-label={t('doc_layout.insert_field', { defaultValue: 'Insert field' })}
      onChange={(e) => e.target.value && onPick(e.target.value)}
      data-testid="layout-merge-picker"
    >
      <option value="">{t('doc_layout.insert_field', { defaultValue: 'Insert field' })}</option>
      {groups.map(([group, fields]) => (
        <optgroup key={group} label={t(`doc_layout.group.${group}`, { defaultValue: group })}>
          {fields.map((f) => {
            const sample = samples[f.path] ?? f.sample;
            return (
              <option key={f.path} value={f.path}>
                {(f.label || f.path) + (sample ? `: ${sample.slice(0, 40)}` : '')}
              </option>
            );
          })}
        </optgroup>
      ))}
    </select>
  );
}

/** Per-language text with a merge field picker; flags fields the document does not know. */
export function I18nTextInput({
  value,
  locale,
  primary,
  onChange,
  multiline,
  spec,
  samples,
  label,
  disabled,
  testId,
}: {
  value: Record<string, string> | undefined;
  locale: string;
  primary: string;
  onChange: (next: Record<string, string>) => void;
  multiline?: boolean;
  spec: LayoutSpecInfo;
  samples: Record<string, string>;
  label: string;
  disabled?: boolean;
  testId?: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLTextAreaElement & HTMLInputElement>(null);
  const own = value?.[locale];
  const shown = own ?? '';
  const fallback = own === undefined ? textIn(value, locale, primary) : undefined;
  const known = useMemo(() => new Set(spec.fields.map((f) => f.path)), [spec.fields]);
  const unknown = unknownFields(shown, known);
  const insert = (path: string) => {
    const el = ref.current;
    const token = `{{${path}}}`;
    const start = el?.selectionStart ?? shown.length;
    const end = el?.selectionEnd ?? shown.length;
    onChange(setText(value, locale, shown.slice(0, start) + token + shown.slice(end)));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + token.length, start + token.length);
    });
  };
  const common = {
    ref,
    value: shown,
    disabled,
    placeholder: fallback ?? '',
    onChange: (e: { target: { value: string } }) => onChange(setText(value, locale, e.target.value)),
    'aria-label': label,
    'data-testid': testId,
  };
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className={clsx(LABEL, 'mb-0')}>
          {label} <span className="normal-case text-content-tertiary">({locale})</span>
        </span>
        <MergeFieldPicker spec={spec} samples={samples} onPick={insert} disabled={disabled} />
      </div>
      {multiline ? (
        <textarea {...common} rows={4} className={clsx(INPUT, 'h-auto py-1.5 font-mono text-xs')} />
      ) : (
        <input {...common} className={INPUT} />
      )}
      {fallback !== undefined && (
        <p className="mt-1 text-2xs text-content-tertiary">
          {t('doc_layout.fallback_hint', { defaultValue: 'Empty in this language: the text above in grey prints.' })}
        </p>
      )}
      {unknown.length > 0 && (
        <p className="mt-1 text-2xs text-semantic-error" role="alert">
          {t('doc_layout.unknown_field', {
            defaultValue: 'Not a field of this document: {{fields}}',
            fields: fmtList(unknown),
          })}
        </p>
      )}
    </div>
  );
}

function FieldSelect({
  spec,
  value,
  onChange,
  disabled,
  label,
  allowEmpty,
}: {
  spec: LayoutSpecInfo;
  value: string;
  onChange: (path: string) => void;
  disabled?: boolean;
  label: string;
  allowEmpty?: boolean;
}) {
  return (
    <select className={INPUT} value={value} disabled={disabled} aria-label={label} onChange={(e) => onChange(e.target.value)}>
      {allowEmpty && <option value="">-</option>}
      {spec.fields.map((f) => (
        <option key={f.path} value={f.path}>
          {f.label ? `${f.label} (${f.path})` : f.path}
        </option>
      ))}
    </select>
  );
}

function ConditionEditor({
  spec,
  value,
  onChange,
  disabled,
}: {
  spec: LayoutSpecInfo;
  value: BlockCondition | undefined;
  onChange: (next: BlockCondition | undefined) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const needsValue = value && value.op !== 'empty' && value.op !== 'not_empty';
  return (
    <fieldset className="rounded-md border border-border-light p-2">
      <legend className={clsx(LABEL, 'px-1')}>{t('doc_layout.condition', { defaultValue: 'Print only when' })}</legend>
      <label className="mb-2 flex items-center gap-2 text-xs text-content-secondary">
        <input
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? { field: spec.fields[0]?.path ?? '', op: 'not_empty' } : undefined)}
        />
        {t('doc_layout.condition_on', { defaultValue: 'Only print this block under a condition' })}
      </label>
      {value && (
        <div className="grid grid-cols-3 gap-2">
          <FieldSelect
            spec={spec}
            value={value.field}
            disabled={disabled}
            label={t('doc_layout.condition_field', { defaultValue: 'Field' })}
            onChange={(field) => onChange({ ...value, field })}
          />
          <select
            className={INPUT}
            value={value.op}
            disabled={disabled}
            aria-label={t('doc_layout.condition_op', { defaultValue: 'Operator' })}
            onChange={(e) => onChange({ ...value, op: e.target.value as BlockCondition['op'] })}
          >
            {spec.condition_ops.map((op) => (
              <option key={op} value={op}>
                {t(`doc_layout.op.${op}`, { defaultValue: op })}
              </option>
            ))}
          </select>
          {needsValue && (
            <input
              className={INPUT}
              value={value.value ?? ''}
              disabled={disabled}
              aria-label={t('doc_layout.condition_value', { defaultValue: 'Value' })}
              onChange={(e) => onChange({ ...value, value: e.target.value })}
            />
          )}
        </div>
      )}
    </fieldset>
  );
}

function StyleEditor({ block, onChange, disabled }: { block: LayoutBlock; onChange: BlockEditorProps['onChange']; disabled: boolean }) {
  const { t } = useTranslation();
  const style = block.style ?? {};
  const set = (patch: Partial<NonNullable<LayoutBlock['style']>>) => onChange({ style: { ...style, ...patch } });
  return (
    <fieldset className="grid grid-cols-4 gap-2 rounded-md border border-border-light p-2">
      <legend className={clsx(LABEL, 'px-1')}>{t('doc_layout.style', { defaultValue: 'Style' })}</legend>
      <label className="col-span-1">
        <span className={LABEL}>{t('doc_layout.align', { defaultValue: 'Alignment' })}</span>
        <select className={INPUT} value={style.align ?? 'left'} disabled={disabled} onChange={(e) => set({ align: e.target.value as 'left' })}>
          {(['left', 'center', 'right', 'justify'] as const).map((a) => (
            <option key={a} value={a}>
              {t(`doc_layout.align_${a}`, { defaultValue: a })}
            </option>
          ))}
        </select>
      </label>
      {(
        [
          ['font_size', t('doc_layout.font_size', { defaultValue: 'Font size, pt' }), 6, 18],
          ['space_before', t('doc_layout.space_before', { defaultValue: 'Space above, mm' }), 0, 40],
          ['space_after', t('doc_layout.space_after', { defaultValue: 'Space below, mm' }), 0, 40],
        ] as const
      ).map(([key, label, min, max]) => (
        <label key={key}>
          <span className={LABEL}>{label}</span>
          <input
            type="number"
            min={min}
            max={max}
            className={INPUT}
            value={style[key] ?? ''}
            disabled={disabled}
            onChange={(e) => set({ [key]: e.target.value === '' ? undefined : Number(e.target.value) })}
          />
        </label>
      ))}
    </fieldset>
  );
}

function RowControls({
  index,
  count,
  onMove,
  onRemove,
  hidden,
  onToggle,
  lock,
  disabled,
}: {
  index: number;
  count: number;
  onMove: (to: number) => void;
  onRemove?: () => void;
  hidden?: boolean;
  onToggle?: () => void;
  lock: string | null;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex shrink-0 items-center">
      <button type="button" className={ICON_BTN} disabled={disabled || index === 0} onClick={() => onMove(index - 1)} aria-label={t('doc_layout.move_up', { defaultValue: 'Move up' })}>
        <ArrowUp size={13} />
      </button>
      <button type="button" className={ICON_BTN} disabled={disabled || index === count - 1} onClick={() => onMove(index + 1)} aria-label={t('doc_layout.move_down', { defaultValue: 'Move down' })}>
        <ArrowDown size={13} />
      </button>
      {lock ? (
        <LockBadge reason={lock} />
      ) : (
        <>
          {onToggle && (
            <button type="button" className={ICON_BTN} disabled={disabled} onClick={onToggle} aria-pressed={hidden} aria-label={hidden ? t('doc_layout.show', { defaultValue: 'Show' }) : t('doc_layout.hide', { defaultValue: 'Hide' })}>
              {hidden ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          )}
          {onRemove && (
            <button type="button" className={ICON_BTN} disabled={disabled} onClick={onRemove} aria-label={t('doc_layout.remove', { defaultValue: 'Remove' })}>
              <Trash2 size={13} />
            </button>
          )}
        </>
      )}
    </div>
  );
}

function ColumnsEditor({ block, spec, locale, primary, locks, readOnly, onChange }: BlockEditorProps) {
  const { t } = useTranslation();
  const collection = spec.collections.find((c) => c.id === block.collection);
  const columns = tableColumns(block);
  const set = (next: TableColumn[]) => onChange({ columns: next });
  const unused = (collection?.columns ?? []).filter((c) => !columns.some((x) => x.id === c.id));
  const addComputed = () => {
    let n = 1;
    while (columns.some((c) => c.id === `calc_${n}`)) n += 1;
    set([...columns, { id: `calc_${n}`, label: { [locale]: t('doc_layout.computed', { defaultValue: 'Computed' }) }, expr: '', format: 'money' }]);
  };
  return (
    <div className="space-y-2">
      <label>
        <span className={LABEL}>{t('doc_layout.collection', { defaultValue: 'Rows from' })}</span>
        <select className={INPUT} value={block.collection ?? ''} disabled={readOnly} onChange={(e) => onChange({ collection: e.target.value })}>
          {spec.collections.map((c) => (
            <option key={c.id} value={c.id}>
              {t(`doc_layout.collection_${c.id}`, { defaultValue: c.label })}
            </option>
          ))}
        </select>
      </label>
      <p className={LABEL}>{t('doc_layout.columns', { defaultValue: 'Columns' })}</p>
      <ul className="space-y-1.5" data-testid="layout-table-columns">
        {columns.map((col, i) => {
          const declared = collection?.columns.find((c) => c.id === col.id);
          const lock = columnLock(block.collection, col.id, locks);
          const computed = col.id.startsWith('calc_');
          return (
            <li key={col.id} className={clsx('rounded-md border border-border-light p-1.5', col.hidden && 'opacity-60')}>
              <div className="flex items-center gap-1.5">
                <input
                  className={clsx(INPUT, 'h-7 flex-1 text-xs')}
                  value={col.label?.[locale] ?? ''}
                  placeholder={textIn(col.label, locale, primary) ?? declared?.heading ?? col.id}
                  disabled={readOnly}
                  aria-label={t('doc_layout.column_heading', { defaultValue: 'Column heading' })}
                  onChange={(e) => set(columns.map((c, j) => (j === i ? { ...c, label: setText(c.label, locale, e.target.value) } : c)))}
                />
                <select
                  className={clsx(INPUT, 'h-7 w-16 text-xs')}
                  value={col.width ?? ''}
                  disabled={readOnly}
                  aria-label={t('doc_layout.column_width', { defaultValue: 'Width' })}
                  onChange={(e) => set(columns.map((c, j) => (j === i ? { ...c, width: (e.target.value || undefined) as TableColumn['width'] } : c)))}
                >
                  <option value="">{t('doc_layout.width_auto', { defaultValue: 'Auto' })}</option>
                  <option value="S">S</option>
                  <option value="M">M</option>
                  <option value="L">L</option>
                </select>
                <RowControls
                  index={i}
                  count={columns.length}
                  disabled={readOnly}
                  lock={lock}
                  hidden={col.hidden}
                  onMove={(to) => set(moveItem(columns, i, to))}
                  onToggle={() => set(columns.map((c, j) => (j === i ? { ...c, hidden: !c.hidden || undefined } : c)))}
                  onRemove={() => set(columns.filter((_, j) => j !== i))}
                />
              </div>
              {computed && (
                <div className="mt-1.5 grid grid-cols-3 gap-1.5">
                  <input
                    className={clsx(INPUT, 'col-span-2 h-7 font-mono text-xs')}
                    value={col.expr ?? ''}
                    disabled={readOnly}
                    placeholder="quantity * unit_rate"
                    aria-label={t('doc_layout.formula', { defaultValue: 'Formula' })}
                    onChange={(e) => set(columns.map((c, j) => (j === i ? { ...c, expr: e.target.value } : c)))}
                  />
                  <select
                    className={clsx(INPUT, 'h-7 text-xs')}
                    value={col.format ?? 'number'}
                    disabled={readOnly}
                    aria-label={t('doc_layout.format', { defaultValue: 'Format' })}
                    onChange={(e) => set(columns.map((c, j) => (j === i ? { ...c, format: e.target.value } : c)))}
                  >
                    {['money', 'quantity', 'number', 'percent', 'text'].map((f) => (
                      <option key={f} value={f}>
                        {t(`doc_layout.format_${f}`, { defaultValue: f })}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {computed && (
                <p className="mt-1 text-2xs text-content-tertiary">
                  {t('doc_layout.formula_hint', {
                    defaultValue: 'Use column names ({{names}}), numbers, + - * / and round, min, max, if.',
                    names: fmtList((collection?.columns ?? []).filter((c) => c.format !== 'text' && c.format !== 'index').map((c) => c.id)),
                  })}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap gap-1.5">
        {unused.map((c) => (
          <button key={c.id} type="button" disabled={readOnly} className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary" onClick={() => set([...columns, { id: c.id }])}>
            <Plus size={12} /> {c.heading || c.label}
          </button>
        ))}
        <button type="button" disabled={readOnly} className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary" onClick={addComputed} data-testid="layout-add-computed">
          <Plus size={12} /> {t('doc_layout.add_computed', { defaultValue: 'Computed column' })}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label>
          <span className={LABEL}>{t('doc_layout.group_by', { defaultValue: 'Group rows by' })}</span>
          <select className={INPUT} value={block.group_by ?? ''} disabled={readOnly} onChange={(e) => onChange({ group_by: e.target.value || undefined })}>
            <option value="">{t('doc_layout.no_grouping', { defaultValue: 'No grouping' })}</option>
            {(collection?.columns ?? []).filter((c) => c.format === 'text').map((c) => (
              <option key={c.id} value={c.id}>
                {c.heading || c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="mt-5 flex items-center gap-2 text-xs text-content-secondary">
          <input type="checkbox" checked={Boolean(block.subtotals)} disabled={readOnly || !block.group_by} onChange={(e) => onChange({ subtotals: e.target.checked })} />
          {t('doc_layout.subtotals', { defaultValue: 'Subtotal per group' })}
        </label>
      </div>
    </div>
  );
}

function FieldsEditor({ block, spec, locale, locks, readOnly, onChange }: BlockEditorProps) {
  const { t } = useTranslation();
  const fields = block.fields ?? [];
  const set = (next: FieldEntry[]) => onChange({ fields: next });
  const labelOf = (path: string) => spec.fields.find((f) => f.path === path)?.label || path;
  return (
    <div className="space-y-2">
      <label>
        <span className={LABEL}>{t('doc_layout.fields_layout', { defaultValue: 'Arrangement' })}</span>
        <select className={INPUT} value={block.layout ?? 'pairs'} disabled={readOnly} onChange={(e) => onChange({ layout: e.target.value as 'pairs' })}>
          <option value="pairs">{t('doc_layout.layout_pairs', { defaultValue: 'Two per row' })}</option>
          <option value="rows">{t('doc_layout.layout_rows', { defaultValue: 'One per row' })}</option>
        </select>
      </label>
      <ul className="space-y-1">
        {fields.map((entry, i) => (
          <li key={`${entry.field}-${i}`} className="flex items-center gap-1.5">
            <input
              className={clsx(INPUT, 'h-7 flex-1 text-xs')}
              value={entry.label?.[locale] ?? ''}
              placeholder={labelOf(entry.field)}
              disabled={readOnly}
              aria-label={t('doc_layout.field_label', { defaultValue: 'Label' })}
              onChange={(e) => set(fields.map((f, j) => (j === i ? { ...f, label: setText(f.label, locale, e.target.value) } : f)))}
            />
            <label className="flex items-center gap-1 text-2xs text-content-tertiary" title={t('doc_layout.omit_empty', { defaultValue: 'Skip when empty' })}>
              <input type="checkbox" checked={Boolean(entry.omit_empty)} disabled={readOnly} onChange={(e) => set(fields.map((f, j) => (j === i ? { ...f, omit_empty: e.target.checked || undefined } : f)))} />
              {t('doc_layout.omit_empty_short', { defaultValue: 'skip empty' })}
            </label>
            <RowControls index={i} count={fields.length} disabled={readOnly} lock={fieldLock(entry.field, locks)} onMove={(to) => set(moveItem(fields, i, to))} onRemove={() => set(fields.filter((_, j) => j !== i))} />
          </li>
        ))}
      </ul>
      <FieldSelect spec={spec} value="" allowEmpty disabled={readOnly} label={t('doc_layout.add_field', { defaultValue: 'Add field' })} onChange={(path) => path && set([...fields, { field: path }])} />
    </div>
  );
}

function TotalsEditor({ block, spec, locale, readOnly, onChange }: BlockEditorProps) {
  const { t } = useTranslation();
  const rows = block.rows ?? [];
  const set = (next: TotalRow[]) => onChange({ rows: next });
  return (
    <div className="space-y-1.5">
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <input className={clsx(INPUT, 'h-7 flex-1 text-xs')} value={row.label?.[locale] ?? ''} placeholder={spec.fields.find((f) => f.path === row.field)?.label ?? ''} disabled={readOnly} aria-label={t('doc_layout.field_label', { defaultValue: 'Label' })} onChange={(e) => set(rows.map((r, j) => (j === i ? { ...r, label: setText(r.label, locale, e.target.value) } : r)))} />
          {row.field !== undefined ? (
            <span className="w-40 truncate font-mono text-2xs text-content-tertiary">{row.field}</span>
          ) : (
            <input className={clsx(INPUT, 'h-7 w-40 font-mono text-xs')} value={row.expr ?? ''} placeholder="doc.total - doc.tax" disabled={readOnly} aria-label={t('doc_layout.formula', { defaultValue: 'Formula' })} onChange={(e) => set(rows.map((r, j) => (j === i ? { ...r, expr: e.target.value } : r)))} />
          )}
          <RowControls index={i} count={rows.length} disabled={readOnly} lock={null} onMove={(to) => set(moveItem(rows, i, to))} onRemove={() => set(rows.filter((_, j) => j !== i))} />
        </div>
      ))}
      <div className="flex gap-1.5">
        <FieldSelect spec={spec} value="" allowEmpty disabled={readOnly} label={t('doc_layout.add_field', { defaultValue: 'Add field' })} onChange={(path) => path && set([...rows, { field: path }])} />
        <button type="button" disabled={readOnly} className="shrink-0 rounded-md border border-dashed border-border px-2 text-xs text-content-secondary hover:bg-surface-secondary" onClick={() => set([...rows, { expr: '', format: 'money', label: { [locale]: '' } }])}>
          {t('doc_layout.add_formula_row', { defaultValue: '+ Formula' })}
        </button>
      </div>
    </div>
  );
}

function SignersEditor({ block, spec, locale, readOnly, onChange }: BlockEditorProps) {
  const { t } = useTranslation();
  const signers = block.signers ?? [];
  const set = (next: Signer[]) => onChange({ signers: next });
  return (
    <div className="space-y-1.5">
      {signers.map((s, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <input className={clsx(INPUT, 'h-7 flex-1 text-xs')} value={s.role?.[locale] ?? ''} placeholder={t('doc_layout.signer_role', { defaultValue: 'Role' })} disabled={readOnly} aria-label={t('doc_layout.signer_role', { defaultValue: 'Role' })} onChange={(e) => set(signers.map((x, j) => (j === i ? { ...x, role: setText(x.role, locale, e.target.value) } : x)))} />
          <div className="w-48">
            <FieldSelect spec={spec} value={s.field} allowEmpty disabled={readOnly} label={t('doc_layout.signer_name', { defaultValue: 'Name from' })} onChange={(field) => set(signers.map((x, j) => (j === i ? { ...x, field } : x)))} />
          </div>
          <RowControls index={i} count={signers.length} disabled={readOnly} lock={null} onMove={(to) => set(moveItem(signers, i, to))} onRemove={() => set(signers.filter((_, j) => j !== i))} />
        </div>
      ))}
      <button type="button" disabled={readOnly || signers.length >= 8} className="rounded-md border border-dashed border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary" onClick={() => set([...signers, { field: '' }])}>
        {t('doc_layout.add_signer', { defaultValue: '+ Signer' })}
      </button>
    </div>
  );
}

export function BlockEditor(props: BlockEditorProps) {
  const { t } = useTranslation();
  const { block, spec, locale, primary, readOnly, onChange, samples, clauses } = props;
  const titled = !['spacer', 'page_break', 'image', 'qr', 'columns', 'heading'].includes(block.type);
  const textProps = { locale, primary, spec, samples, disabled: readOnly };
  return (
    <div className="space-y-3" data-testid={`layout-block-editor-${block.id}`}>
      {titled && (
        <I18nTextInput {...textProps} label={t('doc_layout.block_title', { defaultValue: 'Title' })} value={block.title} onChange={(title) => onChange({ title })} />
      )}
      {block.type === 'section' && (
        <p className="text-xs text-content-tertiary">
          {t('doc_layout.section_hint', { defaultValue: 'Filled from the record by the module. You can rename it, move it or hide it.' })}
        </p>
      )}
      {block.type === 'heading' && (
        <>
          <I18nTextInput {...textProps} label={t('doc_layout.text', { defaultValue: 'Text' })} value={block.text} onChange={(text) => onChange({ text })} testId="layout-heading-text" />
          <select className={INPUT} value={block.level ?? 1} disabled={readOnly} aria-label={t('doc_layout.level', { defaultValue: 'Level' })} onChange={(e) => onChange({ level: Number(e.target.value) as 1 | 2 })}>
            <option value={1}>{t('doc_layout.level_1', { defaultValue: 'Heading' })}</option>
            <option value={2}>{t('doc_layout.level_2', { defaultValue: 'Subheading' })}</option>
          </select>
        </>
      )}
      {(block.type === 'text' || block.type === 'notes') && (
        <>
          <I18nTextInput {...textProps} multiline label={t('doc_layout.text', { defaultValue: 'Text' })} value={block.text} onChange={(text) => onChange({ text })} testId="layout-rich-text" />
          {block.type === 'text' && (
            <p className="text-2xs text-content-tertiary">
              {t('doc_layout.markup_hint', { defaultValue: '**bold**, *italic*, "- " for a list, a blank line for a new paragraph.' })}
            </p>
          )}
        </>
      )}
      {block.type === 'fields' && <FieldsEditor {...props} />}
      {block.type === 'table' && <ColumnsEditor {...props} />}
      {block.type === 'totals' && <TotalsEditor {...props} />}
      {block.type === 'signatures' && <SignersEditor {...props} />}
      {block.type === 'clause' && (
        <>
          <select className={INPUT} value={block.clause_id ?? ''} disabled={readOnly} aria-label={t('doc_layout.clause', { defaultValue: 'Clause' })} onChange={(e) => onChange({ clause_id: e.target.value })}>
            <option value="">{t('doc_layout.clause_own', { defaultValue: 'Own text (no library clause)' })}</option>
            {clauses.map((c) => (
              <option key={c.key} value={c.key}>
                {textIn(c.title, locale, primary) || c.key}
              </option>
            ))}
          </select>
          <I18nTextInput {...textProps} multiline label={t('doc_layout.clause_override', { defaultValue: 'Text (replaces the library text)' })} value={block.text} onChange={(text) => onChange({ text })} />
        </>
      )}
      {block.type === 'image' && (
        <div className="grid grid-cols-2 gap-2">
          <select className={INPUT} value={block.source ?? 'logo'} disabled={readOnly} aria-label={t('doc_layout.image_source', { defaultValue: 'Image' })} onChange={(e) => onChange({ source: e.target.value as 'logo' })}>
            <option value="logo">{t('doc_layout.image_logo', { defaultValue: 'Company logo' })}</option>
            <option value="signature">{t('doc_layout.image_signature', { defaultValue: 'Signature image' })}</option>
          </select>
          <input type="number" min={10} max={180} className={INPUT} value={block.width_mm ?? 40} disabled={readOnly} aria-label={t('doc_layout.width_mm', { defaultValue: 'Width, mm' })} onChange={(e) => onChange({ width_mm: Number(e.target.value) })} />
          {block.source === 'signature' && (
            <input
              type="file"
              accept="image/png"
              disabled={readOnly}
              className="col-span-2 text-xs"
              aria-label={t('doc_layout.upload_png', { defaultValue: 'PNG image' })}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file || file.size > 300_000) return;
                const reader = new FileReader();
                reader.onload = () => onChange({ data: String(reader.result) });
                reader.readAsDataURL(file);
              }}
            />
          )}
        </div>
      )}
      {block.type === 'qr' && (
        <div className="grid grid-cols-2 gap-2">
          <FieldSelect spec={spec} value={block.field ?? ''} disabled={readOnly} label={t('doc_layout.qr_field', { defaultValue: 'Code holds' })} onChange={(field) => onChange({ field })} />
          <label className="flex items-center gap-2 text-xs text-content-secondary">
            <input type="checkbox" checked={Boolean(block.caption)} disabled={readOnly} onChange={(e) => onChange({ caption: e.target.checked })} />
            {t('doc_layout.qr_caption', { defaultValue: 'Print the value under the code' })}
          </label>
        </div>
      )}
      {block.type === 'spacer' && (
        <input type="number" min={1} max={120} className={INPUT} value={block.height_mm ?? 6} disabled={readOnly} aria-label={t('doc_layout.height_mm', { defaultValue: 'Height, mm' })} onChange={(e) => onChange({ height_mm: Number(e.target.value) })} />
      )}
      {block.type === 'page_break' && (
        <p className="text-xs text-content-tertiary">{t('doc_layout.page_break_hint', { defaultValue: 'The next block starts on a new page.' })}</p>
      )}
      <ConditionEditor spec={spec} value={block.condition} disabled={readOnly} onChange={(condition) => onChange({ condition })} />
      {block.type !== 'page_break' && <StyleEditor block={block} onChange={onChange} disabled={readOnly} />}
    </div>
  );
}

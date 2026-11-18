// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The block list (drag to reorder, keyboard too) and the Layout, Branding and
 * History tabs of the document layout editor.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import clsx from 'clsx';
import { ChevronDown, ChevronRight, Copy, Eye, EyeOff, GripVertical, Plus, Trash2 } from 'lucide-react';

import type { Clause, FurnitureLine, LayoutBlock, LayoutChange, LayoutSpecInfo, LayoutState, LayoutTemplate } from './layoutApi';
import { BlockEditor, I18nTextInput, INPUT, LockBadge } from './BlockEditor';
import {
  ADDABLE_BLOCKS,
  allBlockIds,
  blockLock,
  duplicateBlock,
  moveItem,
  newBlock,
  removeBlock,
  textIn,
  updateBlock,
} from './layoutModel';

const LABEL = 'mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary';
const ICON_BTN =
  'inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue disabled:opacity-30';

export interface PanelProps {
  template: LayoutTemplate;
  spec: LayoutSpecInfo;
  locale: string;
  readOnly: boolean;
  samples: Record<string, string>;
  clauses: Clause[];
  onChange: (next: LayoutTemplate) => void;
}

/** What the block list shows as a block's name. */
function useBlockName(spec: LayoutSpecInfo, locale: string, primary: string) {
  const { t } = useTranslation();
  return (block: LayoutBlock): string => {
    const own = textIn(block.title, locale, primary) || (block.type === 'heading' ? textIn(block.text, locale, primary) : '');
    if (own) return own;
    const section = spec.sections.find((s) => s.id === (block.section ?? block.id));
    if (section) return section.heading || t(`doc_layout.section.${section.id}`, { defaultValue: section.label });
    return t(`doc_layout.block.${block.type}`, { defaultValue: block.type });
  };
}

function SortableBlock({
  block,
  props,
  open,
  onToggleOpen,
  name,
}: {
  block: LayoutBlock;
  props: PanelProps;
  open: boolean;
  onToggleOpen: () => void;
  name: string;
}) {
  const { t } = useTranslation();
  const { template, spec, locale, readOnly, onChange } = props;
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: block.id,
    disabled: readOnly,
  });
  const lock = blockLock(block, spec.locks);
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={clsx(
        'rounded-lg border border-border-light bg-surface-primary',
        isDragging && 'z-10 shadow-md',
        block.hidden && 'opacity-60',
      )}
      data-testid={`layout-block-${block.id}`}
    >
      <div className="flex items-center gap-1 px-1.5 py-1">
        <button
          type="button"
          className={clsx(ICON_BTN, 'cursor-grab')}
          disabled={readOnly}
          aria-label={t('doc_layout.drag', { defaultValue: 'Drag to reorder (space, then arrow keys)' })}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={14} />
        </button>
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1 py-1 text-left text-sm text-content-primary hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          aria-expanded={open}
          onClick={onToggleOpen}
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span className="truncate">{name}</span>
          <span className="shrink-0 text-2xs text-content-tertiary">
            {t(`doc_layout.block.${block.type}`, { defaultValue: block.type })}
          </span>
          {block.condition && (
            <span className="shrink-0 rounded bg-surface-secondary px-1 text-2xs text-content-tertiary">
              {t('doc_layout.conditional', { defaultValue: 'conditional' })}
            </span>
          )}
        </button>
        <button
          type="button"
          className={ICON_BTN}
          disabled={readOnly}
          onClick={() => onChange(duplicateBlock(template, block.id))}
          aria-label={t('doc_layout.duplicate', { defaultValue: 'Duplicate' })}
          title={t('doc_layout.duplicate', { defaultValue: 'Duplicate' })}
        >
          <Copy size={13} />
        </button>
        {lock ? (
          <LockBadge reason={lock} />
        ) : (
          <>
            <button
              type="button"
              className={ICON_BTN}
              disabled={readOnly}
              aria-pressed={Boolean(block.hidden)}
              onClick={() => onChange(updateBlock(template, block.id, { hidden: !block.hidden }))}
              aria-label={block.hidden ? t('doc_layout.show', { defaultValue: 'Show' }) : t('doc_layout.hide', { defaultValue: 'Hide' })}
              title={block.hidden ? t('doc_layout.show', { defaultValue: 'Show' }) : t('doc_layout.hide', { defaultValue: 'Hide' })}
              data-testid={`layout-toggle-${block.id}`}
            >
              {block.hidden ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
            <button
              type="button"
              className={ICON_BTN}
              disabled={readOnly}
              onClick={() => onChange(removeBlock(template, block.id))}
              aria-label={t('doc_layout.remove', { defaultValue: 'Remove' })}
              title={t('doc_layout.remove', { defaultValue: 'Remove' })}
            >
              <Trash2 size={13} />
            </button>
          </>
        )}
      </div>
      {open && (
        <div className="border-t border-border-light px-3 py-3">
          {block.type === 'columns' ? (
            <ColumnsBlockEditor block={block} props={props} />
          ) : (
            <BlockEditor
              block={block}
              spec={spec}
              locale={locale}
              primary={template.primary_locale}
              locks={spec.locks}
              clauses={props.clauses}
              samples={props.samples}
              readOnly={readOnly}
              onChange={(patch) => onChange(updateBlock(template, block.id, patch))}
            />
          )}
        </div>
      )}
    </li>
  );
}

/** A two- or three-column container: each column holds its own short list of blocks. */
function ColumnsBlockEditor({ block, props }: { block: LayoutBlock; props: PanelProps }) {
  const { t } = useTranslation();
  const { template, spec, locale, readOnly, onChange } = props;
  const columns = (block.columns as LayoutBlock[][]) ?? [[], []];
  const [openChild, setOpenChild] = useState<string | null>(null);
  const setColumns = (next: LayoutBlock[][]) =>
    onChange(updateBlock(template, block.id, { columns: next, ratios: next.map((_, i) => block.ratios?.[i] ?? 1) }));
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className={LABEL}>{t('doc_layout.column_count', { defaultValue: 'Columns' })}</span>
        {[2, 3].map((n) => (
          <button
            key={n}
            type="button"
            disabled={readOnly}
            aria-pressed={columns.length === n}
            className={clsx('rounded-md border px-2 py-0.5 text-xs', columns.length === n ? 'border-oe-blue text-oe-blue-text' : 'border-border-light')}
            onClick={() => setColumns(n === 2 ? [columns[0] ?? [], [...(columns[1] ?? []), ...(columns[2] ?? [])]] : [...columns, []].slice(0, 3))}
          >
            {n}
          </button>
        ))}
      </div>
      <div className={clsx('grid gap-2', columns.length === 3 ? 'grid-cols-3' : 'grid-cols-2')}>
        {columns.map((children, ci) => (
          <div key={ci} className="space-y-1.5 rounded-md border border-dashed border-border p-1.5">
            {children.map((child) => (
              <div key={child.id} className="rounded-md border border-border-light">
                <div className="flex items-center gap-1 px-1">
                  <button type="button" className="min-w-0 flex-1 truncate py-1 text-left text-xs" aria-expanded={openChild === child.id} onClick={() => setOpenChild(openChild === child.id ? null : child.id)}>
                    {textIn(child.title, locale, template.primary_locale) || t(`doc_layout.block.${child.type}`, { defaultValue: child.type })}
                  </button>
                  <button type="button" className={ICON_BTN} disabled={readOnly} aria-label={t('doc_layout.remove', { defaultValue: 'Remove' })} onClick={() => onChange(removeBlock(template, child.id))}>
                    <Trash2 size={12} />
                  </button>
                </div>
                {openChild === child.id && (
                  <div className="border-t border-border-light p-2">
                    <BlockEditor block={child} spec={spec} locale={locale} primary={template.primary_locale} locks={spec.locks} clauses={props.clauses} samples={props.samples} readOnly={readOnly} onChange={(patch) => onChange(updateBlock(template, child.id, patch))} />
                  </div>
                )}
              </div>
            ))}
            <select
              className={clsx(INPUT, 'h-7 text-xs')}
              value=""
              disabled={readOnly}
              aria-label={t('doc_layout.add_block', { defaultValue: 'Add block' })}
              onChange={(e) => {
                if (!e.target.value) return;
                const child = newBlock(e.target.value as LayoutBlock['type'], spec, allBlockIds(template.body), locale);
                setColumns(columns.map((col, j) => (j === ci ? [...col, child] : col)));
              }}
            >
              <option value="">{t('doc_layout.add_block', { defaultValue: 'Add block' })}</option>
              {spec.column_child_types.map((type) => (
                <option key={type} value={type}>
                  {t(`doc_layout.block.${type}`, { defaultValue: type })}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ContentPanel(props: PanelProps) {
  const { t } = useTranslation();
  const { template, spec, locale, readOnly, onChange } = props;
  const [open, setOpen] = useState<string | null>(null);
  const name = useBlockName(spec, locale, template.primary_locale);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const from = template.body.findIndex((b) => b.id === e.active.id);
    const to = template.body.findIndex((b) => b.id === e.over?.id);
    onChange({ ...template, body: moveItem(template.body, from, to) });
  };
  const add = (type: LayoutBlock['type']) => {
    const block = newBlock(type, spec, allBlockIds(template.body), locale);
    onChange({ ...template, body: [...template.body, block] });
    setOpen(block.id);
  };
  return (
    <div className="space-y-3">
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={template.body.map((b) => b.id)} strategy={verticalListSortingStrategy}>
          <ul className="space-y-1.5" data-testid="layout-block-list">
            {template.body.map((block) => (
              <SortableBlock
                key={block.id}
                block={block}
                props={props}
                name={name(block)}
                open={open === block.id}
                onToggleOpen={() => setOpen(open === block.id ? null : block.id)}
              />
            ))}
          </ul>
        </SortableContext>
      </DndContext>
      {(spec.legal ?? []).length > 0 && (
        <ul className="space-y-1.5" aria-label={t('doc_layout.legal_notes', { defaultValue: 'Legal notes' })} data-testid="layout-legal-blocks">
          {(spec.legal ?? []).map((note) => (
            <li
              key={`${note.country}-${note.id}`}
              aria-disabled="true"
              className="flex items-start gap-1 rounded-md border border-border-light bg-surface-secondary px-2 py-1.5"
            >
              <LockBadge reason={note.source} />
              <div className="min-w-0 flex-1 text-xs">
                <p className="font-medium text-content-primary">
                  {t('doc_layout.legal_note_title', { defaultValue: 'Legal note ({{country}})', country: note.country })}
                  {note.when && (
                    <span className="ms-1 font-normal text-content-tertiary">
                      {t('doc_layout.legal_note_when', { defaultValue: 'printed when it applies' })}
                    </span>
                  )}
                </p>
                <p className="mt-0.5 whitespace-pre-line text-content-secondary">{note.text}</p>
                <p className="mt-0.5 text-content-tertiary">{t('doc_layout.locked_reason', { defaultValue: 'Required by {{source}}', source: note.source })}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <div>
          <p className={LABEL}>{t('doc_layout.add_block', { defaultValue: 'Add block' })}</p>
          <div className="flex flex-wrap gap-1.5">
            {ADDABLE_BLOCKS.filter((type) => spec.block_types.includes(type)).map((type) => (
              <button
                key={type}
                type="button"
                className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                onClick={() => add(type)}
                data-testid={`layout-add-${type}`}
              >
                <Plus size={12} /> {t(`doc_layout.block.${type}`, { defaultValue: type })}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FurnitureEditor({
  lines,
  max,
  label,
  props,
  onChange,
}: {
  lines: FurnitureLine[];
  max: number;
  label: string;
  props: PanelProps;
  onChange: (next: FurnitureLine[]) => void;
}) {
  const { t } = useTranslation();
  return (
    <fieldset className="space-y-2 rounded-md border border-border-light p-2">
      <legend className={clsx(LABEL, 'px-1')}>{label}</legend>
      {lines.map((line, i) => (
        <div key={i} className="flex items-end gap-1.5">
          <div className="flex-1">
            <I18nTextInput
              value={line.text}
              locale={props.locale}
              primary={props.template.primary_locale}
              spec={props.spec}
              samples={props.samples}
              disabled={props.readOnly}
              label={t('doc_layout.line', { defaultValue: 'Line {{n}}', n: i + 1 })}
              onChange={(text) => onChange(lines.map((l, j) => (j === i ? { ...l, text } : l)))}
            />
          </div>
          <select className={clsx(INPUT, 'w-24')} value={line.align ?? 'left'} disabled={props.readOnly} aria-label={t('doc_layout.align', { defaultValue: 'Alignment' })} onChange={(e) => onChange(lines.map((l, j) => (j === i ? { ...l, align: e.target.value as 'left' } : l)))}>
            {(['left', 'center', 'right'] as const).map((a) => (
              <option key={a} value={a}>
                {t(`doc_layout.align_${a}`, { defaultValue: a })}
              </option>
            ))}
          </select>
          <button type="button" className={ICON_BTN} disabled={props.readOnly} aria-label={t('doc_layout.remove', { defaultValue: 'Remove' })} onClick={() => onChange(lines.filter((_, j) => j !== i))}>
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      {lines.length < max && (
        <button type="button" disabled={props.readOnly} className="rounded-md border border-dashed border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary" onClick={() => onChange([...lines, { text: {}, align: 'left' }])}>
          {t('doc_layout.add_line', { defaultValue: '+ Line' })}
        </button>
      )}
      <p className="text-2xs text-content-tertiary">
        {t('doc_layout.page_counter_hint', { defaultValue: 'Insert page.number and page.total for "page 2 of 5".' })}
      </p>
    </fieldset>
  );
}

export function LayoutPanel(props: PanelProps) {
  const { t } = useTranslation();
  const { template, spec, locale, readOnly, onChange } = props;
  const page = template.page;
  const setPage = (patch: Partial<LayoutTemplate['page']>) => onChange({ ...template, page: { ...page, ...patch } });
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <label>
          <span className={LABEL}>{t('doc_layout.page_size', { defaultValue: 'Paper' })}</span>
          <select className={INPUT} value={page.size} disabled={readOnly} onChange={(e) => setPage({ size: e.target.value as 'A4' })} data-testid="layout-page-size">
            {['A4', 'Letter', 'Legal'].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className={LABEL}>{t('doc_layout.orientation', { defaultValue: 'Orientation' })}</span>
          <select className={INPUT} value={page.orientation} disabled={readOnly} onChange={(e) => setPage({ orientation: e.target.value as 'portrait' })}>
            <option value="portrait">{t('doc_layout.portrait', { defaultValue: 'Portrait' })}</option>
            <option value="landscape">{t('doc_layout.landscape', { defaultValue: 'Landscape' })}</option>
          </select>
        </label>
        {(
          [
            ['margin_side_mm', t('doc_layout.margin_side', { defaultValue: 'Side margins, mm' }), 20],
            ['margin_top_mm', t('doc_layout.margin_top', { defaultValue: 'Top margin, mm' }), 18],
            ['margin_bottom_mm', t('doc_layout.margin_bottom', { defaultValue: 'Bottom margin, mm' }), 18],
          ] as const
        ).map(([key, label, fallback]) => (
          <label key={key}>
            <span className={LABEL}>{label}</span>
            <input type="number" min={8} max={40} className={INPUT} value={page[key] ?? fallback} disabled={readOnly} onChange={(e) => setPage({ [key]: Number(e.target.value) })} />
          </label>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm text-content-secondary">
        <input type="checkbox" checked={page.page_numbers !== false} disabled={readOnly} onChange={(e) => setPage({ page_numbers: e.target.checked })} />
        {t('doc_layout.page_numbers', { defaultValue: 'Page numbers in the footer' })}
      </label>
      <label className="flex items-center gap-2 text-sm text-content-secondary">
        <input type="checkbox" checked={page.first_page_header !== false} disabled={readOnly} onChange={(e) => setPage({ first_page_header: e.target.checked })} />
        {t('doc_layout.first_page_header', { defaultValue: 'Header on the first page too' })}
      </label>
      <FurnitureEditor lines={template.header} max={3} label={t('doc_layout.header', { defaultValue: 'Page header' })} props={props} onChange={(header) => onChange({ ...template, header })} />
      <FurnitureEditor lines={template.footer} max={2} label={t('doc_layout.footer', { defaultValue: 'Page footer' })} props={props} onChange={(footer) => onChange({ ...template, footer })} />
      <fieldset className="space-y-1.5 rounded-md border border-border-light p-2">
        <legend className={clsx(LABEL, 'px-1')}>{t('doc_layout.watermark', { defaultValue: 'Watermark by status' })}</legend>
        {spec.statuses.map((status) => (
          <label key={status} className="grid grid-cols-3 items-center gap-2 text-xs text-content-secondary">
            <span>{t(`doc_layout.status.${status}`, { defaultValue: status })}</span>
            <input
              className={clsx(INPUT, 'col-span-2 h-7 text-xs')}
              value={template.watermark[status]?.[locale] ?? ''}
              placeholder={textIn(template.watermark[status], locale, template.primary_locale) ?? ''}
              disabled={readOnly}
              aria-label={t('doc_layout.watermark_for', { defaultValue: 'Watermark for {{status}}', status })}
              onChange={(e) => {
                const value = { ...(template.watermark[status] ?? {}) };
                if (e.target.value) value[locale] = e.target.value;
                else delete value[locale];
                const watermark = { ...template.watermark, [status]: value };
                if (Object.keys(value).length === 0) delete watermark[status];
                onChange({ ...template, watermark });
              }}
            />
          </label>
        ))}
      </fieldset>
    </div>
  );
}

export function BrandingPanel(props: PanelProps) {
  const { t } = useTranslation();
  const { template, readOnly, onChange, locale, spec, samples } = props;
  const branding = template.branding;
  const accent = branding.accent ?? '';
  return (
    <div className="space-y-3">
      <I18nTextInput value={template.title} locale={locale} primary={template.primary_locale} spec={spec} samples={samples} disabled={readOnly} label={t('doc_layout.doc_title', { defaultValue: 'Document title' })} onChange={(title) => onChange({ ...template, title })} />
      <I18nTextInput value={template.subject} locale={locale} primary={template.primary_locale} spec={spec} samples={samples} disabled={readOnly} label={t('doc_layout.doc_subject', { defaultValue: 'Subject line' })} onChange={(subject) => onChange({ ...template, subject })} />
      <label className="flex items-center gap-2 text-sm text-content-secondary">
        <input type="checkbox" checked={template.show_subject} disabled={readOnly} onChange={(e) => onChange({ ...template, show_subject: e.target.checked })} />
        {t('doc_layout.show_subject', { defaultValue: 'Print the subject line' })}
      </label>
      <label className="flex items-center gap-2 text-sm text-content-secondary">
        <input type="checkbox" checked={branding.letterhead !== false} disabled={readOnly} onChange={(e) => onChange({ ...template, branding: { ...branding, letterhead: e.target.checked ? undefined : false } })} />
        {t('doc_layout.letterhead', { defaultValue: 'Company letterhead and logo' })}
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label>
          <span className={LABEL}>{t('doc_layout.accent', { defaultValue: 'Accent colour' })}</span>
          <div className="flex items-center gap-1.5">
            <input type="color" className="h-8 w-10 rounded border border-border" value={accent || '#1f2937'} disabled={readOnly} aria-label={t('doc_layout.accent', { defaultValue: 'Accent colour' })} onChange={(e) => onChange({ ...template, branding: { ...branding, accent: e.target.value } })} />
            <input className={clsx(INPUT, 'font-mono')} value={accent} placeholder="#1F2937" maxLength={7} disabled={readOnly} aria-label={t('doc_layout.accent_hex', { defaultValue: 'Colour code' })} onChange={(e) => onChange({ ...template, branding: { ...branding, accent: e.target.value || undefined } })} />
          </div>
        </label>
        <label>
          <span className={LABEL}>{t('doc_layout.font', { defaultValue: 'Typeface' })}</span>
          <select className={INPUT} value={branding.font ?? 'sans'} disabled={readOnly} onChange={(e) => onChange({ ...template, branding: { ...branding, font: e.target.value === 'serif' ? 'serif' : undefined } })}>
            <option value="sans">{t('doc_layout.font_sans', { defaultValue: 'Sans serif' })}</option>
            <option value="serif">{t('doc_layout.font_serif', { defaultValue: 'Serif' })}</option>
          </select>
        </label>
      </div>
      <p className="text-2xs text-content-tertiary">
        {t('doc_layout.branding_hint', { defaultValue: 'The logo and company details come from the company profile in Settings.' })}
      </p>
    </div>
  );
}

export function HistoryPanel({
  state,
  readOnly,
  busy,
  onRestore,
  onDiff,
  diff,
}: {
  state: LayoutState;
  readOnly: boolean;
  busy: boolean;
  onRestore: (versionId: string) => void;
  onDiff: (versionId: string) => void;
  diff: { versionId: string; changes: LayoutChange[] } | null;
}) {
  const { t, i18n } = useTranslation();
  if (state.versions.length === 0) {
    return (
      <p className="text-sm text-content-tertiary">
        {t('doc_layout.no_versions', { defaultValue: 'Nothing published yet: the document prints in the standard layout.' })}
      </p>
    );
  }
  return (
    <ul className="space-y-1.5" data-testid="layout-versions">
      {state.versions.map((v) => (
        <li key={v.id} className="rounded-md border border-border-light p-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">v{v.number}</span>
            <span className="text-content-secondary">{t(`doc_layout.action.${v.action}`, { defaultValue: v.action })}</span>
            {state.published_number === v.number && (
              <span className="rounded bg-oe-blue/10 px-1.5 text-2xs text-oe-blue-text">{t('doc_layout.in_force', { defaultValue: 'in force' })}</span>
            )}
            <span className="ml-auto text-2xs text-content-tertiary">
              {v.author_name} {v.created_at ? new Date(v.created_at).toLocaleString(i18n.language) : ''}
            </span>
          </div>
          {v.note && <p className="mt-1 text-xs text-content-secondary">{v.note}</p>}
          <div className="mt-1.5 flex gap-1.5">
            <button type="button" className="rounded-md border border-border-light px-2 py-0.5 text-xs hover:bg-surface-secondary" onClick={() => onDiff(v.id)}>
              {t('doc_layout.compare', { defaultValue: 'Compare with standard' })}
            </button>
            {!readOnly && state.published_number !== v.number && (
              <button type="button" disabled={busy} className="rounded-md border border-border-light px-2 py-0.5 text-xs hover:bg-surface-secondary" onClick={() => onRestore(v.id)}>
                {t('doc_layout.restore', { defaultValue: 'Restore' })}
              </button>
            )}
          </div>
          {diff?.versionId === v.id && (
            <ul className="mt-2 space-y-0.5 text-xs" data-testid="layout-diff">
              {diff.changes.length === 0 && <li className="text-content-tertiary">{t('doc_layout.no_changes', { defaultValue: 'Same as the standard layout.' })}</li>}
              {diff.changes.map((c) => (
                <li key={`${c.id}-${c.change}`}>
                  <span className={clsx('mr-1.5 rounded px-1 text-2xs', c.change === 'removed' ? 'bg-semantic-error/10 text-semantic-error' : c.change === 'added' ? 'bg-semantic-success/10 text-semantic-success' : 'bg-surface-secondary')}>
                    {t(`doc_layout.change.${c.change}`, { defaultValue: c.change })}
                  </span>
                  {t(`doc_layout.block.${c.type}`, { defaultValue: c.type })} <span className="font-mono text-content-tertiary">{c.id}</span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

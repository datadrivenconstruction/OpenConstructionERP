// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Temporary Works register.
 *
 * Safety-critical governance for falsework, propping, excavation support and
 * the like: each item runs a gated lifecycle (design check -> permit to load ->
 * inspection -> permit to strike). The page leads with the one signal a
 * Temporary Works Coordinator must never miss: any item bearing load with no
 * valid permit to load (a compliance breach), shown in red at the top.
 */

import { useState, useMemo, useCallback, useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  ShieldAlert,
  ShieldCheck,
  Plus,
  X,
  ChevronRight,
  Pencil,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  CalendarClock,
  Search,
  HardHat,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, ConfirmDialog, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  fetchItems,
  createItem,
  updateItem,
  deleteItem,
  fetchPermits,
  createPermit,
  updatePermit,
  fetchLoadStatus,
  fetchRegister,
  type TemporaryWorksItem,
  type TemporaryWorksPermit,
  type TWType,
  type ItemStatus,
  type DesignCheckCategory,
  type PermitType,
  type PermitStatus,
  type ItemGateStatus,
  type LoadStatus,
  type RegisterRollup,
  type CreateItemPayload,
  type CreatePermitPayload,
} from './api';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildTemporaryWorksInsights } from './temporaryWorksInsights';

/* -- Vocabularies + presentation config ------------------------------------ */

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';
type TFn = (key: string, opts?: Record<string, unknown>) => string;

const TW_TYPES: readonly TWType[] = [
  'falsework',
  'formwork',
  'propping',
  'excavation_support',
  'scaffold',
  'facade_retention',
  'crane_base',
  'edge_protection',
  'dewatering',
  'hoarding',
  'other',
];

const ITEM_STATUSES: readonly ItemStatus[] = [
  'identified',
  'design_brief',
  'design_submitted',
  'design_checked',
  'approved_to_load',
  'loaded',
  'in_use',
  'approved_to_strike',
  'struck',
  'removed',
  'on_hold',
];

const PERMIT_TYPES: readonly PermitType[] = [
  'permit_to_load',
  'permit_to_strike',
  'permit_to_dismantle',
];

const PERMIT_STATUSES: readonly PermitStatus[] = ['draft', 'issued', 'active', 'expired', 'closed'];

const CATEGORY_OPTIONS: readonly ('' | DesignCheckCategory)[] = ['', '0', '1', '2', '3'];

const TW_TYPE_LABEL: Record<TWType, string> = {
  falsework: 'Falsework',
  formwork: 'Formwork',
  propping: 'Propping',
  excavation_support: 'Excavation support',
  scaffold: 'Scaffold',
  facade_retention: 'Facade retention',
  crane_base: 'Crane base',
  edge_protection: 'Edge protection',
  dewatering: 'Dewatering',
  hoarding: 'Hoarding',
  other: 'Other',
};

const ITEM_STATUS_LABEL: Record<ItemStatus, string> = {
  identified: 'Identified',
  design_brief: 'Design brief',
  design_submitted: 'Design submitted',
  design_checked: 'Design checked',
  approved_to_load: 'Permit to load issued',
  loaded: 'Loaded',
  in_use: 'In use',
  approved_to_strike: 'Permit to strike issued',
  struck: 'Struck',
  removed: 'Removed',
  on_hold: 'On hold',
};

const STATUS_VARIANT: Record<ItemStatus, BadgeVariant> = {
  identified: 'neutral',
  design_brief: 'neutral',
  design_submitted: 'blue',
  design_checked: 'blue',
  approved_to_load: 'success',
  loaded: 'warning',
  in_use: 'warning',
  approved_to_strike: 'blue',
  struck: 'success',
  removed: 'neutral',
  on_hold: 'warning',
};

const PERMIT_TYPE_LABEL: Record<PermitType, string> = {
  permit_to_load: 'Permit to load',
  permit_to_strike: 'Permit to strike',
  permit_to_dismantle: 'Permit to dismantle',
};

const PERMIT_TYPE_VARIANT: Record<PermitType, BadgeVariant> = {
  permit_to_load: 'blue',
  permit_to_strike: 'warning',
  permit_to_dismantle: 'neutral',
};

const PERMIT_STATUS_LABEL: Record<PermitStatus, string> = {
  draft: 'Draft',
  issued: 'Issued',
  active: 'Active',
  expired: 'Expired',
  closed: 'Closed',
};

const PERMIT_STATUS_VARIANT: Record<PermitStatus, BadgeVariant> = {
  draft: 'neutral',
  issued: 'success',
  active: 'success',
  expired: 'error',
  closed: 'neutral',
};

const CATEGORY_LABEL: Record<DesignCheckCategory, string> = {
  '0': 'Category 0',
  '1': 'Category 1',
  '2': 'Category 2',
  '3': 'Category 3',
};

const twTypeLabel = (t: TFn, v: TWType): string =>
  t(`temporary_works.tw_type_${v}`, { defaultValue: TW_TYPE_LABEL[v] ?? v });
const itemStatusLabel = (t: TFn, v: ItemStatus): string =>
  t(`temporary_works.status_${v}`, { defaultValue: ITEM_STATUS_LABEL[v] ?? v });
const permitTypeLabel = (t: TFn, v: PermitType): string =>
  t(`temporary_works.permit_type_${v}`, { defaultValue: PERMIT_TYPE_LABEL[v] ?? v });
const permitStatusLabel = (t: TFn, v: PermitStatus): string =>
  t(`temporary_works.permit_status_${v}`, { defaultValue: PERMIT_STATUS_LABEL[v] ?? v });
const categoryLabel = (t: TFn, v: DesignCheckCategory): string =>
  t(`temporary_works.category_${v}`, { defaultValue: CATEGORY_LABEL[v] ?? v });

/* -- Shared field styles + primitives -------------------------------------- */

const fieldBase =
  'h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const inputCls = clsx(fieldBase, 'w-full');
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

function LabeledText({
  label,
  value,
  onChange,
  required,
  placeholder,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  return (
    <label className="block">
      <span className={labelCls}>
        {label}
        {required && <span className="text-semantic-error"> *</span>}
      </span>
      <input
        className={inputCls}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
      />
    </label>
  );
}

function LabeledDate({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className={labelCls}>{label}</span>
      <input type="date" className={inputCls} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function LabeledArea({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className={labelCls}>{label}</span>
      <textarea
        className={textareaCls}
        rows={3}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}

function LabeledSelect<T extends string>({
  label,
  value,
  onChange,
  options,
  labelFor,
}: {
  label: string;
  value: T;
  onChange: (v: T) => void;
  options: readonly T[];
  labelFor: (v: T) => string;
}) {
  return (
    <label className="block">
      <span className={labelCls}>{label}</span>
      <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value as T)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {labelFor(o)}
          </option>
        ))}
      </select>
    </label>
  );
}

function LabeledCheck({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 rounded border-border text-oe-blue focus:ring-2 focus:ring-oe-blue/30"
      />
      <span>
        <span className="text-sm text-content-primary">{label}</span>
        {hint && <span className="block text-xs text-content-tertiary">{hint}</span>}
      </span>
    </label>
  );
}

function ModalShell({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-lg animate-fade-in">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-border bg-surface-elevated shadow-xl animate-card-in"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
          <button
            onClick={onClose}
            aria-label={t('temporary_works.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4">{children}</div>
        <div className="flex items-center justify-end gap-3 border-t border-border-light px-6 py-4">
          {footer}
        </div>
      </div>
    </div>
  );
}

/* -- Item modal ------------------------------------------------------------ */

interface ItemFormState {
  reference: string;
  title: string;
  tw_type: TWType;
  design_check_category: '' | DesignCheckCategory;
  status: ItemStatus;
  twc_name: string;
  designer_name: string;
  checker_name: string;
  location: string;
  required_load_date: string;
  required_strike_date: string;
  design_due_date: string;
  description: string;
  notes: string;
}

function itemToForm(item?: TemporaryWorksItem): ItemFormState {
  return {
    reference: item?.reference ?? '',
    title: item?.title ?? '',
    tw_type: item?.tw_type ?? 'falsework',
    design_check_category: item?.design_check_category ?? '',
    status: item?.status ?? 'identified',
    twc_name: item?.twc_name ?? '',
    designer_name: item?.designer_name ?? '',
    checker_name: item?.checker_name ?? '',
    location: item?.location ?? '',
    required_load_date: item?.required_load_date ?? '',
    required_strike_date: item?.required_strike_date ?? '',
    design_due_date: item?.design_due_date ?? '',
    description: item?.description ?? '',
    notes: item?.notes ?? '',
  };
}

function buildItemPayload(f: ItemFormState): CreateItemPayload {
  const orNull = (v: string): string | null => (v.trim() ? v.trim() : null);
  return {
    reference: f.reference.trim(),
    title: f.title.trim(),
    tw_type: f.tw_type,
    status: f.status,
    design_check_category: f.design_check_category || null,
    twc_name: orNull(f.twc_name),
    designer_name: orNull(f.designer_name),
    checker_name: orNull(f.checker_name),
    location: orNull(f.location),
    required_load_date: f.required_load_date || null,
    required_strike_date: f.required_strike_date || null,
    design_due_date: f.design_due_date || null,
    description: orNull(f.description),
    notes: orNull(f.notes),
  };
}

function ItemModal({
  item,
  onClose,
  onSubmit,
  isPending,
}: {
  item?: TemporaryWorksItem;
  onClose: () => void;
  onSubmit: (data: CreateItemPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ItemFormState>(() => itemToForm(item));
  const [touched, setTouched] = useState(false);
  const set = <K extends keyof ItemFormState>(k: K, v: ItemFormState[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const canSubmit = form.reference.trim().length > 0 && form.title.trim().length > 0;
  const submit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(buildItemPayload(form));
  };

  return (
    <ModalShell
      title={
        item
          ? t('temporary_works.edit_item', { defaultValue: 'Edit item' })
          : t('temporary_works.new_item', { defaultValue: 'New temporary works item' })
      }
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('temporary_works.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} disabled={isPending || !canSubmit} loading={isPending}>
            {item
              ? t('temporary_works.save', { defaultValue: 'Save' })
              : t('temporary_works.create_item', { defaultValue: 'Create item' })}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <LabeledText
          label={t('temporary_works.field_reference', { defaultValue: 'Reference' })}
          value={form.reference}
          onChange={(v) => set('reference', v)}
          required
          placeholder={t('temporary_works.reference_placeholder', { defaultValue: 'e.g. TW-014' })}
          autoFocus
        />
        <LabeledText
          label={t('temporary_works.field_title', { defaultValue: 'Title' })}
          value={form.title}
          onChange={(v) => set('title', v)}
          required
          placeholder={t('temporary_works.title_placeholder', {
            defaultValue: 'e.g. Slab soffit falsework, Level 3',
          })}
        />
        <LabeledSelect
          label={t('temporary_works.field_type', { defaultValue: 'Type' })}
          value={form.tw_type}
          onChange={(v) => set('tw_type', v)}
          options={TW_TYPES}
          labelFor={(v) => twTypeLabel(t, v)}
        />
        <LabeledSelect
          label={t('temporary_works.field_status', { defaultValue: 'Status' })}
          value={form.status}
          onChange={(v) => set('status', v)}
          options={ITEM_STATUSES}
          labelFor={(v) => itemStatusLabel(t, v)}
        />
        <LabeledSelect
          label={t('temporary_works.field_category', { defaultValue: 'Design check category' })}
          value={form.design_check_category}
          onChange={(v) => set('design_check_category', v)}
          options={CATEGORY_OPTIONS}
          labelFor={(v) =>
            v === ''
              ? t('temporary_works.category_unassigned', { defaultValue: 'Unassigned' })
              : categoryLabel(t, v)
          }
        />
        <LabeledText
          label={t('temporary_works.field_twc', { defaultValue: 'Temporary works coordinator' })}
          value={form.twc_name}
          onChange={(v) => set('twc_name', v)}
        />
        <LabeledText
          label={t('temporary_works.field_designer', { defaultValue: 'Designer' })}
          value={form.designer_name}
          onChange={(v) => set('designer_name', v)}
        />
        <LabeledText
          label={t('temporary_works.field_checker', { defaultValue: 'Independent checker' })}
          value={form.checker_name}
          onChange={(v) => set('checker_name', v)}
        />
        <LabeledText
          label={t('temporary_works.field_location', { defaultValue: 'Location' })}
          value={form.location}
          onChange={(v) => set('location', v)}
        />
        <LabeledDate
          label={t('temporary_works.field_design_due', { defaultValue: 'Design due date' })}
          value={form.design_due_date}
          onChange={(v) => set('design_due_date', v)}
        />
        <LabeledDate
          label={t('temporary_works.field_required_load', { defaultValue: 'Required load date' })}
          value={form.required_load_date}
          onChange={(v) => set('required_load_date', v)}
        />
        <LabeledDate
          label={t('temporary_works.field_required_strike', { defaultValue: 'Required strike date' })}
          value={form.required_strike_date}
          onChange={(v) => set('required_strike_date', v)}
        />
      </div>
      <div className="mt-3 space-y-3">
        <LabeledArea
          label={t('temporary_works.field_description', { defaultValue: 'Description' })}
          value={form.description}
          onChange={(v) => set('description', v)}
          placeholder={t('temporary_works.description_placeholder', {
            defaultValue: 'What the temporary works support, the design assumptions and any constraints.',
          })}
        />
        <LabeledArea
          label={t('temporary_works.field_notes', { defaultValue: 'Notes' })}
          value={form.notes}
          onChange={(v) => set('notes', v)}
        />
      </div>
      {touched && !canSubmit && (
        <p className="mt-2 text-xs text-semantic-error">
          {t('temporary_works.required_fields', { defaultValue: 'Reference and title are required.' })}
        </p>
      )}
    </ModalShell>
  );
}

/* -- Permit modal ---------------------------------------------------------- */

interface PermitFormState {
  permit_number: string;
  permit_type: PermitType;
  status: PermitStatus;
  issued_by: string;
  issued_at: string;
  valid_from: string;
  valid_to: string;
  prereq_design_check_accepted: boolean;
  prereq_inspection_passed: boolean;
  conditions: string;
}

function permitToForm(permit?: TemporaryWorksPermit): PermitFormState {
  return {
    permit_number: permit?.permit_number ?? '',
    permit_type: permit?.permit_type ?? 'permit_to_load',
    status: permit?.status ?? 'draft',
    issued_by: permit?.issued_by ?? '',
    issued_at: permit?.issued_at ?? '',
    valid_from: permit?.valid_from ?? '',
    valid_to: permit?.valid_to ?? '',
    prereq_design_check_accepted: permit?.prereq_design_check_accepted ?? false,
    prereq_inspection_passed: permit?.prereq_inspection_passed ?? false,
    conditions: permit?.conditions ?? '',
  };
}

function buildPermitPayload(f: PermitFormState): CreatePermitPayload {
  const orNull = (v: string): string | null => (v.trim() ? v.trim() : null);
  return {
    permit_number: f.permit_number.trim(),
    permit_type: f.permit_type,
    status: f.status,
    issued_by: orNull(f.issued_by),
    issued_at: f.issued_at || null,
    valid_from: f.valid_from || null,
    valid_to: f.valid_to || null,
    conditions: orNull(f.conditions),
    prereq_design_check_accepted: f.prereq_design_check_accepted,
    prereq_inspection_passed: f.prereq_inspection_passed,
  };
}

function PermitModal({
  permit,
  onClose,
  onSubmit,
  isPending,
}: {
  permit?: TemporaryWorksPermit;
  onClose: () => void;
  onSubmit: (data: CreatePermitPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<PermitFormState>(() => permitToForm(permit));
  const [touched, setTouched] = useState(false);
  const set = <K extends keyof PermitFormState>(k: K, v: PermitFormState[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const canSubmit = form.permit_number.trim().length > 0;
  const submit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(buildPermitPayload(form));
  };

  return (
    <ModalShell
      title={
        permit
          ? t('temporary_works.edit_permit_title', { defaultValue: 'Edit permit' })
          : t('temporary_works.new_permit_title', { defaultValue: 'Issue permit' })
      }
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('temporary_works.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} disabled={isPending || !canSubmit} loading={isPending}>
            {permit
              ? t('temporary_works.save', { defaultValue: 'Save' })
              : t('temporary_works.issue_permit', { defaultValue: 'Issue permit' })}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <LabeledText
          label={t('temporary_works.field_permit_number', { defaultValue: 'Permit number' })}
          value={form.permit_number}
          onChange={(v) => set('permit_number', v)}
          required
          placeholder={t('temporary_works.permit_number_placeholder', { defaultValue: 'e.g. PTL-007' })}
          autoFocus
        />
        <LabeledSelect
          label={t('temporary_works.field_permit_type', { defaultValue: 'Permit type' })}
          value={form.permit_type}
          onChange={(v) => set('permit_type', v)}
          options={PERMIT_TYPES}
          labelFor={(v) => permitTypeLabel(t, v)}
        />
        <LabeledSelect
          label={t('temporary_works.field_permit_status', { defaultValue: 'Permit status' })}
          value={form.status}
          onChange={(v) => set('status', v)}
          options={PERMIT_STATUSES}
          labelFor={(v) => permitStatusLabel(t, v)}
        />
        <LabeledText
          label={t('temporary_works.field_issued_by', { defaultValue: 'Issued by' })}
          value={form.issued_by}
          onChange={(v) => set('issued_by', v)}
        />
        <LabeledDate
          label={t('temporary_works.field_issued_at', { defaultValue: 'Issued on' })}
          value={form.issued_at}
          onChange={(v) => set('issued_at', v)}
        />
        <LabeledDate
          label={t('temporary_works.field_valid_from', { defaultValue: 'Valid from' })}
          value={form.valid_from}
          onChange={(v) => set('valid_from', v)}
        />
        <LabeledDate
          label={t('temporary_works.field_valid_to', { defaultValue: 'Valid to' })}
          value={form.valid_to}
          onChange={(v) => set('valid_to', v)}
        />
      </div>
      <div className="mt-3 space-y-2 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
        <p className="text-xs font-medium text-content-secondary">
          {t('temporary_works.load_prereqs', { defaultValue: 'Permit to load prerequisites' })}
        </p>
        <LabeledCheck
          label={t('temporary_works.prereq_design', { defaultValue: 'Independent design check accepted' })}
          hint={t('temporary_works.prereq_design_hint', {
            defaultValue: 'The design check for this category has been reviewed and accepted.',
          })}
          checked={form.prereq_design_check_accepted}
          onChange={(v) => set('prereq_design_check_accepted', v)}
        />
        <LabeledCheck
          label={t('temporary_works.prereq_inspection', { defaultValue: 'Inspection before use passed' })}
          hint={t('temporary_works.prereq_inspection_hint', {
            defaultValue: 'The temporary works were inspected and found built to design before loading.',
          })}
          checked={form.prereq_inspection_passed}
          onChange={(v) => set('prereq_inspection_passed', v)}
        />
      </div>
      <div className="mt-3">
        <LabeledArea
          label={t('temporary_works.field_conditions', { defaultValue: 'Conditions' })}
          value={form.conditions}
          onChange={(v) => set('conditions', v)}
          placeholder={t('temporary_works.conditions_placeholder', {
            defaultValue: 'Any limits on the permit: max load, sequence, weather, hold points.',
          })}
        />
      </div>
      {touched && !canSubmit && (
        <p className="mt-2 text-xs text-semantic-error">
          {t('temporary_works.permit_number_required', { defaultValue: 'Permit number is required.' })}
        </p>
      )}
    </ModalShell>
  );
}

/* -- Compliance banner (the safety signal, first) -------------------------- */

function ComplianceBanner({ loadStatus }: { loadStatus?: LoadStatus }) {
  const { t } = useTranslation();
  if (!loadStatus) return null;
  const breaches = loadStatus.compliance_breaches;

  if (breaches.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-semantic-success/50 bg-semantic-success-bg/50 p-4">
        <ShieldCheck size={20} className="shrink-0 text-semantic-success" />
        <div>
          <h2 className="text-sm font-semibold text-content-primary">
            {t('temporary_works.compliant_title', { defaultValue: 'All temporary works compliant' })}
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('temporary_works.compliant_desc', {
              defaultValue: 'No item is bearing load without a valid permit to load.',
            })}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border-2 border-semantic-error bg-semantic-error-bg/50 p-4">
      <div className="flex items-center gap-2">
        <ShieldAlert size={20} className="shrink-0 text-semantic-error" />
        <h2 className="text-base font-semibold text-semantic-error">
          {t('temporary_works.breach_banner_title', {
            defaultValue: 'Compliance breach: temporary works bearing load with no valid permit to load',
          })}
        </h2>
        <Badge variant="error">{breaches.length}</Badge>
      </div>
      <p className="mt-1 text-sm text-content-secondary">
        {t('temporary_works.breach_banner_desc', {
          defaultValue:
            'These items are carrying construction load with no permit to load in force. Stop and resolve before anyone works on or under them.',
        })}
      </p>
      <ul className="mt-3 space-y-2">
        {breaches.map((b) => (
          <li
            key={b.item_id ?? b.reference}
            className="rounded-lg border border-semantic-error/40 bg-surface-elevated p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="error" size="sm">
                {b.reference}
              </Badge>
              <span className="text-sm font-medium text-content-primary">{b.title}</span>
            </div>
            <p className="mt-1 text-xs text-content-tertiary">{b.reason}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* -- Overdue banner -------------------------------------------------------- */

function OverdueBanner({ register }: { register?: RegisterRollup }) {
  const { t } = useTranslation();
  const load = register?.overdue_to_load.length ?? 0;
  const strike = register?.overdue_to_strike.length ?? 0;
  if (load === 0 && strike === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg/40 px-4 py-2.5 text-sm">
      <CalendarClock size={16} className="shrink-0 text-semantic-warning" />
      {load > 0 && (
        <span className="text-content-secondary">
          {t('temporary_works.overdue_load', { defaultValue: '{{count}} overdue to load', count: load })}
        </span>
      )}
      {strike > 0 && (
        <span className="text-content-secondary">
          {t('temporary_works.overdue_strike', { defaultValue: '{{count}} overdue to strike', count: strike })}
        </span>
      )}
    </div>
  );
}

/* -- Stats ----------------------------------------------------------------- */

function Stat({ label, value, tone = 'default' }: { label: string; value: ReactNode; tone?: 'default' | 'error' }) {
  return (
    <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs">
      <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{label}</p>
      <p
        className={clsx(
          'mt-1 text-lg font-semibold tabular-nums',
          tone === 'error' ? 'text-semantic-error' : 'text-content-primary',
        )}
      >
        {value}
      </p>
    </div>
  );
}

function StatsRow({
  register,
  loadStatus,
  itemCount,
}: {
  register?: RegisterRollup;
  loadStatus?: LoadStatus;
  itemCount: number;
}) {
  const { t } = useTranslation();
  const total = register?.total ?? itemCount;
  const clearance = register?.design_clearance_pct;
  const loadBearing = (register?.status_counts['loaded'] ?? 0) + (register?.status_counts['in_use'] ?? 0);
  const breaches = loadStatus?.compliance_breaches.length ?? 0;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label={t('temporary_works.stat_total', { defaultValue: 'Items' })} value={total} />
      <Stat
        label={t('temporary_works.stat_clearance', { defaultValue: 'Design clearance' })}
        value={clearance != null ? `${clearance}%` : '-'}
      />
      <Stat label={t('temporary_works.stat_load_bearing', { defaultValue: 'Bearing load' })} value={loadBearing} />
      <Stat
        label={t('temporary_works.stat_breaches', { defaultValue: 'Breaches' })}
        value={breaches}
        tone={breaches > 0 ? 'error' : 'default'}
      />
    </div>
  );
}

/* -- Permit row ------------------------------------------------------------ */

function PrereqDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 text-2xs',
        ok ? 'text-semantic-success' : 'text-content-tertiary',
      )}
    >
      {ok ? <CheckCircle2 size={11} /> : <CircleSlash size={11} />}
      {label}
    </span>
  );
}

function PermitRow({
  permit,
  onEdit,
}: {
  permit: TemporaryWorksPermit;
  onEdit: (p: TemporaryWorksPermit) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2">
      <Badge variant={PERMIT_TYPE_VARIANT[permit.permit_type] ?? 'neutral'} size="sm">
        {permitTypeLabel(t, permit.permit_type)}
      </Badge>
      <span className="font-mono text-xs text-content-secondary">{permit.permit_number}</span>
      <Badge variant={PERMIT_STATUS_VARIANT[permit.status] ?? 'neutral'} size="sm" dot>
        {permitStatusLabel(t, permit.status)}
      </Badge>
      <span className="text-xs text-content-tertiary">
        {t('temporary_works.permit_valid', { defaultValue: 'Valid' })}: <DateDisplay value={permit.valid_from} />{' '}
        - <DateDisplay value={permit.valid_to} />
      </span>
      {permit.permit_type === 'permit_to_load' && (
        <span className="flex items-center gap-2">
          <PrereqDot
            ok={permit.prereq_design_check_accepted}
            label={t('temporary_works.prereq_design_short', { defaultValue: 'Design check' })}
          />
          <PrereqDot
            ok={permit.prereq_inspection_passed}
            label={t('temporary_works.prereq_inspection_short', { defaultValue: 'Inspection' })}
          />
        </span>
      )}
      <Button
        variant="ghost"
        size="sm"
        className="ml-auto"
        onClick={() => onEdit(permit)}
        icon={<Pencil size={12} />}
      >
        {t('temporary_works.edit_permit', { defaultValue: 'Edit' })}
      </Button>
    </div>
  );
}

/* -- Item row -------------------------------------------------------------- */

function Detail({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-content-tertiary">{label}</dt>
      <dd className="text-content-primary">{value ?? '-'}</dd>
    </div>
  );
}

function ItemRow({
  item,
  gate,
  permits,
  breaching,
  onEdit,
  onDelete,
  onAddPermit,
  onEditPermit,
}: {
  item: TemporaryWorksItem;
  gate?: ItemGateStatus;
  permits: TemporaryWorksPermit[];
  breaching: boolean;
  onEdit: (item: TemporaryWorksItem) => void;
  onDelete: (item: TemporaryWorksItem) => void;
  onAddPermit: (item: TemporaryWorksItem) => void;
  onEditPermit: (permit: TemporaryWorksPermit) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const clearedLoad = gate?.cleared_to_load ?? false;
  const clearedStrike = gate?.cleared_to_strike ?? false;

  return (
    <div
      className={clsx(
        'border-b border-border-light last:border-b-0',
        breaching && 'bg-semantic-error-bg/30',
      )}
    >
      {/* Collapsed row */}
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-secondary/40"
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronRight
          size={14}
          className={clsx('shrink-0 text-content-tertiary transition-transform', open && 'rotate-90')}
        />
        <span className="w-24 shrink-0 truncate font-mono text-xs font-semibold text-content-secondary">
          {item.reference}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm text-content-primary">{item.title}</span>
        {breaching && (
          <Badge variant="error" size="sm">
            {t('temporary_works.breach_tag', { defaultValue: 'No permit to load' })}
          </Badge>
        )}
        <Badge variant="neutral" size="sm">
          {twTypeLabel(t, item.tw_type)}
        </Badge>
        {item.design_check_category && (
          <Badge variant="blue" size="sm">
            {categoryLabel(t, item.design_check_category)}
          </Badge>
        )}
        <Badge variant={STATUS_VARIANT[item.status] ?? 'neutral'} size="sm" dot>
          {itemStatusLabel(t, item.status)}
        </Badge>
        <span
          className="shrink-0"
          title={
            clearedLoad
              ? t('temporary_works.cleared_to_load', { defaultValue: 'Cleared to load' })
              : t('temporary_works.not_cleared_to_load', { defaultValue: 'Not cleared to load' })
          }
        >
          {clearedLoad ? (
            <CheckCircle2 size={15} className="text-semantic-success" />
          ) : (
            <CircleSlash size={15} className={breaching ? 'text-semantic-error' : 'text-content-tertiary'} />
          )}
        </span>
      </div>

      {/* Expanded detail */}
      {open && (
        <div className="space-y-4 px-4 pb-4 pl-11 animate-fade-in">
          {/* Gate summary */}
          <div className="flex flex-wrap items-center gap-4">
            <span
              className={clsx(
                'inline-flex items-center gap-1.5 text-xs font-medium',
                clearedLoad ? 'text-semantic-success' : breaching ? 'text-semantic-error' : 'text-content-tertiary',
              )}
            >
              {clearedLoad ? <CheckCircle2 size={14} /> : <CircleSlash size={14} />}
              {clearedLoad
                ? t('temporary_works.cleared_to_load', { defaultValue: 'Cleared to load' })
                : t('temporary_works.not_cleared_to_load', { defaultValue: 'Not cleared to load' })}
            </span>
            <span
              className={clsx(
                'inline-flex items-center gap-1.5 text-xs font-medium',
                clearedStrike ? 'text-semantic-success' : 'text-content-tertiary',
              )}
            >
              {clearedStrike ? <CheckCircle2 size={14} /> : <CircleSlash size={14} />}
              {clearedStrike
                ? t('temporary_works.cleared_to_strike', { defaultValue: 'Cleared to strike' })
                : t('temporary_works.not_cleared_to_strike', { defaultValue: 'Not cleared to strike' })}
            </span>
          </div>

          {/* Load gate hint */}
          {!clearedLoad && (
            <div className="flex gap-2 rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg/40 p-3 text-xs text-content-secondary">
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" />
              <span>
                {t('temporary_works.load_gate_hint', {
                  defaultValue:
                    'This item is not cleared to bear load. A valid permit to load (issued or active, in date) recording the design check accepted and the inspection passed is required before it is loaded.',
                })}
              </span>
            </div>
          )}

          {/* Details */}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
            <Detail label={t('temporary_works.field_twc', { defaultValue: 'Temporary works coordinator' })} value={item.twc_name} />
            <Detail label={t('temporary_works.field_designer', { defaultValue: 'Designer' })} value={item.designer_name} />
            <Detail label={t('temporary_works.field_checker', { defaultValue: 'Independent checker' })} value={item.checker_name} />
            <Detail label={t('temporary_works.field_location', { defaultValue: 'Location' })} value={item.location} />
            <Detail
              label={t('temporary_works.field_design_due', { defaultValue: 'Design due date' })}
              value={<DateDisplay value={item.design_due_date} />}
            />
            <Detail
              label={t('temporary_works.field_required_load', { defaultValue: 'Required load date' })}
              value={<DateDisplay value={item.required_load_date} />}
            />
            <Detail
              label={t('temporary_works.field_required_strike', { defaultValue: 'Required strike date' })}
              value={<DateDisplay value={item.required_strike_date} />}
            />
          </dl>

          {item.description && (
            <p className="whitespace-pre-wrap rounded-lg bg-surface-secondary p-3 text-sm text-content-primary">
              {item.description}
            </p>
          )}

          {/* Permits */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('temporary_works.permits', { defaultValue: 'Permits' })}
              </h4>
              <Button variant="secondary" size="sm" onClick={() => onAddPermit(item)} icon={<Plus size={12} />}>
                {t('temporary_works.add_permit', { defaultValue: 'Add permit' })}
              </Button>
            </div>
            {permits.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('temporary_works.no_permits', { defaultValue: 'No permits issued yet.' })}
              </p>
            ) : (
              <div className="space-y-2">
                {permits.map((p) => (
                  <PermitRow key={p.id} permit={p} onEdit={onEditPermit} />
                ))}
              </div>
            )}
          </div>

          {/* Item actions */}
          <div className="flex items-center gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => onEdit(item)} icon={<Pencil size={13} />}>
              {t('temporary_works.edit', { defaultValue: 'Edit' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onDelete(item)} icon={<Trash2 size={13} />}>
              {t('temporary_works.delete', { defaultValue: 'Delete' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* -- Main page ------------------------------------------------------------- */

export function TemporaryWorksPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const projectId = routeProjectId || activeProjectId || '';

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<ItemStatus | ''>('');
  const [typeFilter, setTypeFilter] = useState<TWType | ''>('');
  const [itemModal, setItemModal] = useState<{ item?: TemporaryWorksItem } | null>(null);
  const [permitModal, setPermitModal] = useState<{ itemId: string; permit?: TemporaryWorksPermit } | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  const itemsQuery = useQuery({
    queryKey: ['tw-items', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchItems(projectId, {
        status: statusFilter || undefined,
        tw_type: typeFilter || undefined,
      }),
    enabled: !!projectId,
  });
  const permitsQuery = useQuery({
    queryKey: ['tw-permits', projectId],
    queryFn: () => fetchPermits(projectId),
    enabled: !!projectId,
  });
  const loadStatusQuery = useQuery({
    queryKey: ['tw-load-status', projectId],
    queryFn: () => fetchLoadStatus(projectId),
    enabled: !!projectId,
  });
  const registerQuery = useQuery({
    queryKey: ['tw-register', projectId],
    queryFn: () => fetchRegister(projectId),
    enabled: !!projectId,
  });

  const items = itemsQuery.data ?? [];
  const permits = permitsQuery.data ?? [];
  const loadStatus = loadStatusQuery.data;
  const register = registerQuery.data;

  // Module Insights - toggleable charts built client-side from the items already
  // loaded; an empty project leaves the panel with nothing to draw. Declared
  // here, above the page's first return, so the hook order stays stable.
  const insights = useModuleInsights('temporary-works', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildTemporaryWorksInsights(items, '', t),
    [items, t],
  );

  const permitsByItem = useMemo(() => {
    const m = new Map<string, TemporaryWorksPermit[]>();
    for (const p of permits) {
      const arr = m.get(p.item_id) ?? [];
      arr.push(p);
      m.set(p.item_id, arr);
    }
    return m;
  }, [permits]);

  const gateByItem = useMemo(() => {
    const m = new Map<string, ItemGateStatus>();
    for (const g of loadStatus?.gate_statuses ?? []) {
      if (g.item_id) m.set(g.item_id, g);
    }
    return m;
  }, [loadStatus]);

  const breachIds = useMemo(() => {
    const s = new Set<string>();
    for (const b of loadStatus?.compliance_breaches ?? []) {
      if (b.item_id) s.add(b.item_id);
    }
    return s;
  }, [loadStatus]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (i) => i.reference.toLowerCase().includes(q) || i.title.toLowerCase().includes(q),
    );
  }, [items, search]);

  const invalidateAll = useCallback(() => {
    for (const key of ['tw-items', 'tw-permits', 'tw-load-status', 'tw-register']) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  }, [qc]);

  const toastError = useCallback(
    (e: unknown) => {
      addToast({
        type: 'error',
        title: t('temporary_works.error_title', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
    [addToast, t],
  );

  const createItemMut = useMutation({
    mutationFn: (data: CreateItemPayload) => createItem(projectId, data),
    onSuccess: () => {
      invalidateAll();
      setItemModal(null);
      addToast({ type: 'success', title: t('temporary_works.item_created', { defaultValue: 'Item created' }) });
    },
    onError: toastError,
  });
  const updateItemMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: CreateItemPayload }) => updateItem(projectId, id, data),
    onSuccess: () => {
      invalidateAll();
      setItemModal(null);
      addToast({ type: 'success', title: t('temporary_works.item_updated', { defaultValue: 'Item updated' }) });
    },
    onError: toastError,
  });
  const deleteItemMut = useMutation({
    mutationFn: (id: string) => deleteItem(projectId, id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('temporary_works.item_deleted', { defaultValue: 'Item deleted' }) });
    },
    onError: toastError,
  });
  const createPermitMut = useMutation({
    mutationFn: ({ itemId, data }: { itemId: string; data: CreatePermitPayload }) =>
      createPermit(projectId, itemId, data),
    onSuccess: () => {
      invalidateAll();
      setPermitModal(null);
      addToast({ type: 'success', title: t('temporary_works.permit_created', { defaultValue: 'Permit issued' }) });
    },
    onError: toastError,
  });
  const updatePermitMut = useMutation({
    mutationFn: ({ permitId, data }: { permitId: string; data: CreatePermitPayload }) =>
      updatePermit(projectId, permitId, data),
    onSuccess: () => {
      invalidateAll();
      setPermitModal(null);
      addToast({ type: 'success', title: t('temporary_works.permit_updated', { defaultValue: 'Permit updated' }) });
    },
    onError: toastError,
  });

  const handleItemSubmit = (data: CreateItemPayload) => {
    const editing = itemModal?.item;
    if (editing) updateItemMut.mutate({ id: editing.id, data });
    else createItemMut.mutate(data);
  };

  const handlePermitSubmit = (data: CreatePermitPayload) => {
    if (!permitModal) return;
    if (permitModal.permit) updatePermitMut.mutate({ permitId: permitModal.permit.id, data });
    else createPermitMut.mutate({ itemId: permitModal.itemId, data });
  };

  const handleDelete = useCallback(
    async (item: TemporaryWorksItem) => {
      const ok = await confirm({
        title: t('temporary_works.confirm_delete_title', { defaultValue: 'Delete item?' }),
        message: t('temporary_works.confirm_delete_msg', {
          defaultValue: 'This temporary works item and its permits will be permanently deleted.',
        }),
        confirmLabel: t('temporary_works.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteItemMut.mutate(item.id);
    },
    [confirm, deleteItemMut, t],
  );

  const hasFilter = !!search || !!statusFilter || !!typeFilter;

  const body = (
    <div className="space-y-5">
      <ComplianceBanner loadStatus={loadStatus} />
      <OverdueBanner register={register} />
      <StatsRow register={register} loadStatus={loadStatus} itemCount={items.length} />

      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative max-w-sm flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('temporary_works.search_placeholder', { defaultValue: 'Search reference or title...' })}
            aria-label={t('temporary_works.search_placeholder', { defaultValue: 'Search reference or title...' })}
            className={clsx(inputCls, 'pl-9')}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as ItemStatus | '')}
          aria-label={t('temporary_works.filter_status', { defaultValue: 'Filter by status' })}
          className={clsx(fieldBase, 'w-full sm:w-52')}
        >
          <option value="">{t('temporary_works.all_statuses', { defaultValue: 'All statuses' })}</option>
          {ITEM_STATUSES.map((s) => (
            <option key={s} value={s}>
              {itemStatusLabel(t, s)}
            </option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as TWType | '')}
          aria-label={t('temporary_works.filter_type', { defaultValue: 'Filter by type' })}
          className={clsx(fieldBase, 'w-full sm:w-48')}
        >
          <option value="">{t('temporary_works.all_types', { defaultValue: 'All types' })}</option>
          {TW_TYPES.map((tw) => (
            <option key={tw} value={tw}>
              {twTypeLabel(t, tw)}
            </option>
          ))}
        </select>
      </div>

      {/* Register table */}
      {itemsQuery.isLoading ? (
        <SkeletonTable rows={5} columns={5} />
      ) : itemsQuery.isError ? (
        <Card>
          <p className="text-sm text-content-secondary">
            {t('temporary_works.load_error', { defaultValue: 'Could not load the temporary works register.' })}
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={() => {
              void itemsQuery.refetch();
            }}
          >
            {t('temporary_works.retry', { defaultValue: 'Try again' })}
          </Button>
        </Card>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<HardHat size={28} strokeWidth={1.5} />}
          title={
            hasFilter
              ? t('temporary_works.no_results', { defaultValue: 'No matching items' })
              : t('temporary_works.no_items', { defaultValue: 'No temporary works yet' })
          }
          description={
            hasFilter
              ? t('temporary_works.no_results_hint', { defaultValue: 'Try adjusting your search or filters.' })
              : t('temporary_works.no_items_hint', {
                  defaultValue: 'Add the first falsework, propping or excavation-support item to govern.',
                })
          }
          action={
            hasFilter
              ? undefined
              : {
                  label: t('temporary_works.new_item', { defaultValue: 'New item' }),
                  onClick: () => setItemModal({}),
                }
          }
        />
      ) : (
        <>
          <p className="text-sm text-content-tertiary">
            {t('temporary_works.showing_count', { defaultValue: '{{count}} items', count: filtered.length })}
          </p>
          <Card padding="none" className="overflow-x-auto">
            <div className="min-w-[680px]">
              {filtered.map((item) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  gate={gateByItem.get(item.id)}
                  permits={permitsByItem.get(item.id) ?? []}
                  breaching={breachIds.has(item.id)}
                  onEdit={(it) => setItemModal({ item: it })}
                  onDelete={handleDelete}
                  onAddPermit={(it) => setPermitModal({ itemId: it.id })}
                  onEditPermit={(p) => setPermitModal({ itemId: p.item_id, permit: p })}
                />
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('temporary_works.title', { defaultValue: 'Temporary Works' })}
        subtitle={t('temporary_works.subtitle', {
          defaultValue:
            'Govern falsework, propping and excavation support from design check through permit to load and strike',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <Button
              variant="primary"
              size="sm"
              onClick={() => setItemModal({})}
              disabled={!projectId}
              icon={<Plus size={14} />}
            >
              {t('temporary_works.new_item', { defaultValue: 'New item' })}
            </Button>
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('temporary_works.insights.title', { defaultValue: 'Temporary works insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <RequiresProject
        emptyHint={t('temporary_works.select_project', {
          defaultValue: 'Open a project first to view and govern its temporary works.',
        })}
      >
        {body}
      </RequiresProject>

      {itemModal && (
        <ItemModal
          item={itemModal.item}
          onClose={() => setItemModal(null)}
          onSubmit={handleItemSubmit}
          isPending={createItemMut.isPending || updateItemMut.isPending}
        />
      )}

      {permitModal && (
        <PermitModal
          permit={permitModal.permit}
          onClose={() => setPermitModal(null)}
          onSubmit={handlePermitSubmit}
          isPending={createPermitMut.isPending || updatePermitMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

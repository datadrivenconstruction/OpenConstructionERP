// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The package plan: how the work is cut into contracts, who designs, builds
// and supplies each part, who signs with whom and on what price basis. A
// package can point to the procurement record that awards it, and then reads
// its progress from that record. A banner says where the plan does not fit
// the chosen form.

import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Ban, Boxes, CheckCircle2, Link2, Link2Off, Pencil, Plus, RotateCcw, Trash2, Wand2 } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';

import { canEditPlan } from './access';
import {
  createPackage,
  deletePackage,
  derivePackages,
  linkPackage,
  setPackageStatus,
  unlinkPackage,
  updatePackage,
  type Consistency,
  type ContractingParty,
  type DeliveryCatalogue,
  type DeliveryModel,
  type DeliveryPackage,
  type PackageInput,
  type PackageKind,
  type PackageLinkKind,
  type PackageStatus,
  type PriceBasis,
} from './api';
import { Field, FindingList, INPUT_CLASS, PACKAGE_TONE, ProblemList, ReasonedButton, ServerRefusal, ToneBadge } from './DeliveryBits';
import { ExportButtons } from './ExportButtons';
import { useRefusalText, useRefusalToast } from './hooks';
import {
  CONTRACTING_PARTY,
  PACKAGE_KIND,
  PACKAGE_LINK_KIND,
  PACKAGE_STATUS,
  PRICE_BASIS,
  partyNamer,
  vocab,
  type KeyText,
  type LabelContext,
} from './labels';
import { RecordPicker } from './RecordPicker';
import { changedFields, filterPackages, nextPackageStatuses, packageProblems, packageTree, type ResponsibilityFilter } from './rules';

const KINDS = Object.keys(PACKAGE_KIND) as PackageKind[];
const PRICE_BASES = Object.keys(PRICE_BASIS) as PriceBasis[];
const LINK_KINDS = Object.keys(PACKAGE_LINK_KIND) as PackageLinkKind[];
const FILTERS: ResponsibilityFilter[] = ['all', 'designs', 'builds', 'supplies'];

const FILTER: Record<ResponsibilityFilter, KeyText> = {
  all: ['delivery_model.ui.packages.filter.all', 'Whole plan'],
  designs: ['delivery_model.ui.packages.filter.designs', 'Who designs'],
  builds: ['delivery_model.ui.packages.filter.builds', 'Who builds'],
  supplies: ['delivery_model.ui.packages.filter.supplies', 'Who supplies'],
};

type Duty = 'designs' | 'builds' | 'supplies' | 'manages';
const DUTIES: Duty[] = ['designs', 'builds', 'supplies', 'manages'];
const DUTY: Record<Duty, KeyText> = {
  designs: ['delivery_model.ui.packages.duty.designs', 'Designs'],
  builds: ['delivery_model.ui.packages.duty.builds', 'Builds'],
  supplies: ['delivery_model.ui.packages.duty.supplies', 'Supplies'],
  manages: ['delivery_model.ui.packages.duty.manages', 'Manages'],
};

const STATUS_ACTION: Record<PackageStatus, KeyText> = {
  planned: ['delivery_model.ui.packages.action.reopen', 'Put back into the plan'],
  closed: ['delivery_model.ui.packages.action.close', 'Close out'],
  cancelled: ['delivery_model.ui.packages.action.cancel', 'Cancel package'],
};

export const PACKAGE_KEY_MAPS: Record<string, Record<string, KeyText>> = { FILTER, DUTY, STATUS_ACTION };

const PLAN_FINDINGS = ['packages_inconsistent_with_form', 'price_basis_inconsistent_with_form', 'contract_type_inconsistent_with_form'];

export interface PackagePlanPanelProps {
  projectId: string;
  model: DeliveryModel;
  packages: DeliveryPackage[];
  consistency: Consistency | null;
  catalogue: DeliveryCatalogue | null;
  labels: LabelContext;
  onChanged: () => void;
}

type Editing = { mode: 'new' } | { mode: 'edit'; pkg: DeliveryPackage } | null;

export function PackagePlanPanel({ projectId, model, packages, consistency, catalogue, labels, onChanged }: PackagePlanPanelProps) {
  const { t } = useTranslation();
  const onError = useRefusalToast();
  const [filter, setFilter] = useState<ResponsibilityFilter>('all');
  const [editing, setEditing] = useState<Editing>(null);
  const [linking, setLinking] = useState<DeliveryPackage | null>(null);
  const [deleting, setDeleting] = useState<DeliveryPackage | null>(null);
  const editV = canEditPlan(model);
  // The usual packages come from the chosen form, or before a proposal from the leading one.
  const deriveV = editV;
  const partyName = useMemo(() => partyNamer(labels, catalogue?.parties ?? []), [labels, catalogue]);
  const rows = useMemo(() => packageTree(filterPackages(packages, filter)), [packages, filter]);
  const planFindings = (consistency?.items ?? []).filter((f) => PLAN_FINDINGS.includes(f.code));
  const titleOf = (ref: string) => packages.find((p) => p.code === ref || p.id === ref)?.title ?? ref;

  const derive = useMutation({ mutationFn: () => derivePackages(projectId), onSuccess: onChanged, onError });
  const status = useMutation({
    mutationFn: (v: { id: string; status: PackageStatus }) => setPackageStatus(projectId, v.id, v.status),
    onSuccess: onChanged,
    onError,
  });
  const unlink = useMutation({ mutationFn: (id: string) => unlinkPackage(projectId, id), onSuccess: onChanged, onError });
  const remove = useMutation({
    mutationFn: (id: string) => deletePackage(projectId, id),
    onSuccess: () => {
      setDeleting(null);
      onChanged();
    },
    onError: (err) => {
      setDeleting(null);
      onError(err);
    },
  });

  const dialogs = (
    <>
      {editing && (
        <PackageDialog
          projectId={projectId}
          pkg={editing.mode === 'edit' ? editing.pkg : null}
          packages={packages}
          catalogue={catalogue}
          labels={labels}
          onClose={() => setEditing(null)}
          onDone={onChanged}
        />
      )}
      {linking && <LinkPackageDialog projectId={projectId} pkg={linking} labels={labels} onClose={() => setLinking(null)} onDone={onChanged} />}
      <ConfirmDialog
        open={!!deleting}
        loading={remove.isPending}
        title={t('delivery_model.ui.packages.delete_title', { defaultValue: 'Delete this package?' })}
        message={t('delivery_model.ui.packages.delete_body', {
          defaultValue: '{{name}} is removed from the plan. A package that is linked or has packages under it cannot be deleted.',
          name: deleting?.title ?? '',
        })}
        confirmLabel={t('delivery_model.ui.packages.delete_confirm', { defaultValue: 'Delete package' })}
        cancelLabel={t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  if (packages.length === 0) {
    return (
      <div className="space-y-4" data-testid="packages-empty">
        <EmptyState
          icon={<Boxes size={28} />}
          title={t('delivery_model.ui.packages.empty_title', { defaultValue: 'No packages yet' })}
          description={t('delivery_model.ui.packages.empty_body', {
            defaultValue:
              'A package is one contract to let: who designs, builds or supplies a part of the work. Start from the usual packages of the chosen form, then adjust them.',
          })}
        />
        <div className="flex flex-wrap items-start justify-center gap-3">
          <ReasonedButton verdict={deriveV} icon={<Wand2 size={14} />} loading={derive.isPending} onClick={() => derive.mutate()} data-testid="derive-button">
            {t('delivery_model.ui.packages.derive', { defaultValue: 'Create the usual packages' })}
          </ReasonedButton>
          {!editV && (
            <Button variant="secondary" icon={<Plus size={14} />} onClick={() => setEditing({ mode: 'new' })} data-testid="add-package-button">
              {t('delivery_model.ui.packages.add', { defaultValue: 'Add a package' })}
            </Button>
          )}
        </div>
        {dialogs}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="package-plan-panel">
      <div className="flex flex-wrap items-start gap-3">
        <ReasonedButton verdict={editV} icon={<Plus size={14} />} onClick={() => setEditing({ mode: 'new' })} data-testid="add-package-button">
          {t('delivery_model.ui.packages.add', { defaultValue: 'Add a package' })}
        </ReasonedButton>
        {!deriveV && (
          <Button
            variant="secondary"
            icon={<Wand2 size={14} />}
            loading={derive.isPending}
            onClick={() => derive.mutate()}
            data-testid="derive-button"
            title={t('delivery_model.ui.packages.derive_hint', {
              defaultValue: 'Adds the usual packages of the chosen form that are not in the plan yet.',
            })}
          >
            {t('delivery_model.ui.packages.derive', { defaultValue: 'Create the usual packages' })}
          </Button>
        )}
        <span className="ml-auto">
          <ExportButtons projectId={projectId} what="packages" />
        </span>
      </div>

      {planFindings.length > 0 ? (
        <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-3" role="status" data-testid="consistency-banner">
          <p className="mb-1 text-sm font-medium text-content-primary">
            {t('delivery_model.ui.packages.inconsistent', { defaultValue: 'The plan does not fit the chosen form yet' })}
          </p>
          <FindingList findings={planFindings} refName={titleOf} testId="consistency-findings" />
        </div>
      ) : (
        consistency &&
        model.selected_form_code && (
          <p className="text-sm text-semantic-success" data-testid="consistency-ok">
            {t('delivery_model.ui.packages.consistent', { defaultValue: 'The plan fits the chosen form.' })}
          </p>
        )
      )}

      <div
        className="flex flex-wrap gap-1.5"
        role="group"
        aria-label={t('delivery_model.ui.packages.filter_label', { defaultValue: 'Show packages by duty' })}
      >
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={filter === f}
            data-testid={`package-filter-${f}`}
            onClick={() => setFilter(f)}
            className={clsx(
              'rounded-full border px-3 py-1 text-xs',
              filter === f ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary',
            )}
          >
            {vocab(labels.t, FILTER, f)}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-content-tertiary" data-testid="packages-none-in-filter">
          {t('delivery_model.ui.packages.none_in_filter', { defaultValue: 'No package of the plan has this duty.' })}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface-elevated shadow-sm">
          <table className="w-full min-w-[860px] text-sm" data-testid="package-table">
            <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.packages.col_package', { defaultValue: 'Package' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.packages.col_duties', { defaultValue: 'Does' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.packages.col_party', { defaultValue: 'Done by' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.packages.col_contract', { defaultValue: 'Contract with' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.packages.col_price', { defaultValue: 'Price basis' })}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.packages.col_status', { defaultValue: 'Status' })}</th>
                <th scope="col" className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ pkg, depth }) => (
                <tr key={pkg.id} className="border-t border-border-light align-top" data-testid="package-row">
                  <th scope="row" className="px-3 py-2 text-left font-normal" style={{ paddingInlineStart: `${0.75 + depth * 1.25}rem` }}>
                    <span className="block font-medium text-content-primary">{pkg.title}</span>
                    <span className="block text-xs text-content-tertiary">
                      <span className="font-mono">{pkg.code}</span>
                      <span className="ml-2">{vocab(labels.t, PACKAGE_KIND, pkg.kind)}</span>
                    </span>
                    {pkg.need_date && (
                      <span className="block text-xs text-content-tertiary">
                        {t('delivery_model.ui.packages.needed_by', { defaultValue: 'Needed by {{date}}', date: fmtDate(pkg.need_date) })}
                      </span>
                    )}
                  </th>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap gap-1">
                      {DUTIES.filter((d) => pkg[d]).map((d) => (
                        <span key={d} className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-secondary">
                          {vocab(labels.t, DUTY, d)}
                        </span>
                      ))}
                    </span>
                  </td>
                  <td className="px-3 py-2">{partyName(pkg.party)}</td>
                  <td className="px-3 py-2">{vocab(labels.t, CONTRACTING_PARTY, pkg.contracting_party)}</td>
                  <td className="px-3 py-2">
                    {pkg.price_basis ? vocab(labels.t, PRICE_BASIS, pkg.price_basis) : ''}
                    {pkg.standard_form && <span className="block text-xs text-content-tertiary">{pkg.standard_form}</span>}
                  </td>
                  <td className="px-3 py-2">
                    <ToneBadge tone={PACKAGE_TONE[pkg.effective_status]} testId="package-status">
                      {vocab(labels.t, PACKAGE_STATUS, pkg.effective_status)}
                    </ToneBadge>
                    {pkg.link && (
                      <span
                        className={clsx('mt-1 block text-2xs', pkg.link.missing ? 'text-semantic-error' : 'text-content-tertiary')}
                        data-testid="package-link"
                      >
                        {pkg.link.missing
                          ? t('delivery_model.ui.packages.link_missing', { defaultValue: 'The linked record no longer exists' })
                          : t('delivery_model.ui.packages.linked_to', {
                              defaultValue: 'Linked: {{kind}}',
                              kind: vocab(labels.t, PACKAGE_LINK_KIND, pkg.link.kind),
                            })}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {!editV && (
                      <span className="flex justify-end gap-0.5">
                        <IconAction
                          label={t('delivery_model.ui.packages.edit_of', { defaultValue: 'Edit {{name}}', name: pkg.title })}
                          onClick={() => setEditing({ mode: 'edit', pkg })}
                          testId="package-edit"
                        >
                          <Pencil size={14} />
                        </IconAction>
                        {pkg.link ? (
                          <IconAction
                            label={t('delivery_model.ui.packages.unlink_of', { defaultValue: 'Remove the link of {{name}}', name: pkg.title })}
                            onClick={() => unlink.mutate(pkg.id)}
                            testId="package-unlink"
                          >
                            <Link2Off size={14} />
                          </IconAction>
                        ) : (
                          <IconAction
                            label={t('delivery_model.ui.packages.link_of', { defaultValue: 'Link {{name}} to a procurement record', name: pkg.title })}
                            onClick={() => setLinking(pkg)}
                            testId="package-link-action"
                          >
                            <Link2 size={14} />
                          </IconAction>
                        )}
                        {nextPackageStatuses(pkg.status).map((next) => (
                          <IconAction
                            key={next}
                            label={vocab(labels.t, STATUS_ACTION, next)}
                            onClick={() => status.mutate({ id: pkg.id, status: next })}
                            testId={`package-status-${next}`}
                          >
                            {next === 'closed' ? <CheckCircle2 size={14} /> : next === 'cancelled' ? <Ban size={14} /> : <RotateCcw size={14} />}
                          </IconAction>
                        ))}
                        <IconAction
                          label={t('delivery_model.ui.packages.delete_of', { defaultValue: 'Delete {{name}}', name: pkg.title })}
                          onClick={() => setDeleting(pkg)}
                          testId="package-delete"
                        >
                          <Trash2 size={14} />
                        </IconAction>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {dialogs}
    </div>
  );
}

function IconAction({ label, onClick, testId, children }: { label: string; onClick: () => void; testId: string; children: ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      data-testid={testId}
      onClick={onClick}
      className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
    >
      {children}
    </button>
  );
}

interface PackageDialogProps {
  projectId: string;
  /** null creates a package. */
  pkg: DeliveryPackage | null;
  packages: DeliveryPackage[];
  catalogue: DeliveryCatalogue | null;
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

function draftOfPackage(pkg: DeliveryPackage | null): PackageInput {
  return {
    code: pkg?.code ?? '',
    title: pkg?.title ?? '',
    kind: pkg?.kind ?? 'construction',
    designs: pkg?.designs ?? false,
    builds: pkg?.builds ?? true,
    supplies: pkg?.supplies ?? false,
    manages: pkg?.manages ?? false,
    party: pkg?.party ?? 'contractor',
    contracting_party: pkg?.contracting_party ?? 'owner',
    price_basis: pkg?.price_basis ?? null,
    standard_form: pkg?.standard_form ?? '',
    parent_id: pkg?.parent_id ?? null,
    scope: pkg?.scope ?? '',
    wbs_ref: pkg?.wbs_ref ?? '',
    boq_ref: pkg?.boq_ref ?? '',
    need_date: pkg?.need_date ?? null,
  };
}

export function PackageDialog({ projectId, pkg, packages, catalogue, labels, onClose, onDone }: PackageDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const isNew = !pkg;
  const [draft, setDraft] = useState<PackageInput>(() => draftOfPackage(pkg));
  const [tried, setTried] = useState(false);
  const problems = packageProblems(draft, isNew);
  const partyName = useMemo(() => partyNamer(labels, catalogue?.parties ?? []), [labels, catalogue]);
  const parties = catalogue?.parties ?? [];
  const set = <K extends keyof PackageInput>(key: K, value: PackageInput[K]) => setDraft((d) => ({ ...d, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const body = { ...draft, code: draft.code.trim(), title: draft.title.trim() };
      if (!pkg) return createPackage(projectId, body);
      // Only what changed travels; a null among it clears that field.
      const changes = changedFields(draftOfPackage(pkg), body);
      delete changes.code;
      return updatePackage(projectId, pkg.id, changes);
    },
    onSuccess: () => {
      onDone();
      onClose();
    },
  });
  const send = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={save.isPending}
      testId="package-dialog"
      title={
        isNew
          ? t('delivery_model.ui.packages.new_title', { defaultValue: 'New package' })
          : t('delivery_model.ui.packages.edit_title', { defaultValue: 'Edit package' })
      }
      subtitle={t('delivery_model.ui.packages.dialog_subtitle', {
        defaultValue: 'One contract to let: what it covers, who does it and who signs it.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} onClick={send} data-testid="package-send">
            {t('delivery_model.ui.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={save.isError ? refusal(save.error) : null} />
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('delivery_model.ui.packages.code', { defaultValue: 'Code' })}>
            <input className={INPUT_CLASS} value={draft.code} disabled={!isNew} maxLength={64} data-testid="package-code" onChange={(e) => set('code', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.packages.title', { defaultValue: 'Title' })} className="sm:col-span-2">
            <input className={INPUT_CLASS} value={draft.title} maxLength={500} data-testid="package-title" onChange={(e) => set('title', e.target.value)} />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('delivery_model.ui.packages.kind', { defaultValue: 'Kind of package' })}>
            <select className={INPUT_CLASS} value={draft.kind} onChange={(e) => set('kind', e.target.value as PackageKind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {vocab(labels.t, PACKAGE_KIND, k)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('delivery_model.ui.packages.col_party', { defaultValue: 'Done by' })}>
            <select className={INPUT_CLASS} value={draft.party} onChange={(e) => set('party', e.target.value)}>
              {!parties.some((p) => p.code === draft.party) && <option value={draft.party}>{partyName(draft.party)}</option>}
              {parties.map((p) => (
                <option key={p.code} value={p.code}>
                  {partyName(p.code)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-content-primary">
            {t('delivery_model.ui.packages.duties', { defaultValue: 'What this package does' })}
          </legend>
          <div className="flex flex-wrap gap-4">
            {DUTIES.map((d) => (
              <label key={d} className="inline-flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={draft[d]} onChange={(e) => set(d, e.target.checked)} />
                {vocab(labels.t, DUTY, d)}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('delivery_model.ui.packages.col_contract', { defaultValue: 'Contract with' })}>
            <select className={INPUT_CLASS} value={draft.contracting_party} onChange={(e) => set('contracting_party', e.target.value as ContractingParty)}>
              {(Object.keys(CONTRACTING_PARTY) as ContractingParty[]).map((c) => (
                <option key={c} value={c}>
                  {vocab(labels.t, CONTRACTING_PARTY, c)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('delivery_model.ui.packages.col_price', { defaultValue: 'Price basis' })}>
            <select className={INPUT_CLASS} value={draft.price_basis ?? ''} onChange={(e) => set('price_basis', (e.target.value || null) as PriceBasis | null)}>
              <option value="">{t('delivery_model.ui.packages.price_open', { defaultValue: 'Not decided yet' })}</option>
              {PRICE_BASES.map((b) => (
                <option key={b} value={b}>
                  {vocab(labels.t, PRICE_BASIS, b)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('delivery_model.ui.packages.parent', { defaultValue: 'Sits under' })}>
            <select className={INPUT_CLASS} value={draft.parent_id ?? ''} onChange={(e) => set('parent_id', e.target.value || null)}>
              <option value="">{t('delivery_model.ui.packages.parent_none', { defaultValue: 'No package above it' })}</option>
              {packages
                .filter((p) => p.id !== pkg?.id)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
            </select>
          </Field>
          <Field label={t('delivery_model.ui.packages.need_date', { defaultValue: 'Contract needed by' })}>
            <input type="date" className={INPUT_CLASS} value={draft.need_date ?? ''} onChange={(e) => set('need_date', e.target.value || null)} />
          </Field>
          <Field
            label={t('delivery_model.ui.packages.standard_form', { defaultValue: 'Standard contract form' })}
            hint={t('delivery_model.ui.packages.standard_form_hint', { defaultValue: 'The published contract conditions it will use, if any.' })}
          >
            <input className={INPUT_CLASS} value={draft.standard_form} maxLength={120} onChange={(e) => set('standard_form', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.packages.wbs_ref', { defaultValue: 'Work breakdown reference' })}>
            <input className={INPUT_CLASS} value={draft.wbs_ref} maxLength={120} onChange={(e) => set('wbs_ref', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.packages.boq_ref', { defaultValue: 'Bill of quantities reference' })}>
            <input className={INPUT_CLASS} value={draft.boq_ref} maxLength={120} onChange={(e) => set('boq_ref', e.target.value)} />
          </Field>
        </div>
        <Field label={t('delivery_model.ui.packages.scope', { defaultValue: 'What it covers' })}>
          <textarea rows={3} className={INPUT_CLASS} value={draft.scope} onChange={(e) => set('scope', e.target.value)} />
        </Field>
        {tried && <ProblemList problems={problems} testId="package-problems" />}
      </div>
    </WideModal>
  );
}

interface LinkPackageDialogProps {
  projectId: string;
  pkg: DeliveryPackage;
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

export function LinkPackageDialog({ projectId, pkg, labels, onClose, onDone }: LinkPackageDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const [kind, setKind] = useState<PackageLinkKind>('contract');
  const [recordId, setRecordId] = useState('');
  const [tried, setTried] = useState(false);
  const link = useMutation({
    mutationFn: () => linkPackage(projectId, pkg.id, { link_kind: kind, link_id: recordId }),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });
  const send = () => {
    setTried(true);
    if (recordId) link.mutate();
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={link.isPending}
      size="md"
      testId="link-package-dialog"
      title={t('delivery_model.ui.link.title', { defaultValue: 'Link to a procurement record' })}
      subtitle={t('delivery_model.ui.link.subtitle', {
        defaultValue: '{{name}} then shows the progress of that record: in procurement, awarded.',
        name: pkg.title,
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={link.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={link.isPending} onClick={send} data-testid="link-send">
            {t('delivery_model.ui.link.send', { defaultValue: 'Link' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={link.isError ? refusal(link.error) : null} />
        <Field label={t('delivery_model.ui.link.kind', { defaultValue: 'Type of record' })}>
          <select
            className={INPUT_CLASS}
            value={kind}
            data-testid="link-kind"
            onChange={(e) => {
              setKind(e.target.value as PackageLinkKind);
              setRecordId('');
            }}
          >
            {LINK_KINDS.map((k) => (
              <option key={k} value={k}>
                {vocab(labels.t, PACKAGE_LINK_KIND, k)}
              </option>
            ))}
          </select>
        </Field>
        <RecordPicker projectId={projectId} kind={kind} value={recordId} onChange={setRecordId} />
        {tried && !recordId && <ProblemList problems={['record_required']} testId="link-problems" />}
      </div>
    </WideModal>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The contract side of the project: contract forms and price bases, land
// tenure, utility contracts, the agreement with the user and the partner
// structure (project company or joint venture). The kinds come from the
// pinned catalogue; a signed item is terminated, never deleted.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { FileText, Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import type { BadgeVariant } from '@/shared/ui/Badge';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';

import { canEditPlan } from './access';
import {
  createContractItem,
  deleteContractItem,
  updateContractItem,
  type ContractGroup,
  type ContractItem,
  type ContractItemInput,
  type ContractItemStatus,
  type DeliveryCatalogue,
  type DeliveryModel,
  type DeliveryPackage,
  type PriceBasis,
} from './api';
import { Field, FindingList, INPUT_CLASS, ReasonedButton, ServerRefusal, ToneBadge } from './DeliveryBits';
import { useRefusalText, useRefusalToast } from './hooks';
import { CONTRACT_GROUP, CONTRACT_STATUS, PRICE_BASIS, catalogueText, vocab, type LabelContext } from './labels';

const GROUPS = Object.keys(CONTRACT_GROUP) as ContractGroup[];
const STATUSES = Object.keys(CONTRACT_STATUS) as ContractItemStatus[];
const BASES = Object.keys(PRICE_BASIS) as PriceBasis[];

const STATUS_TONE: Record<ContractItemStatus, BadgeVariant> = {
  draft: 'neutral',
  negotiating: 'warning',
  agreed: 'blue',
  signed: 'success',
  terminated: 'neutral',
};

export interface ContractPanelProps {
  projectId: string;
  items: ContractItem[];
  packages: DeliveryPackage[];
  catalogue: DeliveryCatalogue | null;
  model: Pick<DeliveryModel, 'can' | 'status'>;
  labels: LabelContext;
  onChanged: () => void;
}

type Editing = { mode: 'new'; group: ContractGroup } | { mode: 'edit'; item: ContractItem } | null;

export function ContractPanel({ projectId, model, items, packages, catalogue, labels, onChanged }: ContractPanelProps) {
  const { t } = useTranslation();
  const onError = useRefusalToast();
  const [editing, setEditing] = useState<Editing>(null);
  const [deleting, setDeleting] = useState<ContractItem | null>(null);
  const editV = canEditPlan(model);
  const kindName = (group: ContractGroup, code: string) => {
    const kind = catalogue?.contract_kinds?.find((k) => k.group === group && k.code === code);
    return catalogueText(labels, { key: kind?.name_key, texts: kind?.labels, code });
  };

  const remove = useMutation({
    mutationFn: (id: string) => deleteContractItem(projectId, id),
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
        <ContractDialog
          projectId={projectId}
          item={editing.mode === 'edit' ? editing.item : null}
          group={editing.mode === 'edit' ? editing.item.group_code : editing.group}
          packages={packages}
          catalogue={catalogue}
          labels={labels}
          kindName={kindName}
          onClose={() => setEditing(null)}
          onDone={onChanged}
        />
      )}
      <ConfirmDialog
        open={!!deleting}
        loading={remove.isPending}
        title={t('delivery_model.ui.contract.delete_title', { defaultValue: 'Delete this item?' })}
        message={t('delivery_model.ui.contract.delete_body', {
          defaultValue: '{{name}} is removed from the contract side of the project.',
          name: deleting ? deleting.title || deleting.code : '',
        })}
        confirmLabel={t('delivery_model.ui.contract.delete_confirm', { defaultValue: 'Delete item' })}
        cancelLabel={t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  if (items.length === 0) {
    return (
      <div className="space-y-4" data-testid="contract-empty">
        <EmptyState
          icon={<FileText size={28} />}
          title={t('delivery_model.ui.contract.empty_title', { defaultValue: 'No contract-side items yet' })}
          description={t('delivery_model.ui.contract.empty_body', {
            defaultValue:
              'Record the contract forms, the land tenure, the utility contracts, the agreement with the user and the partner structure of the project.',
          })}
        />
        <div className="flex justify-center">
          <ReasonedButton verdict={editV} icon={<Plus size={14} />} onClick={() => setEditing({ mode: 'new', group: 'contract_form' })} data-testid="add-contract-item">
            {t('delivery_model.ui.contract.add', { defaultValue: 'Add an item' })}
          </ReasonedButton>
        </div>
        {dialogs}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="contract-panel">
      {GROUPS.map((group) => {
        const rows = items.filter((i) => i.group_code === group);
        const total =
          group === 'partner_structure'
            ? rows
                .filter((r) => r.share_percent && r.status !== 'terminated')
                .reduce((sum, r) => sum + Number(r.share_percent), 0)
            : null;
        return (
          <section key={group} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="contract-group" data-group={group}>
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <h3 className="text-sm font-semibold text-content-primary">{vocab(labels.t, CONTRACT_GROUP, group)}</h3>
              {total !== null && rows.length > 0 && (
                <span className="text-xs text-content-secondary" data-testid="partner-total">
                  {t('delivery_model.ui.contract.partners_total', { defaultValue: 'Shares add up to {{total}} percent.', total })}
                </span>
              )}
              <span className="ml-auto">
                <ReasonedButton size="sm" variant="secondary" verdict={editV} icon={<Plus size={13} />} onClick={() => setEditing({ mode: 'new', group })} data-testid="add-contract-item">
                  {t('delivery_model.ui.contract.add', { defaultValue: 'Add an item' })}
                </ReasonedButton>
              </span>
            </div>
            {rows.length === 0 ? (
              <p className="text-sm text-content-tertiary">{t('delivery_model.ui.contract.group_empty', { defaultValue: 'Nothing recorded yet.' })}</p>
            ) : (
              <ul className="divide-y divide-border-light">
                {rows.map((item) => (
                  <li key={item.id} className="flex flex-wrap items-start gap-3 py-2 text-sm" data-testid="contract-row">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-content-tertiary">{item.code}</span>
                        <span className="font-medium text-content-primary">{item.title || kindName(item.group_code, item.kind_code)}</span>
                        <ToneBadge tone={STATUS_TONE[item.status]} testId="contract-status">
                          {vocab(labels.t, CONTRACT_STATUS, item.status)}
                        </ToneBadge>
                      </div>
                      <p className="text-xs text-content-secondary">
                        {[
                          kindName(item.group_code, item.kind_code),
                          item.counterparty,
                          item.price_basis ? vocab(labels.t, PRICE_BASIS, item.price_basis) : '',
                          item.share_percent
                            ? t('delivery_model.ui.contract.share_of', { defaultValue: 'Share {{share}} percent', share: item.share_percent })
                            : '',
                          item.start_date ? fmtDate(item.start_date) : '',
                        ]
                          .filter(Boolean)
                          .join(' - ')}
                      </p>
                      <FindingList findings={item.findings} testId="contract-findings" />
                    </div>
                    {!editV && (
                      <span className="flex gap-1">
                        <button
                          type="button"
                          className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                          data-testid="contract-edit"
                          onClick={() => setEditing({ mode: 'edit', item })}
                          aria-label={t('delivery_model.ui.packages.edit_of', { defaultValue: 'Edit {{name}}', name: item.title || item.code })}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                          data-testid="contract-delete"
                          onClick={() => setDeleting(item)}
                          aria-label={t('delivery_model.ui.packages.delete_of', { defaultValue: 'Delete {{name}}', name: item.title || item.code })}
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
      {dialogs}
    </div>
  );
}

interface ContractDialogProps {
  projectId: string;
  /** null creates an item. */
  item: ContractItem | null;
  group: ContractGroup;
  packages: DeliveryPackage[];
  catalogue: DeliveryCatalogue | null;
  labels: LabelContext;
  kindName: (group: ContractGroup, code: string) => string;
  onClose: () => void;
  onDone: () => void;
}

function draftOf(item: ContractItem | null, group: ContractGroup): ContractItemInput {
  return {
    code: item?.code ?? '',
    group_code: group,
    kind_code: item?.kind_code ?? '',
    title: item?.title ?? '',
    counterparty: item?.counterparty ?? '',
    package_id: item?.package_id ?? null,
    status: item?.status ?? 'draft',
    reference: item?.reference ?? '',
    start_date: item?.start_date ?? null,
    end_date: item?.end_date ?? null,
    price_basis: item?.price_basis ?? null,
    share_percent: item?.share_percent ?? null,
    notes: item?.notes ?? '',
  };
}

function ContractDialog({ projectId, item, group, packages, catalogue, labels, kindName, onClose, onDone }: ContractDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const isNew = !item;
  const [draft, setDraft] = useState<ContractItemInput>(() => draftOf(item, group));
  const [tried, setTried] = useState(false);
  const set = <K extends keyof ContractItemInput>(key: K, value: ContractItemInput[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const kinds = (catalogue?.contract_kinds ?? []).filter((k) => k.group === group);
  const problems: string[] = [];
  if (isNew && !draft.code.trim()) problems.push(t('delivery_model.ui.contract.problem_code', { defaultValue: 'Give the item a code.' }));
  if (!draft.kind_code) problems.push(t('delivery_model.ui.contract.problem_kind', { defaultValue: 'Choose a kind.' }));

  const save = useMutation({
    mutationFn: () => {
      const body: ContractItemInput = { ...draft, code: draft.code.trim() };
      if (!item) return createContractItem(projectId, body);
      const { code: _code, group_code: _group, ...changes } = body;
      void _code;
      void _group;
      return updateContractItem(projectId, item.id, changes);
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
      testId="contract-dialog"
      title={
        isNew
          ? t('delivery_model.ui.contract.new_title', { defaultValue: 'New contract item' })
          : t('delivery_model.ui.contract.edit_title', { defaultValue: 'Edit contract item' })
      }
      subtitle={vocab(labels.t, CONTRACT_GROUP, group)}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} onClick={send} data-testid="contract-send">
            {t('delivery_model.ui.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={save.isError ? refusal(save.error) : null} />
        {tried && problems.length > 0 && (
          <ul className="text-sm text-semantic-error" role="alert">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('delivery_model.ui.contract.code', { defaultValue: 'Code' })}>
            <input className={INPUT_CLASS} value={draft.code} disabled={!isNew} maxLength={64} data-testid="contract-code" onChange={(e) => set('code', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.contract.kind', { defaultValue: 'Kind' })} className="sm:col-span-2">
            <select className={INPUT_CLASS} value={draft.kind_code} data-testid="contract-kind" onChange={(e) => set('kind_code', e.target.value)}>
              <option value="">{t('delivery_model.ui.choose', { defaultValue: 'Choose' })}</option>
              {kinds.map((k) => (
                <option key={k.code} value={k.code}>
                  {kindName(group, k.code)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('delivery_model.ui.contract.title', { defaultValue: 'Title' })} className="sm:col-span-2">
            <input className={INPUT_CLASS} value={draft.title} maxLength={500} onChange={(e) => set('title', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.contract.counterparty', { defaultValue: 'Counterparty' })}>
            <input className={INPUT_CLASS} value={draft.counterparty} maxLength={255} data-testid="contract-counterparty" onChange={(e) => set('counterparty', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.contract.status', { defaultValue: 'Status' })}>
            <select className={INPUT_CLASS} value={draft.status} onChange={(e) => set('status', e.target.value as ContractItemStatus)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {vocab(labels.t, CONTRACT_STATUS, s)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('delivery_model.ui.contract.start_date', { defaultValue: 'Start' })}>
            <input type="date" className={INPUT_CLASS} value={draft.start_date ?? ''} onChange={(e) => set('start_date', e.target.value || null)} />
          </Field>
          <Field label={t('delivery_model.ui.contract.end_date', { defaultValue: 'End' })}>
            <input type="date" className={INPUT_CLASS} value={draft.end_date ?? ''} onChange={(e) => set('end_date', e.target.value || null)} />
          </Field>
          {group === 'contract_form' && (
            <>
              <Field label={t('delivery_model.ui.contract.price_basis', { defaultValue: 'Price basis' })}>
                <select className={INPUT_CLASS} value={draft.price_basis ?? ''} onChange={(e) => set('price_basis', (e.target.value || null) as PriceBasis | null)}>
                  <option value="">{t('delivery_model.ui.choose', { defaultValue: 'Choose' })}</option>
                  {BASES.map((b) => (
                    <option key={b} value={b}>
                      {vocab(labels.t, PRICE_BASIS, b)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('delivery_model.ui.contract.package', { defaultValue: 'Governs package' })}>
                <select className={INPUT_CLASS} value={draft.package_id ?? ''} onChange={(e) => set('package_id', e.target.value || null)}>
                  <option value="">{t('delivery_model.ui.choose', { defaultValue: 'Choose' })}</option>
                  {packages.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          )}
          {group === 'partner_structure' && (
            <Field label={t('delivery_model.ui.contract.share', { defaultValue: 'Share in percent' })}>
              <input className={INPUT_CLASS} inputMode="decimal" value={draft.share_percent ?? ''} data-testid="contract-share" onChange={(e) => set('share_percent', e.target.value.trim() || null)} />
            </Field>
          )}
          <Field label={t('delivery_model.ui.contract.reference', { defaultValue: 'Reference' })}>
            <input className={INPUT_CLASS} value={draft.reference} maxLength={120} onChange={(e) => set('reference', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.contract.notes', { defaultValue: 'Notes' })} className="sm:col-span-2">
            <textarea className={INPUT_CLASS} rows={3} value={draft.notes} onChange={(e) => set('notes', e.target.value)} />
          </Field>
        </div>
      </div>
    </WideModal>
  );
}

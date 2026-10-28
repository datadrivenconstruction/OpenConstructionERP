// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Owner-furnished items: equipment, material, design or services the owner
// supplies itself and a contractor installs or relies on. Each item needs a
// procurement route and an arrival date that is in time for the package that
// installs it; the list flags an item without a route and one that arrives
// too late.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { ArrowRight, PackageOpen, Pencil, Plus, Route, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';

import { canEditPlan } from './access';
import {
  createOfi,
  deleteOfi,
  setOfiRoute,
  setOfiStatus,
  updateOfi,
  type DeliveryModel,
  type DeliveryPackage,
  type InstallBy,
  type OfiInput,
  type OfiKind,
  type OfiLinkKind,
  type OfiRoute,
  type OfiStatus,
  type OwnerFurnishedItem,
} from './api';
import { Field, FindingList, INPUT_CLASS, OFI_TONE, ProblemList, ReasonedButton, ServerRefusal, ToneBadge } from './DeliveryBits';
import { useRefusalText, useRefusalToast } from './hooks';
import { INSTALL_BY, OFI_KIND, OFI_LINK_KIND, OFI_ROUTE, OFI_STATUS, vocab, type KeyText, type LabelContext } from './labels';
import { RecordPicker } from './RecordPicker';
import { changedFields, nextOfiStatus, ofiProblems } from './rules';

const KINDS = Object.keys(OFI_KIND) as OfiKind[];
const ROUTES = Object.keys(OFI_ROUTE) as OfiRoute[];
const LINKABLE: ReadonlyArray<OfiRoute> = ['rfq', 'purchase_order', 'requisition'];

const NEXT_ACTION: Partial<Record<OfiStatus, KeyText>> = {
  ordered: ['delivery_model.ui.ofi.action.ordered', 'Mark as ordered'],
  delivered: ['delivery_model.ui.ofi.action.delivered', 'Mark as delivered'],
  handed_to_installer: ['delivery_model.ui.ofi.action.handed_to_installer', 'Mark as handed over'],
};

export const OFI_KEY_MAPS: Record<string, Record<string, KeyText>> = { NEXT_ACTION: NEXT_ACTION as Record<string, KeyText> };

export interface OfiPanelProps {
  projectId: string;
  items: OwnerFurnishedItem[];
  packages: DeliveryPackage[];
  model: Pick<DeliveryModel, 'can' | 'status'>;
  labels: LabelContext;
  onChanged: () => void;
}

type Editing = { mode: 'new' } | { mode: 'edit'; item: OwnerFurnishedItem } | null;

export function OfiPanel({ projectId, model, items, packages, labels, onChanged }: OfiPanelProps) {
  const { t } = useTranslation();
  const onError = useRefusalToast();
  const [editing, setEditing] = useState<Editing>(null);
  const [routing, setRouting] = useState<OwnerFurnishedItem | null>(null);
  const [deleting, setDeleting] = useState<OwnerFurnishedItem | null>(null);
  const editV = canEditPlan(model);
  const packageTitle = (id: string | null) => packages.find((p) => p.id === id)?.title ?? '';

  const advance = useMutation({
    mutationFn: (v: { id: string; status: OfiStatus }) => setOfiStatus(projectId, v.id, v.status),
    onSuccess: onChanged,
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteOfi(projectId, id),
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
        <OfiDialog
          projectId={projectId}
          item={editing.mode === 'edit' ? editing.item : null}
          packages={packages}
          labels={labels}
          onClose={() => setEditing(null)}
          onDone={onChanged}
        />
      )}
      {routing && <OfiRouteDialog projectId={projectId} item={routing} labels={labels} onClose={() => setRouting(null)} onDone={onChanged} />}
      <ConfirmDialog
        open={!!deleting}
        loading={remove.isPending}
        title={t('delivery_model.ui.ofi.delete_title', { defaultValue: 'Delete this item?' })}
        message={t('delivery_model.ui.ofi.delete_body', {
          defaultValue: '{{name}} is removed from the list of owner-furnished items.',
          name: deleting?.description ?? '',
        })}
        confirmLabel={t('delivery_model.ui.ofi.delete_confirm', { defaultValue: 'Delete item' })}
        cancelLabel={t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  const addButton = (
    <ReasonedButton verdict={editV} icon={<Plus size={14} />} onClick={() => setEditing({ mode: 'new' })} data-testid="add-ofi-button">
      {t('delivery_model.ui.ofi.add', { defaultValue: 'Add an item' })}
    </ReasonedButton>
  );

  if (items.length === 0) {
    return (
      <div className="space-y-4" data-testid="ofi-empty">
        <EmptyState
          icon={<PackageOpen size={28} />}
          title={t('delivery_model.ui.ofi.empty_title', { defaultValue: 'No owner-furnished items yet' })}
          description={t('delivery_model.ui.ofi.empty_body', {
            defaultValue:
              'List what the owner supplies itself, for example a lift bought directly or a utility connection. Each item gets a procurement route and a date the installer needs it by.',
          })}
        />
        <div className="flex justify-center">{addButton}</div>
        {dialogs}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="ofi-panel">
      <div className="flex flex-wrap items-start gap-3">{addButton}</div>
      <div className="overflow-x-auto rounded-xl border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[820px] text-sm" data-testid="ofi-table">
          <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.ofi.col_item', { defaultValue: 'Item' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.ofi.col_installer', { defaultValue: 'Installed by' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.ofi.col_route', { defaultValue: 'How it is bought' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.ofi.col_dates', { defaultValue: 'Dates' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.ofi.col_status', { defaultValue: 'Status' })}</th>
              <th scope="col" className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const next = nextOfiStatus(item.status);
              const nextLabel = next ? NEXT_ACTION[next] : undefined;
              const hasRoute = !!item.procurement_route && item.procurement_route !== 'none_yet';
              return (
                <tr key={item.id} className="border-t border-border-light align-top" data-testid="ofi-row">
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="block font-medium text-content-primary">{item.description}</span>
                    <span className="block text-xs text-content-tertiary">
                      <span className="font-mono">{item.code}</span>
                      <span className="ml-2">{vocab(labels.t, OFI_KIND, item.item_kind)}</span>
                    </span>
                    <span className="mt-1 block">
                      <FindingList findings={item.findings} testId="ofi-findings" />
                    </span>
                  </th>
                  <td className="px-3 py-2">
                    {item.install_by === 'package' && item.package_id
                      ? packageTitle(item.package_id) || vocab(labels.t, INSTALL_BY, 'package')
                      : vocab(labels.t, INSTALL_BY, item.install_by)}
                  </td>
                  <td className="px-3 py-2" data-testid="ofi-route">
                    {hasRoute ? (
                      vocab(labels.t, OFI_ROUTE, item.procurement_route)
                    ) : (
                      <span className="text-semantic-error">{vocab(labels.t, OFI_ROUTE, 'none_yet')}</span>
                    )}
                    {item.link && (
                      <span className={item.link.missing ? 'block text-2xs text-semantic-error' : 'block text-2xs text-content-tertiary'}>
                        {item.link.missing
                          ? t('delivery_model.ui.packages.link_missing', { defaultValue: 'The linked record no longer exists' })
                          : t('delivery_model.ui.packages.linked_to', {
                              defaultValue: 'Linked: {{kind}}',
                              kind: vocab(labels.t, OFI_LINK_KIND, item.link.kind),
                            })}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-content-secondary">
                    {item.need_by_date && (
                      <span className="block">
                        {t('delivery_model.ui.ofi.needed_by', { defaultValue: 'Needed by {{date}}', date: fmtDate(item.need_by_date) })}
                      </span>
                    )}
                    {item.expected_delivery_date && (
                      <span className="block">
                        {t('delivery_model.ui.ofi.expected', { defaultValue: 'Expected {{date}}', date: fmtDate(item.expected_delivery_date) })}
                      </span>
                    )}
                    {item.latest_order_date && (
                      <span className="block" data-testid="ofi-order-by">
                        {t('delivery_model.ui.ofi.order_by', { defaultValue: 'Order by {{date}}', date: fmtDate(item.latest_order_date) })}
                      </span>
                    )}
                    {item.plant_item && (
                      <span className={item.plant_item.missing ? 'block text-semantic-warning' : 'block'} data-testid="ofi-plant-item">
                        {item.plant_item.missing
                          ? t('delivery_model.ui.ofi.plant_missing', {
                              defaultValue: 'Linked plant item {{code}} was not found in the plant register',
                              code: item.plant_item.code,
                            })
                          : t('delivery_model.ui.ofi.plant_linked', { defaultValue: 'Plant item {{code}}', code: item.plant_item.code })}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <ToneBadge tone={OFI_TONE[item.status]} testId="ofi-status">
                      {vocab(labels.t, OFI_STATUS, item.status)}
                    </ToneBadge>
                  </td>
                  <td className="px-3 py-2">
                    {!editV && (
                      <span className="flex flex-wrap justify-end gap-1">
                        {next && nextLabel && (
                          <Button
                            size="sm"
                            variant="secondary"
                            icon={<ArrowRight size={13} />}
                            loading={advance.isPending && advance.variables?.id === item.id}
                            onClick={() => advance.mutate({ id: item.id, status: next })}
                            data-testid="ofi-advance"
                          >
                            {t(nextLabel[0], { defaultValue: nextLabel[1] })}
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant={hasRoute ? 'ghost' : 'secondary'}
                          icon={<Route size={13} />}
                          onClick={() => setRouting(item)}
                          data-testid="ofi-route-action"
                        >
                          {hasRoute
                            ? t('delivery_model.ui.ofi.change_route', { defaultValue: 'Change route' })
                            : t('delivery_model.ui.ofi.set_route', { defaultValue: 'Set route' })}
                        </Button>
                        <button
                          type="button"
                          className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                          data-testid="ofi-edit"
                          onClick={() => setEditing({ mode: 'edit', item })}
                          aria-label={t('delivery_model.ui.packages.edit_of', { defaultValue: 'Edit {{name}}', name: item.description })}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                          data-testid="ofi-delete"
                          onClick={() => setDeleting(item)}
                          aria-label={t('delivery_model.ui.packages.delete_of', { defaultValue: 'Delete {{name}}', name: item.description })}
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {dialogs}
    </div>
  );
}

interface OfiDialogProps {
  projectId: string;
  /** null creates an item. */
  item: OwnerFurnishedItem | null;
  packages: DeliveryPackage[];
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

function draftOfItem(item: OwnerFurnishedItem | null): OfiInput {
  return {
    code: item?.code ?? '',
    description: item?.description ?? '',
    item_kind: item?.item_kind ?? 'equipment',
    install_by: item?.install_by ?? 'package',
    package_id: item?.package_id ?? null,
    need_by_date: item?.need_by_date ?? null,
    expected_delivery_date: item?.expected_delivery_date ?? null,
    enquiry_date: item?.enquiry_date ?? null,
    lead_time_days: item?.lead_time_days ?? null,
    plant_item_id: item?.plant_item_id ?? null,
  };
}

export function OfiDialog({ projectId, item, packages, labels, onClose, onDone }: OfiDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const isNew = !item;
  const [draft, setDraft] = useState<OfiInput>(() => draftOfItem(item));
  const [tried, setTried] = useState(false);
  const problems = ofiProblems(draft, isNew);
  const set = <K extends keyof OfiInput>(key: K, value: OfiInput[K]) => setDraft((d) => ({ ...d, [key]: value }));
  // While the plant register answers for the item, the enquiry date and the lead time are its figures.
  const fromRegister = item?.dates_source === 'plant_register';
  const plantCode = item?.plant_item?.code ?? '';
  const registerHint = fromRegister
    ? t('delivery_model.ui.ofi.from_register', { defaultValue: 'Read from plant item {{code}} in the plant register.', code: plantCode })
    : undefined;

  const save = useMutation({
    mutationFn: () => {
      const body: OfiInput = {
        ...draft,
        code: draft.code.trim(),
        description: draft.description.trim(),
        package_id: draft.install_by === 'package' ? draft.package_id : null,
      };
      if (!item) return createOfi(projectId, body);
      // Only what changed travels; a null among it clears that field.
      const changes = changedFields(draftOfItem(item), body);
      delete changes.code;
      return updateOfi(projectId, item.id, changes);
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
      testId="ofi-dialog"
      title={
        isNew
          ? t('delivery_model.ui.ofi.new_title', { defaultValue: 'New owner-furnished item' })
          : t('delivery_model.ui.ofi.edit_title', { defaultValue: 'Edit owner-furnished item' })
      }
      subtitle={t('delivery_model.ui.ofi.dialog_subtitle', {
        defaultValue: 'Something the owner supplies itself and a package installs or relies on.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} onClick={send} data-testid="ofi-send">
            {t('delivery_model.ui.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={save.isError ? refusal(save.error) : null} />
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('delivery_model.ui.packages.code', { defaultValue: 'Code' })}>
            <input className={INPUT_CLASS} value={draft.code} disabled={!isNew} maxLength={64} data-testid="ofi-code" onChange={(e) => set('code', e.target.value)} />
          </Field>
          <Field label={t('delivery_model.ui.ofi.description', { defaultValue: 'What it is' })} className="sm:col-span-2">
            <input className={INPUT_CLASS} value={draft.description} data-testid="ofi-description" onChange={(e) => set('description', e.target.value)} />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('delivery_model.ui.ofi.kind', { defaultValue: 'Kind of item' })}>
            <select className={INPUT_CLASS} value={draft.item_kind} onChange={(e) => set('item_kind', e.target.value as OfiKind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {vocab(labels.t, OFI_KIND, k)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('delivery_model.ui.ofi.col_installer', { defaultValue: 'Installed by' })}>
            <select className={INPUT_CLASS} value={draft.install_by} data-testid="ofi-install-by" onChange={(e) => set('install_by', e.target.value as InstallBy)}>
              {(Object.keys(INSTALL_BY) as InstallBy[]).map((v) => (
                <option key={v} value={v}>
                  {vocab(labels.t, INSTALL_BY, v)}
                </option>
              ))}
            </select>
          </Field>
          {draft.install_by === 'package' && (
            <Field label={t('delivery_model.ui.ofi.package', { defaultValue: 'Installing package' })} className="sm:col-span-2">
              <select className={INPUT_CLASS} value={draft.package_id ?? ''} data-testid="ofi-package" onChange={(e) => set('package_id', e.target.value || null)}>
                <option value="">{t('delivery_model.ui.choose', { defaultValue: 'Choose' })}</option>
                {packages.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label={t('delivery_model.ui.ofi.need_by', { defaultValue: 'Installer needs it by' })}>
            <input type="date" className={INPUT_CLASS} value={draft.need_by_date ?? ''} onChange={(e) => set('need_by_date', e.target.value || null)} />
          </Field>
          <Field
            label={t('delivery_model.ui.ofi.expected_date', { defaultValue: 'Expected on site' })}
            hint={t('delivery_model.ui.ofi.expected_hint', { defaultValue: 'Read from the linked order once the item is linked to one.' })}
          >
            <input
              type="date"
              className={INPUT_CLASS}
              value={draft.expected_delivery_date ?? ''}
              onChange={(e) => set('expected_delivery_date', e.target.value || null)}
            />
          </Field>
          <Field label={t('delivery_model.ui.ofi.enquiry_date', { defaultValue: 'Enquiry sent on' })} hint={registerHint}>
            <input
              type="date"
              className={INPUT_CLASS}
              disabled={fromRegister}
              data-testid="ofi-enquiry-date"
              value={draft.enquiry_date ?? ''}
              onChange={(e) => set('enquiry_date', e.target.value || null)}
            />
          </Field>
          <Field label={t('delivery_model.ui.ofi.lead_time', { defaultValue: 'Lead time in days' })} hint={registerHint}>
            <input
              type="number"
              min={0}
              max={3650}
              disabled={fromRegister}
              className={INPUT_CLASS}
              value={draft.lead_time_days ?? ''}
              onChange={(e) => set('lead_time_days', e.target.value === '' ? null : Math.max(0, Math.trunc(Number(e.target.value))))}
            />
          </Field>
        </div>
        {item?.plant_item && (
          <div className="space-y-1 rounded-lg border border-border bg-surface-elevated shadow-sm p-3 text-sm" data-testid="ofi-plant-link">
            <p className="text-content-primary">
              {item.plant_item.missing
                ? t('delivery_model.ui.ofi.plant_missing', {
                    defaultValue: 'Linked plant item {{code}} was not found in the plant register',
                    code: item.plant_item.code,
                  })
                : t('delivery_model.ui.ofi.plant_linked', { defaultValue: 'Plant item {{code}}', code: item.plant_item.code })}
            </p>
            {item.latest_order_date && (
              <p className="text-xs text-content-secondary">
                {t('delivery_model.ui.ofi.order_by', { defaultValue: 'Order by {{date}}', date: fmtDate(item.latest_order_date) })}
              </p>
            )}
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input
                type="checkbox"
                data-testid="ofi-plant-unlink"
                checked={draft.plant_item_id === null}
                onChange={(e) => set('plant_item_id', e.target.checked ? null : (item.plant_item_id ?? null))}
              />
              {t('delivery_model.ui.ofi.plant_unlink', {
                defaultValue: 'Remove the link to the plant item. The dates are then kept on this item.',
              })}
            </label>
          </div>
        )}
        {tried && <ProblemList problems={problems} testId="ofi-problems" />}
      </div>
    </WideModal>
  );
}

interface OfiRouteDialogProps {
  projectId: string;
  item: OwnerFurnishedItem;
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

export function OfiRouteDialog({ projectId, item, labels, onClose, onDone }: OfiRouteDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const [route, setRoute] = useState<OfiRoute>(item.procurement_route ?? 'none_yet');
  const [recordId, setRecordId] = useState(item.link?.id ?? '');
  const linkKind = LINKABLE.includes(route) ? (route as OfiLinkKind) : null;

  const save = useMutation({
    mutationFn: () =>
      setOfiRoute(projectId, item.id, {
        procurement_route: route,
        ...(linkKind && recordId ? { link_kind: linkKind, link_id: recordId } : {}),
      }),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  return (
    <WideModal
      open
      onClose={onClose}
      busy={save.isPending}
      size="md"
      testId="ofi-route-dialog"
      title={t('delivery_model.ui.ofi.route_title', { defaultValue: 'How the owner buys it' })}
      subtitle={item.description}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()} data-testid="ofi-route-send">
            {t('delivery_model.ui.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={save.isError ? refusal(save.error) : null} />
        <Field label={t('delivery_model.ui.ofi.route', { defaultValue: 'Procurement route' })}>
          <select
            className={INPUT_CLASS}
            value={route}
            data-testid="ofi-route-select"
            onChange={(e) => {
              setRoute(e.target.value as OfiRoute);
              setRecordId('');
            }}
          >
            {ROUTES.map((r) => (
              <option key={r} value={r}>
                {vocab(labels.t, OFI_ROUTE, r)}
              </option>
            ))}
          </select>
        </Field>
        {linkKind && (
          <>
            <p className="text-xs text-content-secondary">
              {t('delivery_model.ui.ofi.route_link_hint', {
                defaultValue: 'Optional: link the record so the expected date and the status follow it.',
              })}
            </p>
            <RecordPicker projectId={projectId} kind={linkKind} value={recordId} onChange={setRecordId} />
          </>
        )}
      </div>
    </WideModal>
  );
}

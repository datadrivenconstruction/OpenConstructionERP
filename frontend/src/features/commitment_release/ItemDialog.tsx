// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Adding or editing a commitment item: what the project intends to commit,
// how much, of which type, and by when the decision is needed. The type and
// the amount decide who approves, so the type is fixed once a release was
// requested and the dialog says so instead of offering a select that the
// server would refuse.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';
import { WideModal } from '@/shared/ui/WideModal';

import { itemVerdict, type Verdict } from './access';
import { createItem, updateItem, type CommitmentItem, type CommitmentMatrix } from './api';
import { FIELD_CLASS, Field, RefusalBox, reasonText, refusalText } from './CommitmentBits';
import { useReferences } from './hooks';
import { PLANNED_SOURCE, codeName, vocab, type LabelContext } from './labels';
import { areaOptions, gateOptions, plantItemOptions, withCurrent } from './references';
import { ITEM_PROBLEM, changedItemInput, draftOfItem, itemProblems, toItemInput, type ItemDraft } from './rules';

export interface ItemDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  matrix: CommitmentMatrix;
  /** The item to edit, or null to add one. */
  item: CommitmentItem | null;
  /**
   * Whether the viewer may name the owner: the project's manage flag for a
   * new item, the item's own field flag for an existing one. Null means yes.
   */
  ownerVerdict: Verdict;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onSaved: (item: CommitmentItem) => void;
}

export function ItemDialog({
  open,
  onClose,
  projectId,
  matrix,
  item,
  ownerVerdict,
  labels,
  personName,
  onSaved,
}: ItemDialogProps) {
  const { t } = useTranslation();
  const mode = item ? 'edit' : 'create';
  const [draft, setDraft] = useState<ItemDraft>(() => draftOfItem(item, matrix.base_currency));
  const [tried, setTried] = useState(false);

  const typeFixed = !!item && item.status !== 'planned';
  // A planned amount read from a budget line, a cost line or a position is
  // set where that record lives; this dialog only types an estimate.
  const amountEditable = draft.plannedSource === 'manual';
  const set = (patch: Partial<ItemDraft>) => setDraft((d) => ({ ...d, ...patch }));

  // The gate and the area are the project's own governance rows. What a
  // readiness gate reads may only change while the item is planned, and by a
  // manager: the server says so with its own flag for these fields.
  const refsQ = useReferences(projectId, open);
  const gateVerdict = item ? itemVerdict(item, 'edit_gate_fields') : null;
  const gates = withCurrent(gateOptions(refsQ.data, labels), draft.gateCode, labels);
  const areas = withCurrent(areaOptions(refsQ.data, labels), draft.areaCode, labels);
  // Offered only where the server says the project has a plant register to choose from.
  const plantAvailable = !!refsQ.data?.plant_items?.available;
  const plantItems = plantItemOptions(
    refsQ.data,
    labels,
    item?.plant_item_id ? { id: item.plant_item_id, code: item.plant_item_code ?? null } : null,
  );
  const tiedToGate = !!draft.gateCode || !!draft.areaCode;
  // On a project that does not use gates a stored gate or area is kept as it is: shown, never edited, never checked.
  const gatesOff = refsQ.data?.gates_in_use === false;
  // A stored gate without its area cannot be repaired there, so it does not stop the item from being saved.
  const problems = itemProblems(draft, mode).filter((p) => !(gatesOff && p === 'gate_needs_area'));

  const save = useMutation({
    mutationFn: () => {
      return item
        ? updateItem(projectId, item.id, changedItemInput(draft, item))
        : createItem(projectId, toItemInput(draft, mode));
    },
    onSuccess: (saved) => {
      onSaved(saved);
      onClose();
    },
  });

  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="item-dialog"
      title={
        item
          ? t('commitment.item_form.edit_title', { defaultValue: 'Edit commitment item' })
          : t('commitment.item_form.add_title', { defaultValue: 'Add commitment item' })
      }
      subtitle={t('commitment.item_form.subtitle', {
        defaultValue: 'One line for one thing the project will commit money to: a works package, an order, a design appointment.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {tried && problems.length > 0 && (
            <ul className="mr-auto space-y-0.5 text-xs text-semantic-error" data-testid="item-problems">
              {problems.map((p) => (
                <li key={p} data-problem={p}>
                  {t(ITEM_PROBLEM[p][0], { defaultValue: ITEM_PROBLEM[p][1] })}
                </li>
              ))}
            </ul>
          )}
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('commitment.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={submit} data-testid="item-save">
            {item
              ? t('commitment.item_form.save', { defaultValue: 'Save item' })
              : t('commitment.item_form.add', { defaultValue: 'Add item' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {save.isError && <RefusalBox message={refusalText(t, save.error)} />}

        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
          <Field id="item-code" label={t('commitment.item_form.code', { defaultValue: 'Code' })} required={!item}>
            <input
              id="item-code"
              className={FIELD_CLASS}
              value={draft.code}
              disabled={!!item}
              onChange={(e) => set({ code: e.target.value })}
            />
          </Field>
          <Field id="item-title" label={t('commitment.item_form.title', { defaultValue: 'What is committed' })} required>
            <input
              id="item-title"
              className={FIELD_CLASS}
              value={draft.title}
              onChange={(e) => set({ title: e.target.value })}
            />
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            id="item-type"
            label={t('commitment.grid.type', { defaultValue: 'Type' })}
            hint={
              typeFixed
                ? t('commitment.item_form.type_fixed', {
                    defaultValue: 'The type cannot change once a release was requested.',
                  })
                : t('commitment.item_form.type_hint', {
                    defaultValue: 'With the amount, the type decides which tier approves.',
                  })
            }
            required
          >
            <select
              id="item-type"
              className={FIELD_CLASS}
              value={draft.commitmentType}
              disabled={typeFixed}
              onChange={(e) => set({ commitmentType: e.target.value })}
            >
              <option value="">{t('commitment.item_form.choose_type', { defaultValue: 'Choose a type' })}</option>
              {matrix.commitment_types.map((ct) => (
                <option key={ct.code} value={ct.code}>
                  {codeName(labels, 'type', ct.code, ct.name)}
                </option>
              ))}
            </select>
          </Field>
          <Field
            id="item-owner"
            label={t('commitment.item_form.owner', { defaultValue: 'Owner' })}
            hint={
              ownerVerdict
                ? reasonText(t, ownerVerdict)
                : t('commitment.item_form.owner_hint', {
                    defaultValue:
                      'The owner cannot approve releases of this item. Naming somebody else, or changing the owner later, needs a project manager.',
                  })
            }
          >
            {ownerVerdict ? (
              // The picker is not offered where the server would refuse the choice.
              <input
                id="item-owner"
                className={FIELD_CLASS}
                disabled
                data-testid="item-owner-locked"
                data-reason={ownerVerdict}
                value={
                  item
                    ? personName(item.owner_user_id) ?? t('commitment.unknown_person', { defaultValue: 'Project member' })
                    : t('commitment.item_form.owner_self', { defaultValue: 'You, as the person adding the item' })
                }
                readOnly
              />
            ) : (
              <ProjectPeopleSelect
                id="item-owner"
                projectId={projectId}
                value={draft.ownerUserId}
                displayValue={personName(draft.ownerUserId) ?? undefined}
                onChange={(userId) => set({ ownerUserId: userId })}
                placeholder={t('commitment.item_form.owner_placeholder', { defaultValue: 'Who looks after this item' })}
              />
            )}
          </Field>
        </div>

        {amountEditable ? (
          <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Field
              id="item-amount"
              label={t('commitment.item_form.planned_amount', { defaultValue: 'Planned amount (estimate)' })}
              required
            >
              <input
                id="item-amount"
                inputMode="decimal"
                autoComplete="off"
                className={FIELD_CLASS}
                value={draft.plannedAmount}
                onChange={(e) => set({ plannedAmount: e.target.value })}
              />
            </Field>
            <Field id="item-currency" label={t('commitment.release.currency', { defaultValue: 'Currency' })} required>
              <input
                id="item-currency"
                maxLength={3}
                className={FIELD_CLASS}
                value={draft.currency}
                onChange={(e) => set({ currency: e.target.value.toUpperCase() })}
              />
            </Field>
          </div>
        ) : (
          <p className="rounded-md bg-surface-secondary p-3 text-sm text-content-secondary" data-testid="item-amount-derived">
            {t('commitment.item_form.amount_derived', {
              defaultValue: 'The planned amount is read from: {{source}}. Change it there.',
              source: vocab(t, PLANNED_SOURCE, draft.plannedSource),
            })}
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <Field
            id="item-decision-date"
            label={t('commitment.grid.latest_decision_date', { defaultValue: 'Latest decision date' })}
            hint={t('commitment.item_form.decision_date_hint', {
              defaultValue: 'The day the release has to be decided so the work or delivery starts on time.',
            })}
          >
            <input
              id="item-decision-date"
              type="date"
              className={FIELD_CLASS}
              value={draft.latestDecisionDate}
              onChange={(e) => set({ latestDecisionDate: e.target.value })}
            />
          </Field>
          <Field
            id="item-lead"
            label={t('commitment.item_form.lead_time', { defaultValue: 'Lead time, days' })}
            hint={
              item?.lead_time_source === 'plant_item'
                ? t('commitment.item_form.lead_time_overridden', {
                    defaultValue:
                      'The lead time in force comes from the linked plant item. The figure typed here applies only without that link.',
                  })
                : undefined
            }
          >
            <input
              id="item-lead"
              inputMode="numeric"
              className={FIELD_CLASS}
              value={draft.leadTimeDays}
              onChange={(e) => set({ leadTimeDays: e.target.value })}
            />
          </Field>
          <Field id="item-buffer" label={t('commitment.item_form.buffer', { defaultValue: 'Decision buffer, days' })}>
            <input
              id="item-buffer"
              inputMode="numeric"
              className={FIELD_CLASS}
              value={draft.decisionBufferDays}
              onChange={(e) => set({ decisionBufferDays: e.target.value })}
            />
          </Field>
        </div>

        {plantAvailable &&
          (plantItems.length > 0 ? (
            <Field
              id="item-plant"
              label={t('commitment.item_form.plant_item', { defaultValue: 'Plant item' })}
              hint={t('commitment.item_form.plant_item_hint', {
                defaultValue:
                  'Choose it when this commitment pays for an item of the plant register. Its lead time and latest order date then set the dates of this item.',
              })}
            >
              <select
                id="item-plant"
                className={FIELD_CLASS}
                value={draft.plantItemId}
                onChange={(e) => set({ plantItemId: e.target.value })}
              >
                <option value="">{t('commitment.item_form.plant_item_none', { defaultValue: 'No plant item' })}</option>
                {plantItems.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <p className="text-sm text-content-tertiary" data-testid="item-plant-empty">
              {t('commitment.item_form.plant_item_empty', {
                defaultValue:
                  'The plant register of this project has no item yet. Once it has, this commitment can be linked to one here.',
              })}
            </p>
          ))}

        {matrix.novelty_flags.length > 0 && (
          <fieldset className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
            <legend className="px-1 text-xs font-semibold text-content-secondary">
              {t('commitment.item_form.flags', { defaultValue: 'Raises the approval tier' })}
            </legend>
            {matrix.novelty_flags.map((flag) => (
              <label key={flag.code} className="mr-4 inline-flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={draft.flags.includes(flag.code)}
                  onChange={() =>
                    set({
                      flags: draft.flags.includes(flag.code)
                        ? draft.flags.filter((f) => f !== flag.code)
                        : [...draft.flags, flag.code],
                    })
                  }
                />
                {codeName(labels, 'flag', flag.code, flag.name)}
              </label>
            ))}
          </fieldset>
        )}

        <fieldset className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="item-gate-fields">
          <legend className="px-1 text-xs font-semibold text-content-secondary">
            {t('commitment.item_form.gate_title', { defaultValue: 'Readiness gate' })}
          </legend>
          {refsQ.isLoading ? (
            <p className="text-sm text-content-tertiary">
              {t('commitment.item_form.gate_loading', { defaultValue: 'Loading the gates of the project' })}
            </p>
          ) : refsQ.isError && !tiedToGate ? (
            <p className="text-sm text-content-secondary" data-testid="item-gate-error">
              {t('commitment.item_form.gate_error', {
                defaultValue: 'The gates of the project could not be read. The item can be saved without a gate and tied to one later.',
              })}
            </p>
          ) : refsQ.data?.gates_in_use === false && !tiedToGate ? (
            <p className="text-sm text-content-secondary" data-testid="item-gates-not-in-use">
              {t('commitment.item_form.gates_not_in_use', {
                defaultValue:
                  'This project does not use gates, so the item is not tied to one. Releases, holds and aborts are decided on the approval tiers as everywhere else.',
              })}
            </p>
          ) : !refsQ.isError && !refsQ.data?.has_model && !tiedToGate ? (
            <p className="text-sm text-content-secondary" data-testid="item-gate-no-model">
              {t('commitment.item_form.gate_no_model', {
                defaultValue:
                  'This project has no phases and gates yet, so there is no gate to tie the item to. Set them up under Project governance first.',
              })}
            </p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="item-gate" label={t('commitment.item_form.gate', { defaultValue: 'Gate' })}>
                  <select
                    id="item-gate"
                    className={FIELD_CLASS}
                    value={draft.gateCode}
                    disabled={!!gateVerdict || gatesOff}
                    onChange={(e) => set({ gateCode: e.target.value })}
                  >
                    <option value="">{t('commitment.item_form.gate_none', { defaultValue: 'No gate' })}</option>
                    {gates.map((g) => (
                      <option key={g.value} value={g.value}>
                        {g.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field id="item-area" label={t('commitment.item_form.area', { defaultValue: 'Management area' })}>
                  <select
                    id="item-area"
                    className={FIELD_CLASS}
                    value={draft.areaCode}
                    disabled={!!gateVerdict || gatesOff}
                    onChange={(e) => set({ areaCode: e.target.value })}
                  >
                    <option value="">{t('commitment.item_form.area_none', { defaultValue: 'No area' })}</option>
                    {areas.map((a) => (
                      <option key={a.value} value={a.value}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <p
                className="mt-2 text-xs text-content-tertiary"
                data-testid={gatesOff ? 'item-gates-off-stored' : gateVerdict ? 'item-gate-locked' : 'item-gate-hint'}
              >
                {gatesOff
                  ? t('commitment.item_form.gates_off_stored', {
                      defaultValue:
                        'This project does not use gates. What was stored on this item earlier is shown here and kept as it is: it is not checked and cannot be changed.',
                    })
                  : gateVerdict
                  ? reasonText(t, gateVerdict)
                  : t('commitment.item_form.gate_hint', {
                      defaultValue:
                        'The gate whose readiness check counts this item. A gate asks each management area for its own evidence, so an item with a gate needs its area.',
                    })}
              </p>
            </>
          )}
        </fieldset>

        <Field
          id="item-split"
          label={t('commitment.item_form.split_group', { defaultValue: 'Split group' })}
          hint={t('commitment.item_form.split_group_hint', {
            defaultValue: 'Give the same name to items that are parts of one purchase. Their amounts are added up when the tier is worked out. It cannot change once a release was requested.',
          })}
        >
          <input
            id="item-split"
            className={FIELD_CLASS}
            value={draft.splitGroup}
            onChange={(e) => set({ splitGroup: e.target.value })}
          />
        </Field>
      </div>
    </WideModal>
  );
}

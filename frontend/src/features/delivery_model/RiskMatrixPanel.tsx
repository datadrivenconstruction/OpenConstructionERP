// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Who carries which risk. One row per risk category of the catalogue: the
// party that carries it, on what basis, and whether somebody has confirmed
// it. A row nobody touched shows the usual allocation of the form in grey; an
// edited row is amber until confirmed. Confirmed rows can be sent to the risk
// register so each risk gets an owner there.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { CheckCheck, ListPlus, Pencil, ShieldAlert } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal } from '@/shared/ui/WideModal';
import { getErrorMessage } from '@/shared/lib/api';

import { canEditAllocations, personOnly } from './access';
import {
  confirmAllocations,
  deliveryKeys,
  deliveryViolations,
  putAllocation,
  seedRisks,
  type AllocationInput,
  type AllocationItem,
  type AllocationMatrix,
  type Basis,
  type DeliveryCatalogue,
  type DeliveryModel,
  type Finding,
} from './api';
import { CELL_TONE, Field, FindingList, INPUT_CLASS, ProblemList, ReasonedButton, ReviewMark, ServerRefusal, ToneBadge } from './DeliveryBits';
import { ExportButtons } from './ExportButtons';
import { useRefusalText, useRefusalToast } from './hooks';
import { BASIS, catalogueSentence, catalogueText, formName, partyNamer, vocab, type KeyText, type LabelContext } from './labels';
import { SHARED_BASES, SHARED_PARTY, allocationProblems, cellState, matrixSummary, shownAllocation, toAllocationInput, type CellState } from './rules';

const BASES: Basis[] = ['contract', 'insurance', 'shared_pain_gain', 'statute', 'ground_baseline'];

const CELL_STATE: Record<CellState, KeyText> = {
  empty: ['delivery_model.ui.matrix.state.empty', 'Nobody yet'],
  default: ['delivery_model.ui.matrix.state.default', 'Usual, not confirmed'],
  unconfirmed: ['delivery_model.ui.matrix.state.unconfirmed', 'Changed, not confirmed'],
  confirmed: ['delivery_model.ui.matrix.state.confirmed', 'Confirmed'],
  link_missing: ['delivery_model.ui.matrix.state.link_missing', 'Risk register entry deleted'],
  not_applicable: ['delivery_model.ui.matrix.state.not_applicable', 'Not applicable'],
};

export const MATRIX_KEY_MAPS: Record<string, Record<string, KeyText>> = { CELL_STATE };

type PartyName = (code: string | null | undefined) => string;

/** Who carries a risk: one party, or the sharing parties with their shares in percent. */
export function Carrier({
  party,
  shares,
  partyName,
}: {
  party: string | null;
  shares: Record<string, string>;
  partyName: PartyName;
}) {
  const { t } = useTranslation();
  const entries = Object.entries(shares ?? {});
  if (party === SHARED_PARTY && entries.length > 0) {
    return (
      <ul className="space-y-0.5" data-testid="carrier-shares">
        {entries.map(([code, share]) => (
          <li key={code}>
            {t('delivery_model.ui.matrix.share', { defaultValue: '{{party}}: {{share}} %', party: partyName(code), share })}
          </li>
        ))}
      </ul>
    );
  }
  return <span>{party ? partyName(party) : t('delivery_model.ui.matrix.nobody', { defaultValue: 'Nobody yet' })}</span>;
}

export interface RiskMatrixPanelProps {
  projectId: string;
  model: DeliveryModel;
  matrix: AllocationMatrix;
  catalogue: DeliveryCatalogue | null;
  labels: LabelContext;
  onChanged: () => void;
}

export function RiskMatrixPanel({ projectId, model, matrix, catalogue, labels, onChanged }: RiskMatrixPanelProps) {
  const { t } = useTranslation();
  const onError = useRefusalToast();
  const [editing, setEditing] = useState<AllocationItem | null>(null);
  const [seeding, setSeeding] = useState(false);
  const editV = canEditAllocations(model);
  const partyName = useMemo(() => partyNamer(labels, matrix.parties), [labels, matrix.parties]);
  const summary = useMemo(() => matrixSummary(matrix.items), [matrix.items]);
  const form = catalogue?.forms.find((f) => f.code === matrix.form_code) ?? null;
  const categoryName = (item: Pick<AllocationItem, 'name_key' | 'category_code'>) =>
    catalogueText(labels, { key: item.name_key, code: item.category_code });

  const confirmAll = useMutation({ mutationFn: () => confirmAllocations(projectId), onSuccess: onChanged, onError });
  const confirmOne = useMutation({
    mutationFn: (category: string) => confirmAllocations(projectId, [category]),
    onSuccess: onChanged,
    onError,
  });

  if (matrix.items.length === 0) {
    return (
      <EmptyState
        icon={<ShieldAlert size={28} />}
        title={t('delivery_model.ui.matrix.empty_title', { defaultValue: 'No risk categories' })}
        description={t('delivery_model.ui.matrix.empty_body', {
          defaultValue: 'The catalogue of this project lists no risk categories. Choose another catalogue to allocate risks.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4" data-testid="risk-matrix-panel">
      <div className="flex flex-wrap items-start gap-3">
        {summary.toConfirm > 0 && (
          <ReasonedButton
            verdict={editV}
            icon={<CheckCheck size={14} />}
            loading={confirmAll.isPending}
            onClick={() => confirmAll.mutate()}
            data-testid="confirm-all-button"
            title={t('delivery_model.ui.matrix.confirm_all_hint', {
              defaultValue: 'Rows nobody edited take the usual allocation of the form.',
            })}
          >
            {t('delivery_model.ui.matrix.confirm_all', { defaultValue: 'Confirm all' })}
          </ReasonedButton>
        )}
        {summary.seedable > 0 && (
          <ReasonedButton
            verdict={personOnly(editV)}
            variant={summary.toConfirm > 0 ? 'secondary' : 'primary'}
            icon={<ListPlus size={14} />}
            onClick={() => setSeeding(true)}
            data-testid="seed-risks-button"
          >
            {t('delivery_model.ui.matrix.seed', { defaultValue: 'Add to risk register' })}
          </ReasonedButton>
        )}
        <span className="ml-auto">
          <ExportButtons projectId={projectId} what="matrix" />
        </span>
      </div>

      <p className="text-sm text-content-secondary" data-testid="matrix-summary">
        {matrix.form_code
          ? t('delivery_model.ui.matrix.read_against', {
              defaultValue: 'Read against {{form}}.',
              form: formName(labels, form, matrix.form_code),
            })
          : t('delivery_model.ui.matrix.no_form', {
              defaultValue: 'No form leads the comparison yet, so no usual allocation is shown.',
            })}{' '}
        {t('delivery_model.ui.matrix.progress', {
          defaultValue: '{{confirmed}} of {{total}} risks confirmed.',
          confirmed: summary.confirmed,
          total: summary.total,
        })}
        {summary.errors > 0 && (
          <span className="ml-2 font-medium text-semantic-error" data-testid="matrix-errors">
            {t('delivery_model.ui.matrix.errors', { defaultValue: 'To fix: {{n}}', n: summary.errors })}
          </span>
        )}
      </p>

      <div className="overflow-x-auto rounded-xl border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[720px] text-sm" data-testid="risk-matrix-table">
          <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.matrix.col_risk', { defaultValue: 'Risk' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.matrix.col_carrier', { defaultValue: 'Carried by' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.matrix.col_basis', { defaultValue: 'Basis' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('delivery_model.ui.matrix.col_state', { defaultValue: 'State' })}</th>
              <th scope="col" className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {matrix.items.map((item) => {
              const state = cellState(item);
              const shown = shownAllocation(item);
              const description = catalogueSentence(labels, item.description_key);
              const linked = item.allocation?.risk_item_ids.length ?? 0;
              return (
                <tr
                  key={item.category_code}
                  className="border-t border-border-light align-top"
                  data-testid="risk-row"
                  data-state={state}
                >
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="block font-medium text-content-primary">{categoryName(item)}</span>
                    {description && <span className="block text-xs text-content-tertiary">{description}</span>}
                    <span className="mt-1 block">
                      <FindingList findings={item.findings} testId="risk-findings" />
                    </span>
                  </th>
                  <td className={clsx('px-3 py-2', state === 'default' && 'text-content-tertiary')}>
                    {state === 'not_applicable' ? (
                      <span className="text-content-tertiary">{vocab(labels.t, CELL_STATE, 'not_applicable')}</span>
                    ) : (
                      <Carrier party={shown?.party ?? null} shares={shown?.shares ?? {}} partyName={partyName} />
                    )}
                    {item.allocation?.rationale && (
                      <span className="mt-1 block text-xs text-content-secondary">{item.allocation.rationale}</span>
                    )}
                    {state === 'default' && item.default && (
                      <span className="mt-1 block">
                        <ReviewMark status={item.default.review_status} sourceUrl={item.default.source_url} />
                      </span>
                    )}
                  </td>
                  <td className={clsx('px-3 py-2', state === 'default' && 'text-content-tertiary')}>
                    {shown && state !== 'not_applicable' ? vocab(labels.t, BASIS, shown.basis) : ''}
                  </td>
                  <td className="px-3 py-2">
                    <ToneBadge tone={CELL_TONE[state]} testId="risk-state">
                      {vocab(labels.t, CELL_STATE, state)}
                    </ToneBadge>
                    {linked > 0 && (
                      <span className="mt-1 block text-2xs text-content-tertiary" data-testid="risk-linked">
                        {t('delivery_model.ui.matrix.in_register', { defaultValue: 'In the risk register' })}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {!editV && (
                      <span className="flex justify-end gap-1">
                        {(state === 'default' || state === 'unconfirmed') && (
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={confirmOne.isPending && confirmOne.variables === item.category_code}
                            onClick={() => confirmOne.mutate(item.category_code)}
                            data-testid="confirm-row"
                          >
                            {t('delivery_model.ui.matrix.confirm', { defaultValue: 'Confirm' })}
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Pencil size={13} />}
                          onClick={() => setEditing(item)}
                          data-testid="edit-row"
                          aria-label={t('delivery_model.ui.matrix.edit_of', {
                            defaultValue: 'Change who carries {{risk}}',
                            risk: categoryName(item),
                          })}
                        >
                          {t('delivery_model.ui.edit', { defaultValue: 'Change' })}
                        </Button>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {editV && (
        <p className="text-xs text-content-tertiary" data-testid="matrix-read-only">
          <ReasonedButton verdict={editV} size="sm" variant="ghost">
            {t('delivery_model.ui.edit', { defaultValue: 'Change' })}
          </ReasonedButton>
        </p>
      )}

      {matrix.orphans.length > 0 && (
        <div className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3 text-sm" data-testid="matrix-orphans">
          <p className="font-medium text-content-primary">
            {t('delivery_model.ui.matrix.orphans_title', { defaultValue: 'Allocations without a category' })}
          </p>
          <p className="text-xs text-content-secondary">
            {t('delivery_model.ui.matrix.orphans_body', {
              defaultValue: 'These risks were allocated under an earlier catalogue and have no category in the current one. They no longer count.',
            })}
          </p>
          <ul className="mt-1 list-disc pl-5 text-xs text-content-secondary">
            {matrix.orphans.map((o) => (
              <li key={o.id}>{catalogueText(labels, { code: o.category_code })}</li>
            ))}
          </ul>
        </div>
      )}

      {editing && (
        <AllocationDialog
          projectId={projectId}
          item={editing}
          matrix={matrix}
          labels={labels}
          onClose={() => setEditing(null)}
          onDone={onChanged}
        />
      )}
      {seeding && <SeedRisksDialog projectId={projectId} matrix={matrix} labels={labels} onClose={() => setSeeding(false)} onDone={onChanged} />}
    </div>
  );
}

interface AllocationDialogProps {
  projectId: string;
  item: AllocationItem;
  matrix: AllocationMatrix;
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

function draftOf(item: AllocationItem): AllocationInput {
  const shown = shownAllocation(item);
  return {
    party: shown?.party ?? null,
    basis: shown?.basis ?? 'contract',
    shares: { ...(shown?.shares ?? {}) },
    rationale: item.allocation?.rationale ?? '',
    not_applicable: item.allocation?.not_applicable ?? false,
  };
}

export function AllocationDialog({ projectId, item, matrix, labels, onClose, onDone }: AllocationDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const partyName = useMemo(() => partyNamer(labels, matrix.parties), [labels, matrix.parties]);
  const [draft, setDraft] = useState<AllocationInput>(() => draftOf(item));
  const [tried, setTried] = useState(false);
  const [violations, setViolations] = useState<Finding[]>([]);
  const problems = allocationProblems(draft);
  const name = catalogueText(labels, { key: item.name_key, code: item.category_code });
  const sharers = matrix.parties.filter((p) => p.code !== SHARED_PARTY);
  const usual = item.default;
  const usualRationale = catalogueSentence(labels, usual?.rationale_key);

  const save = useMutation({
    mutationFn: () => putAllocation(projectId, item.category_code, toAllocationInput(draft)),
    onSuccess: () => {
      onDone();
      onClose();
    },
    onError: (err) => setViolations(deliveryViolations(err)),
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
      size="md"
      testId="allocation-dialog"
      title={t('delivery_model.ui.allocation.title', { defaultValue: 'Who carries this risk' })}
      subtitle={name}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} onClick={send} data-testid="allocation-send">
            {t('delivery_model.ui.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={save.isError ? refusal(save.error) : null} />
        <FindingList findings={violations} testId="allocation-violations" />

        {usual && (
          <div className="rounded-lg bg-surface-secondary p-3 text-xs text-content-secondary" data-testid="usual-allocation">
            <p className="flex flex-wrap items-center gap-2 font-medium text-content-primary">
              {t('delivery_model.ui.allocation.usual', { defaultValue: 'Usual for this form' })}
              <ReviewMark status={usual.review_status} sourceUrl={usual.source_url} />
            </p>
            <Carrier party={usual.party} shares={usual.shares ?? {}} partyName={partyName} />
            {usualRationale && <p>{usualRationale}</p>}
            <Button
              size="sm"
              variant="ghost"
              className="mt-1"
              onClick={() =>
                setDraft((d) => ({ ...d, not_applicable: false, party: usual.party, basis: usual.basis, shares: { ...(usual.shares ?? {}) } }))
              }
            >
              {t('delivery_model.ui.allocation.use_usual', { defaultValue: 'Use the usual allocation' })}
            </Button>
          </div>
        )}

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.not_applicable}
            data-testid="allocation-na"
            onChange={(e) => setDraft((d) => ({ ...d, not_applicable: e.target.checked }))}
          />
          {t('delivery_model.ui.allocation.not_applicable', { defaultValue: 'This risk does not apply to the project' })}
        </label>

        {!draft.not_applicable && (
          <>
            <Field label={t('delivery_model.ui.matrix.col_carrier', { defaultValue: 'Carried by' })}>
              <select
                className={INPUT_CLASS}
                data-testid="allocation-party"
                value={draft.party ?? ''}
                onChange={(e) => {
                  const party = e.target.value || null;
                  // A shared risk cannot sit "by contract"; start from the first sharing mechanism.
                  setDraft((d) => ({
                    ...d,
                    party,
                    basis: party === SHARED_PARTY && !SHARED_BASES.includes(d.basis) ? 'shared_pain_gain' : d.basis,
                  }));
                }}
              >
                <option value="">{t('delivery_model.ui.choose', { defaultValue: 'Choose' })}</option>
                {matrix.parties.map((p) => (
                  <option key={p.code} value={p.code}>
                    {partyName(p.code)}
                  </option>
                ))}
              </select>
            </Field>
            {draft.party === SHARED_PARTY && (
              <fieldset className="space-y-1.5" data-testid="allocation-shares">
                <legend className="text-sm font-medium text-content-primary">
                  {t('delivery_model.ui.allocation.shares', { defaultValue: 'Shares in percent, adding up to 100' })}
                </legend>
                {sharers.map((p) => (
                  <label key={p.code} className="flex items-center gap-3 text-sm">
                    <span className="w-1/2 truncate">{partyName(p.code)}</span>
                    <input
                      className={clsx(INPUT_CLASS, 'w-28 tabular-nums')}
                      inputMode="decimal"
                      value={draft.shares[p.code] ?? ''}
                      onChange={(e) => setDraft((d) => ({ ...d, shares: { ...d.shares, [p.code]: e.target.value } }))}
                      aria-label={t('delivery_model.ui.allocation.share_of', { defaultValue: 'Share of {{party}}', party: partyName(p.code) })}
                    />
                  </label>
                ))}
              </fieldset>
            )}
            <Field label={t('delivery_model.ui.matrix.col_basis', { defaultValue: 'Basis' })}>
              <select
                className={INPUT_CLASS}
                value={draft.basis}
                data-testid="allocation-basis"
                onChange={(e) => setDraft((d) => ({ ...d, basis: e.target.value as Basis }))}
              >
                {(draft.party === SHARED_PARTY ? SHARED_BASES : BASES).map((b) => (
                  <option key={b} value={b}>
                    {vocab(labels.t, BASIS, b)}
                  </option>
                ))}
              </select>
            </Field>
          </>
        )}

        <Field
          label={t('delivery_model.ui.allocation.rationale', { defaultValue: 'Reason' })}
          hint={t('delivery_model.ui.allocation.rationale_hint', {
            defaultValue: 'Needed when the risk does not apply or sits with another party than usual.',
          })}
        >
          <textarea
            rows={3}
            className={INPUT_CLASS}
            data-testid="allocation-rationale"
            value={draft.rationale}
            onChange={(e) => setDraft((d) => ({ ...d, rationale: e.target.value }))}
          />
        </Field>

        {tried && <ProblemList problems={problems} testId="allocation-problems" />}
      </div>
    </WideModal>
  );
}

interface SeedRisksDialogProps {
  projectId: string;
  matrix: AllocationMatrix;
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

/** Shows which risk register entries would be created, and creates them only on confirmation. */
export function SeedRisksDialog({ projectId, matrix, labels, onClose, onDone }: SeedRisksDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const partyName = useMemo(() => partyNamer(labels, matrix.parties), [labels, matrix.parties]);
  const previewQ = useQuery({
    queryKey: [...deliveryKeys.allocations(projectId), 'seed-preview'],
    queryFn: () => seedRisks(projectId, { preview: true }).then((page) => page.items),
    gcTime: 0,
  });
  const create = useMutation({
    mutationFn: () => seedRisks(projectId, { preview: false }),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });
  const rows = previewQ.data ?? [];

  return (
    <WideModal
      open
      onClose={onClose}
      busy={create.isPending}
      size="md"
      testId="seed-risks-dialog"
      title={t('delivery_model.ui.seed.title', { defaultValue: 'Add risks to the risk register' })}
      subtitle={t('delivery_model.ui.seed.subtitle', {
        defaultValue: 'One entry per confirmed risk that is not in the register yet. Each entry can then get an owner and a response.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={create.isPending} disabled={rows.length === 0} onClick={() => create.mutate()} data-testid="seed-send">
            {t('delivery_model.ui.seed.send', { defaultValue: 'Create entries' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={create.isError ? refusal(create.error) : previewQ.isError ? getErrorMessage(previewQ.error) : null} />
        {previewQ.isLoading ? (
          <p className="text-sm text-content-tertiary">{t('delivery_model.ui.loading', { defaultValue: 'Loading' })}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-content-secondary" data-testid="seed-nothing">
            {t('delivery_model.ui.seed.nothing', { defaultValue: 'Every confirmed risk is already in the risk register.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border bg-surface-elevated shadow-sm text-sm" data-testid="seed-preview">
            {rows.map((r) => (
              <li key={r.category_code} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="font-medium text-content-primary">{r.title}</span>
                <span className="text-xs text-content-secondary">{partyName(r.party)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </WideModal>
  );
}

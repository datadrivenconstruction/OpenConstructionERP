// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The documents an item counts as committed, and a way to ask what a new
// amount on one of them would do.
//
// A linked document shows the amount it counts with, which can differ from
// the amount on the document, and the row says why. The item view carries
// document ids only, so the names are read from the module that owns each
// kind. A contract line is named with its contract, because a line code
// alone ("1.2") says nothing.
//
// The check sends nothing but a question: the server answers what its guard
// would say if the document carried the new amount, and records nothing.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueries, useQuery } from '@tanstack/react-query';
import { Link2, Scale, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';

import {
  addLink,
  checkDocument,
  commitmentKeys,
  removeLink,
  type CheckResult,
  type CommitmentItem,
  type ItemLink,
  type LinkKind,
} from './api';
import type { Verdict } from './access';
import { Amount, FIELD_CLASS, Field, ReasonedButton, RefusalBox, reasonText, refusalText } from './CommitmentBits';
import { PAGE_SIZE, PICKABLE_KINDS, listContractLines, listDocuments, type ListedKind } from './documents';
import { CHECK_REASON, LINK_KIND, LINK_NOTE, vocab } from './labels';
import { checkOutcome, normalizeAmount, type CheckOutcome } from './rules';

const STALE = 60_000;

interface LinkListProps {
  projectId: string;
  item: CommitmentItem;
  /** Whether the viewer may change the links; null means yes. */
  editVerdict: Verdict;
  onChanged: () => void;
}

/** The names of the item's linked documents, read from the lists of the modules that own them. */
function useLinkNames(projectId: string, links: ItemLink[]): (link: ItemLink) => string | null {
  const { t } = useTranslation();
  const kinds = [...new Set(links.map((l): ListedKind => (l.kind === 'contract_line' ? 'contract' : l.kind)))];
  const contracts = [
    ...new Set(links.filter((l) => l.kind === 'contract_line' && l.contract_id).map((l) => l.contract_id as string)),
  ];
  const lists = useQueries({
    queries: kinds.map((k) => ({
      queryKey: commitmentKeys.documents(projectId, k),
      queryFn: () => listDocuments(projectId, k),
      staleTime: STALE,
    })),
  });
  const lineLists = useQueries({
    queries: contracts.map((c) => ({
      queryKey: commitmentKeys.contractLines(projectId, c),
      queryFn: () => listContractLines(c),
      staleTime: STALE,
    })),
  });
  const names = new Map<string, string>();
  for (const q of lists) for (const d of q.data?.options ?? []) names.set(d.id, d.label);
  const lines = new Map<string, string>();
  for (const q of lineLists) for (const d of q.data ?? []) lines.set(d.id, d.label);

  return (link) => {
    if (link.kind !== 'contract_line') return names.get(link.document_id) ?? null;
    const line = lines.get(link.document_id);
    const contract = link.contract_id ? names.get(link.contract_id) : undefined;
    if (line && contract) {
      return t('commitment.links.line_of_contract', { defaultValue: '{{line}}, contract {{contract}}', line, contract });
    }
    return line ?? null;
  };
}

export function LinkList({ projectId, item, editVerdict, onChanged }: LinkListProps) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState<LinkKind>('contract');
  const [contractId, setContractId] = useState('');
  const [documentId, setDocumentId] = useState('');
  const linkName = useLinkNames(projectId, item.links);
  const isLine = kind === 'contract_line';

  // A line is picked in two steps: its contract first, then the line.
  const listKind: ListedKind = isLine ? 'contract' : kind;
  const optionsQ = useQuery({
    queryKey: commitmentKeys.documents(projectId, listKind),
    queryFn: () => listDocuments(projectId, listKind),
    enabled: adding,
    staleTime: STALE,
  });
  const linesQ = useQuery({
    queryKey: commitmentKeys.contractLines(projectId, contractId),
    queryFn: () => listContractLines(contractId),
    enabled: adding && isLine && !!contractId,
    staleTime: STALE,
  });
  const linked = new Set(item.links.map((l) => l.document_id));
  const listed = optionsQ.data?.options ?? [];
  const documents = isLine ? listed : listed.filter((d) => !linked.has(d.id));
  const lines = (linesQ.data ?? []).filter((d) => !linked.has(d.id));

  const close = () => {
    setAdding(false);
    setContractId('');
    setDocumentId('');
  };
  const add = useMutation({
    mutationFn: () => addLink(projectId, item.id, kind, documentId),
    onSuccess: () => {
      close();
      onChanged();
    },
  });
  const remove = useMutation({
    mutationFn: (linkId: string) => removeLink(projectId, item.id, linkId),
    onSuccess: onChanged,
  });

  return (
    <section data-testid="links">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('commitment.drawer.links', { defaultValue: 'Linked documents' })}
        </h3>
        {!adding && (
          <ReasonedButton
            size="sm"
            variant="secondary"
            icon={<Link2 size={14} />}
            verdict={editVerdict}
            onClick={() => {
              add.reset();
              setAdding(true);
            }}
            data-testid="link-add"
          >
            {t('commitment.links.add', { defaultValue: 'Link a document' })}
          </ReasonedButton>
        )}
      </div>

      {remove.isError && <RefusalBox message={refusalText(t, remove.error)} />}

      {item.links.length === 0 && !adding ? (
        <p className="text-sm text-content-tertiary" data-testid="links-empty">
          {t('commitment.links.empty', {
            defaultValue: 'No document is linked, so nothing counts as committed yet. Link the contract or the purchase order once it exists.',
          })}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {item.links.map((link) => (
            <li
              key={link.link_id}
              data-testid="link-row"
              className="flex flex-wrap items-start gap-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-2.5 text-sm"
            >
              <div className="min-w-0 flex-1">
                <p className="text-content-primary" data-testid="link-name">
                  {linkName(link) ??
                    (link.found
                      ? vocab(t, LINK_KIND, link.kind)
                      : t('commitment.links.not_found', { defaultValue: 'This document no longer exists' }))}
                </p>
                <p className="flex flex-wrap gap-x-3 text-xs text-content-tertiary">
                  <span>{vocab(t, LINK_KIND, link.kind)}</span>
                  {link.closed && <span>{t('commitment.links.closed', { defaultValue: 'Completed' })}</span>}
                </p>
                {link.notes.map((note) => {
                  const entry = LINK_NOTE[note.split(':')[0] ?? ''];
                  return entry ? (
                    <p key={note} className="text-xs text-content-secondary">
                      {t(entry[0], { defaultValue: entry[1] })}
                    </p>
                  ) : null;
                })}
              </div>
              <div className="text-right">
                <p className="font-medium tabular-nums text-content-primary">
                  {link.counts ? (
                    <Amount value={link.counted_amount} currency={link.currency} />
                  ) : (
                    <span className="text-content-tertiary">
                      {t('commitment.links.not_counted', { defaultValue: 'Not counted' })}
                    </span>
                  )}
                </p>
                {link.counts && link.document_amount !== link.counted_amount && (
                  <p className="text-xs text-content-tertiary">
                    {t('commitment.links.document_amount', { defaultValue: 'On the document' })}{' '}
                    <Amount value={link.document_amount} currency={link.currency} />
                  </p>
                )}
              </div>
              {!editVerdict && (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 size={14} />}
                  loading={remove.isPending && remove.variables === link.link_id}
                  aria-label={t('commitment.links.remove', { defaultValue: 'Remove this link' })}
                  onClick={() => remove.mutate(link.link_id)}
                  data-testid="link-remove"
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <div className="mt-2 space-y-2 rounded-lg bg-surface-secondary p-3" data-testid="link-add-form">
          {add.isError && <RefusalBox message={refusalText(t, add.error)} />}
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <select
              aria-label={t('commitment.links.kind', { defaultValue: 'Kind of document' })}
              className={FIELD_CLASS}
              value={kind}
              data-testid="link-kind"
              onChange={(e) => {
                setKind(e.target.value as LinkKind);
                setContractId('');
                setDocumentId('');
              }}
            >
              {PICKABLE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {vocab(t, LINK_KIND, k)}
                </option>
              ))}
            </select>
            <select
              aria-label={
                isLine
                  ? t('commitment.links.contract_of_line', { defaultValue: 'Contract the line belongs to' })
                  : t('commitment.links.document', { defaultValue: 'Document' })
              }
              className={FIELD_CLASS}
              value={isLine ? contractId : documentId}
              disabled={optionsQ.isLoading}
              data-testid="link-document"
              onChange={(e) => {
                if (isLine) {
                  setContractId(e.target.value);
                  setDocumentId('');
                } else {
                  setDocumentId(e.target.value);
                }
              }}
            >
              <option value="">
                {optionsQ.isLoading
                  ? t('commitment.links.loading', { defaultValue: 'Loading documents' })
                  : isLine
                    ? t('commitment.links.choose_contract', { defaultValue: 'Choose the contract' })
                    : t('commitment.links.choose', { defaultValue: 'Choose a document' })}
              </option>
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
          {isLine && contractId && (
            <select
              aria-label={t('commitment.links.line', { defaultValue: 'Contract line' })}
              className={FIELD_CLASS}
              value={documentId}
              disabled={linesQ.isLoading}
              data-testid="link-line"
              onChange={(e) => setDocumentId(e.target.value)}
            >
              <option value="">
                {linesQ.isLoading
                  ? t('commitment.links.loading_lines', { defaultValue: 'Loading the lines of the contract' })
                  : t('commitment.links.choose_line', { defaultValue: 'Choose a line' })}
              </option>
              {lines.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          )}
          {optionsQ.isError && <RefusalBox message={refusalText(t, optionsQ.error)} />}
          {linesQ.isError && <RefusalBox message={refusalText(t, linesQ.error)} />}
          {optionsQ.isSuccess && documents.length === 0 && (
            <p className="text-xs text-content-tertiary" data-testid="link-no-documents">
              {isLine
                ? t('commitment.links.no_contracts', { defaultValue: 'This project has no contract yet.' })
                : t('commitment.links.none_of_kind', {
                    defaultValue: 'This project has no document of this kind that is not linked already.',
                  })}
            </p>
          )}
          {isLine && !!contractId && linesQ.isSuccess && lines.length === 0 && (
            <p className="text-xs text-content-tertiary" data-testid="link-no-lines">
              {t('commitment.links.no_lines', {
                defaultValue: 'This contract has no line that is not linked already. Link the contract itself instead.',
              })}
            </p>
          )}
          {optionsQ.data?.truncated && (
            <p className="text-xs text-content-secondary" data-testid="link-truncated">
              {t('commitment.links.truncated', {
                defaultValue: 'Only the first {{shown}} documents of this kind are listed. One further down cannot be picked here.',
                shown: PAGE_SIZE,
              })}
            </p>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              loading={add.isPending}
              disabled={!documentId}
              onClick={() => add.mutate()}
              data-testid="link-add-send"
            >
              {t('commitment.links.add', { defaultValue: 'Link a document' })}
            </Button>
            <Button size="sm" variant="ghost" onClick={close}>
              {t('commitment.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}

      {item.links.length > 0 && <CheckPanel projectId={projectId} links={item.links} linkName={linkName} />}
    </section>
  );
}

const OUTCOME_TEXT: Record<CheckOutcome, readonly [key: string, english: string]> = {
  fits: ['commitment.check.outcome.fits', 'It would go through: the item stays within its released amount and tolerance.'],
  warn: ['commitment.check.outcome.warn', 'It would go through with a warning that is kept on the record.'],
  block: ['commitment.check.outcome.block', 'It would be refused until a further release is approved.'],
  unchecked: [
    'commitment.check.outcome.unchecked',
    'Nothing would check it: this project does not hold documents against their releases.',
  ],
};

const OUTCOME_CLASS: Record<CheckOutcome, string> = {
  fits: 'border-semantic-success/30 bg-semantic-success-bg',
  warn: 'border-semantic-warning/30 bg-semantic-warning-bg',
  block: 'border-semantic-error/30 bg-semantic-error-bg',
  unchecked: 'border-border-light bg-surface-primary',
};

const CHANGE_KINDS: readonly LinkKind[] = ['change_order', 'variation_order'];

/**
 * "What would happen": a new amount for one linked document, and the answer
 * the guard would give. Reading is enough to ask, so the panel follows no
 * permission flag, and it writes nothing.
 */
function CheckPanel({
  projectId,
  links,
  linkName,
}: {
  projectId: string;
  links: ItemLink[];
  linkName: (link: ItemLink) => string | null;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [linkId, setLinkId] = useState('');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState(links[0]?.currency ?? '');
  const link = links.find((l) => l.link_id === linkId) ?? links[0];
  const check = useMutation({
    mutationFn: (body: Parameters<typeof checkDocument>[1]): Promise<CheckResult> => checkDocument(projectId, body),
  });
  if (!link) return null;

  const usedCurrency = currency.trim().toUpperCase();
  const newAmount = normalizeAmount(amount);
  // A change that its contract already carries adds nothing of its own: the
  // server would answer the same for any amount, so the question is not asked.
  const insideContract = link.notes.some((note) => note.split(':')[0] === 'inside_contract_value');
  const ready = !insideContract && newAmount !== null && /^[A-Z]{3}$/.test(usedCurrency);
  const outcome = check.data ? checkOutcome(check.data) : null;
  const edited = () => {
    if (check.data || check.isError) check.reset();
  };

  if (!open) {
    return (
      <div className="mt-2">
        <Button size="sm" variant="ghost" icon={<Scale size={14} />} onClick={() => setOpen(true)} data-testid="check-open">
          {t('commitment.check.open', { defaultValue: 'What if an amount changes?' })}
        </Button>
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-3 rounded-lg bg-surface-secondary p-3" data-testid="check-panel">
      <div>
        <h4 className="text-sm font-semibold text-content-primary">
          {t('commitment.check.title', { defaultValue: 'What would happen' })}
        </h4>
        <p className="text-xs text-content-secondary">
          {t('commitment.check.intro', {
            defaultValue: 'Try a new amount for a linked document and see what the project would do with it. Nothing is saved.',
          })}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <Field id="check-document" label={t('commitment.links.document', { defaultValue: 'Document' })}>
          <select
            id="check-document"
            className={FIELD_CLASS}
            value={link.link_id}
            onChange={(e) => {
              setLinkId(e.target.value);
              setCurrency(links.find((l) => l.link_id === e.target.value)?.currency ?? '');
              edited();
            }}
          >
            {links.map((l) => (
              <option key={l.link_id} value={l.link_id}>
                {linkName(l) ?? vocab(t, LINK_KIND, l.kind)}
              </option>
            ))}
          </select>
        </Field>
        <Field
          id="check-amount"
          label={
            CHANGE_KINDS.includes(link.kind)
              ? t('commitment.check.amount_of_change', { defaultValue: 'Amount of the change' })
              : t('commitment.check.new_total', { defaultValue: 'New total of the document' })
          }
          required
        >
          <input
            id="check-amount"
            inputMode="decimal"
            autoComplete="off"
            className={FIELD_CLASS}
            value={amount}
            onChange={(e) => {
              setAmount(e.target.value);
              edited();
            }}
          />
        </Field>
        <Field id="check-currency" label={t('commitment.release.currency', { defaultValue: 'Currency' })} required>
          <input
            id="check-currency"
            maxLength={3}
            className={FIELD_CLASS}
            value={currency}
            onChange={(e) => {
              setCurrency(e.target.value.toUpperCase());
              edited();
            }}
          />
        </Field>
      </div>

      {insideContract && (
        <p className="text-sm text-content-secondary" data-testid="check-inside-contract">
          {t('commitment.check.inside_contract', {
            defaultValue:
              'This change is already inside the value of its contract, so it adds nothing of its own. Try a new total on the contract instead.',
          })}
        </p>
      )}

      {check.isError && <RefusalBox message={refusalText(t, check.error)} />}

      {check.data && outcome && (
        <div
          role="status"
          data-testid="check-result"
          data-outcome={outcome}
          className={`space-y-1.5 rounded-md border p-3 text-sm ${OUTCOME_CLASS[outcome]}`}
        >
          <p className="font-medium text-content-primary">
            {t(OUTCOME_TEXT[outcome][0], { defaultValue: OUTCOME_TEXT[outcome][1] })}
          </p>
          {check.data.reasons.map((reason) => {
            const own = CHECK_REASON[reason.code];
            return (
              <div key={reason.code} data-testid="check-reason" data-code={reason.code}>
                <p className="text-content-secondary">
                  {own ? t(own[0], { defaultValue: own[1] }) : reasonText(t, reason.code)}
                </p>
                {reason.would_commit !== undefined && (
                  <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs tabular-nums">
                    <dt className="text-content-tertiary">
                      {t('commitment.check.would_commit', { defaultValue: 'Would be bound' })}
                    </dt>
                    <dd data-testid="check-would-commit">
                      <Amount value={reason.would_commit} currency={reason.currency ?? ''} />
                    </dd>
                    <dt className="text-content-tertiary">{t('commitment.check.released', { defaultValue: 'Released' })}</dt>
                    <dd>
                      <Amount value={reason.released} currency={reason.currency ?? ''} />
                    </dd>
                    <dt className="text-content-tertiary">
                      {t('commitment.check.ceiling', { defaultValue: 'Limit with tolerance' })}
                    </dt>
                    <dd>
                      <Amount value={reason.ceiling} currency={reason.currency ?? ''} />
                    </dd>
                  </dl>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex gap-2">
        <Button
          size="sm"
          variant="secondary"
          loading={check.isPending}
          disabled={!ready}
          onClick={() =>
            check.mutate({
              kind: link.kind,
              document_id: link.document_id,
              new_amount: newAmount ?? '',
              currency: usedCurrency,
            })
          }
          data-testid="check-send"
        >
          {t('commitment.check.send', { defaultValue: 'Check' })}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            check.reset();
            setOpen(false);
          }}
        >
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      </div>
    </div>
  );
}

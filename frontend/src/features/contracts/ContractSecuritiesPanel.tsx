// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ContractSecuritiesPanel — the bonds, guarantees and insurance held against a
// contract, as rows you can add, open and change.
//
// The register was enforced before it was reachable. ContractPerformanceBondRule
// warns when a contract whose terms demand a performance bond has no active
// security row, and the only thing the product showed was the aggregate above
// ("3 active bonds worth 2M"): a number nobody could get to a row of. Every
// instrument had to be filed somewhere else, and the rule pointed at a register
// the user could not open.
//
// Two things the panel is careful about, both commercial rather than cosmetic:
//
//   * Currency is per row. A performance bond is regularly issued by a bank in
//     a different currency from the contract, so the currency travels with the
//     amount and is never inherited silently at display time.
//   * The face value is a Decimal. It is held as the string that came off the
//     wire from first render to submit, so an edit that only changes the expiry
//     date cannot round the amount on its way back.
//
// Expiry is why the register exists at all, so the expiry column carries the
// same red / amber badge ContractExpiryBadge puts on a contract end date, on
// the same 30-day window, rather than a second convention of its own.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import {
  Landmark,
  Plus,
  Trash2,
  Pencil,
  AlertTriangle,
  Clock,
} from 'lucide-react';

import { Badge, Button, ConfirmDialog } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtPercent as fmtPercentInAppLanguage } from '@/shared/lib/formatters';
import {
  listContractSecurities,
  createContractSecurity,
  updateContractSecurity,
  deleteContractSecurity,
  CONTRACT_SECURITY_TYPES,
  CONTRACT_SECURITY_STATUSES,
  type ContractSecurity,
  type ContractSecurityCreate,
  type ContractSecurityUpdate,
} from './api';

/* ── Enum labels ──────────────────────────────────────────────────────── */

// Last-resort English, worded exactly as en.ts words it. Every value is a key,
// so these should never render; they exist because each t() in this tree
// carries a defaultValue.
const TYPE_LABELS: Record<string, string> = {
  performance_bond: 'Performance bond',
  payment_bond: 'Payment bond',
  advance_payment_bond: 'Advance payment bond',
  retention_bond: 'Retention bond',
  parent_company_guarantee: 'Parent company guarantee',
  bank_guarantee: 'Bank guarantee',
  insurance_pl: 'Public liability insurance',
  insurance_car: 'Contractors all risks insurance',
  insurance_pi: 'Professional indemnity insurance',
  other: 'Other',
};

const STATUS_LABELS: Record<string, string> = {
  required: 'Required',
  received: 'Received',
  active: 'Active',
  expired: 'Expired',
  released: 'Released',
  claimed: 'Claimed',
};

function typeLabel(t: TFunction, value: string): string {
  return t(`contracts.security_type.${value}`, {
    defaultValue: TYPE_LABELS[value] ?? value,
  });
}

// Shares the key namespace the coverage panel already reads, so a status reads
// the same word in the summary and in the row it was counted from.
function statusLabel(t: TFunction, value: string): string {
  return t(`contracts.security_status_${value}`, {
    defaultValue: STATUS_LABELS[value] ?? value,
  });
}

function statusTone(
  status: string,
): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  switch (status) {
    case 'active':
      return 'success';
    case 'received':
      return 'blue';
    case 'required':
    case 'expired':
      return 'warning';
    case 'claimed':
      return 'error';
    default:
      return 'neutral';
  }
}

/* ── Expiry ───────────────────────────────────────────────────────────── */

// UTC-day arithmetic on the YYYY-MM-DD string, so a 2 AM page load in Europe
// does not shift the bucket boundary. Deliberately a local copy of the same
// twelve lines ContractExpiryBadge and DeliveryCountdownBadge each hold: what
// has to agree across the three is the window and the colours, and pulling one
// module's private helper into another to save a dozen lines would couple three
// screens to whichever of them happens to be edited next.
function diffDaysUtc(isoYmd: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoYmd);
  if (!m) return null;
  const target = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate(),
  );
  return Math.round((target - today) / 86_400_000);
}

// An instrument that has been handed back or called on is finished, and a red
// badge on it would be reporting history as if it were a deadline. Everything
// else still runs, including a `required` row: a bond the contract demanded,
// with a validity window that has already closed, is exactly the case worth
// shouting about.
const EXPIRY_SILENT = new Set<string>(['released', 'claimed']);

/** Red past the expiry date, amber inside 30 days of it, nothing before that. */
export function SecurityExpiryBadge({
  validTo,
  status,
}: {
  validTo: string | null;
  status: string;
}) {
  const { t } = useTranslation();

  if (!validTo || EXPIRY_SILENT.has(status)) return null;

  const days = diffDaysUtc(validTo);
  if (days === null) return null;

  if (days < 0) {
    return (
      <Badge variant="error" size="sm" dot>
        <AlertTriangle size={10} className="me-1 inline-block" aria-hidden />
        {t('contracts.expired_by', {
          defaultValue: 'Expired {{days}}d',
          days: Math.abs(days),
        })}
      </Badge>
    );
  }
  if (days <= 30) {
    return (
      <Badge variant="warning" size="sm">
        <Clock size={10} className="me-1 inline-block" aria-hidden />
        {t('contracts.expires_in', { defaultValue: 'Expires {{days}}d', days })}
      </Badge>
    );
  }
  return null;
}

/* ── Draft ────────────────────────────────────────────────────────────── */

// Every field is a string, including the two Decimals. The value the user typed
// is the value that goes back, unparsed.
interface Draft {
  security_type: string;
  reference: string;
  provider_name: string;
  amount: string;
  currency: string;
  percent_of_contract: string;
  valid_from: string;
  valid_to: string;
  status: string;
  notes: string;
}

function emptyDraft(currency: string): Draft {
  return {
    security_type: 'performance_bond',
    reference: '',
    provider_name: '',
    amount: '',
    currency,
    percent_of_contract: '',
    valid_from: '',
    valid_to: '',
    status: 'required',
    notes: '',
  };
}

/** The row as typed text, keeping the wire form of both Decimal fields. */
function draftFrom(row: ContractSecurity): Draft {
  return {
    security_type: row.security_type,
    reference: row.reference ?? '',
    provider_name: row.provider_name,
    amount: String(row.amount),
    currency: row.currency,
    percent_of_contract:
      row.percent_of_contract == null ? '' : String(row.percent_of_contract),
    valid_from: row.valid_from ?? '',
    valid_to: row.valid_to ?? '',
    status: row.status,
    notes: row.notes ?? '',
  };
}

/** A non-negative number, or empty. Anything else is a typo, not a value. */
function amountValid(raw: string): boolean {
  if (raw.trim() === '') return true;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0;
}

function percentValid(raw: string): boolean {
  if (raw.trim() === '') return true;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 && n <= 100;
}

/**
 * Two decimals, the way the header's retention percentage is already shown.
 * Display only: the stored Decimal comes back as "10.0000" and reads badly, but
 * the string the form round-trips is untouched by this.
 */
function fmtPercent(v: number | string): string {
  const n = Number(v);
  return Number.isFinite(n) ? fmtPercentInAppLanguage(n, 2) : String(v);
}

/**
 * Exactly the test `MoneyDisplay` applies before it agrees to render: trimmed,
 * three capitals, no case folding. Asked here because the two answers print
 * different things, and the value cell has to know which branch it is on.
 */
function hasUsableCurrency(code: string | null | undefined): boolean {
  return /^[A-Z]{3}$/.test((code ?? '').trim());
}

/* ── Panel ────────────────────────────────────────────────────────────── */

interface ContractSecuritiesPanelProps {
  contractId: string;
  /** The contract's own currency, offered as the default on a new row only. */
  currency: string;
}

export function ContractSecuritiesPanel({
  contractId,
  currency,
}: ContractSecuritiesPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // `new` while adding, the row id while editing one, null when neither.
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(() => emptyDraft(currency));
  const [pendingDelete, setPendingDelete] = useState<ContractSecurity | null>(
    null,
  );

  const rowsQ = useQuery<ContractSecurity[]>({
    queryKey: ['contracts', 'securities', contractId],
    queryFn: () => listContractSecurities(contractId),
  });

  // Soonest expiry first, because that is the question the panel answers.
  // Open-ended instruments have no deadline to sort by and sit underneath.
  const rows = useMemo(() => {
    const list = rowsQ.data ?? [];
    return [...list].sort((a, b) => {
      if (a.valid_to && b.valid_to) return a.valid_to.localeCompare(b.valid_to);
      if (a.valid_to) return -1;
      if (b.valid_to) return 1;
      return 0;
    });
  }, [rowsQ.data]);

  const editingRow = useMemo(
    () => (editing && editing !== 'new'
      ? (rowsQ.data ?? []).find((r) => r.id === editing) ?? null
      : null),
    [editing, rowsQ.data],
  );

  // The service drops nulls before it writes, so a saved date or percentage has
  // no clear operation behind it. Emptying the box in the form would look like
  // it worked and change nothing, so the panel says so instead of pretending.
  const clearedLocked = useMemo(() => {
    if (!editingRow) return false;
    const wasSet = (v: string | number | null) => v != null && String(v) !== '';
    return (
      (wasSet(editingRow.valid_from) && draft.valid_from.trim() === '') ||
      (wasSet(editingRow.valid_to) && draft.valid_to.trim() === '') ||
      (wasSet(editingRow.percent_of_contract) &&
        draft.percent_of_contract.trim() === '') ||
      // Currency is here for a different reason than the rest: the API would
      // accept the empty string, we decline to send it. From the user's side
      // the behaviour is the same, which is what the notice describes.
      (wasSet(editingRow.currency) && draft.currency.trim() === '')
    );
  }, [editingRow, draft]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['contracts', 'securities', contractId] });
    // The aggregate above this panel counts these rows, and the completeness
    // report runs the performance-bond rule over them, so both have to hear
    // about a new bond without a reload.
    qc.invalidateQueries({
      queryKey: ['contracts', 'security-coverage', contractId],
    });
    qc.invalidateQueries({
      queryKey: ['contracts', 'completeness', contractId],
    });
  };

  const closeForm = () => {
    setEditing(null);
    setDraft(emptyDraft(currency));
  };

  const createMut = useMutation({
    mutationFn: () => {
      const body: ContractSecurityCreate = {
        contract_id: contractId,
        security_type: draft.security_type,
        provider_name: draft.provider_name.trim(),
        currency: draft.currency.trim().toUpperCase(),
        status: draft.status,
      };
      if (draft.reference.trim()) body.reference = draft.reference.trim();
      if (draft.amount.trim()) body.amount = draft.amount.trim();
      if (draft.percent_of_contract.trim())
        body.percent_of_contract = draft.percent_of_contract.trim();
      if (draft.valid_from.trim()) body.valid_from = draft.valid_from.trim();
      if (draft.valid_to.trim()) body.valid_to = draft.valid_to.trim();
      if (draft.notes.trim()) body.notes = draft.notes.trim();
      return createContractSecurity(contractId, body);
    },
    onSuccess: () => {
      invalidate();
      closeForm();
      addToast({
        type: 'success',
        title: t('contracts.securities.created', {
          defaultValue: 'Security added',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const updateMut = useMutation({
    mutationFn: (securityId: string) => {
      // Free text goes over as typed, empty included: the schema takes an empty
      // string there and that is the only clear the API offers. The dated and
      // numeric fields are sent only when they hold something, since an empty
      // string fails their format check outright.
      const body: ContractSecurityUpdate = {
        security_type: draft.security_type,
        reference: draft.reference.trim(),
        provider_name: draft.provider_name.trim(),
        status: draft.status,
        notes: draft.notes.trim(),
      };
      // Currency is the exception among the free-text fields. The API would
      // take an empty string and store it, and a stored amount with no code is
      // a figure nobody can act on. An emptied box therefore leaves the saved
      // code standing, and the form says so before the user presses Save.
      if (draft.currency.trim()) {
        body.currency = draft.currency.trim().toUpperCase();
      }
      if (draft.amount.trim()) body.amount = draft.amount.trim();
      if (draft.percent_of_contract.trim())
        body.percent_of_contract = draft.percent_of_contract.trim();
      if (draft.valid_from.trim()) body.valid_from = draft.valid_from.trim();
      if (draft.valid_to.trim()) body.valid_to = draft.valid_to.trim();
      return updateContractSecurity(securityId, body);
    },
    onSuccess: () => {
      invalidate();
      closeForm();
      addToast({
        type: 'success',
        title: t('contracts.securities.updated', {
          defaultValue: 'Security updated',
        }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMut = useMutation({
    mutationFn: (securityId: string) => deleteContractSecurity(securityId),
    onSuccess: () => {
      invalidate();
      setPendingDelete(null);
      addToast({
        type: 'success',
        title: t('contracts.securities.deleted', {
          defaultValue: 'Security removed',
        }),
      });
    },
    onError: (err) => {
      setPendingDelete(null);
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const saving = createMut.isPending || updateMut.isPending;
  const canSave =
    amountValid(draft.amount) && percentValid(draft.percent_of_contract) && !saving;

  const startAdd = () => {
    setDraft(emptyDraft(currency));
    setEditing('new');
  };

  const startEdit = (row: ContractSecurity) => {
    setDraft(draftFrom(row));
    setEditing(row.id);
  };

  const submit = () => {
    if (!canSave) return;
    if (editing === 'new') createMut.mutate();
    else if (editing) updateMut.mutate(editing);
  };

  const field = (key: keyof Draft, value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const inputCls =
    'rounded-md border border-border-light bg-surface-elevated px-2 py-1.5 text-sm';
  const labelCls = 'text-xs text-content-tertiary';

  return (
    <div className="rounded-lg border border-border-light">
      <header className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Landmark size={15} className="text-content-tertiary" />
          <span className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('contracts.securities.title', {
              defaultValue: 'Bonds and guarantees',
            })}
          </span>
        </div>
        {editing === null && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={14} />}
            onClick={startAdd}
          >
            {t('contracts.securities.add', { defaultValue: 'Add security' })}
          </Button>
        )}
      </header>

      <div className="px-4 py-3">
        {rowsQ.isLoading && (
          <p className="text-sm text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        )}

        {!rowsQ.isLoading && rows.length === 0 && (
          <p className="text-sm text-content-tertiary">
            {t('contracts.securities.empty', {
              defaultValue:
                'No bonds, guarantees or insurance recorded. Add the instruments the contract terms call for, and their expiry is tracked from here.',
            })}
          </p>
        )}

        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="text-left py-1">
                    {t('contracts.securities.col_type', {
                      defaultValue: 'Type',
                    })}
                  </th>
                  <th className="text-left py-1">
                    {t('contracts.securities.col_issuer', {
                      defaultValue: 'Issuer',
                    })}
                  </th>
                  <th className="text-left py-1">
                    {t('contracts.securities.col_reference', {
                      defaultValue: 'Reference',
                    })}
                  </th>
                  <th className="text-right py-1">
                    {t('contracts.securities.col_value', {
                      defaultValue: 'Value',
                    })}
                  </th>
                  <th className="text-right py-1">
                    {t('contracts.securities.col_percent', {
                      defaultValue: '% of contract',
                    })}
                  </th>
                  <th className="text-left py-1">
                    {t('contracts.securities.col_valid_from', {
                      defaultValue: 'Valid from',
                    })}
                  </th>
                  <th className="text-left py-1">
                    {t('contracts.securities.col_expiry', {
                      defaultValue: 'Expiry',
                    })}
                  </th>
                  <th className="text-left py-1">
                    {t('contracts.securities.col_status', {
                      defaultValue: 'Status',
                    })}
                  </th>
                  <th className="text-right py-1">
                    <span className="sr-only">
                      {t('common.actions', { defaultValue: 'Actions' })}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-border-light">
                    <td className="py-1.5 pe-2">{typeLabel(t, row.security_type)}</td>
                    <td className="py-1.5 pe-2 text-content-secondary">
                      {row.provider_name || '—'}
                    </td>
                    <td className="py-1.5 pe-2 font-mono text-xs text-content-secondary">
                      {row.reference || '—'}
                    </td>
                    {/* The row's own currency, never the contract's: the two
                        differ often enough that assuming would misstate the
                        cover by the exchange rate. */}
                    <td className="py-1.5 pe-2 text-right font-medium tabular-nums">
                      {hasUsableCurrency(row.currency) ? (
                        <MoneyDisplay
                          amount={row.amount}
                          currency={row.currency}
                          showCode
                        />
                      ) : (
                        /* Without a usable code MoneyDisplay prints an em-dash
                           and drops the number. That is right for a preferences
                           gap and wrong here: the face value is the one thing a
                           bond row exists to state, and the API defaults
                           currency to an empty string, so an imported or seeded
                           instrument lands on this branch as a matter of course.
                           Show the figure as stored and say the code is missing,
                           rather than hiding the amount to punish the gap. */
                        <span
                          title={t('contracts.securities.currency_missing', {
                            defaultValue:
                              'No currency recorded for this instrument, so the figure is shown unqualified.',
                          })}
                        >
                          {row.amount}
                          <span className="ms-1 font-normal text-semantic-warning">
                            {t('contracts.securities.currency_unknown', {
                              defaultValue: '(no currency)',
                            })}
                          </span>
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pe-2 text-right tabular-nums text-content-secondary">
                      {row.percent_of_contract == null
                        ? '—'
                        : fmtPercent(row.percent_of_contract)}
                    </td>
                    <td className="py-1.5 pe-2 text-content-secondary">
                      {row.valid_from ? (
                        <DateDisplay value={row.valid_from} />
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-1.5 pe-2">
                      {row.valid_to ? (
                        <span className="flex flex-wrap items-center gap-1.5">
                          <DateDisplay value={row.valid_to} />
                          <SecurityExpiryBadge
                            validTo={row.valid_to}
                            status={row.status}
                          />
                        </span>
                      ) : (
                        <span className="text-content-tertiary">
                          {t('contracts.securities.no_expiry', {
                            defaultValue: 'Open-ended',
                          })}
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pe-2">
                      <Badge variant={statusTone(row.status)} size="sm" dot>
                        {statusLabel(t, row.status)}
                      </Badge>
                    </td>
                    <td className="py-1.5 text-right whitespace-nowrap">
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Pencil size={14} />}
                        aria-label={t('contracts.securities.edit', {
                          defaultValue: 'Edit security',
                        })}
                        onClick={() => startEdit(row)}
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Trash2 size={14} />}
                        aria-label={t('contracts.securities.remove', {
                          defaultValue: 'Remove security',
                        })}
                        onClick={() => setPendingDelete(row)}
                        disabled={deleteMut.isPending}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {editing !== null && (
          <div className="mt-3 rounded-lg bg-surface-secondary p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {editing === 'new'
                ? t('contracts.securities.form_add_title', {
                    defaultValue: 'New security',
                  })
                : t('contracts.securities.form_edit_title', {
                    defaultValue: 'Edit security',
                  })}
            </p>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_type', {
                    defaultValue: 'Type',
                  })}
                </span>
                <select
                  className={inputCls}
                  value={draft.security_type}
                  onChange={(e) => field('security_type', e.target.value)}
                >
                  {CONTRACT_SECURITY_TYPES.map((ty) => (
                    <option key={ty} value={ty}>
                      {typeLabel(t, ty)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_status', {
                    defaultValue: 'Status',
                  })}
                </span>
                <select
                  className={inputCls}
                  value={draft.status}
                  onChange={(e) => field('status', e.target.value)}
                >
                  {CONTRACT_SECURITY_STATUSES.map((st) => (
                    <option key={st} value={st}>
                      {statusLabel(t, st)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_issuer', {
                    defaultValue: 'Issuer',
                  })}
                </span>
                <input
                  className={inputCls}
                  value={draft.provider_name}
                  onChange={(e) => field('provider_name', e.target.value)}
                  autoComplete="organization"
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_reference', {
                    defaultValue: 'Reference',
                  })}
                </span>
                <input
                  className={inputCls}
                  value={draft.reference}
                  onChange={(e) => field('reference', e.target.value)}
                  maxLength={120}
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_amount', {
                    defaultValue: 'Value',
                  })}
                </span>
                {/* inputMode over type=number: a number input hands back a
                    browser-normalised value, and the point of holding this as
                    text is that the Decimal goes back exactly as typed. */}
                <input
                  className={inputCls}
                  value={draft.amount}
                  onChange={(e) => field('amount', e.target.value)}
                  inputMode="decimal"
                  autoComplete="off"
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_currency', {
                    defaultValue: 'Currency',
                  })}
                </span>
                <input
                  className={`${inputCls} uppercase`}
                  value={draft.currency}
                  onChange={(e) => field('currency', e.target.value)}
                  maxLength={3}
                  autoComplete="off"
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_percent', {
                    defaultValue: '% of contract',
                  })}
                </span>
                <input
                  className={inputCls}
                  value={draft.percent_of_contract}
                  onChange={(e) =>
                    field('percent_of_contract', e.target.value)
                  }
                  inputMode="decimal"
                  autoComplete="off"
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_valid_from', {
                    defaultValue: 'Valid from',
                  })}
                </span>
                <input
                  className={inputCls}
                  type="date"
                  value={draft.valid_from}
                  onChange={(e) => field('valid_from', e.target.value)}
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className={labelCls}>
                  {t('contracts.securities.field_valid_to', {
                    defaultValue: 'Expiry',
                  })}
                </span>
                <input
                  className={inputCls}
                  type="date"
                  value={draft.valid_to}
                  onChange={(e) => field('valid_to', e.target.value)}
                />
              </label>
            </div>

            <label className="mt-2 flex flex-col gap-1">
              <span className={labelCls}>
                {t('contracts.securities.field_notes', {
                  defaultValue: 'Notes',
                })}
              </span>
              <textarea
                className={inputCls}
                rows={2}
                value={draft.notes}
                onChange={(e) => field('notes', e.target.value)}
              />
            </label>

            <p className="mt-2 text-xs text-content-tertiary">
              {t('contracts.securities.currency_hint', {
                defaultValue:
                  'The currency belongs to this instrument, not to the contract. Change it when the bond was issued in another one.',
              })}
            </p>

            {!amountValid(draft.amount) && (
              <p className="mt-1 text-xs text-red-600 dark:text-red-400">
                {t('contracts.securities.amount_invalid', {
                  defaultValue:
                    'Enter the face value as a number, with no currency symbol or thousands separator.',
                })}
              </p>
            )}
            {!percentValid(draft.percent_of_contract) && (
              <p className="mt-1 text-xs text-red-600 dark:text-red-400">
                {t('contracts.securities.percent_invalid', {
                  defaultValue: 'Enter a percentage between 0 and 100.',
                })}
              </p>
            )}
            {clearedLocked && (
              <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                {t('contracts.securities.clear_locked', {
                  defaultValue:
                    'A saved date, percentage or currency cannot be emptied here, only replaced. The stored value is kept for any box left blank.',
                })}
              </p>
            )}

            <div className="mt-3 flex items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={submit}
                disabled={!canSave}
                loading={saving}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
              <Button variant="ghost" size="sm" onClick={closeForm}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('contracts.securities.delete_title', {
          defaultValue: 'Remove this security?',
        })}
        message={t('contracts.securities.delete_message', {
          // The label opens the sentence rather than sitting inside it, so no
          // translation has to be re-cased to fit.
          defaultValue:
            '{{type}} will be removed from the register. The instrument itself is unaffected, only this record of it.',
          type: pendingDelete ? typeLabel(t, pendingDelete.security_type) : '',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        variant="danger"
        loading={deleteMut.isPending}
        onConfirm={() => {
          if (pendingDelete) deleteMut.mutate(pendingDelete.id);
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

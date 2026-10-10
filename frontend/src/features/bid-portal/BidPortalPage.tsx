// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Public price-entry page for an invited subcontractor (`/tendering/bid/:token`).
 *
 * The bidder has no account and no operator to ask, so the page has to read
 * in one pass: what is being tendered and until when, the bill with a price
 * field per line, the running sum in the package currency, a draft button and
 * a submit button that asks once more. After submitting, the same page is a
 * read-only receipt.
 *
 * Nothing on the page comes from the buyer's own pricing: the API hands over
 * text, units and quantities only.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, CheckCircle2, Clock, Lock, AlertTriangle } from 'lucide-react';

import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { sortLanguagesByName } from '@/shared/lib/languageOrder';
import { Button, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { formatCurrency } from '@/shared/lib/money';
import { formatDateValue } from '@/shared/lib/formatters';
import { localizedUnitCode } from '@/shared/lib/unitLabels';
import { parseMoneyInput, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { useNumberLocale } from '@/stores/usePreferencesStore';

import {
  BidPortalError,
  fetchBidPortal,
  saveBidDraft,
  submitBid,
  type BidPortalErrorCode,
  type BidPortalLine,
  type BidPortalView,
} from './api';

type PageState =
  | { kind: 'loading' }
  | { kind: 'error'; code: BidPortalErrorCode }
  | { kind: 'ready'; view: BidPortalView };

/** One typed price: empty, a usable number, or something we cannot accept. */
interface ParsedPrice {
  raw: string;
  value: number | null;
  invalid: boolean;
}

function parsePrice(raw: string): ParsedPrice {
  const text = raw.trim();
  if (!text) return { raw, value: null, invalid: false };
  const value = parseMoneyInput(text);
  if (value === null || value < 0) return { raw, value: null, invalid: true };
  return { raw, value, invalid: false };
}

function quantityOf(line: BidPortalLine): number {
  const n = Number(line.quantity);
  return Number.isFinite(n) ? n : 0;
}

export function BidPortalPage() {
  const { token = '' } = useParams<{ token: string }>();
  const { t, i18n } = useTranslation();
  const numberLocale = useNumberLocale();
  const { confirm, ...confirmProps } = useConfirm();

  const [state, setState] = useState<PageState>({ kind: 'loading' });
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'save' | 'submit' | null>(null);
  const [actionError, setActionError] = useState<BidPortalErrorCode | null>(null);
  const [serverLineErrors, setServerLineErrors] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const adopt = useCallback((view: BidPortalView) => {
    setState({ kind: 'ready', view });
    setInputs({ ...view.draft.unit_prices });
    setNotes(view.draft.notes || '');
    setDirty(false);
    setServerLineErrors({});
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setState({ kind: 'error', code: 'not_found' });
      return;
    }
    fetchBidPortal(token)
      .then((view) => {
        if (!cancelled) adopt(view);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ kind: 'error', code: err instanceof BidPortalError ? err.code : 'unknown' });
      });
    return () => {
      cancelled = true;
    };
  }, [token, adopt]);

  // A bidder who typed prices and closes the tab should be asked first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const view = state.kind === 'ready' ? state.view : null;
  const readOnly = !view || view.state !== 'open';
  const currency = view?.currency ?? '';

  const items = useMemo(() => (view ? view.lines.filter((l) => l.kind === 'item') : []), [view]);
  const parsed = useMemo(() => {
    const out: Record<string, ParsedPrice> = {};
    for (const line of items) out[line.id] = parsePrice(inputs[line.id] ?? '');
    return out;
  }, [items, inputs]);

  const pricedCount = items.filter((l) => parsed[l.id]?.value !== null && parsed[l.id]?.value !== undefined).length;
  const invalidCount = items.filter((l) => parsed[l.id]?.invalid).length;
  const unpricedCount = items.length - pricedCount - invalidCount;
  const sum = items.reduce((acc, l) => acc + (parsed[l.id]?.value ?? 0) * quantityOf(l), 0);

  // A field the bidder edits keeps the canonical form they typed or the
  // server stored; once the bid is in and the field is only read, the price
  // is written the reader's way (52,50 rather than 52.50).
  const priceFormat = useMemo(
    () => new Intl.NumberFormat(numberLocale, { minimumFractionDigits: 2, maximumFractionDigits: 4 }),
    [numberLocale],
  );
  const qtyFormat = useMemo(
    () => new Intl.NumberFormat(numberLocale, { maximumFractionDigits: 3 }),
    [numberLocale],
  );
  const money = (value: number | string) => formatCurrency(value, currency, numberLocale);

  const body = () => {
    const unit_prices: Record<string, string> = {};
    for (const line of items) {
      const raw = (inputs[line.id] ?? '').trim();
      if (raw) unit_prices[line.id] = toDecimalPayloadString(raw, '');
    }
    return { unit_prices, notes, currency };
  };

  const handleFailure = (err: unknown) => {
    if (err instanceof BidPortalError) {
      if (['not_found', 'revoked', 'expired'].includes(err.code)) {
        setState({ kind: 'error', code: err.code });
        return;
      }
      setActionError(err.code);
      setServerLineErrors(Object.fromEntries(err.lineErrors.map((e) => [e.line_id, e.reason])));
      return;
    }
    setActionError('unknown');
  };

  const onSave = async () => {
    setBusy('save');
    setActionError(null);
    try {
      adopt(await saveBidDraft(token, body()));
    } catch (err) {
      handleFailure(err);
    } finally {
      setBusy(null);
    }
  };

  const onSubmit = async () => {
    const ok = await confirm({
      title: t('bid_portal.confirm.title', { defaultValue: 'Submit your bid?' }),
      message:
        t('bid_portal.confirm.sum', { defaultValue: 'Bid sum: {{amount}}.', amount: money(sum) }) +
        ' ' +
        (unpricedCount > 0
          ? t('bid_portal.confirm.unpriced', {
              defaultValue_one: '{{count}} line has no price and will be treated as not offered.',
              defaultValue_other: '{{count}} lines have no price and will be treated as not offered.',
              count: unpricedCount,
            }) + ' '
          : '') +
        t('bid_portal.confirm.final', {
          defaultValue: 'After submitting you can no longer change your prices.',
        }),
      confirmLabel: t('bid_portal.submit', { defaultValue: 'Submit bid' }),
      variant: 'warning',
    });
    if (!ok) return;
    setBusy('submit');
    setActionError(null);
    try {
      adopt(await submitBid(token, body()));
    } catch (err) {
      handleFailure(err);
    } finally {
      setBusy(null);
    }
  };

  if (state.kind === 'loading') {
    return (
      <Shell>
        <p className="py-16 text-center text-sm text-content-tertiary" data-testid="bid-portal-loading">
          {t('bid_portal.loading', { defaultValue: 'Loading the bill...' })}
        </p>
      </Shell>
    );
  }

  if (state.kind === 'error') {
    return (
      <Shell>
        <LinkProblem code={state.code} />
      </Shell>
    );
  }

  const v = state.view;
  const deadlineText = v.deadline ? formatDateValue(v.deadline, { dateStyle: 'medium' }) : '';

  return (
    <Shell>
      <section className="space-y-1">
        {(v.buyer_name || v.project_name) && (
          <p className="flex flex-wrap gap-x-3 text-xs uppercase tracking-wide text-content-tertiary">
            {v.buyer_name && <span>{v.buyer_name}</span>}
            {v.project_name && <span>{v.project_name}</span>}
          </p>
        )}
        <h1 className="text-xl font-semibold text-content-primary" data-testid="bid-portal-title">
          {v.package_name}
        </h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-content-secondary">
          <span>
            {t('bid_portal.for_company', { defaultValue: 'Bid of {{company}}', company: v.bidder_company })}
          </span>
          {deadlineText && (
            <span className="inline-flex items-center gap-1">
              <Clock size={14} aria-hidden />
              {t('bid_portal.deadline', { defaultValue: 'Deadline: {{date}}', date: deadlineText })}
            </span>
          )}
          {currency && (
            <span>{t('bid_portal.currency', { defaultValue: 'Prices in {{currency}}', currency })}</span>
          )}
        </div>
        {v.package_description && (
          <p className="pt-2 text-sm text-content-secondary whitespace-pre-line">{v.package_description}</p>
        )}
      </section>

      {v.state === 'submitted' && (
        <div
          className="mt-4 flex items-start gap-3 rounded-lg border border-semantic-success/40 bg-semantic-success-bg p-4"
          data-testid="bid-portal-receipt"
          role="status"
        >
          <CheckCircle2 className="mt-0.5 shrink-0 text-semantic-success" size={20} aria-hidden />
          <div className="text-sm text-content-primary">
            <p className="font-medium">
              {t('bid_portal.receipt.title', { defaultValue: 'Your bid has been submitted.' })}
            </p>
            <p className="text-content-secondary">
              {t('bid_portal.receipt.detail', {
                defaultValue: 'Submitted {{date}}. Bid sum: {{amount}}. The prices below can no longer be changed.',
                date: v.submitted_at ? formatDateValue(v.submitted_at, { dateStyle: 'medium', timeStyle: 'short' }) : '',
                amount: money(v.bid_amount ?? sum),
              })}
            </p>
          </div>
        </div>
      )}

      {v.state === 'closed' && (
        <div className="mt-4 flex items-start gap-3 rounded-lg border border-border-light bg-surface-secondary p-4" role="status">
          <Lock className="mt-0.5 shrink-0 text-content-tertiary" size={20} aria-hidden />
          <p className="text-sm text-content-secondary">
            {t('bid_portal.closed', {
              defaultValue: 'This tender is closed. Prices can no longer be entered.',
            })}
          </p>
        </div>
      )}

      {!readOnly && (
        <p className="mt-4 text-sm text-content-secondary">
          {t('bid_portal.instructions', {
            defaultValue:
              'Enter a unit price for each line. The line sum and the bid sum update as you type. Save a draft at any time; submit once you are done.',
          })}
        </p>
      )}

      <div className="mt-4 overflow-x-auto rounded-lg border border-border-light bg-surface-primary">
        <table className="w-full min-w-[720px] text-sm" data-testid="bid-portal-table">
          <thead className="bg-surface-secondary text-left text-xs font-medium text-content-tertiary">
            <tr>
              <th scope="col" className="px-3 py-2 w-24">
                {t('bid_portal.col.ordinal', { defaultValue: 'Item no.' })}
              </th>
              <th scope="col" className="px-3 py-2">
                {t('bid_portal.col.description', { defaultValue: 'Description' })}
              </th>
              <th scope="col" className="px-3 py-2 w-16">
                {t('bid_portal.col.unit', { defaultValue: 'Unit' })}
              </th>
              <th scope="col" className="px-3 py-2 w-24 text-right">
                {t('bid_portal.col.quantity', { defaultValue: 'Quantity' })}
              </th>
              <th scope="col" className="px-3 py-2 w-36 text-right">
                {t('bid_portal.col.unit_price', { defaultValue: 'Unit price' })}
              </th>
              <th scope="col" className="px-3 py-2 w-32 text-right">
                {t('bid_portal.col.line_sum', { defaultValue: 'Line sum' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {v.lines.map((line) => {
              if (line.kind === 'section') {
                return (
                  <tr key={line.id} className="border-t border-border-light bg-surface-secondary/60">
                    <td className="px-3 py-2 font-mono text-xs text-content-secondary">{line.ordinal}</td>
                    <td colSpan={5} className="px-3 py-2 font-semibold text-content-primary">
                      {line.short_text}
                    </td>
                  </tr>
                );
              }
              const p = parsed[line.id];
              const lineSum = p?.value !== null && p?.value !== undefined ? p.value * quantityOf(line) : null;
              const serverReason = serverLineErrors[line.id];
              const isOpen = !!expanded[line.id];
              const inputId = `bid-price-${line.id}`;
              return (
                <tr key={line.id} className="border-t border-border-light align-top">
                  <td className="px-3 py-2 font-mono text-xs text-content-secondary">{line.ordinal}</td>
                  <td className="px-3 py-2 text-content-primary">
                    <label htmlFor={inputId} className="block">
                      {line.short_text}
                    </label>
                    {line.long_text && (
                      <>
                        <button
                          type="button"
                          onClick={() => setExpanded((s) => ({ ...s, [line.id]: !isOpen }))}
                          className="mt-1 inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
                          aria-expanded={isOpen}
                        >
                          {isOpen ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}
                          {isOpen
                            ? t('bid_portal.hide_long_text', { defaultValue: 'Hide full text' })
                            : t('bid_portal.show_long_text', { defaultValue: 'Show full text' })}
                        </button>
                        {isOpen && (
                          <p className="mt-1 whitespace-pre-line text-xs text-content-secondary">{line.long_text}</p>
                        )}
                      </>
                    )}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">{localizedUnitCode(line.unit, i18n.language)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                    {qtyFormat.format(quantityOf(line))}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <input
                      id={inputId}
                      type="text"
                      inputMode="decimal"
                      autoComplete="off"
                      value={
                        readOnly && p?.value !== null && p?.value !== undefined
                          ? priceFormat.format(p.value)
                          : (inputs[line.id] ?? '')
                      }
                      disabled={readOnly}
                      onChange={(e) => {
                        const next = e.target.value;
                        setInputs((s) => ({ ...s, [line.id]: next }));
                        setDirty(true);
                      }}
                      aria-invalid={p?.invalid || !!serverReason}
                      data-testid={`bid-price-input-${line.ordinal}`}
                      className={
                        'min-h-11 w-full rounded border px-2 text-right tabular-nums bg-surface-primary ' +
                        'focus:outline-none focus:ring-2 focus:ring-oe-blue disabled:bg-surface-secondary ' +
                        (p?.invalid || serverReason ? 'border-semantic-error' : 'border-border-light')
                      }
                    />
                    {(p?.invalid || serverReason) && (
                      <span className="mt-0.5 block text-2xs text-semantic-error">
                        {t('bid_portal.invalid_price', { defaultValue: 'Enter a number of 0 or more' })}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-content-primary">
                    {lineSum === null ? (
                      <span className="text-content-quaternary">{t('bid_portal.not_priced', { defaultValue: 'not priced' })}</span>
                    ) : (
                      money(lineSum)
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4">
        <label htmlFor="bid-portal-notes" className="block text-sm font-medium text-content-primary">
          {t('bid_portal.notes', { defaultValue: 'Notes for the buyer (optional)' })}
        </label>
        <textarea
          id="bid-portal-notes"
          value={notes}
          disabled={readOnly}
          maxLength={2000}
          rows={3}
          onChange={(e) => {
            setNotes(e.target.value);
            setDirty(true);
          }}
          className="mt-1 w-full rounded border border-border-light bg-surface-primary p-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue disabled:bg-surface-secondary"
        />
      </div>

      <div className="sticky bottom-0 mt-6 -mx-4 border-t border-border-light bg-surface-primary/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <p className="text-xs text-content-tertiary" data-testid="bid-portal-progress">
              {t('bid_portal.progress', {
                defaultValue: '{{priced}} of {{total}} lines priced',
                priced: pricedCount,
                total: items.length,
              })}
            </p>
            <p className="text-lg font-semibold tabular-nums text-content-primary" data-testid="bid-portal-sum">
              {money(sum)}
            </p>
          </div>
          {actionError && (
            <p className="flex items-center gap-1 text-sm text-semantic-error" role="alert" data-testid="bid-portal-action-error">
              <AlertTriangle size={14} aria-hidden />
              <ActionErrorText code={actionError} />
            </p>
          )}
          {!readOnly && (
            <>
              <Button
                variant="secondary"
                onClick={onSave}
                loading={busy === 'save'}
                disabled={busy !== null || invalidCount > 0}
                data-testid="bid-portal-save"
              >
                {t('bid_portal.save_draft', { defaultValue: 'Save draft' })}
              </Button>
              <Button
                variant="primary"
                onClick={onSubmit}
                loading={busy === 'submit'}
                disabled={busy !== null || pricedCount === 0 || invalidCount > 0}
                data-testid="bid-portal-submit"
              >
                {t('bid_portal.submit', { defaultValue: 'Submit bid' })}
              </Button>
            </>
          )}
        </div>
        {!readOnly && v.draft.saved_at && !dirty && (
          <p className="mt-1 text-2xs text-content-tertiary">
            {t('bid_portal.draft_saved', {
              defaultValue: 'Draft saved {{date}}',
              date: formatDateValue(v.draft.saved_at, { dateStyle: 'medium', timeStyle: 'short' }),
            })}
          </p>
        )}
      </div>

      <ConfirmDialog {...confirmProps} />
    </Shell>
  );
}

function ActionErrorText({ code }: { code: BidPortalErrorCode }) {
  const { t } = useTranslation();
  switch (code) {
    case 'invalid_prices':
      return <>{t('bid_portal.error.invalid_prices', { defaultValue: 'Some prices could not be accepted. Check the marked lines.' })}</>;
    case 'nothing_priced':
      return <>{t('bid_portal.error.nothing_priced', { defaultValue: 'Enter at least one price before submitting.' })}</>;
    case 'already_submitted':
      return <>{t('bid_portal.error.already_submitted', { defaultValue: 'This bid was already submitted.' })}</>;
    case 'closed':
      return <>{t('bid_portal.error.closed', { defaultValue: 'The tender is closed.' })}</>;
    case 'currency_mismatch':
      return <>{t('bid_portal.error.currency', { defaultValue: 'The currency of the tender has changed. Reload the page.' })}</>;
    case 'rate_limited':
      return <>{t('bid_portal.error.rate_limited', { defaultValue: 'Too many requests. Wait a minute and try again.' })}</>;
    default:
      return <>{t('bid_portal.error.unknown', { defaultValue: 'Something went wrong. Your entries are still on this page; try again.' })}</>;
  }
}

function LinkProblem({ code }: { code: BidPortalErrorCode }) {
  const { t } = useTranslation();
  const title =
    code === 'expired'
      ? t('bid_portal.link.expired_title', { defaultValue: 'This link has expired' })
      : code === 'revoked'
        ? t('bid_portal.link.revoked_title', { defaultValue: 'This link is no longer valid' })
        : code === 'not_found'
          ? t('bid_portal.link.not_found_title', { defaultValue: 'This link does not work' })
          : t('bid_portal.link.error_title', { defaultValue: 'The bill could not be loaded' });
  const detail =
    code === 'expired'
      ? t('bid_portal.link.expired_detail', {
          defaultValue: 'The deadline for this tender has passed. Contact the company that invited you if you still want to bid.',
        })
      : code === 'revoked'
        ? t('bid_portal.link.revoked_detail', {
            defaultValue: 'The company that invited you replaced or withdrew this link. Use the newest invitation email, or ask them for a new link.',
          })
        : code === 'not_found'
          ? t('bid_portal.link.not_found_detail', {
              defaultValue: 'Check that the whole link from the invitation email was copied, or ask the company that invited you for a new one.',
            })
          : t('bid_portal.link.error_detail', { defaultValue: 'Try again in a moment.' });
  return (
    <div className="mx-auto max-w-lg py-16 text-center" data-testid={`bid-portal-link-${code}`} role="alert">
      <AlertTriangle className="mx-auto text-content-tertiary" size={32} aria-hidden />
      <h1 className="mt-3 text-lg font-semibold text-content-primary">{title}</h1>
      <p className="mt-2 text-sm text-content-secondary">{detail}</p>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { t, i18n } = useTranslation();
  const currentLang =
    SUPPORTED_LANGUAGES.find((l) => i18n.language === l.code)?.code ??
    SUPPORTED_LANGUAGES.find((l) => i18n.language.startsWith(l.code))?.code ??
    'en';
  return (
    <div className="min-h-screen bg-surface-secondary">
      <header className="w-full border-b border-border-light bg-surface-primary">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <span className="text-sm font-medium text-content-primary">
            {t('bid_portal.brand', { defaultValue: 'Price entry' })}
          </span>
          <label className="flex items-center gap-2 text-xs text-content-secondary">
            <span className="sr-only">{t('bid_portal.language', { defaultValue: 'Language' })}</span>
            <select
              value={currentLang}
              onChange={(e) => void i18n.changeLanguage(e.target.value)}
              className="min-h-11 rounded border border-border-light bg-surface-primary px-2 py-1 text-xs font-medium text-content-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue"
              data-testid="bid-portal-locale"
            >
              {sortLanguagesByName(SUPPORTED_LANGUAGES).map((loc) => (
                <option key={loc.code} value={loc.code}>
                  {loc.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}

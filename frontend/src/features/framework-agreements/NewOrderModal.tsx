// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * New call-off order, keyboard first: focus starts in "Find item", Enter adds the highlighted
 * item and moves to its quantity, Ctrl+Enter issues. Rates come priced from the server
 * (period factor, conditions, rounding) and are read-only; the cap check is the server's.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CircleAlert, Info, Trash2 } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { todayLocalISO } from '@/shared/lib/dates';
import { useToastStore } from '@/stores/useToastStore';
import { fwkApi, fwkKeys, type AgreementDetail, type Finding } from './api';
import { CapMeter } from './CapMeter';
import { parsePastedLines } from './status';

interface Props {
  agreement: AgreementDetail;
  canOverride: boolean;
  onClose: () => void;
  onCreated: (orderId: string) => void;
}

interface Line {
  code: string;
  quantity: string;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function FindingList({ findings }: { findings: Finding[] }) {
  if (!findings.length) return null;
  return (
    <ul className="space-y-1.5" aria-live="polite">
      {findings.map((f, i) => {
        const Icon = f.severity === 'error' ? CircleAlert : f.severity === 'warning' ? AlertTriangle : Info;
        const tone =
          f.severity === 'error'
            ? 'text-semantic-error'
            : f.severity === 'warning'
              ? 'text-semantic-warning'
              : 'text-content-secondary';
        return (
          <li key={`${f.code}-${i}`} className="flex items-start gap-2 text-sm">
            <Icon size={14} className={`mt-0.5 shrink-0 ${tone}`} aria-hidden="true" />
            <span>
              <span className="text-content-primary">{f.message}</span>
              {f.suggestion && <span className="block text-xs text-content-tertiary">{f.suggestion}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function NewOrderModal({ agreement, canOverride, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const findRef = useRef<HTMLInputElement>(null);
  const qtyRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const [orderedAt, setOrderedAt] = useState(todayLocalISO());
  const [site, setSite] = useState('');
  const [ownSite, setOwnSite] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [lines, setLines] = useState<Line[]>([]);
  const [find, setFind] = useState('');
  const [cursor, setCursor] = useState(0);
  const [reason, setReason] = useState('');
  const [focusCode, setFocusCode] = useState<string | null>(null);

  const items = useQuery({ queryKey: [...fwkKeys.detail(agreement.id), 'items'], queryFn: () => fwkApi.items(agreement.id) });
  const adjustments = useQuery({
    queryKey: [...fwkKeys.detail(agreement.id), 'adjustments'],
    queryFn: () => fwkApi.adjustments(agreement.id),
  });
  const orders = useQuery({ queryKey: fwkKeys.orders(agreement.id), queryFn: () => fwkApi.orders(agreement.id) });

  const active = useMemo(() => (items.data ?? []).filter((i) => i.is_active), [items.data]);
  const byCode = useMemo(() => new Map(active.map((i) => [i.code, i])), [active]);
  const matches = useMemo(() => {
    const needle = find.trim().toLowerCase();
    if (!needle) return [];
    return active.filter((i) => `${i.code} ${i.description}`.toLowerCase().includes(needle)).slice(0, 8);
  }, [active, find]);
  const conditionTags = useMemo(() => {
    const fromAdj = (adjustments.data ?? []).map((a) => a.condition).filter(Boolean);
    return [...new Set([...fromAdj, ...(agreement.pack.condition_tags ?? [])])];
  }, [adjustments.data, agreement.pack.condition_tags]);
  const sites = useMemo(
    () => [...new Set((orders.data?.items ?? []).map((o) => o.site_label).filter(Boolean))],
    [orders.data],
  );

  const validLines = lines.filter((l) => Number(l.quantity) > 0);
  const request = useDebounced({ ordered_at: orderedAt, tags, lines: validLines }, 250);
  const quote = useQuery({
    queryKey: ['framework-agreements', 'quote', agreement.id, request],
    queryFn: () => fwkApi.quote(agreement.id, request),
    enabled: request.lines.length > 0 && Boolean(request.ordered_at),
    placeholderData: (prev) => prev,
  });

  useEffect(() => {
    if (focusCode && qtyRefs.current[focusCode]) {
      qtyRefs.current[focusCode]!.focus();
      qtyRefs.current[focusCode]!.select();
      setFocusCode(null);
    }
  }, [focusCode, lines]);

  const addItem = (code: string) => {
    setLines((ls) => (ls.some((l) => l.code === code) ? ls : [...ls, { code, quantity: '1' }]));
    setFind('');
    setCursor(0);
    setFocusCode(code);
  };

  const copyLast = async () => {
    const last = (orders.data?.items ?? []).find((o) => o.site_label === site && o.order_status !== 'cancelled');
    if (!last) return;
    const detail = await fwkApi.order(last.id);
    setLines(
      detail.lines
        .filter((l) => l.origin === 'framework_item')
        .map((l) => ({ code: l.code, quantity: l.quantity })),
    );
    setTags(last.tags);
  };

  const q = quote.data;
  const overCap = Boolean(q?.over_cap);
  const policy = agreement.terms.override_policy ?? 'block';
  const needsReason = overCap;
  const reasonOk = reason.trim().length >= 20;
  const blocked = !q || q.blocking || quote.isFetching || validLines.length === 0;
  const canIssue = !blocked && (!needsReason || ((canOverride || policy === 'warn') && reasonOk));

  const save = useMutation({
    mutationFn: (issue: boolean) =>
      fwkApi.createOrder(agreement.id, {
        ordered_at: orderedAt,
        tags,
        lines: validLines,
        site_label: site.trim(),
        own_site_project: ownSite,
        issue,
        override_reason: issue && needsReason ? reason.trim() : undefined,
      }),
    onSuccess: (order) => {
      qc.invalidateQueries({ queryKey: fwkKeys.all });
      onCreated(order.id);
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const priced = new Map((q?.lines ?? []).map((l) => [l.code, l]));
  const headroom = q?.cap.headroom_after ?? q?.cap.headroom_before;

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      title={t('framework.new_order', { defaultValue: 'New order' })}
      subtitle={agreement.title}
      busy={save.isPending}
      initialFocusSelector="#fwk-find-item"
      footer={
        <>
          <Button variant="secondary" disabled={validLines.length === 0 || save.isPending} onClick={() => save.mutate(false)}>
            {t('framework.order.save_draft', { defaultValue: 'Save draft' })}
          </Button>
          <Button variant="primary" disabled={!canIssue} loading={save.isPending} onClick={() => save.mutate(true)}>
            {needsReason
              ? t('framework.cap.override', { defaultValue: 'Issue with override' })
              : t('framework.order.issue', { defaultValue: 'Issue order' })}
          </Button>
        </>
      }
    >
      <div
        className="space-y-4"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && canIssue) {
            e.preventDefault();
            save.mutate(true);
          }
        }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1">
            <span className="oe-label">{t('framework.order.ordered_at', { defaultValue: 'Ordered' })}</span>
            <input type="date" className="oe-input" value={orderedAt} onChange={(e) => setOrderedAt(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 sm:col-span-2">
            <span className="oe-label">{t('framework.order.site', { defaultValue: 'Site' })}</span>
            <input className="oe-input" list="fwk-sites" value={site} onChange={(e) => setSite(e.target.value)} />
            <datalist id="fwk-sites">
              {sites.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="inline-flex items-center gap-1.5">
            <input type="checkbox" checked={ownSite} onChange={(e) => setOwnSite(e.target.checked)} />
            {t('framework.order.own_site_project', { defaultValue: 'Run as its own site project' })}
          </label>
          {site && sites.includes(site) && (
            <button type="button" className="text-oe-blue hover:underline" onClick={copyLast}>
              {t('framework.order.copy_last', { defaultValue: 'Copy last order at this site' })}
            </button>
          )}
          {q?.period_label && (
            <span className="ms-auto text-xs text-content-tertiary">
              {t('framework.order.rate_period', {
                defaultValue: 'Rate period {{label}}, factor {{factor}}',
                label: q.period_label,
                factor: q.factor ?? '1',
              })}
            </span>
          )}
        </div>
        {conditionTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('framework.order.conditions', { defaultValue: 'Conditions' })}>
            <span className="oe-label">{t('framework.order.conditions', { defaultValue: 'Conditions' })}</span>
            {conditionTags.map((tag) => {
              const on = tags.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setTags((ts) => (on ? ts.filter((x) => x !== tag) : [...ts, tag]))}
                  className={`rounded-full border px-3 py-1 text-xs font-medium ${
                    on ? 'border-oe-blue bg-oe-blue/10 text-oe-blue' : 'border-border-light text-content-secondary'
                  }`}
                >
                  {t(`framework.tag.${tag}`, { defaultValue: tag.replace(/_/g, ' ') })}
                </button>
              );
            })}
          </div>
        )}

        <div className="relative">
          <label className="flex flex-col gap-1">
            <span className="oe-label">{t('framework.order.find_item', { defaultValue: 'Find item' })}</span>
            <input
              id="fwk-find-item"
              ref={findRef}
              className="oe-input"
              role="combobox"
              aria-expanded={matches.length > 0}
              aria-controls="fwk-find-list"
              value={find}
              onChange={(e) => {
                setFind(e.target.value);
                setCursor(0);
              }}
              onPaste={(e) => {
                const pasted = parsePastedLines(e.clipboardData.getData('text'));
                if (pasted.length) {
                  e.preventDefault();
                  setLines((ls) => [...ls.filter((l) => !pasted.some((p) => p.code === l.code)), ...pasted]);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  setCursor((c) => Math.min(c + 1, Math.max(matches.length - 1, 0)));
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  setCursor((c) => Math.max(c - 1, 0));
                } else if (e.key === 'Enter' && !e.ctrlKey && matches[cursor]) {
                  e.preventDefault();
                  addItem(matches[cursor]!.code);
                }
              }}
              placeholder={t('framework.order.find_hint', { defaultValue: 'Type a code or words; paste code and quantity rows' })}
            />
          </label>
          {find.trim() && (
            <ul
              id="fwk-find-list"
              role="listbox"
              className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-border-light bg-surface-primary shadow-lg"
            >
              {matches.map((m, i) => (
                <li
                  key={m.id}
                  role="option"
                  aria-selected={i === cursor}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    addItem(m.code);
                  }}
                  className={`flex cursor-pointer items-center gap-3 px-3 py-1.5 text-sm ${i === cursor ? 'bg-surface-secondary' : ''}`}
                >
                  <bdi className="w-24 shrink-0 font-mono text-xs">{m.code}</bdi>
                  <span className="flex-1 truncate">{m.description}</span>
                  <span className="text-xs text-content-tertiary">{m.unit}</span>
                  {m.effective_rate && (
                    <span className="w-24 text-end tabular-nums">
                      <MoneyDisplay amount={m.effective_rate} currency={agreement.currency} />
                    </span>
                  )}
                </li>
              ))}
              <li role="option" aria-selected={false} className="border-t border-border-light px-3 py-1.5 text-xs text-content-tertiary">
                {t('framework.order.not_in_list', { defaultValue: 'Not in the price list: raise it as an extra once the order is issued' })}
              </li>
            </ul>
          )}
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-xs text-content-tertiary">
              <th scope="col" className="py-1.5 text-start font-medium">{t('framework.col.code', { defaultValue: 'Code' })}</th>
              <th scope="col" className="py-1.5 text-start font-medium">{t('framework.col.description', { defaultValue: 'Description' })}</th>
              <th scope="col" className="w-24 py-1.5 text-end font-medium">{t('framework.col.qty', { defaultValue: 'Qty' })}</th>
              <th scope="col" className="w-12 py-1.5 text-start font-medium">{t('framework.col.unit', { defaultValue: 'Unit' })}</th>
              <th scope="col" className="w-28 py-1.5 text-end font-medium">{t('framework.col.rate', { defaultValue: 'Rate' })}</th>
              <th scope="col" className="w-28 py-1.5 text-end font-medium">{t('framework.col.total', { defaultValue: 'Total' })}</th>
              <th scope="col" className="w-8"><span className="sr-only">{t('common.actions', { defaultValue: 'Actions' })}</span></th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const item = byCode.get(l.code);
              const p = priced.get(l.code);
              const build = p?.rate_build as Record<string, string> | undefined;
              return (
                <tr key={l.code} className="border-b border-border-light">
                  <td className="py-1.5"><bdi className="font-mono text-xs">{l.code}</bdi></td>
                  <td className="py-1.5">{item?.description ?? <span className="text-semantic-error">{t('framework.order.unknown_item', { defaultValue: 'Not in the price list' })}</span>}</td>
                  <td className="py-1.5 text-end">
                    <input
                      ref={(el) => {
                        qtyRefs.current[l.code] = el;
                      }}
                      aria-label={t('framework.col.qty', { defaultValue: 'Qty' })}
                      inputMode="decimal"
                      className="oe-input-sm w-20 text-end"
                      value={l.quantity}
                      onChange={(e) => {
                        const v = e.target.value.replace(',', '.');
                        setLines((ls) => ls.map((x) => (x.code === l.code ? { ...x, quantity: v } : x)));
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.ctrlKey) {
                          e.preventDefault();
                          findRef.current?.focus();
                        }
                      }}
                    />
                  </td>
                  <td className="py-1.5 text-content-tertiary">{item?.unit}</td>
                  <td
                    className="py-1.5 text-end tabular-nums"
                    title={
                      build
                        ? t('framework.rate_build.tooltip', {
                            defaultValue: 'Base {{base}} x factor {{factor}} = {{escalated}}; after conditions {{rate}}',
                            base: build.base_rate,
                            factor: build.period_factor,
                            escalated: build.escalated_rate,
                            rate: p?.unit_rate,
                          })
                        : undefined
                    }
                  >
                    {p ? <MoneyDisplay amount={p.unit_rate} currency={agreement.currency} /> : '-'}
                  </td>
                  <td className="py-1.5 text-end tabular-nums">
                    {p ? <MoneyDisplay amount={p.total} currency={agreement.currency} /> : '-'}
                  </td>
                  <td className="py-1.5 text-end">
                    <button
                      type="button"
                      aria-label={t('common.remove', { defaultValue: 'Remove' })}
                      onClick={() => setLines((ls) => ls.filter((x) => x.code !== l.code))}
                      className="rounded p-1 text-content-tertiary hover:text-semantic-error"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {q && (
          <div className="space-y-3 rounded-lg border border-border-light p-3">
            <div className="flex flex-wrap items-center gap-4">
              <span className="text-sm">
                {t('framework.order.net', { defaultValue: 'Net' })}{' '}
                <strong className="tabular-nums"><MoneyDisplay amount={q.net} currency={agreement.currency} /></strong>
              </span>
              {q.cap.cap && (
                <div className="min-w-[220px] flex-1">
                  <CapMeter
                    cap={q.cap.cap}
                    committed={q.cap.total_after ?? '0'}
                    certified={agreement.consumption.certified}
                    threshold_pct={agreement.consumption.threshold_pct}
                    valueText={`${q.cap.pct_after ?? '-'} %`}
                  />
                  {headroom != null && (
                    <span className="text-xs text-content-tertiary">
                      {t('framework.order.headroom_after', { defaultValue: 'Headroom after this order:' })}{' '}
                      <MoneyDisplay amount={headroom} currency={agreement.currency} />
                    </span>
                  )}
                </div>
              )}
            </div>
            <FindingList findings={q.findings} />
            {needsReason && (
              <label className="flex flex-col gap-1">
                <span className="oe-label">
                  {t('framework.cap.override_reason', { defaultValue: 'Reason for exceeding the cap' })}
                </span>
                {canOverride || policy === 'warn' ? (
                  <>
                    <textarea className="oe-input min-h-[64px]" value={reason} onChange={(e) => setReason(e.target.value)} />
                    <span className="text-xs text-content-tertiary">
                      {t('framework.cap.reason_min', { defaultValue: 'At least 20 characters; kept with the order.' })}
                    </span>
                  </>
                ) : (
                  <span className="text-sm text-semantic-error">
                    {t('framework.cap.no_right', {
                      defaultValue: 'Only a user allowed to override the cap can issue this order. Save it as a draft.',
                    })}
                  </span>
                )}
              </label>
            )}
          </div>
        )}
        {quote.isError && <p className="text-sm text-semantic-error">{getErrorMessage(quote.error)}</p>}
      </div>
    </WideModal>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PositionActualsDrawer - what actually happened against one bill position.
//
// Opened from a BOQ position row. The Cost Spine rollup answers the same
// question keyed by cost line and in money alone; this answers it keyed by the
// position, which is the language the estimate is written in, and puts the
// site's own record next to the money.
//
// Three things this panel exists to NOT do:
//
//   1. Draw a zero where nobody has reported. `installed_percent` is null when
//      the crew has never visited the position and that is a different fact
//      from reporting none. It gets no bar and no number, it gets a sentence.
//   2. Clamp an overrun. Committing more than was estimated makes the
//      remaining negative; it is reported signed, under its own label, because
//      a finding that reads as a completed line is worse than no line.
//   3. Add money to quantity. The platform links quantity through
//      `boq_position_id` and money through `cost_line_id`. Both are shown,
//      both are labelled, and nothing is ever summed across them.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Ruler, Wallet, HardHat, Link2Off, Info } from 'lucide-react';

import { SideDrawer, Skeleton } from '@/shared/ui';
import { formatCurrency, currencyFractionDigits, toNum } from '@/shared/lib/money';
import { fmtNumber, fmtPercent } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { costModelApi, type PositionActualsRow } from './api';

export interface PositionActualsDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Project that owns the position; the endpoint is project scoped. */
  projectId: string | null | undefined;
  /** The bill position to inspect; when null the drawer fetches nothing. */
  positionId: string | null;
  /**
   * Ordinal and description already in hand from the grid row, used for the
   * header while the figures load. Only the header: no figure on this panel is
   * ever taken from the grid, they all come back from the endpoint together so
   * they are consistent with each other.
   */
  positionOrdinal?: string;
  positionDescription?: string;
}

/** Quantities are carried to four places server side; keep all four. */
const QTY_DECIMALS = 4;

/**
 * How many decimals a rate string actually carries, ignoring trailing zeros.
 *
 * `estimate_unit_rate` is the one figure the backend deliberately does NOT
 * quantise to the currency minor unit, because a rate of 0.0001 multiplied by
 * a quantity is a real amount and rounding it to 0.00 on the way in destroys
 * it. So the rate is rendered at whatever precision it arrived with, floored
 * at the currency's own minor units so a plain 180 still looks like money.
 */
function rateDecimals(raw: string, currency: string): number {
  const floor = currencyFractionDigits(currency);
  const n = toNum(raw);
  if (n === 0) return floor;
  // Counted from the PARSED value, never from the incoming text. The wire is
  // not always fixed point: Pydantic renders a Decimal with str(), and Python
  // switches to exponent form once the exponent passes -6, so a rate of
  // 0.0000001 arrives as "1E-7" with no '.' in it at all. Counting characters
  // would see zero decimals there, fall back to the currency's two, and print
  // 0.00, which is the exact rounding-away this function exists to prevent.
  const digits = Math.abs(n).toFixed(8).replace(/0+$/, '');
  const fraction = digits.includes('.') ? (digits.split('.')[1] ?? '') : '';
  return Math.min(Math.max(fraction.length, floor), 8);
}

/** One label / value pair. `value` is already formatted by the caller. */
function Row({
  label,
  value,
  emphasize = false,
  tone,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
  tone?: 'warning';
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-sm text-content-secondary">{label}</span>
      <span
        className={[
          'whitespace-nowrap tabular-nums text-sm',
          emphasize ? 'font-semibold' : '',
          tone === 'warning' ? 'text-semantic-warning' : 'text-content-primary',
        ].join(' ')}
      >
        {value}
      </span>
    </div>
  );
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        <span className="text-content-quaternary">{icon}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

/** A quiet explanatory line, used wherever a figure is deliberately absent. */
function Note({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-content-tertiary">{children}</p>;
}

export function PositionActualsDrawer({
  open,
  onClose,
  projectId,
  positionId,
  positionOrdinal,
  positionDescription,
}: PositionActualsDrawerProps) {
  const { t } = useTranslation();

  const { data, isLoading, error } = useQuery({
    queryKey: ['costmodel', 'position-actuals', projectId, positionId],
    queryFn: () => costModelApi.getPositionActuals(projectId as string, positionId as string),
    enabled: open && !!projectId && !!positionId,
    retry: false,
  });

  // One position in, at most one row out. An empty list on a 200 is its own
  // fact: the endpoint drops positions whose BOQ belongs to another project,
  // so "no row" means the position did not resolve here, not "nothing
  // recorded". Those get different sentences.
  const row: PositionActualsRow | null = data?.rows?.[0] ?? null;
  const currency = data?.currency ?? '';

  const money = (v: string) => formatCurrency(v, currency);
  const qty = (v: string) => fmtNumber(v, QTY_DECIMALS);

  // Estimate minus committed arrives signed. Negative is an overrun and gets
  // its own label rather than a minus sign in front of the remaining one: a
  // sign smuggled into a single key cannot be reworded by a translator, and
  // "-1,200 not yet committed" is not a sentence in any language.
  const uncommitted = row ? Number(row.uncommitted_amount) : 0;
  const overOrdered = Number.isFinite(uncommitted) && uncommitted < 0;

  // Null means never reported. Checked against null explicitly, never through
  // a falsy test and never after Number(), because Number(null) is a
  // confident zero and that is exactly the collapse this panel avoids.
  const neverReported = !row || row.installed_percent === null;

  const header = [positionOrdinal, positionDescription].filter(Boolean).join(' ').trim();

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={header || t('costmodel.actuals.title')}
      subtitle={
        <span className="inline-flex items-center gap-1">
          <HardHat size={11} />
          {t('costmodel.actuals.subtitle')}
        </span>
      }
    >
      <div className="space-y-6 p-5">
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton height={28} className="w-full" rounded="md" />
            <Skeleton height={120} className="w-full" rounded="lg" />
            <Skeleton height={160} className="w-full" rounded="lg" />
          </div>
        ) : error ? (
          <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg/30 p-3 text-sm text-semantic-error">
            {getErrorMessage(error)}
          </div>
        ) : !row ? (
          <Note>{t('costmodel.actuals.not_found')}</Note>
        ) : (
          <>
            {/* The project may genuinely have no base currency. The endpoint
                returns "" rather than guessing, so say so rather than letting
                bare numbers pass as amounts in an unnamed unit. */}
            {currency === '' && (
              <div className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary p-3 text-xs text-content-secondary">
                <Info size={14} className="mt-px shrink-0 text-content-tertiary" />
                <span>{t('costmodel.actuals.no_currency')}</span>
              </div>
            )}

            {/* ── The quantity spine ───────────────────────────────── */}
            <Section icon={<Ruler size={14} />} title={t('costmodel.actuals.section_estimate')}>
              <div className="divide-y divide-border-light rounded-lg border border-border-light px-3">
                <Row
                  label={t('costmodel.actuals.estimate_quantity')}
                  value={`${qty(row.estimate_quantity)}${row.unit ? ` ${row.unit}` : ''}`}
                />
                <Row
                  label={t('costmodel.actuals.estimate_unit_rate')}
                  value={formatCurrency(row.estimate_unit_rate, currency, undefined, {
                    maximumFractionDigits: rateDecimals(row.estimate_unit_rate, currency),
                  })}
                />
                <Row
                  label={t('costmodel.actuals.estimate_amount')}
                  value={money(row.estimate_amount)}
                  emphasize
                />
              </div>
            </Section>

            {/* ── The money spine ──────────────────────────────────── */}
            <Section icon={<Wallet size={14} />} title={t('costmodel.actuals.section_money')}>
              {!row.on_cost_spine ? (
                // No cost line, so nothing COULD have been attributed here.
                // A column of zeros would read as "ordered nothing, contracted
                // nothing", which is a claim about the project rather than
                // about the link, and it is the wrong one.
                <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
                  <p className="mb-1 flex items-center gap-2 text-sm font-medium text-content-primary">
                    <Link2Off size={14} className="shrink-0 text-content-tertiary" />
                    {t('costmodel.actuals.off_spine_title')}
                  </p>
                  <p className="text-xs text-content-secondary">
                    {t('costmodel.actuals.off_spine_body')}
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-border-light rounded-lg border border-border-light px-3">
                  {row.cost_line_code && (
                    <Row label={t('costmodel.actuals.cost_line')} value={row.cost_line_code} />
                  )}
                  <Row label={t('costmodel.actuals.budget_planned')} value={money(row.budget_planned)} />
                  <Row label={t('costmodel.actuals.budget_actual')} value={money(row.budget_actual)} />
                  <Row label={t('costmodel.actuals.committed')} value={money(row.committed_amount)} />
                  <Row label={t('costmodel.actuals.contracted')} value={money(row.contracted_amount)} />
                  <Row label={t('costmodel.actuals.claimed')} value={money(row.claimed_amount)} />
                  <Row
                    label={
                      overOrdered
                        ? t('costmodel.actuals.over_ordered')
                        : t('costmodel.actuals.uncommitted')
                    }
                    // Rendered from the signed value as it arrived. Not
                    // abs(), not max(0, x): an overrun that prints as a
                    // finished line is the failure this label exists for.
                    value={money(row.uncommitted_amount)}
                    emphasize
                    tone={overOrdered ? 'warning' : undefined}
                  />
                </div>
              )}
            </Section>

            {/* ── What the site reports ────────────────────────────── */}
            <Section icon={<HardHat size={14} />} title={t('costmodel.actuals.section_site')}>
              <div className="divide-y divide-border-light rounded-lg border border-border-light px-3">
                {neverReported ? (
                  // No bar, no percentage, no derived value. An empty bar at
                  // zero is indistinguishable from a crew reporting no work
                  // done, and installed_amount is a zero the server derived
                  // from the very null being reported here, so it would be
                  // stating the absence twice as if it were a measurement.
                  <div className="py-2">
                    <Row label={t('costmodel.actuals.installed_percent')} value={t('costmodel.actuals.never_reported')} />
                    <Note>{t('costmodel.actuals.never_reported_hint')}</Note>
                  </div>
                ) : (
                  <div className="py-2">
                    <Row
                      label={t('costmodel.actuals.installed_percent')}
                      value={fmtPercent(row.installed_percent, 2)}
                      emphasize
                    />
                    <div className="mb-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
                      {/* The track cannot draw past its own end, so the width
                          is capped while the figure above stays exact. The
                          number is the record; the bar is a hint. */}
                      <div
                        className="h-full rounded-full bg-oe-blue"
                        style={{
                          width: `${Math.max(0, Math.min(100, Number(row.installed_percent)))}%`,
                        }}
                      />
                    </div>
                    <Row
                      label={t('costmodel.actuals.installed_amount')}
                      value={money(row.installed_amount)}
                    />
                  </div>
                )}
                <Row
                  label={t('costmodel.actuals.consumed_quantity')}
                  value={`${qty(row.consumed_quantity)}${row.unit ? ` ${row.unit}` : ''}`}
                />
                <Row
                  label={t('costmodel.actuals.consumed_amount')}
                  value={money(row.consumed_amount)}
                />
              </div>
              {Number(row.consumed_quantity) === 0 && Number(row.consumed_amount) === 0 && (
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('costmodel.actuals.nothing_consumed')}
                </p>
              )}
            </Section>

            {/* Said out loud because the two blocks above sit one under the
                other and look addable. They are not: the quantity reaches this
                position through boq_position_id and the money through
                cost_line_id, and they are only the same item of work, never
                the same measure. */}
            <p className="border-t border-border-light pt-3 text-xs text-content-tertiary">
              {t('costmodel.actuals.money_note')}
            </p>
          </>
        )}
      </div>
    </SideDrawer>
  );
}

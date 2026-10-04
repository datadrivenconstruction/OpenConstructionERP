// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The finance side of the risk-to-contingency link: under a Contingency
 * budget line, what risks have drawn from it, what is left, and a way back to
 * the risk register where the drawdowns are confirmed.
 *
 * Read straight from the line's metadata, which the Budgets table already
 * holds, so the finance page needs no extra request. Renders nothing for any
 * other category.
 */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { fmtCurrency } from '@/shared/lib/formatters';
import { drawnOnBudgetLine, isContingencyCategory, money, type MoneyWire } from './contingency';

export interface ContingencyBudgetNoteProps {
  category: string | null | undefined;
  metadata: Record<string, unknown> | null | undefined;
  revised: MoneyWire | null | undefined;
  original: MoneyWire | null | undefined;
  currency?: string;
}

export function ContingencyBudgetNote({ category, metadata, revised, original, currency }: ContingencyBudgetNoteProps) {
  const { t } = useTranslation();
  if (!isContingencyCategory(category)) return null;
  const { total } = drawnOnBudgetLine(metadata);
  const allocated = money(revised) !== 0 ? money(revised) : money(original);
  const remaining = allocated - total;
  return (
    <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-content-tertiary">
      {total > 0 && (
        <span className="tabular-nums" data-testid="contingency-drawn">
          {t('risk.cont_budget_drawn', {
            defaultValue: 'Drawn for risks {{drawn}}, {{remaining}} left',
            drawn: fmtCurrency(total, currency),
            remaining: fmtCurrency(remaining, currency),
          })}
        </span>
      )}
      <Link to="/risks" className="inline-flex items-center gap-0.5 font-medium text-oe-blue-text hover:underline">
        <ShieldAlert size={11} />
        {t('risk.cont_budget_link', { defaultValue: 'Risk register' })}
      </Link>
    </span>
  );
}

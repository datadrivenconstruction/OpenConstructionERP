// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The finance side of the risk-to-contingency link: under a Contingency
 * budget line, what risks have drawn from it, what is left, and a way back to
 * the risk register where the drawdowns are confirmed.
 *
 * Drawn and left are read straight from the line's metadata, which the
 * Budgets table already holds. The risk-based figure (EMV of the open risks)
 * comes from the register's contingency position; React Query shares that one
 * request across every contingency row. Renders nothing for any other
 * category.
 */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ShieldAlert } from 'lucide-react';
import { fmtCurrency } from '@/shared/lib/formatters';
import {
  allocatedOnBudgetLine,
  contingencyQueryKey,
  drawnOnBudgetLine,
  fetchContingency,
  isContingencyCategory,
  money,
  type MoneyWire,
} from './contingency';

export interface ContingencyBudgetNoteProps {
  /** Project of the line; without it the risk-based figure is not fetched. */
  projectId?: string | null;
  category: string | null | undefined;
  metadata: Record<string, unknown> | null | undefined;
  revised: MoneyWire | null | undefined;
  original: MoneyWire | null | undefined;
  currency?: string;
}

export function ContingencyBudgetNote({
  projectId,
  category,
  metadata,
  revised,
  original,
  currency,
}: ContingencyBudgetNoteProps) {
  const { t } = useTranslation();
  const isContingency = isContingencyCategory(category);
  // Called before the early return so the hook order never changes.
  const position = useQuery({
    queryKey: contingencyQueryKey(projectId ?? ''),
    queryFn: () => fetchContingency(projectId ?? ''),
    enabled: isContingency && !!projectId,
    staleTime: 30_000,
    retry: false,
  });
  if (!isContingency) return null;
  const riskBased = position.data;
  const { total } = drawnOnBudgetLine(metadata);
  const allocated = allocatedOnBudgetLine(revised, original);
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
      {riskBased && (
        <span className="tabular-nums" data-testid="contingency-risk-based">
          {t('risk.cont_budget_risk_based', {
            defaultValue: 'Risk-based {{emv}}',
            emv: fmtCurrency(money(riskBased.emv), riskBased.currency || currency),
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

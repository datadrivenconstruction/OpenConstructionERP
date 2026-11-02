// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Consolidated e-invoice wizard: period -> receipts (eligible pre-selected,
 * excluded listed with the reason) -> review totals -> create. Shown only for
 * a market whose mandate file declares a grouping rule.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge, Button, EmptyState, SkeletonTable } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { createConsolidated, previewConsolidated } from './lifecycleApi';
import { lastMonth } from './lifecycleView';

type WizardStep = 'period' | 'receipts' | 'review';

export function ConsolidatedModal({
  open,
  onClose,
  projectId,
  profileId,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  profileId: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [period, setPeriod] = useState(() => lastMonth(new Date()));
  const [step, setStep] = useState<WizardStep>('period');
  const body = { project_id: projectId, profile_id: profileId, period };

  const preview = useQuery({
    queryKey: ['einvoice-clearance', 'consolidated', projectId, profileId, period],
    queryFn: () => previewConsolidated(body),
    enabled: open && step !== 'period',
  });
  const create = useMutation({
    mutationFn: () => createConsolidated(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['einvoice-clearance'] });
      onClose();
    },
    onError: (err: unknown) =>
      addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) }),
  });

  const plan = preview.data;
  const reason = (code?: string | null) =>
    code === 'over_cap'
      ? t('einvoice.consolidated.reason.overCap', { defaultValue: 'Over the single-sale limit: needs its own e-invoice' })
      : code === 'activity'
        ? t('einvoice.consolidated.reason.activity', { defaultValue: 'Activity may not be consolidated' })
        : t('einvoice.consolidated.reason.other', { defaultValue: 'Not eligible' });

  const footer = (
    <div className="flex justify-between gap-2">
      <Button variant="ghost" onClick={step === 'period' ? onClose : () => setStep(step === 'review' ? 'receipts' : 'period')}>
        {t('common.back', { defaultValue: 'Back' })}
      </Button>
      {step === 'review' ? (
        <Button onClick={() => create.mutate()} disabled={create.isPending || !plan?.count}>
          {t('einvoice.consolidated.create', { defaultValue: 'Create consolidated e-invoice' })}
        </Button>
      ) : (
        <Button onClick={() => setStep(step === 'period' ? 'receipts' : 'review')} disabled={step === 'receipts' && !plan?.count}>
          {t('common.next', { defaultValue: 'Next' })}
        </Button>
      )}
    </div>
  );

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('einvoice.consolidated.title', { defaultValue: 'Consolidated e-invoice' })}
      subtitle={
        plan?.due_date ? (
          <Badge variant="warning">
            {t('einvoice.deadline.submitBy', { defaultValue: 'Submit by {{date}}', date: plan.due_date })}
          </Badge>
        ) : undefined
      }
      footer={footer}
    >
      {step === 'period' && (
        <label className="block text-sm">
          <span className="block mb-1">{t('einvoice.consolidated.period', { defaultValue: 'Period' })}</span>
          <input
            type="month"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-lg border border-border-light bg-surface-primary px-3 py-2"
          />
        </label>
      )}
      {step !== 'period' && preview.isLoading && <SkeletonTable rows={5} />}
      {step === 'receipts' && plan && plan.count === 0 && plan.excluded.length === 0 && (
        <EmptyState title={t('einvoice.consolidated.empty', { defaultValue: 'No B2C receipts in this period.' })} />
      )}
      {step === 'receipts' && plan && (plan.count > 0 || plan.excluded.length > 0) && (
        <div className="space-y-3 text-sm">
          <p>
            {t('einvoice.consolidated.included', {
              defaultValue: 'Receipts included: {{count}}',
              count: plan.count,
            })}
          </p>
          {plan.excluded.length > 0 && (
            <div>
              <p className="font-medium">{t('einvoice.consolidated.excluded', { defaultValue: 'Excluded' })}</p>
              <ul className="list-disc ps-5">
                {plan.excluded.map((r) => (
                  <li key={r.source_id || r.number}>
                    <span dir="ltr">{r.number}</span> · <DateDisplay value={r.date} /> ·{' '}
                    <MoneyDisplay amount={r.gross} currency={plan.currency_code} /> · {reason(r.reason)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {step === 'review' && plan && (
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt>{t('einvoice.consolidated.net', { defaultValue: 'Net' })}</dt>
          <dd><MoneyDisplay amount={plan.net} currency={plan.currency_code} /></dd>
          <dt>{t('einvoice.consolidated.tax', { defaultValue: 'Tax' })}</dt>
          <dd><MoneyDisplay amount={plan.tax} currency={plan.currency_code} /></dd>
          <dt className="font-semibold">{t('common.total', { defaultValue: 'Total' })}</dt>
          <dd className="font-semibold"><MoneyDisplay amount={plan.total} currency={plan.currency_code} /></dd>
        </dl>
      )}
    </WideModal>
  );
}

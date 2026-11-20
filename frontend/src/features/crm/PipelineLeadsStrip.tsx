/**
 * Qualified leads waiting above the pipeline board, one click from a deal.
 * The deal takes the lead's account, the first open stage and the user's
 * currency; a lead with no account opens its drawer so one can be picked.
 */
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowRightCircle } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { convertLead, type Lead } from './api';

export function PipelineLeadsStrip({
  leads,
  onOpenLead,
}: {
  leads: Lead[];
  onOpenLead: (id: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const currency = usePreferencesStore((s) => s.currency);
  const ready = leads.filter((l) => l.status === 'qualified');

  const mut = useMutation({
    mutationFn: (lead: Lead) =>
      convertLead(lead.id, {
        title: `${lead.contact_name} - ${t('crm.opportunity_suffix', { defaultValue: 'opportunity' })}`,
        currency,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crm', 'leads'] });
      qc.invalidateQueries({ queryKey: ['crm', 'opportunities'] });
      addToast({ type: 'success', title: t('crm.lead_converted', { defaultValue: 'Lead converted to a deal' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (ready.length === 0) return null;
  return (
    <Card padding="sm" data-testid="pipeline-leads-strip">
      <p className="oe-overline mb-2">
        {t('crm.strip_title', { defaultValue: 'Qualified leads ready to become deals' })}
      </p>
      <ul className="flex flex-wrap gap-2">
        {ready.map((l) => (
          <li
            key={l.id}
            className="flex items-center gap-2 rounded-lg border border-border-light px-3 py-1.5 text-sm"
          >
            <button type="button" className="font-medium hover:underline" onClick={() => onOpenLead(l.id)}>
              {l.contact_name}
            </button>
            <Button
              variant="secondary"
              size="sm"
              icon={<ArrowRightCircle size={14} />}
              disabled={mut.isPending}
              onClick={() => (l.account_id ? mut.mutate(l) : onOpenLead(l.id))}
            >
              {t('crm.strip_convert', { defaultValue: 'Convert to deal' })}
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

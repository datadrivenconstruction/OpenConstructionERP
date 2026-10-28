// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * AI / heuristic change-order draft modal (TOP-30 #11).
 *
 * Two steps: paste site notes (or an RFI / daily-log excerpt), generate a
 * review-ready draft, then edit and confirm. The draft comes from an AI model
 * when a provider key is configured, otherwise from a deterministic heuristic -
 * either way it is only a suggestion. Following the platform's "AI suggests,
 * human confirms" rule, nothing is created until the user clicks Create, and
 * every figure stays editable first.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Sparkles, AlertTriangle, Wand2 } from 'lucide-react';
import { Button, Badge } from '@/shared/ui';
import { WideModal, WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import { apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { aiDraftChangeOrder, type AIDraftResponse } from './api';

interface ChangeOrder {
  id: string;
}

function ConfidenceMeter({ value }: { value: number }) {
  const tone = value >= 80 ? 'bg-semantic-success' : value >= 50 ? 'bg-semantic-warning' : 'bg-semantic-error';
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-secondary">
        <span className={`block h-full ${tone}`} style={{ width: `${Math.max(4, value)}%` }} />
      </span>
      <span className="text-2xs text-content-tertiary tabular-nums">{value}%</span>
    </span>
  );
}

export function AIDraftModal({
  projectId,
  currency,
  onClose,
  onCreated,
}: {
  projectId: string;
  currency: string;
  onClose: () => void;
  onCreated: (orderId: string) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [sourceKind, setSourceKind] = useState<'free_text' | 'rfi' | 'daily_log'>('free_text');
  const [sourceText, setSourceText] = useState('');
  const [draft, setDraft] = useState<AIDraftResponse | null>(null);
  // Editable copies once a draft exists.
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [cost, setCost] = useState('0');
  const [days, setDays] = useState('0');

  const draftMut = useMutation({
    mutationFn: () =>
      aiDraftChangeOrder({
        project_id: projectId,
        source_kind: sourceKind,
        source_text: sourceText,
        currency,
      }),
    onSuccess: (d) => {
      setDraft(d);
      setTitle(d.title);
      setDescription(d.description);
      setCost(d.cost_impact);
      setDays(String(d.schedule_impact_days));
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const createMut = useMutation({
    mutationFn: () =>
      apiPost<ChangeOrder>('/v1/changeorders/', {
        project_id: projectId,
        title: title.trim(),
        description: description.trim(),
        reason_category: draft?.reason_category || 'client_request',
        schedule_impact_days: Math.max(0, Math.round(Number(days) || 0)),
        cost_impact: cost.trim() || '0',
        metadata: {
          source: draft?.source_kind || sourceKind,
          ai_used: draft?.ai_used ?? false,
          ai_provider: draft?.provider || '',
          ai_confidence: draft?.confidence ?? 0,
        },
      }),
    onSuccess: (order) => {
      queryClient.invalidateQueries({ queryKey: ['changeorders'] });
      queryClient.invalidateQueries({ queryKey: ['changeorders-summary'] });
      addToast({
        type: 'success',
        title: t('changeorders.ai_created', { defaultValue: 'Change order created from draft' }),
      });
      onCreated(order.id);
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('changeorders.ai_draft_title', { defaultValue: 'Draft a change order from notes' })}
      size="lg"
      busy={draftMut.isPending || createMut.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {draft ? (
            <Button
              variant="primary"
              disabled={!title.trim() || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              {createMut.isPending
                ? t('common.creating', { defaultValue: 'Creating...' })
                : t('changeorders.ai_create', { defaultValue: 'Create change order' })}
            </Button>
          ) : (
            <Button
              variant="primary"
              disabled={!sourceText.trim() || draftMut.isPending}
              onClick={() => draftMut.mutate()}
            >
              <Wand2 size={15} className="mr-1.5" />
              {draftMut.isPending
                ? t('changeorders.ai_generating', { defaultValue: 'Generating…' })
                : t('changeorders.ai_generate', { defaultValue: 'Generate draft' })}
            </Button>
          )}
        </>
      }
    >
      {!draft ? (
        <div className="space-y-4">
          <p className="text-sm text-content-secondary">
            {t('changeorders.ai_intro', {
              defaultValue:
                'Paste the site notes, an RFI thread or a daily-diary entry. We will read the obvious scope, cost and schedule signals into a draft you can review and edit before anything is saved.',
            })}
          </p>
          <div>
            <label htmlFor="ai-source-kind" className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('changeorders.ai_source', { defaultValue: 'Source' })}
            </label>
            <select
              id="ai-source-kind"
              value={sourceKind}
              onChange={(e) => setSourceKind(e.target.value as typeof sourceKind)}
              className={fieldCls}
            >
              <option value="free_text">{t('changeorders.ai_src_free', { defaultValue: 'Free text / site notes' })}</option>
              <option value="daily_log">{t('changeorders.ai_src_log', { defaultValue: 'Daily diary entry' })}</option>
              <option value="rfi">{t('changeorders.ai_src_rfi', { defaultValue: 'RFI thread' })}</option>
            </select>
          </div>
          <div>
            <label htmlFor="ai-source-text" className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('changeorders.ai_text', { defaultValue: 'Notes' })}
            </label>
            <textarea
              id="ai-source-text"
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              rows={7}
              placeholder={t('changeorders.ai_placeholder', {
                defaultValue:
                  'e.g. Extra rock excavation in the north footing. Roughly 3 days delay. Additional material and plant about CAD 15,000.',
              })}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={draft.ai_used ? 'blue' : 'neutral'} size="sm">
              <Sparkles size={12} className="mr-1" />
              {draft.ai_used
                ? t('changeorders.ai_by', { defaultValue: 'Drafted by AI ({{p}})', p: draft.provider })
                : t('changeorders.ai_heuristic', { defaultValue: 'Offline heuristic draft' })}
            </Badge>
            <span className="flex items-center gap-1.5 text-xs text-content-tertiary">
              {t('changeorders.ai_confidence', { defaultValue: 'Confidence' })}
              <ConfidenceMeter value={draft.confidence} />
            </span>
          </div>

          <div className="flex items-start gap-2 rounded-md bg-semantic-warning-bg px-3 py-2">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[#b45309]" />
            <p className="text-xs text-[#b45309]">{draft.note}</p>
          </div>

          <WideModalSection columns={2}>
            <WideModalField label={t('common.title', { defaultValue: 'Title' })} required span={2} htmlFor="ai-title">
              <input id="ai-title" value={title} onChange={(e) => setTitle(e.target.value)} className={fieldCls} />
            </WideModalField>
            <WideModalField label={t('common.description', { defaultValue: 'Description' })} span={2} htmlFor="ai-desc">
              <textarea
                id="ai-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </WideModalField>
            <WideModalField
              label={t('changeorders.cost_impact', { defaultValue: 'Cost impact' }) + (currency ? ` (${currency})` : '')}
              htmlFor="ai-cost"
            >
              <input id="ai-cost" type="number" value={cost} onChange={(e) => setCost(e.target.value)} className={fieldCls} />
            </WideModalField>
            <WideModalField label={t('changeorders.schedule_days', { defaultValue: 'Schedule days' })} htmlFor="ai-days">
              <input id="ai-days" type="number" value={days} onChange={(e) => setDays(e.target.value)} className={fieldCls} />
            </WideModalField>
          </WideModalSection>

          {draft.lines.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('changeorders.ai_lines', { defaultValue: 'Suggested line items' })}
              </p>
              <div className="overflow-hidden rounded-md border border-border-light">
                <table className="w-full text-sm">
                  <tbody>
                    {draft.lines.map((l, i) => (
                      <tr key={i} className="border-b border-border-light last:border-0">
                        <td className="px-3 py-2 text-content-secondary">{l.description}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-content-primary">{l.cost_delta}</td>
                        <td className="px-3 py-2 text-right">
                          <ConfidenceMeter value={l.confidence} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-1.5 text-2xs text-content-tertiary">
                {t('changeorders.ai_lines_note', {
                  defaultValue:
                    'Line items are shown for reference. Add them on the change-order detail page after creating it.',
                })}
              </p>
            </div>
          )}

          <button
            type="button"
            onClick={() => setDraft(null)}
            className="text-xs font-medium text-oe-blue hover:underline"
          >
            {t('changeorders.ai_back', { defaultValue: 'Back to notes' })}
          </button>
        </div>
      )}
    </WideModal>
  );
}

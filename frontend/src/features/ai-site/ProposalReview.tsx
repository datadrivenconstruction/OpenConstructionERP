// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared review list for site-assistant proposals: confidence chip, Accept / Edit / Reject per
 * item, and one confirm button that sends only the accepted items (with their edits). Nothing
 * is written until the person confirms.
 */

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Check, Info, Pencil, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { ConfidenceBadge } from '@/shared/ui/ConfidenceBadge';
import type { ConfirmSelection } from './api';

export function DegradedBanner({ className = '' }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      data-testid="site-ai-degraded-banner"
      className={`flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200 ${className}`}
    >
      <Info size={14} className="mt-0.5 shrink-0" />
      <span>
        {t('site_ai.degraded_banner', {
          defaultValue: 'No AI provider configured: showing rule-based result',
        })}{' '}
        <Link to="/settings?tab=ai" className="underline">
          {t('site_ai.connect_provider', { defaultValue: 'Connect a provider' })}
        </Link>
      </span>
    </div>
  );
}

type Decision = 'pending' | 'accepted' | 'rejected';

export interface ReviewItem {
  id: string;
  confidence: number;
}

export interface ProposalReviewProps<T extends ReviewItem> {
  items: T[];
  degraded: boolean;
  /** Read-only view of one item. */
  renderItem: (item: T) => ReactNode;
  /** Editable view; call `setDraft` with the changed fields (they become `edits`). */
  renderEdit: (item: T, draft: Record<string, unknown>, setDraft: (patch: Record<string, unknown>) => void) => ReactNode;
  /** Server-side result per item after a confirm attempt (error text keeps the item open). */
  errors?: Record<string, string>;
  busy?: boolean;
  onConfirm: (selected: ConfirmSelection[]) => void;
  onRejectAll: () => void;
  /** Fields to fill into an accepted item that has none, e.g. a localized default title. */
  defaultEdits?: (item: T) => Record<string, unknown> | undefined;
  emptyLabel?: string;
}

export function ProposalReview<T extends ReviewItem>({
  items,
  degraded,
  renderItem,
  renderEdit,
  errors,
  busy,
  onConfirm,
  onRejectAll,
  defaultEdits,
  emptyLabel,
}: ProposalReviewProps<T>) {
  const { t } = useTranslation();
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [edits, setEdits] = useState<Record<string, Record<string, unknown>>>({});
  const [editing, setEditing] = useState<string | null>(null);

  const decide = (id: string, d: Decision) => setDecisions((prev) => ({ ...prev, [id]: d }));
  const accepted = items.filter((i) => decisions[i.id] === 'accepted');

  const confirm = () =>
    onConfirm(
      accepted.map((item) => {
        const merged = { ...(defaultEdits?.(item) ?? {}), ...(edits[item.id] ?? {}) };
        return Object.keys(merged).length ? { id: item.id, edits: merged } : { id: item.id };
      }),
    );

  return (
    <div className="flex flex-col gap-3" data-testid="proposal-review">
      {degraded && <DegradedBanner />}
      {items.length === 0 && (
        <p className="py-6 text-center text-sm text-content-tertiary" data-testid="proposal-review-empty">
          {emptyLabel ?? t('site_ai.nothing_proposed', { defaultValue: 'Nothing to propose from the available data.' })}
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {items.map((item) => {
          const d = decisions[item.id] ?? 'pending';
          const err = errors?.[item.id];
          return (
            <li
              key={item.id}
              data-testid={`proposal-item-${item.id}`}
              data-decision={d}
              className={`rounded-lg border p-3 ${
                d === 'accepted'
                  ? 'border-emerald-300 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/20'
                  : d === 'rejected'
                    ? 'border-border-light opacity-60'
                    : 'border-border-light'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1 text-sm">
                  {editing === item.id
                    ? renderEdit(item, edits[item.id] ?? {}, (patch) =>
                        setEdits((prev) => ({ ...prev, [item.id]: { ...(prev[item.id] ?? {}), ...patch } })),
                      )
                    : renderItem(item)}
                </div>
                <ConfidenceBadge score={item.confidence} showScore />
              </div>
              {err && (
                <p role="alert" className="mt-2 text-xs text-semantic-error">
                  {err}
                </p>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={d === 'accepted' ? 'primary' : 'secondary'}
                  icon={<Check size={13} />}
                  onClick={() => {
                    decide(item.id, 'accepted');
                    setEditing(null);
                  }}
                  data-testid={`proposal-accept-${item.id}`}
                >
                  {t('site_ai.accept', { defaultValue: 'Accept' })}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<Pencil size={13} />}
                  onClick={() => {
                    setEditing(editing === item.id ? null : item.id);
                    if (editing !== item.id) decide(item.id, 'accepted');
                  }}
                  data-testid={`proposal-edit-${item.id}`}
                >
                  {editing === item.id
                    ? t('site_ai.done_editing', { defaultValue: 'Done' })
                    : t('site_ai.edit', { defaultValue: 'Edit' })}
                </Button>
                <Button
                  size="sm"
                  variant={d === 'rejected' ? 'primary' : 'ghost'}
                  icon={<X size={13} />}
                  onClick={() => {
                    decide(item.id, 'rejected');
                    setEditing(null);
                  }}
                  data-testid={`proposal-reject-${item.id}`}
                >
                  {t('site_ai.reject', { defaultValue: 'Reject' })}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {items.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border-light pt-3">
          <Button variant="ghost" size="sm" onClick={onRejectAll} disabled={busy} data-testid="proposal-reject-all">
            {t('site_ai.reject_all', { defaultValue: 'Reject all' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={confirm}
            disabled={busy || accepted.length === 0}
            data-testid="proposal-confirm"
          >
            {t('site_ai.confirm_n', { defaultValue: 'Save accepted ({{n}})', n: accepted.length })}
          </Button>
        </div>
      )}
    </div>
  );
}

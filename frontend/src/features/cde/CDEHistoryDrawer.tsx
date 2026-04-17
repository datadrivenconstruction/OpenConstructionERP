import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { X, History, ArrowRight } from 'lucide-react';
import { Badge, DateDisplay } from '@/shared/ui';
import { fetchContainerHistory, type StateTransitionEntry } from './api';

/**
 * Right-side drawer that shows the state-transition audit log for a CDE
 * container (RFC 33 §3.4). Driven by `GET /v1/cde/containers/{id}/history/`.
 */
export function CDEHistoryDrawer({
  containerId,
  containerCode,
  onClose,
}: {
  containerId: string;
  containerCode: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  const { data: history = [], isLoading } = useQuery({
    queryKey: ['cde-history', containerId],
    queryFn: () => fetchContainerHistory(containerId),
  });

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40 animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-label={t('cde.history_title', { defaultValue: 'State transition history' })}
    >
      <div
        className="w-full max-w-md bg-surface-primary border-l border-border shadow-xl flex flex-col animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <History size={18} className="text-oe-blue" />
            <div>
              <h3 className="text-base font-semibold">
                {t('cde.history_title', { defaultValue: 'State transition history' })}
              </h3>
              <p className="text-xs text-content-tertiary mt-0.5 font-mono">
                {containerCode}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-secondary text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-16 animate-pulse rounded-lg bg-surface-secondary"
                />
              ))}
            </div>
          ) : history.length === 0 ? (
            <div className="text-center py-10 text-content-tertiary text-sm">
              <History size={24} className="mx-auto mb-2 opacity-30" />
              <p>
                {t('cde.history_empty', {
                  defaultValue: 'No state transitions yet — promote the container to start the audit trail.',
                })}
              </p>
            </div>
          ) : (
            <ol className="space-y-3">
              {history.map((row) => (
                <HistoryRow key={row.id} row={row} />
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}

function HistoryRow({ row }: { row: StateTransitionEntry }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-lg border border-border bg-surface-secondary/40 p-3 text-sm">
      <div className="flex items-center gap-2 mb-1">
        <Badge variant="neutral" size="sm" className="font-mono">
          {t(`cde.state_${row.from_state}`, { defaultValue: row.from_state })}
        </Badge>
        <ArrowRight size={12} className="text-content-tertiary" />
        <Badge variant="blue" size="sm" className="font-mono">
          {t(`cde.state_${row.to_state}`, { defaultValue: row.to_state })}
        </Badge>
        {row.gate_code && (
          <Badge variant="neutral" size="sm" className="ml-auto font-mono">
            {t('cde.gate_label', { defaultValue: 'Gate {{code}}', code: row.gate_code })}
          </Badge>
        )}
      </div>
      <DateDisplay
        value={row.transitioned_at}
        className="text-xs text-content-tertiary"
      />
      {row.user_role && (
        <p className="text-xs text-content-tertiary mt-1">
          {t('cde.history_by_role', {
            defaultValue: 'By: {{role}}',
            role: row.user_role,
          })}
        </p>
      )}
      {row.reason && (
        <p className="text-xs text-content-secondary mt-2 italic">
          &ldquo;{row.reason}&rdquo;
        </p>
      )}
      {row.signature && (
        <p className="text-xs text-content-tertiary mt-1">
          {t('cde.history_signature', {
            defaultValue: 'Signed: {{signer}}',
            signer: row.signature,
          })}
        </p>
      )}
    </li>
  );
}

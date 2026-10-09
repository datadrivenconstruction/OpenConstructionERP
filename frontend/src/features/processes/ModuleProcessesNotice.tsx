// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Banner for a module page whose feature leans on a background service that is
 * off: it names the service, says what is missing and turns it on in one click
 * (or tells a non-admin whom to ask). Renders nothing while everything the
 * module needs is running, and nothing on a server without the processes API.
 */

import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2, Power } from 'lucide-react';

import { getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { isControllable, isLoading, isUnsupported, ramOf, useEnsureModule, useProcessAction, useProcesses } from './api';
import { formatMb, processName, processOffImpact, useIsProcessAdmin } from './labels';
import { useProcessesUi } from './useProcessesUi';

export function ModuleProcessesNotice({ moduleId, className }: { moduleId: string; className?: string }) {
  const { t } = useTranslation();
  const isAdmin = useIsProcessAdmin();
  useEnsureModule(moduleId);
  const { data, error } = useProcesses();
  const action = useProcessAction();
  const openPanel = useProcessesUi((s) => s.openPanel);
  const addToast = useToastStore((s) => s.addToast);

  const off = (data?.processes ?? []).filter(
    (p) => p.modules.includes(moduleId) && (!p.enabled || p.status === 'error' || isLoading(p)),
  );
  if (off.length === 0 || isUnsupported(error)) return null;

  const starting = off.every((p) => p.enabled && isLoading(p));
  const names = fmtList(off.map((p) => processName(t, p)));
  const mb = off.reduce((s, p) => s + ramOf(p), 0);

  const turnOn = () =>
    off
      .filter((p) => isControllable(p) && (!p.enabled || p.status === 'error'))
      .forEach((p) =>
        action.mutate(
          { id: p.id, action: p.enabled ? 'restart' : 'enable' },
          {
            onError: (err) =>
              addToast({
                type: 'error',
                title: t('processes.action_failed', { defaultValue: 'Could not change {{name}}', name: processName(t, p) }),
                message: getErrorMessage(err),
              }),
          },
        ),
      );

  return (
    <div
      role="status"
      data-testid={`module-processes-notice-${moduleId}`}
      data-state={starting ? 'preparing' : 'off'}
      className={
        (starting
          ? 'flex items-center gap-2 rounded-xl border border-sky-500/25 bg-sky-500/5 px-3 py-2 text-xs '
          : 'flex flex-col gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm sm:flex-row sm:items-center ') +
        (className ?? '')
      }
    >
      <div className="flex min-w-0 flex-1 items-start gap-2">
        {starting ? (
          <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-sky-600" aria-hidden />
        ) : (
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" aria-hidden />
        )}
        <div className="min-w-0">
          <p className="font-medium text-content-primary">
            {starting
              ? t('processes.notice.preparing', {
                  defaultValue: 'Preparing {{names}}. You can keep working, this note clears by itself.',
                  names,
                })
              : t('processes.notice.needs', { defaultValue: 'This feature needs {{names}}. It is off.', names })}
          </p>
          {!starting && off.length === 1 && (
            <p className="mt-0.5 text-xs text-content-secondary">{processOffImpact(t, off[0]!)}</p>
          )}
        </div>
      </div>
      {!starting && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {isAdmin && off.some(isControllable) ? (
            <button
              type="button"
              onClick={turnOn}
              disabled={action.isPending}
              data-testid="module-processes-turn-on"
              className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white hover:bg-oe-blue/90 disabled:opacity-60"
            >
              <Power size={12} aria-hidden />
              {t('processes.notice.turn_on', { defaultValue: 'Turn on (uses ~{{value}})', value: formatMb(t, mb) })}
            </button>
          ) : (
            <span className="text-xs text-content-secondary">
              {t('processes.notice.ask_admin', { defaultValue: 'Ask an administrator to turn it on.' })}
            </span>
          )}
          <button
            type="button"
            onClick={() => openPanel(off[0]!.id)}
            className="text-xs font-medium text-oe-blue hover:underline"
          >
            {t('processes.notice.more', { defaultValue: 'What is this?' })}
          </button>
        </div>
      )}
    </div>
  );
}

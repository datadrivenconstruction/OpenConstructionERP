// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The first-run choice is sent, and the services it starts are followed, from
 * the header rather than from the wizard. The wizard closes the moment the
 * admin answers it: the server only records the choice and queues the starts,
 * and the services load one after another in the background, which can take
 * minutes for an AI model. Nobody should sit in front of a dialog for that.
 *
 * What the admin sees instead: a toast that the services are starting, the
 * header spinner with "preparing ...", then one toast when everything is up,
 * or one per service that failed, each with a Retry. A module page that needs
 * a service still loading says so through `ModuleProcessesNotice`.
 */

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { QueryClient } from '@tanstack/react-query';

import i18n from '@/app/i18n';
import { apiPost, getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { isLoading, processesKey, useProcessAction, useProcesses, type ProcessesSnapshot } from './api';
import { processName } from './labels';
import { useProcessesUi } from './useProcessesUi';

export interface FirstRunBody {
  module_ids: string[];
  start_now: boolean;
}

/** Toasts that wait for a click stay up long enough to be read and clicked. */
const ACTION_TOAST_MS = 12000;

/**
 * Send the wizard's answer without anyone waiting on it. Never throws: a
 * failure is a toast with a Retry that sends the same answer again.
 */
export function sendFirstRun(qc: QueryClient, body: FirstRunBody): Promise<void> {
  const { addToast } = useToastStore.getState();
  return Promise.resolve()
    .then(() => apiPost<ProcessesSnapshot>('/v1/processes/first-run', body))
    .then((snapshot) => {
      if (snapshot?.processes) {
        qc.setQueryData(processesKey, snapshot);
        // The server's answer, not the wizard's guess, says what is loading:
        // a lazy service only goes to "on" and loads on first use.
        const loading = snapshot.processes.filter((p) => p.enabled && isLoading(p));
        if (loading.length > 0) {
          useProcessesUi.getState().watchStarts(loading.map((p) => p.id));
          addToast(
            {
              type: 'info',
              title: i18n.t('processes.start_background_title', {
                defaultValue: 'Starting services in the background',
              }),
              message: i18n.t('processes.start_background_message', {
                defaultValue:
                  'You can keep working. {{names}} start one after another; Background services in the top bar shows the progress.',
                names: fmtList(loading.map((p) => processName(i18n.t, p))),
              }),
            },
            { duration: 8000 },
          );
        }
      }
    })
    .catch((err: unknown) => {
      addToast(
        {
          type: 'error',
          title: i18n.t('processes.wizard.failed', { defaultValue: 'Could not start the services' }),
          message: getErrorMessage(err),
          action: {
            label: i18n.t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void sendFirstRun(qc, body),
          },
        },
        { duration: ACTION_TOAST_MS },
      );
    })
    .finally(() => qc.invalidateQueries({ queryKey: processesKey }));
}

/**
 * Follows the services in `startWatch` until each is up or has failed. Mounted
 * once, in the header, so it keeps following after the wizard is gone.
 */
export function ProcessesStartWatch() {
  const { t } = useTranslation();
  const watch = useProcessesUi((s) => s.startWatch);
  const watchStarts = useProcessesUi((s) => s.watchStarts);
  const settleStart = useProcessesUi((s) => s.settleStart);
  const addToast = useToastStore((s) => s.addToast);
  const action = useProcessAction();
  // Poll fast while anything is followed; the header's own query shares the cache.
  const { data } = useProcesses(watch.length > 0);
  // What came up in this round, for the one "ready" toast at the end.
  const ready = useRef<string[]>([]);
  const failedInRound = useRef(false);

  useEffect(() => {
    if (!data || watch.length === 0) return;
    for (const id of watch) {
      const p = data.processes.find((x) => x.id === id);
      if (p && p.enabled && isLoading(p)) continue;
      settleStart(id);
      if (!p || !p.enabled) continue;
      const name = processName(t, p);
      if (p.status === 'error') {
        failedInRound.current = true;
        addToast(
          {
            type: 'error',
            title: t('processes.start_failed', { defaultValue: '{{name}} could not start', name }),
            message:
              p.last_error?.message ??
              t('processes.start_failed_hint', {
                defaultValue: 'Background services in the top bar has the details.',
              }),
            action: {
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () =>
                action.mutate(
                  { id: p.id, action: 'restart' },
                  {
                    onSuccess: () => watchStarts([p.id]),
                    onError: (err) =>
                      addToast({
                        type: 'error',
                        title: t('processes.action_failed', { defaultValue: 'Could not change {{name}}', name }),
                        message: getErrorMessage(err),
                      }),
                  },
                ),
            },
          },
          { duration: ACTION_TOAST_MS },
        );
      } else {
        ready.current.push(name);
      }
    }
  }, [data, watch, settleStart, watchStarts, addToast, action, t]);

  // The round is over once nothing is followed any more.
  useEffect(() => {
    if (watch.length > 0) return;
    if (ready.current.length > 0 && !failedInRound.current) {
      addToast({
        type: 'success',
        title: t('processes.start_ready_title', { defaultValue: 'Background services are ready' }),
        message: t('processes.start_ready_message', {
          defaultValue: 'Ready to use: {{names}}',
          names: fmtList(ready.current),
        }),
      });
    }
    ready.current = [];
    failedInRound.current = false;
  }, [watch.length, addToast, t]);

  return null;
}

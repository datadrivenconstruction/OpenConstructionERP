// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Reopening a decided gate. The earlier decision stays on record; the gate
// starts a new attempt in preparation. A reopening needs a written reason,
// and after a go the server also moves the project back to the phase the gate
// leaves, because a gate can only be reviewed from that phase. That is not a
// choice, so the dialog offers none: it says what will happen before the
// click instead of leaving it to a surprise in the matrix.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Undo2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';

import type { GovernanceGate } from './api';
import { reopenProblem, reopenRewind } from './decisionRules';
import { OUTCOME, vocab } from './labels';

export interface ReopenDialogProps {
  open: boolean;
  onClose: () => void;
  gate: GovernanceGate;
  gateName: string;
  /** The phase the project returns to, named for the reader. */
  fromPhaseName: string;
  busy: boolean;
  /** The server's refusal of the last try, already as a sentence. */
  serverError: string | null;
  onSubmit: (body: { rationale: string }) => void;
}

export function ReopenDialog({
  open,
  onClose,
  gate,
  gateName,
  fromPhaseName,
  busy,
  serverError,
  onSubmit,
}: ReopenDialogProps) {
  const { t } = useTranslation();
  const [rationale, setRationale] = useState('');
  const [tried, setTried] = useState(false);
  const rewind = reopenRewind(gate) === 'forced';
  const problem = reopenProblem(rationale);

  const send = () => {
    if (problem) {
      setTried(true);
      return;
    }
    onSubmit({ rationale: rationale.trim() });
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="reopen-dialog"
      title={t('governance.project.reopen.title', { defaultValue: 'Reopen gate' })}
      subtitle={t('governance.project.reopen.subtitle', {
        defaultValue: '{{gate}} starts a new attempt in preparation. The earlier decision stays on record.',
        gate: gateName,
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('governance.project.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button icon={<Undo2 size={14} />} loading={busy} onClick={send} data-testid="reopen-submit">
            {t('governance.project.reopen.submit', { defaultValue: 'Reopen gate' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {serverError && (
          <div role="alert" className="rounded-md border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm text-content-primary">
            {serverError}
          </div>
        )}

        {gate.last_outcome && (
          <p className="text-sm text-content-secondary">
            {t('governance.project.reopen.last_outcome', {
              defaultValue: 'Decided as: {{outcome}}',
              outcome: vocab(t, OUTCOME, gate.last_outcome),
            })}
          </p>
        )}

        <div>
          <label htmlFor="reopen-rationale" className="mb-1 block text-sm font-semibold text-content-primary">
            {t('governance.project.reopen.rationale', { defaultValue: 'Why the gate is reopened' })}
            <span className="ml-1 text-xs font-normal text-semantic-error">
              {t('governance.project.required', { defaultValue: 'required' })}
            </span>
          </label>
          <textarea
            id="reopen-rationale"
            rows={3}
            className="w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder={t('governance.project.reopen.rationale_placeholder', {
              defaultValue: 'What changed since the decision. It stays on the record.',
            })}
          />
          {tried && problem && (
            <p className="mt-1 text-xs text-semantic-error" role="alert" data-testid="reopen-problem">
              {t('governance.project.reopen.rationale_required', { defaultValue: 'Write down why the gate is reopened.' })}
            </p>
          )}
        </div>

        <div className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3 text-sm" data-testid="reopen-rewind" data-rewind={rewind ? 'forced' : 'none'}>
          <p className="font-medium text-content-primary">
            {rewind
              ? t('governance.project.reopen.rewind_forced', {
                  defaultValue: 'The project moves back to the phase "{{phase}}".',
                  phase: fromPhaseName,
                })
              : t('governance.project.reopen.rewind_none', {
                  defaultValue: 'The project stays in the phase "{{phase}}".',
                  phase: fromPhaseName,
                })}
          </p>
          <p className="mt-1 text-xs text-content-secondary">
            {rewind
              ? t('governance.project.reopen.rewind_forced_hint', {
                  defaultValue:
                    'The gate was passed, so the project already sits in the next phase. A gate is reviewed from the phase it leaves, so reopening takes the project back there.',
                })
              : t('governance.project.reopen.rewind_none_hint', {
                  defaultValue: 'The gate was not passed, so the project never left this phase.',
                })}
          </p>
        </div>
      </div>
    </WideModal>
  );
}

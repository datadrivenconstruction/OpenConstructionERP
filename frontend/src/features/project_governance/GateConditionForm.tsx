// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A further condition on a gate that was decided as go with conditions. The
// decision itself is final, but an open point found afterwards still needs an
// owner and a date, and it joins the same register as the others.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { useToastStore } from '@/stores/useToastStore';

import { addGateCondition, type ConditionInput, type GateArea } from './api';
import { ConditionFields } from './ConditionFields';
import { emptyCondition, toConditionInput } from './decisionRules';
import { errorText, refusalText } from './labels';

export interface GateConditionFormProps {
  projectId: string;
  gateId: string;
  areas: GateArea[];
  areaName: (code: string) => string;
  documentName: (docType: string) => string;
  onDone: () => void;
  onCancel: () => void;
}

export function GateConditionForm({
  projectId,
  gateId,
  areas,
  areaName,
  documentName,
  onDone,
  onCancel,
}: GateConditionFormProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState<ConditionInput>(emptyCondition);
  const [tried, setTried] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const missingText = !draft.text.trim();

  const save = useMutation({
    mutationFn: () => addGateCondition(projectId, gateId, toConditionInput(draft)),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('governance.project.gate.condition_added', { defaultValue: 'Condition added' }),
      });
      onDone();
    },
    onError: (err) => setServerError(refusalText(t, err)),
  });
  const send = () => {
    if (missingText) {
      setTried(true);
      return;
    }
    setServerError(null);
    save.mutate();
  };

  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="gate-condition-form">
      <p className="text-xs text-content-secondary">
        {t('governance.project.gate.add_condition_hint', {
          defaultValue:
            'The condition joins the ones this gate was passed with. An owner and a due date keep it from being forgotten.',
        })}
      </p>
      <ConditionFields
        projectId={projectId}
        value={draft}
        areas={areas}
        areaName={areaName}
        documentName={documentName}
        onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
      />
      {tried && missingText && (
        <p className="text-xs text-semantic-error" role="alert" data-testid="gate-condition-problem">
          {errorText(t, 'condition_text_required')}
        </p>
      )}
      {serverError && (
        <p className="text-xs text-semantic-error" role="alert" data-testid="gate-condition-error">
          {serverError}
        </p>
      )}
      <div className="flex gap-2">
        <Button size="sm" loading={save.isPending} onClick={send} data-testid="gate-condition-send">
          {t('governance.project.gate.add_condition_send', { defaultValue: 'Add condition' })}
        </Button>
        <Button size="sm" variant="ghost" disabled={save.isPending} onClick={onCancel}>
          {t('governance.project.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </div>
  );
}

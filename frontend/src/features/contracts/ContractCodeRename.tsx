// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Rename a draft contract.
//
// A contract's code could not be changed at all, so a code typed by mistake
// was freed only by deleting the draft and writing it again. The server takes a
// new code while the contract is a draft and refuses it afterwards, because a
// signed contract is quoted by its code on every certificate and invoice. The
// control is offered only on a draft for the same reason.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { PenLine } from 'lucide-react';

import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { updateContract, type ContractItem } from './api';

export function ContractCodeRename({ contract }: { contract: ContractItem }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState(contract.code);

  const renameMut = useMutation({
    mutationFn: () => updateContract(contract.id, { code: code.trim() }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['contracts', 'list'] });
      setEditing(false);
      addToast({
        type: 'success',
        title: t('contracts.code_renamed', { defaultValue: 'Contract code changed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (contract.status !== 'draft') return null;

  if (!editing) {
    return (
      <button
        type="button"
        data-testid="contract-code-rename"
        onClick={() => {
          setCode(contract.code);
          setEditing(true);
        }}
        aria-label={t('contracts.rename_code', { defaultValue: 'Change the contract code' })}
        title={t('contracts.rename_code', { defaultValue: 'Change the contract code' })}
        className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
      >
        <PenLine size={13} />
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-1">
      <input
        type="text"
        data-testid="contract-code-input"
        value={code}
        maxLength={80}
        autoFocus
        onChange={(e) => setCode(e.target.value)}
        aria-label={t('contracts.code', { defaultValue: 'Code' })}
        className="w-36 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
      />
      <Button
        size="sm"
        onClick={() => renameMut.mutate()}
        loading={renameMut.isPending}
        disabled={!code.trim() || code.trim() === contract.code}
      >
        {t('common.save', { defaultValue: 'Save' })}
      </Button>
      <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
        {t('common.cancel', { defaultValue: 'Cancel' })}
      </Button>
    </span>
  );
}

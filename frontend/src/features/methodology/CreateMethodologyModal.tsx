// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Create a blank project-scoped methodology. Seeds a single VAT step so the
// new methodology is a valid cascade out of the box; everything is then edited
// in the methodology editor.

import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Button, Input } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { methodologyApi } from './api';
import type { Methodology, MarkupStep } from './types';

interface Props {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onCreated: (m: Methodology) => void;
}

/** A minimal, valid starting cascade: a single direct base and a 0% VAT step. */
function blankCascade(): {
  base_mapping: Record<string, string[]>;
  composites: Record<string, string[]>;
  cascade_steps: MarkupStep[];
} {
  return {
    base_mapping: {
      labor: ['labor'],
      materials: ['material'],
      equipment: ['equipment'],
      subcontract: ['subcontractor'],
    },
    composites: { direct: ['labor', 'materials', 'equipment', 'subcontract'] },
    cascade_steps: [
      {
        key: 'vat',
        label: 'VAT',
        category: 'tax',
        kind: 'percentage',
        rate: '0',
        amount: '0',
        base: ['direct'],
      },
    ],
  };
}

export function CreateMethodologyModal({ open, projectId, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [name, setName] = useState('');
  const [currency, setCurrency] = useState('');
  const [decimals, setDecimals] = useState('2');

  useEffect(() => {
    if (open) {
      setName('');
      setCurrency('');
      setDecimals('2');
    }
  }, [open]);

  const createMut = useMutation({
    mutationFn: () => {
      const seed = blankCascade();
      // `Number(decimals) || 2` turned a user-entered 0 (whole-unit currency
      // such as JPY) into 2, because 0 is falsy. Clamp to the backend's [0, 8].
      const d = Number(decimals);
      return methodologyApi.create({
        project_id: projectId,
        name: name.trim(),
        currency: currency.trim().toUpperCase(),
        decimals: Number.isFinite(d) ? Math.min(8, Math.max(0, d)) : 2,
        ...seed,
        vat_rate: '0',
      });
    },
    onSuccess: (m) => {
      addToast({
        type: 'success',
        title: t('methodology.create_modal.created', {
          defaultValue: '{{name}} created',
          name: m.name,
        }),
      });
      onCreated(m);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSave = name.trim().length > 0 && !createMut.isPending;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    createMut.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="sm"
      busy={createMut.isPending}
      title={t('methodology.create_modal.title', { defaultValue: 'New methodology' })}
      subtitle={t('methodology.create_modal.subtitle', {
        defaultValue:
          'Start from a blank cascade. You can add base sets and markup steps in the editor, or install a built-in template instead.',
      })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!canSave} loading={createMut.isPending}>
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label={t('methodology.create_modal.name', { defaultValue: 'Name' })}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('methodology.create_modal.name_placeholder', {
            defaultValue: 'e.g. Our standard estimate',
          })}
          autoFocus
          maxLength={255}
        />
        <div className="grid grid-cols-2 gap-4">
          <Input
            label={t('methodology.create_modal.currency', { defaultValue: 'Currency (optional)' })}
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            placeholder="EUR"
            maxLength={8}
          />
          <Input
            label={t('methodology.create_modal.decimals', { defaultValue: 'Decimals' })}
            type="number"
            min={0}
            max={8}
            value={decimals}
            onChange={(e) => setDecimals(e.target.value)}
          />
        </div>
      </form>
    </WideModal>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Rename dialog for the estimate list rows. The editor header renames inline
 * (BOQRenameTitle); a list row has no room for an input, so it asks here.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui';
import { useRenameBOQ } from './useRenameBOQ';

interface BOQRenameDialogProps {
  boqId: string;
  name: string;
  onClose: () => void;
}

export function BOQRenameDialog({ boqId, name, onClose }: BOQRenameDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(name);
  const rename = useRenameBOQ(onClose);
  const next = draft.trim();

  const submit = () => {
    if (!next || rename.isPending) return;
    if (next === name) {
      onClose();
      return;
    }
    rename.mutate({ boqId, name: next });
  };

  return (
    <div
      className="fixed inset-0 z-modal flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t('boq.rename', { defaultValue: 'Rename estimate' })}
      onClick={onClose}
    >
      <form
        className="w-full max-w-sm rounded-xl bg-surface-primary p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose();
        }}
      >
        <h2 className="oe-section-title mb-3">
          {t('boq.rename', { defaultValue: 'Rename estimate' })}
        </h2>
        <input
          autoFocus
          value={draft}
          maxLength={255}
          data-testid="boq-rename-dialog-input"
          onChange={(e) => setDraft(e.target.value)}
          onFocus={(e) => e.currentTarget.select()}
          className="oe-input mb-4 w-full"
        />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button type="submit" size="sm" disabled={!next} loading={rename.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </form>
    </div>
  );
}

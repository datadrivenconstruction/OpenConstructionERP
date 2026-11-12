// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Edit text" before downloading one award letter or rejection notice.
 *
 * Opens the text this letter would use now (project, company or default, in
 * the project's language). Changes apply to this one letter. A manager or
 * admin may tick "also save as template" to keep the wording for the company.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { Button, SkeletonText } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { downloadTenderLetter, getLetterTemplate, saveLetterTemplate } from './api';
import { LetterTextEditor, hasBlockingIssue } from './LetterTextEditor';
import type { LetterText } from './letterRules';

export interface LetterEditDialogProps {
  open: boolean;
  onClose: () => void;
  packageId: string;
  projectId: string;
  bidId: string;
  kind: 'award-letter' | 'rejection-letter';
  company: string;
}

export function LetterEditDialog({ open, onClose, packageId, projectId, bidId, kind, company }: LetterEditDialogProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const canSaveTemplate = userRole === 'admin' || userRole === 'manager';
  const key = kind === 'award-letter' ? 'tendering.award_letter' : 'tendering.rejection_letter';

  const resolved = useQuery({
    queryKey: ['letter-templates', key, 'project', projectId],
    queryFn: () => getLetterTemplate(key, { projectId }),
    enabled: open && !!projectId,
  });
  const [draft, setDraft] = useState<LetterText | null>(null);
  const [saveAsTemplate, setSaveAsTemplate] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open && resolved.data) setDraft(resolved.data.text);
    if (!open) setSaveAsTemplate(false);
  }, [open, resolved.data]);

  const placeholders = resolved.data?.placeholders ?? [];
  const blocked = !draft || hasBlockingIssue(draft, placeholders);

  const download = async () => {
    if (!draft || !resolved.data) return;
    setBusy(true);
    try {
      if (saveAsTemplate && canSaveTemplate) {
        await saveLetterTemplate(key, { ...draft, language: resolved.data.language });
        void qc.invalidateQueries({ queryKey: ['letter-templates'] });
      }
      const blob = await downloadTenderLetter(packageId, bidId, kind, draft);
      if (!blob) {
        addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
        return;
      }
      const safeCompany = company.replace(/[^a-z0-9_-]+/gi, '_') || 'bidder';
      triggerDownload(blob, `${kind === 'award-letter' ? 'award_letter' : 'rejection_notice'}_${safeCompany}.pdf`);
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="xl"
      busy={busy}
      title={t('letter_templates.edit_text', { defaultValue: 'Edit text' })}
      subtitle={t('letter_templates.one_off_hint', { defaultValue: 'Changes apply to this letter only.' })}
      testId="letter-edit-dialog"
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {canSaveTemplate && (
            <label className="mr-auto flex items-center gap-2 text-sm text-content-secondary">
              <input
                type="checkbox"
                checked={saveAsTemplate}
                onChange={(e) => setSaveAsTemplate(e.target.checked)}
                data-testid="letter-save-as-template"
              />
              {t('letter_templates.save_as_template', { defaultValue: 'Also save as the template for this language' })}
            </label>
          )}
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" icon={<Download size={16} />} onClick={download} disabled={blocked || busy} loading={busy}>
            {t('letter_templates.download', { defaultValue: 'Download PDF' })}
          </Button>
        </div>
      }
    >
      {resolved.isLoading || !draft ? (
        <SkeletonText lines={8} />
      ) : (
        <LetterTextEditor value={draft} onChange={setDraft} placeholders={placeholders} />
      )}
    </WideModal>
  );
}

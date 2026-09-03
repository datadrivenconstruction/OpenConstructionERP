// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ProjectJobNumberChip — the job number, in the project header's chip row.
 *
 * Every register and work-request reference on a project is minted from
 * ``project_code`` (REG-RFQ-<job>-0001, ENG-<job>-004), so it is not a
 * settings-page detail: it belongs on the hub, beside the classification
 * standard and the currency, and it has to be fixable in place.
 *
 * Set: a monospace `Job 25406` chip with a pencil, and a right-click that
 * opens the same editor. Unset: a dashed "＋ Set the job number" action, so
 * the gap is visible rather than silently absent.
 *
 * The editor is the app's ``askDialog`` (this browser has no window.prompt).
 * It is imported lazily, matching how the rest of the page reaches for it.
 */

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil } from 'lucide-react';

export interface ProjectJobNumberChipProps {
  /** Current ``project.project_code``; null / empty renders the set action. */
  code: string | null | undefined;
  /** Called with the trimmed new code, only when it actually changed. */
  onChange: (code: string) => void;
  /** Read-only mode hides the pencil and the right-click editor. */
  canManage?: boolean;
}

export function ProjectJobNumberChip({
  code,
  onChange,
  canManage = true,
}: ProjectJobNumberChipProps) {
  const { t } = useTranslation();

  const openEditor = useCallback(async () => {
    if (!canManage) return;
    const { ask } = await import('@/shared/ui/askDialog');
    const answers = await ask({
      title: t('projects.job_no_title', { defaultValue: 'Job Number' }),
      note: t('projects.job_no_note', {
        defaultValue:
          'Register references are minted from this number, so it must match the job-management system.',
      }),
      fields: [
        {
          label: t('projects.job_no_label', { defaultValue: 'Job number' }),
          value: code ?? '',
          placeholder: 'e.g. 25406',
        },
      ],
      okLabel: t('common.save', { defaultValue: 'Save' }),
    });
    const next = answers?.[0]?.trim();
    // An unchanged value is not a no-op the caller should have to filter out;
    // swallowing it here keeps a stray PATCH off the wire.
    if (next && next !== (code ?? '')) onChange(next);
  }, [canManage, code, onChange, t]);

  if (code) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 px-2.5 py-0.5 text-xs font-semibold text-oe-blue"
        data-testid="project-job-chip"
        onContextMenu={(e) => {
          if (!canManage) return;
          e.preventDefault();
          void openEditor();
        }}
        title={t('projects.job_no_change_hint', {
          defaultValue: 'Job number — right-click or use the pencil to change it',
        })}
      >
        {t('projects.job_no_prefix', { defaultValue: 'Job' })}{' '}
        <span className="font-mono tracking-tight">{code}</span>
        {canManage && (
          <button
            type="button"
            onClick={() => void openEditor()}
            aria-label={t('projects.job_no_edit', {
              defaultValue: 'Change job number',
            })}
            data-testid="project-job-chip-edit"
            className="ml-0.5 text-oe-blue/70 transition-colors hover:text-oe-blue"
          >
            <Pencil size={11} />
          </button>
        )}
      </span>
    );
  }

  if (!canManage) return null;

  return (
    <button
      type="button"
      onClick={() => void openEditor()}
      data-testid="project-job-chip-set"
      className="inline-flex items-center gap-1 rounded-full border border-dashed border-amber-400 px-2.5 py-0.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-50 dark:text-amber-300 dark:hover:bg-amber-950/30"
    >
      + {t('projects.job_no_add_long', { defaultValue: 'Set the job number' })}
    </button>
  );
}

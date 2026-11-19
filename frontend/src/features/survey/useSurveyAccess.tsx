// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { Eye } from 'lucide-react';
import { useAuthStore } from '@/stores/useAuthStore';
import { roleHasPermission } from '@/shared/lib/permissionGates';

/** What the signed-in user may do on survey pages; mirrors survey.write / survey.confirm on the server. */
export function surveyAccess(role: string | null | undefined): { canWrite: boolean; canConfirm: boolean } {
  const surveyor = (role ?? '').toLowerCase() === 'surveyor';
  return {
    canWrite: roleHasPermission(role, 'survey.write'),
    // The server gives surveyors survey.confirm on top of the editor rank.
    canConfirm: surveyor || roleHasPermission(role, 'survey.confirm'),
  };
}

export function useSurveyAccess() {
  const role = useAuthStore((s) => s.userRole);
  return surveyAccess(role);
}

/** One quiet line telling a viewer why the action buttons are missing. */
export function ViewOnlyNote() {
  const { t } = useTranslation();
  const { canWrite } = useSurveyAccess();
  if (canWrite) return null;
  return (
    <div
      role="note"
      className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs text-content-secondary"
    >
      <Eye size={14} className="shrink-0" />
      {t('survey.access.view_only', {
        defaultValue: 'View only: your role can read survey data. Ask a project manager for edit rights.',
      })}
    </div>
  );
}

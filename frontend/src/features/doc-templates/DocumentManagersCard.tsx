// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Admin card: who holds the Document manager role (edit and publish document
 * wording without being an admin). Admins hold it implicitly.
 */

import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { UserCog } from 'lucide-react';
import { Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { listManagers, setManager } from './api';

export function DocumentManagersCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const role = useAuthStore((s) => s.userRole);
  const isAdmin = role === 'admin' || role === 'superuser' || role === 'owner';
  const q = useQuery({ queryKey: ['doc-templates', 'managers'], queryFn: listManagers, enabled: isAdmin });
  const m = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) => setManager(id, on),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['doc-templates'] });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  if (!isAdmin || !q.data) return null;
  const others = q.data.items.filter((u) => u.role !== 'admin');
  return (
    <Card padding="md" data-testid="doc-managers">
      <div className="flex items-start gap-2">
        <UserCog size={16} className="mt-0.5 text-content-secondary" />
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('settings.document_templates.managers_title', { defaultValue: 'Document managers' })}
          </h3>
          <p className="text-xs text-content-secondary">
            {t('settings.document_templates.managers_hint', {
              defaultValue: 'Admins can always edit and publish wording. Give the role to others who should.',
            })}
          </p>
        </div>
      </div>
      {others.length > 0 && (
        <ul className="mt-3 divide-y divide-border-light">
          {others.map((u) => (
            <li key={u.user_id} className="flex items-center justify-between py-1.5 text-sm">
              <span>
                {u.full_name || u.email} <span className="text-xs text-content-tertiary">{u.email}</span>
              </span>
              <label className="flex items-center gap-2 text-xs text-content-secondary">
                <input
                  type="checkbox"
                  checked={u.is_manager}
                  disabled={m.isPending}
                  onChange={(e) => m.mutate({ id: u.user_id, on: e.target.checked })}
                />
                {t('settings.document_templates.manager_role', { defaultValue: 'Document manager' })}
              </label>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

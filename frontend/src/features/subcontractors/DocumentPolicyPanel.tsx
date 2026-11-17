// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The installation's required-documents list for subcontract agreements and
 * whether a gap only warns or blocks activation and payment approval.
 *
 * Presets are offered only when the project's national pack contributes them,
 * so a market with none sees only the platform's roles.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { getDocumentPolicy, putDocumentPolicy, type RequiredDocument } from './api';
import { toggleRole } from './requiredDocuments';
import { roleLabel } from './AgreementDocumentsPanel';

export function DocumentPolicyPanel({ projectId }: { projectId?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const q = useQuery({
    queryKey: ['subcontractors', 'document-policy', projectId ?? null],
    queryFn: () => getDocumentPolicy(projectId),
  });
  const [required, setRequired] = useState<RequiredDocument[]>([]);
  const [enforcement, setEnforcement] = useState<'warn' | 'block'>('warn');

  useEffect(() => {
    if (q.data) {
      setRequired(q.data.required);
      setEnforcement(q.data.enforcement);
    }
  }, [q.data]);

  const save = useMutation({
    mutationFn: () => putDocumentPolicy({ required, enforcement }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subcontractors', 'document-policy'] });
      qc.invalidateQueries({ queryKey: ['subcontractors', 'required-documents'] });
      addToast({ type: 'success', title: t('subcontractors.docs.policy_saved', { defaultValue: 'Required documents saved' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (!q.data) return null;
  const roles = Array.from(new Set([...q.data.roles, ...required.map((r) => r.role)]));

  return (
    <section className="space-y-2 text-sm" data-testid="document-policy">
      <h3 className="font-medium">{t('subcontractors.docs.policy_title', { defaultValue: 'Required documents' })}</h3>
      <ul className="space-y-1">
        {roles.map((role) => {
          const row = required.find((r) => r.role === role);
          return (
            <li key={role} className="flex items-center gap-3">
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={!!row}
                  onChange={() => setRequired((l) => toggleRole(l, role))}
                  data-testid={`policy-role-${role}`}
                />
                {roleLabel(t, role)}
              </label>
              {row && (
                <label className="flex items-center gap-1 text-xs text-content-secondary">
                  <input
                    type="checkbox"
                    checked={row.signed}
                    onChange={(e) =>
                      setRequired((l) => l.map((r) => (r.role === role ? { ...r, signed: e.target.checked } : r)))
                    }
                  />
                  {t('subcontractors.docs.must_be_signed', { defaultValue: 'must be signed' })}
                </label>
              )}
            </li>
          );
        })}
      </ul>
      {q.data.presets.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="policy-presets">
          {q.data.presets.map((p) => (
            <Button
              key={p.role}
              size="sm"
              variant="ghost"
              onClick={() => setRequired((l) => (l.some((r) => r.role === p.role) ? l : [...l, { role: p.role, signed: !!p.signed }]))}
            >
              + {p.label || roleLabel(t, p.role)}
            </Button>
          ))}
        </div>
      )}
      <label className="flex items-center gap-2 text-xs">
        <span>{t('subcontractors.docs.enforcement', { defaultValue: 'When a document is missing or expired' })}</span>
        <select
          className="oe-input"
          value={enforcement}
          onChange={(e) => setEnforcement(e.target.value as 'warn' | 'block')}
          data-testid="policy-enforcement"
        >
          <option value="warn">{t('subcontractors.docs.enforcement_warn', { defaultValue: 'Warn' })}</option>
          <option value="block">{t('subcontractors.docs.enforcement_block', { defaultValue: 'Block approval and activation' })}</option>
        </select>
      </label>
      <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
        {t('common.save', { defaultValue: 'Save' })}
      </Button>
    </section>
  );
}

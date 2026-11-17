// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Documents attached to a subcontract agreement, and where the agreement
 * stands against the required list.
 *
 * Uploads go to POST /agreements/{id}/documents, which checks the file's magic
 * bytes against the document allow-list. The required list and its enforcement
 * (warn or block) are the installation's, read from the server; a missing or
 * expired required document shows here before anyone hits a refusal.
 */

import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Paperclip, Trash2, Upload } from 'lucide-react';
import type { TFunction } from 'i18next';

import { Badge, Button } from '@/shared/ui';
import { apiDelete, getAuthToken, API_BASE, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  DOCUMENT_ROLES,
  getRequiredDocumentStatus,
  listAgreementDocuments,
  type Agreement,
  type AgreementDocument,
} from './api';

export function roleLabel(t: TFunction, role: string): string {
  return t(`subcontractors.docs.role.${role}`, { defaultValue: role.replace(/_/g, ' ') });
}

export function AgreementDocumentsPanel({ agreement }: { agreement: Agreement }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fileRef = useRef<HTMLInputElement>(null);
  const [role, setRole] = useState<string>(DOCUMENT_ROLES[0]);
  const [signed, setSigned] = useState('');
  const [until, setUntil] = useState('');
  const [busy, setBusy] = useState(false);

  const docsQ = useQuery({
    queryKey: ['subcontractors', 'agreement-documents', agreement.id],
    queryFn: () => listAgreementDocuments(agreement.id),
  });
  const statusQ = useQuery({
    queryKey: ['subcontractors', 'required-documents', agreement.id],
    queryFn: () => getRequiredDocumentStatus(agreement.id),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['subcontractors', 'agreement-documents', agreement.id] });
    qc.invalidateQueries({ queryKey: ['subcontractors', 'required-documents', agreement.id] });
  };

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append('doc_role', role);
      if (signed) form.append('signed_date', signed);
      if (until) form.append('valid_until', until);
      form.append('file', file);
      const token = getAuthToken();
      const resp = await fetch(`${API_BASE}/v1/subcontractors/agreements/${agreement.id}/documents`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: form,
      });
      if (!resp.ok) {
        let detail: string;
        try {
          const j = await resp.json();
          detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
        } catch {
          detail = `HTTP ${resp.status}`;
        }
        addToast({
          type: 'error',
          title: t('subcontractors.upload_failed', { defaultValue: 'Upload failed' }),
          message: detail,
        });
        return;
      }
      setSigned('');
      setUntil('');
      refresh();
      addToast({ type: 'success', title: t('subcontractors.docs.uploaded', { defaultValue: 'Document attached' }) });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const remove = async (doc: AgreementDocument) => {
    try {
      await apiDelete(`/v1/subcontractors/agreements/${agreement.id}/documents/${doc.id}`);
      refresh();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    }
  };

  const docs = docsQ.data ?? [];
  const gaps = statusQ.data?.gaps ?? [];
  const blocks = statusQ.data?.enforcement === 'block';

  return (
    <div className="mt-3 border-t border-border-light pt-3" data-testid="agreement-documents">
      <p className="mb-1.5 flex items-center gap-1 text-xs font-medium text-content-secondary">
        <Paperclip size={12} />
        {t('subcontractors.docs.title', { defaultValue: 'Documents' })}
      </p>
      {gaps.length > 0 && (
        <ul className="mb-2 space-y-1" data-testid="required-gaps">
          {gaps.map((g) => (
            <li key={g.role} className="flex items-center gap-2 text-xs">
              <Badge variant={blocks ? 'error' : 'warning'} dot>
                {t(`subcontractors.docs.state.${g.state}`, { defaultValue: g.state })}
              </Badge>
              <span>{roleLabel(t, g.role)}</span>
            </li>
          ))}
        </ul>
      )}
      {docs.length > 0 && (
        <ul className="mb-2 space-y-1">
          {docs.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2 text-xs text-content-secondary">
              <span className="truncate">
                {roleLabel(t, d.doc_role)}: {d.title || d.filename}
                {d.valid_until ? ` (${d.valid_until})` : ''}
              </span>
              <span className="flex items-center gap-1">
                <a
                  className="text-oe-blue hover:underline"
                  href={`${API_BASE}/v1/subcontractors/agreements/${agreement.id}/documents/${d.id}/download`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t('common.download', { defaultValue: 'Download' })}
                </a>
                <button
                  type="button"
                  aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  onClick={() => remove(d)}
                  className="text-content-tertiary hover:text-semantic-error"
                >
                  <Trash2 size={12} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <label className="flex flex-col gap-0.5">
          <span className="text-content-tertiary">{t('subcontractors.docs.role_label', { defaultValue: 'Document type' })}</span>
          <select className="oe-input" value={role} onChange={(e) => setRole(e.target.value)} data-testid="doc-role">
            {DOCUMENT_ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(t, r)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-content-tertiary">{t('subcontractors.docs.signed_date', { defaultValue: 'Signed on' })}</span>
          <input type="date" className="oe-input" value={signed} onChange={(e) => setSigned(e.target.value)} />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-content-tertiary">{t('subcontractors.docs.valid_until', { defaultValue: 'Valid until' })}</span>
          <input type="date" className="oe-input" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          data-testid="doc-file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
          }}
        />
        <Button
          size="sm"
          variant="secondary"
          loading={busy}
          icon={<Upload size={12} />}
          onClick={() => fileRef.current?.click()}
        >
          {t('subcontractors.docs.attach', { defaultValue: 'Attach file' })}
        </Button>
      </div>
    </div>
  );
}

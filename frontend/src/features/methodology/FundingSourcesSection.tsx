// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Funding-sources master list for a project. Funding sources are project-scoped
// (not tied to a single methodology), so this list is the same across every
// methodology in the project. Add / edit / delete inline.

import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Coins, Pencil, Plus, Trash2 } from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, Input, Skeleton } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { methodologyApi } from './api';
import type { FundingSource } from './types';

interface Props {
  projectId: string;
  readOnly: boolean;
}

export function FundingSourcesSection({ projectId, readOnly }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [modal, setModal] = useState<{ open: boolean; initial: FundingSource | null }>({
    open: false,
    initial: null,
  });

  const fsQ = useQuery({
    queryKey: ['methodology', 'funding-sources', projectId],
    queryFn: () => methodologyApi.listFundingSources(projectId),
    enabled: !!projectId,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['methodology', 'funding-sources', projectId] });

  const deleteMut = useMutation({
    mutationFn: (id: string) => methodologyApi.removeFundingSource(id, projectId),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('methodology.funding.deleted', { defaultValue: 'Funding source removed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <Card padding="lg">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('methodology.funding.title', { defaultValue: 'Funding sources' })}
          </h3>
          <p className="mt-0.5 text-xs text-content-secondary">
            {t('methodology.funding.subtitle', {
              defaultValue:
                'The budget lines an estimate can be allocated against - grant, own funds, loan, investor. Shared across this project.',
            })}
          </p>
        </div>
        {!readOnly && (
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setModal({ open: true, initial: null })}
          >
            {t('methodology.funding.add', { defaultValue: 'Add source' })}
          </Button>
        )}
      </div>

      <div className="mt-4">
        {fsQ.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : fsQ.isError ? (
          <ErrorState
            title={t('methodology.funding.error', { defaultValue: 'Could not load funding sources.' })}
            onRetry={() => fsQ.refetch()}
          />
        ) : (fsQ.data ?? []).length === 0 ? (
          <EmptyState
            icon={<Coins size={20} />}
            title={t('methodology.funding.empty', { defaultValue: 'No funding sources yet' })}
            description={t('methodology.funding.empty_desc', {
              defaultValue: 'Add the budget lines this project draws on.',
            })}
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-border-light">
            <table className="min-w-full text-sm">
              <thead className="bg-surface-secondary/40 text-xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">
                    {t('methodology.funding.col_code', { defaultValue: 'Code' })}
                  </th>
                  <th className="px-3 py-2 text-left font-medium">
                    {t('methodology.funding.col_name', { defaultValue: 'Name' })}
                  </th>
                  {!readOnly && <th className="w-24 px-3 py-2" />}
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {(fsQ.data ?? []).map((fs) => (
                  <tr key={fs.id} className="hover:bg-surface-secondary/40">
                    <td className="px-3 py-2 font-mono text-xs text-content-secondary">{fs.code}</td>
                    <td className="px-3 py-2 text-content-primary">{fs.name}</td>
                    {!readOnly && (
                      <td className="px-3 py-2">
                        <div className="flex justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => setModal({ open: true, initial: fs })}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                            aria-label={t('common.edit', { defaultValue: 'Edit' })}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteMut.mutate(fs.id)}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error"
                            aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <FundingSourceModal
        open={modal.open}
        projectId={projectId}
        initial={modal.initial}
        onClose={() => setModal({ open: false, initial: null })}
        onSaved={() => {
          setModal({ open: false, initial: null });
          invalidate();
        }}
      />
    </Card>
  );
}

function FundingSourceModal({
  open,
  projectId,
  initial,
  onClose,
  onSaved,
}: {
  open: boolean;
  projectId: string;
  initial: FundingSource | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!initial;

  const [code, setCode] = useState('');
  const [name, setName] = useState('');

  useEffect(() => {
    if (!open) return;
    setCode(initial?.code ?? '');
    setName(initial?.name ?? '');
  }, [open, initial]);

  const saveMut = useMutation({
    mutationFn: () => {
      if (isEdit && initial) {
        // Only what the user actually edited goes back. Renaming a source used
        // to rewrite its code as it stood when this list was read, undoing
        // anyone else's edit to it without a word. The update route dumps with
        // `exclude_unset=True`, so an omitted field is left alone. Each
        // comparison uses the same expression the prefill effect above uses, so
        // an untouched field always reads as unchanged.
        const patch: { code?: string; name?: string } = {};
        if (code !== (initial.code ?? '')) patch.code = code.trim();
        if (name !== (initial.name ?? '')) patch.name = name.trim();
        return methodologyApi.updateFundingSource(initial.id, projectId, patch);
      }
      return methodologyApi.createFundingSource({
        project_id: projectId,
        code: code.trim(),
        name: name.trim(),
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: isEdit
          ? t('methodology.funding.updated', { defaultValue: 'Funding source updated' })
          : t('methodology.funding.added', { defaultValue: 'Funding source added' }),
      });
      onSaved();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSave = code.trim().length > 0 && name.trim().length > 0 && !saveMut.isPending;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    saveMut.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="sm"
      busy={saveMut.isPending}
      title={
        isEdit
          ? t('methodology.funding.edit_title', { defaultValue: 'Edit funding source' })
          : t('methodology.funding.add_title', { defaultValue: 'Add funding source' })
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saveMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!canSave} loading={saveMut.isPending}>
            {isEdit ? t('common.save', { defaultValue: 'Save' }) : t('common.add', { defaultValue: 'Add' })}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label={t('methodology.funding.code_field', { defaultValue: 'Code' })}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder={t('methodology.funding.code_placeholder', { defaultValue: 'e.g. GRANT' })}
          autoFocus
          maxLength={80}
        />
        <Input
          label={t('methodology.funding.name_field', { defaultValue: 'Name' })}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('methodology.funding.name_placeholder', {
            defaultValue: 'e.g. Government grant',
          })}
          maxLength={255}
        />
      </form>
    </WideModal>
  );
}

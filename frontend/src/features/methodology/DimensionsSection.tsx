// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Analytical-dimensions editor for one methodology. Dimensions (flat reference
// lists or value trees, e.g. the CBS "Chapters" / "Главы") are project-scoped
// rows tied to this methodology slug. Add a dimension with seed values; delete
// removes it and its values.

import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ListTree, Plus, Tags, Trash2 } from 'lucide-react';
import { Badge, Button, Card, EmptyState, ErrorState, Input, Skeleton } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { methodologyApi } from './api';
import type { DimensionKind, DimensionValueCreate } from './types';

interface Props {
  projectId: string;
  methodologySlug: string;
  readOnly: boolean;
}

export function DimensionsSection({ projectId, methodologySlug, readOnly }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [addOpen, setAddOpen] = useState(false);

  const dimsQ = useQuery({
    queryKey: ['methodology', 'dimensions', projectId, methodologySlug],
    queryFn: () => methodologyApi.listDimensions(projectId, methodologySlug),
    enabled: !!projectId && !!methodologySlug,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ['methodology', 'dimensions', projectId, methodologySlug],
    });

  const deleteMut = useMutation({
    mutationFn: (dimensionId: string) => methodologyApi.removeDimension(dimensionId, projectId),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('methodology.dimensions.deleted', { defaultValue: 'Dimension removed' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  return (
    <Card padding="lg">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('methodology.dimensions.title', { defaultValue: 'Analytical dimensions' })}
          </h3>
          <p className="mt-0.5 text-xs text-content-secondary">
            {t('methodology.dimensions.subtitle', {
              defaultValue:
                'Tag estimate lines along extra axes - construction chapters (CBS), section type, stage. Flat lists or value trees.',
            })}
          </p>
        </div>
        {!readOnly && (
          <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setAddOpen(true)}>
            {t('methodology.dimensions.add', { defaultValue: 'Add dimension' })}
          </Button>
        )}
      </div>

      <div className="mt-4">
        {dimsQ.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : dimsQ.isError ? (
          <ErrorState
            title={t('methodology.dimensions.error', { defaultValue: 'Could not load dimensions.' })}
            onRetry={() => dimsQ.refetch()}
          />
        ) : (dimsQ.data ?? []).length === 0 ? (
          <EmptyState
            icon={<Tags size={20} />}
            title={t('methodology.dimensions.empty', { defaultValue: 'No dimensions yet' })}
            description={t('methodology.dimensions.empty_desc', {
              defaultValue: 'Add a dimension to classify estimate lines beyond the cost breakdown.',
            })}
          />
        ) : (
          <div className="space-y-3">
            {(dimsQ.data ?? []).map((dim) => (
              <div
                key={dim.id}
                className="rounded-lg border border-border-light bg-surface-secondary/20 px-3 py-2.5"
              >
                <div className="flex items-center gap-2">
                  {dim.kind === 'tree' ? (
                    <ListTree size={15} className="text-content-tertiary" />
                  ) : (
                    <Tags size={15} className="text-content-tertiary" />
                  )}
                  <span className="text-sm font-medium text-content-primary">{dim.label}</span>
                  <span className="font-mono text-2xs text-content-tertiary">{dim.key}</span>
                  {dim.is_required && (
                    <Badge variant="warning" size="sm">
                      {t('methodology.dimensions.required', { defaultValue: 'Required' })}
                    </Badge>
                  )}
                  <Badge variant="neutral" size="sm">
                    {dim.kind === 'tree'
                      ? t('methodology.dimensions.tree', { defaultValue: 'Tree' })
                      : t('methodology.dimensions.flat', { defaultValue: 'Flat' })}
                  </Badge>
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => deleteMut.mutate(dim.id)}
                      className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error"
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
                {dim.values.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {dim.values.slice(0, 16).map((v) => (
                      <span
                        key={v.id}
                        className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-primary px-2 py-0.5 text-2xs text-content-secondary"
                      >
                        <span className="font-mono text-content-tertiary">{v.code}</span>
                        {v.label}
                      </span>
                    ))}
                    {dim.values.length > 16 && (
                      <span className="text-2xs italic text-content-tertiary">
                        {t('methodology.dimensions.more', {
                          defaultValue: '+{{count}} more',
                          count: dim.values.length - 16,
                        })}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <AddDimensionModal
        open={addOpen}
        projectId={projectId}
        methodologySlug={methodologySlug}
        onClose={() => setAddOpen(false)}
        onAdded={() => {
          setAddOpen(false);
          invalidate();
        }}
      />
    </Card>
  );
}

function AddDimensionModal({
  open,
  projectId,
  methodologySlug,
  onClose,
  onAdded,
}: {
  open: boolean;
  projectId: string;
  methodologySlug: string;
  onClose: () => void;
  onAdded: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [label, setLabel] = useState('');
  const [key, setKey] = useState('');
  const [kind, setKind] = useState<DimensionKind>('flat');
  const [isRequired, setIsRequired] = useState(false);
  // Seed values as "code label" lines, one per row, in a single textarea.
  const [valuesText, setValuesText] = useState('');

  const reset = () => {
    setLabel('');
    setKey('');
    setKind('flat');
    setIsRequired(false);
    setValuesText('');
  };

  const parseValues = (): DimensionValueCreate[] => {
    return valuesText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const sp = line.indexOf(' ');
        if (sp < 0) return { code: line, label: line };
        return { code: line.slice(0, sp).trim(), label: line.slice(sp + 1).trim() };
      });
  };

  const createMut = useMutation({
    mutationFn: () => {
      const derivedKey =
        key.trim() || label.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
      return methodologyApi.createDimension({
        project_id: projectId,
        methodology_slug: methodologySlug,
        key: derivedKey || 'dimension',
        label: label.trim(),
        kind,
        is_required: isRequired,
        values: parseValues(),
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('methodology.dimensions.added', { defaultValue: 'Dimension added' }),
      });
      reset();
      onAdded();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const canSave = label.trim().length > 0 && !createMut.isPending;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    createMut.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="md"
      busy={createMut.isPending}
      title={t('methodology.dimensions.add_title', { defaultValue: 'Add analytical dimension' })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!canSave} loading={createMut.isPending}>
            {t('common.add', { defaultValue: 'Add' })}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label={t('methodology.dimensions.label_field', { defaultValue: 'Label' })}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t('methodology.dimensions.label_placeholder', {
              defaultValue: 'e.g. Construction chapter',
            })}
            autoFocus
          />
          <Input
            label={t('methodology.dimensions.key_field', { defaultValue: 'Key (optional)' })}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="cbs_chapter"
          />
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-content-primary">
              {t('methodology.dimensions.kind_field', { defaultValue: 'Kind' })}
            </span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as DimensionKind)}
              className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary"
            >
              <option value="flat">{t('methodology.dimensions.flat', { defaultValue: 'Flat' })}</option>
              <option value="tree">{t('methodology.dimensions.tree', { defaultValue: 'Tree' })}</option>
            </select>
          </label>
          <label className="mt-5 inline-flex items-center gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              checked={isRequired}
              onChange={(e) => setIsRequired(e.target.checked)}
              className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
            />
            {t('methodology.dimensions.required_field', { defaultValue: 'Required on every line' })}
          </label>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-content-primary">
            {t('methodology.dimensions.values_field', { defaultValue: 'Values (one per line)' })}
          </label>
          <textarea
            value={valuesText}
            onChange={(e) => setValuesText(e.target.value)}
            rows={6}
            placeholder={t('methodology.dimensions.values_placeholder', {
              defaultValue: '1 Site preparation\n2 Main buildings and structures\n3 Auxiliary buildings',
            })}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 font-mono text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
          <p className="text-xs text-content-tertiary">
            {t('methodology.dimensions.values_hint', {
              defaultValue: 'Format: code, a space, then the label. The code is the part before the first space.',
            })}
          </p>
        </div>
      </form>
    </WideModal>
  );
}

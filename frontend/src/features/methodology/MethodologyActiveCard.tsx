// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Project Settings card: choose which estimating methodology this project uses.
// The active methodology is what the cascade compute and BOQ markups read from;
// projects that never pick one fall back to the neutral International default.
// Per the founder, this switch lives in project Settings (not on the editor).

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Layers3, Save, SlidersHorizontal } from 'lucide-react';
import { Badge, Button, Card, CardHeader, Skeleton } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { methodologyApi } from './api';
import { INTERNATIONAL_SLUG } from './types';

interface Props {
  projectId: string;
}

export function MethodologyActiveCard({ projectId }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [draftSlug, setDraftSlug] = useState<string>('');

  const listQ = useQuery({
    queryKey: ['methodology', 'list', projectId],
    queryFn: () => methodologyApi.list(projectId),
    enabled: !!projectId,
  });

  const activeQ = useQuery({
    queryKey: ['methodology', 'active', projectId],
    queryFn: () => methodologyApi.getActive(projectId),
    enabled: !!projectId,
  });

  // Sync the draft to the server's active slug once it loads / changes.
  useEffect(() => {
    if (activeQ.data) setDraftSlug(activeQ.data.methodology_slug);
  }, [activeQ.data]);

  const setActiveMut = useMutation({
    mutationFn: (slug: string) => methodologyApi.setActive(projectId, slug),
    onSuccess: (res) => {
      queryClient.setQueryData(['methodology', 'active', projectId], res);
      setDraftSlug(res.methodology_slug);
      addToast({
        type: 'success',
        title: t('methodology.active.saved', { defaultValue: 'Active methodology updated' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const activeSlug = activeQ.data?.methodology_slug ?? INTERNATIONAL_SLUG;
  const dirty = draftSlug !== '' && draftSlug !== activeSlug;

  // All methodologies visible to the project (built-ins + the project's own
  // clones). The International default is always offered even when its row is
  // not in the list (the backend accepts the built-in slug directly).
  const rows = listQ.data ?? [];
  const hasInternationalRow = rows.some((r) => r.slug === INTERNATIONAL_SLUG);

  return (
    <Card padding="lg" id="methodology">
      <CardHeader
        title={t('methodology.active.title', { defaultValue: 'Estimating methodology' })}
        subtitle={t('methodology.active.subtitle', {
          defaultValue:
            'The markup cascade this project uses to turn direct costs into a final estimate. New projects use the neutral International method until you pick another.',
        })}
        action={
          <Button
            variant="ghost"
            size="sm"
            icon={<SlidersHorizontal size={14} />}
            onClick={() => navigate('/methodologies')}
          >
            {t('methodology.active.manage', { defaultValue: 'Manage methodologies' })}
          </Button>
        }
      />

      <div className="mt-4">
        {listQ.isLoading || activeQ.isLoading ? (
          <Skeleton className="h-10 w-full max-w-md" />
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-content-primary">
                {t('methodology.active.field', { defaultValue: 'Active methodology' })}
              </span>
              <select
                value={draftSlug}
                onChange={(e) => setDraftSlug(e.target.value)}
                className="h-9 min-w-[18rem] rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              >
                {!hasInternationalRow && (
                  <option value={INTERNATIONAL_SLUG}>
                    {t('methodology.active.international', { defaultValue: 'International (neutral default)' })}
                  </option>
                )}
                {rows.map((m) => (
                  <option key={m.id} value={m.slug}>
                    {m.name}
                    {m.scope !== 'project' ? ` ${t('methodology.active.builtin_suffix', { defaultValue: '(built-in)' })}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="primary"
              size="sm"
              icon={<Save size={14} />}
              disabled={!dirty}
              loading={setActiveMut.isPending}
              onClick={() => setActiveMut.mutate(draftSlug)}
            >
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
        )}

        <div className="mt-3 flex items-center gap-2 text-xs text-content-tertiary">
          <Layers3 size={13} />
          <span>
            {t('methodology.active.current', { defaultValue: 'Currently active:' })}{' '}
            <Badge variant="blue" size="sm">
              <span className="font-mono">{activeSlug}</span>
            </Badge>
          </span>
        </div>

        {rows.filter((r) => r.scope === 'project').length === 0 && (
          <button
            type="button"
            onClick={() => navigate('/methodologies')}
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-oe-blue-text hover:underline"
          >
            {t('methodology.active.install_hint', {
              defaultValue: 'Install a country or industry methodology to customise it',
            })}
            <ArrowRight size={12} />
          </button>
        )}
      </div>
    </Card>
  );
}

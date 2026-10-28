// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Split a group: pick a subset of its elements and pull them into a new
// group (POST /runs/{id}/groups/split). Loads the group detail to list its
// element ids. The grouping math stays on the backend; this only chooses
// which elements move.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Split } from 'lucide-react';
import { Button, SideDrawer } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { aiEstimatorApi } from '../api';

export function SplitGroupDrawer({
  runId,
  groupId,
  open,
  onClose,
}: {
  runId: string;
  groupId: string;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [desc, setDesc] = useState('');

  const detailQ = useQuery({
    enabled: open && !!groupId,
    queryKey: ['aiest-group-detail', runId, groupId],
    queryFn: () => aiEstimatorApi.getGroup(runId, groupId),
  });
  const detail = detailQ.data;
  const elementIds = detail?.element_ids ?? [];

  const splitM = useMutation({
    mutationFn: () =>
      aiEstimatorApi.splitGroup(runId, {
        element_ids: [...picked],
        ...(desc.trim() ? { new_description: desc.trim() } : {}),
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('aiest.split.done', { defaultValue: 'Group split' }),
      });
      qc.invalidateQueries({ queryKey: ['aiest-groups', runId] });
      onClose();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.split.failed', { defaultValue: 'Could not split the group' }),
        message: e.message,
      }),
  });

  const toggle = (id: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Disallow moving every element (that would leave an empty source group).
  const canSplit = picked.size > 0 && picked.size < elementIds.length;

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      busy={splitM.isPending}
      widthClass="max-w-md"
      title={t('aiest.split.title', { defaultValue: 'Split group' })}
      subtitle={detail?.description ?? detail?.group_key}
    >
      <div className="space-y-4 p-4">
        <p className="text-xs text-content-secondary">
          {t('aiest.split.help', {
            defaultValue:
              'Select the elements to move into a new group. The rest stay in this group. You cannot move every element.',
          })}
        </p>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-content-primary">
            {t('aiest.split.new_label', { defaultValue: 'New group label' })}
          </label>
          <input
            type="text"
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder={t('aiest.split.new_placeholder', { defaultValue: 'Optional' })}
            className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm"
          />
        </div>

        {detailQ.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-content-tertiary">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('aiest.split.loading', { defaultValue: 'Loading elements...' })}
          </div>
        ) : elementIds.length === 0 ? (
          <p className="py-8 text-center text-sm text-content-tertiary">
            {t('aiest.split.no_elements', { defaultValue: 'This group has no listed elements.' })}
          </p>
        ) : (
          <div className="max-h-72 overflow-y-auto rounded-lg border border-border-light">
            <ul className="divide-y divide-border-light">
              {elementIds.map((eid) => (
                <li key={eid}>
                  <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm hover:bg-surface-secondary">
                    <input
                      type="checkbox"
                      checked={picked.has(eid)}
                      onChange={() => toggle(eid)}
                      className="accent-oe-blue"
                    />
                    <span className="truncate font-mono text-xs text-content-secondary">{eid}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-border-light pt-3">
          <Button variant="ghost" onClick={onClose} disabled={splitM.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            icon={<Split className="h-4 w-4" />}
            disabled={!canSplit}
            loading={splitM.isPending}
            onClick={() => splitM.mutate()}
          >
            {t('aiest.split.confirm', {
              defaultValue: 'Move {{n}} into a new group',
              n: picked.size,
            })}
          </Button>
        </div>
      </div>
    </SideDrawer>
  );
}

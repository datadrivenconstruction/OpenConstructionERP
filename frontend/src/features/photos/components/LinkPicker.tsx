// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Link a photo to a record of a project register. BOQ positions, activities, safety observations
// and locations link from their own screens, where the photo strip already knows the target.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link2, Loader2 } from 'lucide-react';
import { fetchPunchItems } from '@/features/punchlist/api';
import { fetchInspections } from '@/features/inspections/api';
import { fetchFieldReports } from '@/features/fieldreports/api';
import { listDiaries } from '@/features/daily-diary/api';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { addLink, photosKeys, type TargetKind } from '../api';

export const PICKABLE_KINDS = ['punch_item', 'inspection', 'field_report', 'diary'] as const;
type PickableKind = (typeof PICKABLE_KINDS)[number];

interface Option {
  id: string;
  label: string;
}

async function loadOptions(kind: PickableKind, projectId: string): Promise<Option[]> {
  switch (kind) {
    case 'punch_item':
      return (await fetchPunchItems(projectId, { limit: 100 })).items.map((i) => ({ id: i.id, label: i.title }));
    case 'inspection':
      return (await fetchInspections({ project_id: projectId })).items.map((i) => ({
        id: i.id,
        label: [i.inspection_number, i.title].filter(Boolean).join(' '),
      }));
    case 'field_report':
      return (await fetchFieldReports(projectId)).map((r) => ({ id: r.id, label: r.report_date }));
    case 'diary':
      return (await listDiaries({ project_id: projectId, limit: 100 })).items.map((d) => ({
        id: d.id,
        label: d.diary_date,
      }));
  }
}

interface LinkPickerProps {
  photoId: string;
  projectId: string;
  linked: { target_kind: string; target_id: string }[];
}

export function LinkPicker({ photoId, projectId, linked }: LinkPickerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [kind, setKind] = useState<PickableKind>('punch_item');
  const [search, setSearch] = useState('');
  const options = useQuery({
    queryKey: ['photo-archive', 'link-options', projectId, kind],
    queryFn: () => loadOptions(kind, projectId),
    staleTime: 60_000,
  });
  const taken = useMemo(
    () => new Set(linked.filter((l) => l.target_kind === kind).map((l) => l.target_id)),
    [linked, kind],
  );
  const shown = (options.data ?? [])
    .filter((o) => !taken.has(o.id))
    .filter((o) => !search || o.label.toLowerCase().includes(search.toLowerCase()))
    .slice(0, 30);

  const link = useMutation({
    mutationFn: (targetId: string) => addLink(photoId, kind as TargetKind, targetId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: photosKeys.all });
      addToast({ type: 'success', title: t('photoArchive.links.added') });
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.links.add_failed'), message: getErrorMessage(err) }),
  });

  return (
    <div className="space-y-2" data-testid="link-picker">
      <div className="flex gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as PickableKind)}
          className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs"
          aria-label={t('photoArchive.links.kind')}
        >
          {PICKABLE_KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`photoArchive.target.${k}`)}
            </option>
          ))}
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('photoArchive.links.search')}
          className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs"
        />
      </div>
      {options.isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin text-content-tertiary" aria-hidden />
      ) : options.isError ? (
        <p className="text-xs text-semantic-error">{t('photoArchive.links.load_failed')}</p>
      ) : shown.length === 0 ? (
        <p className="text-xs text-content-tertiary">{t('photoArchive.links.nothing')}</p>
      ) : (
        <ul className="max-h-40 space-y-1 overflow-y-auto">
          {shown.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                disabled={link.isPending}
                onClick={() => link.mutate(o.id)}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-surface-secondary"
              >
                <Link2 className="h-3 w-3 shrink-0 text-content-tertiary" aria-hidden />
                <span className="truncate">{o.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

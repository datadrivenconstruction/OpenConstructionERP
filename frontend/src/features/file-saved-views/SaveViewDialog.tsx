// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SaveViewDialog — modal that captures a snapshot of the current
// /files filter under a name + icon + optional share-with-project.

import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Bookmark,
  ClipboardList,
  FileBarChart,
  FileText,
  Image as ImageIcon,
  Layers,
  Layout,
  Pin,
  Tag as TagIcon,
} from 'lucide-react';

import { WideModal } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui/Button';
import { Input } from '@/shared/ui/Input';
import { useCreateView } from './hooks';
import type { FilterSnapshot } from './types';

interface SaveViewDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string | null | undefined;
  filter: FilterSnapshot;
}

/** Curated lucide-react icon set offered in the picker. The string
 * value is the canonical lucide key — stored on the view as
 * ``icon`` and re-resolved by the rail. */
//
// Each option carries its own name because the nine buttons are otherwise
// indistinguishable to anyone who cannot see them: here the picture IS the
// label, so without these a screen reader announces nine controls called
// "button". The names are local keys rather than reuse from the common
// namespace on purpose. `common.close` and `common.cancel` are action names
// with one correct rendering anywhere, while these nine are picture names that
// only work as a mutually distinct set, and a borrowed key drifts when someone
// edits it for an unrelated reason with this row nowhere in front of them.
//
// Translators: all nine must stay distinct from one another after translation,
// since the name is the only thing separating one button from the next. Layout
// and Layers are the pair most likely to collapse together.
const ICON_OPTIONS: Array<{ key: string; labelKey: string; label: string; Icon: typeof Bookmark }> = [
  { key: 'bookmark', labelKey: 'files.views.icon_bookmark', label: 'Bookmark', Icon: Bookmark },
  { key: 'clipboard-list', labelKey: 'files.views.icon_clipboard', label: 'Clipboard', Icon: ClipboardList },
  { key: 'file-text', labelKey: 'files.views.icon_document', label: 'Document', Icon: FileText },
  { key: 'image', labelKey: 'files.views.icon_image', label: 'Image', Icon: ImageIcon },
  { key: 'layout', labelKey: 'files.views.icon_layout', label: 'Layout', Icon: Layout },
  { key: 'layers', labelKey: 'files.views.icon_layers', label: 'Layers', Icon: Layers },
  { key: 'file-bar-chart', labelKey: 'files.views.icon_bar_chart', label: 'Bar chart', Icon: FileBarChart },
  { key: 'tag', labelKey: 'files.views.icon_tag', label: 'Tag', Icon: TagIcon },
  { key: 'pin', labelKey: 'files.views.icon_pin', label: 'Pin', Icon: Pin },
];

export function SaveViewDialog({ open, onClose, projectId, filter }: SaveViewDialogProps) {
  const { t } = useTranslation();
  const iconGroupLabelId = useId();
  const createMut = useCreateView(projectId);

  const [name, setName] = useState('');
  const [icon, setIcon] = useState<string>('bookmark');
  const [shareWithProject, setShareWithProject] = useState(false);
  const [pinOnSave, setPinOnSave] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName('');
      setIcon('bookmark');
      setShareWithProject(false);
      setPinOnSave(false);
      setError(null);
    }
  }, [open]);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t('files.views.error_name_required', { defaultValue: 'Name is required' }));
      return;
    }
    setError(null);
    try {
      await createMut.mutateAsync({
        name: trimmed,
        icon,
        project_id: projectId ?? null,
        filter_json: filter,
        is_pinned: pinOnSave,
        is_shared: shareWithProject,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('files.views.dialog_title', { defaultValue: 'Save current filter as view' })}
      subtitle={t('files.views.dialog_subtitle', {
        defaultValue: 'Re-apply this filter from the saved-views rail with one click.',
      })}
      size="md"
      busy={createMut.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={submit} loading={createMut.isPending}>
            {t('files.views.dialog_save', { defaultValue: 'Save view' })}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-content-primary">
            {t('files.views.dialog_name_label', { defaultValue: 'Name' })}
          </span>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('files.views.dialog_name_placeholder', {
              defaultValue: 'e.g. Structural drawings for review',
            })}
            data-testid="save-view-name-input"
            autoFocus
            maxLength={128}
          />
        </label>
        <div className="flex flex-col gap-1.5 text-sm">
          <span id={iconGroupLabelId} className="font-medium text-content-primary">
            {t('files.views.dialog_icon_label', { defaultValue: 'Icon' })}
          </span>
          {/*
            role="group" rather than radiogroup, deliberately. Exactly one icon
            can be chosen, so the semantics argue for a radiogroup, but that
            role carries a keyboard contract: a reader told this is a radiogroup
            will press the arrow keys and expect the selection to move. Claiming
            the role without implementing roving focus would be a false promise,
            which is worse than the plain buttons it replaced. role="group"
            accepts a name and promises nothing about the keyboard.
          */}
          <div
            role="group"
            aria-labelledby={iconGroupLabelId}
            className="flex flex-wrap gap-1.5"
            data-testid="save-view-icon-grid"
          >
            {ICON_OPTIONS.map(({ key, labelKey, label, Icon }) => (
              <button
                key={key}
                type="button"
                onClick={() => setIcon(key)}
                aria-label={t(labelKey, { defaultValue: label })}
                aria-pressed={icon === key}
                className={clsx(
                  'flex h-8 w-8 items-center justify-center rounded-md border',
                  icon === key
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                )}
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={pinOnSave}
              onChange={(e) => setPinOnSave(e.target.checked)}
              data-testid="save-view-pin-checkbox"
            />
            <span>{t('files.views.dialog_pin', { defaultValue: 'Pin to top of rail' })}</span>
          </label>
          {projectId && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={shareWithProject}
                onChange={(e) => setShareWithProject(e.target.checked)}
                data-testid="save-view-share-checkbox"
              />
              <span>
                {t('files.views.dialog_share', {
                  defaultValue: 'Share with everyone on this project',
                })}
              </span>
            </label>
          )}
        </div>
        {error && (
          <div
            role="alert"
            className="rounded-md border border-semantic-error/40 bg-semantic-error/10 px-3 py-2 text-sm text-semantic-error"
          >
            {error}
          </div>
        )}
      </div>
    </WideModal>
  );
}

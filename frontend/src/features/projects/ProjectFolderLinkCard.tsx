// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The link to the project's folder outside the platform (shared drive, cloud
// folder). Optional; emptying the box sends null, which clears it. The same
// rule the server applies is checked here first so a typo is explained in
// words instead of coming back as a 422.

import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FolderOpen, Save } from 'lucide-react';
import { Button, Card, CardHeader } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi, type Project } from './api';
import { FOLDER_LINK_MAX, folderLinkProblem } from './folderLink';

export function ProjectFolderLinkCard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const saved = project.external_folder_url ?? '';
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);

  const value = draft.trim();
  const problem = folderLinkProblem(value);

  const saveMut = useMutation({
    mutationFn: () => projectsApi.update(project.id, { external_folder_url: value || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({
        type: 'success',
        title: t('project.settings.saved', { defaultValue: 'Project settings saved' }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('project.settings.save_failed', { defaultValue: 'Failed to save settings' }),
        message: getErrorMessage(err),
      }),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (problem || value === saved) return;
    saveMut.mutate();
  };

  return (
    <Card padding="lg">
      <CardHeader
        title={t('project.settings.folder.title', { defaultValue: 'External folder' })}
        subtitle={t('project.settings.folder.subtitle', {
          defaultValue:
            'A link to where the project files live outside the platform, such as a shared drive or a cloud folder. It appears on the project page.',
        })}
      />
      <form onSubmit={submit} className="mt-4 flex flex-col gap-3 md:flex-row md:flex-wrap md:items-end">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <label htmlFor="project-folder-link" className="text-sm font-medium text-content-primary">
            {t('project.settings.folder.label', { defaultValue: 'Folder link' })}
          </label>
          <input
            id="project-folder-link"
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="https://, smb://, \\server\share"
            autoComplete="off"
            aria-invalid={problem !== null || undefined}
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          />
        </div>
        <Button
          variant="primary"
          size="sm"
          type="submit"
          icon={<Save size={14} />}
          loading={saveMut.isPending}
          disabled={problem !== null || value === saved}
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
        <p className="flex items-center gap-1.5 text-xs text-content-tertiary md:basis-full">
          <FolderOpen size={12} className="shrink-0" />
          {t('project.settings.folder.helper', {
            defaultValue: 'A web link, a file: or smb: link, or a network path such as \\\\server\\share.',
          })}
        </p>
        {problem && (
          <p role="alert" className="text-xs text-semantic-error md:basis-full">
            {problem === 'too_long'
              ? t('project.settings.folder.too_long', {
                  max: FOLDER_LINK_MAX,
                  defaultValue: 'The link is too long. Use at most {{max}} characters.',
                })
              : t('project.settings.folder.invalid', {
                  defaultValue: 'Start with http://, https://, file://, smb:// or a network path like \\\\server\\share.',
                })}
          </p>
        )}
      </form>
    </Card>
  );
}

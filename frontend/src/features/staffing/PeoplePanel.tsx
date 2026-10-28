// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The people on the project who have a personnel file: name, roles, period
// and whether they are cleared to work. Nothing of a file's content is shown
// here, and a file opens only for a reader the server lets in (`can.open`).
// A new file is offered for the people the server lists as candidates.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderLock, Lock, Plus } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import type { FileCandidate, PersonnelFileRow, StaffingCatalogue } from './api';
import { CreateFileDialog } from './FileDialogs';
import { FILE_STATUS, catalogueName, vocab, whyNot, type LabelContext } from './labels';
import { ClearedBadge, FILE_TONE, ToneBadge, personLabel } from './StaffingBits';

export interface PeoplePanelProps {
  projectId: string;
  files: PersonnelFileRow[];
  candidates: FileCandidate[];
  catalogue: StaffingCatalogue | null;
  labels: LabelContext;
  onOpen: (fileId: string) => void;
  onChanged: () => void;
}

export function PeoplePanel({ projectId, files, candidates, catalogue, labels, onOpen, onChanged }: PeoplePanelProps) {
  const { t } = useTranslation();
  const [creating, setCreating] = useState(false);
  // Whether a file can be opened for anybody is the server's call, per person.
  const mayCreate = candidates.some((c) => c.can.create_file.allowed);
  const createRefusal = mayCreate
    ? ''
    : candidates.length === 0
      ? t('staffing.people.no_candidates', {
          defaultValue: 'Nobody on the staffing plan is waiting for a personnel file. Put a person on a position first.',
        })
      : whyNot(labels.t, candidates[0]!.can.create_file) || t('staffing.file.no_access', { defaultValue: 'You cannot open this file.' });

  const dialog = (
    <CreateFileDialog
      open={creating}
      projectId={projectId}
      labels={labels}
      candidates={candidates}
      onClose={() => setCreating(false)}
      onDone={onChanged}
    />
  );

  if (files.length === 0) {
    return (
      <>
        <EmptyState
          icon={<FolderLock size={28} />}
          title={t('staffing.people.empty_title', { defaultValue: 'No personnel files yet' })}
          description={t('staffing.people.empty_body', {
            defaultValue:
              'A personnel file tracks the documents a person needs before starting work, plus travel and leave. Open one for each person you put on a position.',
          })}
          action={
            mayCreate
              ? {
                  label: t('staffing.file.create', { defaultValue: 'Open personnel file' }),
                  onClick: () => setCreating(true),
                }
              : undefined
          }
        />
        {!mayCreate && (
          <p className="mt-2 text-center text-sm text-content-secondary" role="status" data-testid="create-file-refused">
            {createRefusal}
          </p>
        )}
        {dialog}
      </>
    );
  }

  return (
    <div className="space-y-3" data-testid="people-panel">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm text-content-secondary">
          {t('staffing.people.intro', {
            defaultValue: 'A file opens only for the area owner, the line manager of the position and the person concerned. Every opening is logged.',
          })}
        </p>
        <Button
          size="sm"
          icon={<Plus size={14} />}
          disabled={!mayCreate}
          title={createRefusal || undefined}
          onClick={() => setCreating(true)}
          data-testid="create-file"
        >
          {t('staffing.file.create', { defaultValue: 'Open personnel file' })}
        </Button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[680px] text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
              <th scope="col" className="px-3 py-2 font-medium">{t('staffing.fill.person', { defaultValue: 'Person' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('staffing.people.roles', { defaultValue: 'Roles' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.period', { defaultValue: 'Period' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('staffing.people.clearance', { defaultValue: 'Clearance' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('staffing.file.title', { defaultValue: 'Personnel file' })}</th>
              <th scope="col" className="px-3 py-2 font-medium">
                <span className="sr-only">{t('staffing.actions', { defaultValue: 'Actions' })}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.id} className="border-b border-border-light last:border-b-0" data-testid="file-row">
                <td className="px-3 py-2 font-medium text-content-primary">{personLabel(labels.t, f.name)}</td>
                <td className="px-3 py-2 text-content-secondary">
                  {f.roles.length > 0
                    ? fmtList(f.roles.map((r) => catalogueName(labels, catalogue, 'role', r)))
                    : t('staffing.people.no_role', { defaultValue: 'No position yet' })}
                </td>
                <td className="px-3 py-2 text-content-secondary">
                  {f.start
                    ? f.end
                      ? t('staffing.period_range', { defaultValue: '{{from}} to {{to}}', from: fmtDate(f.start), to: fmtDate(f.end) })
                      : t('staffing.period_from', { defaultValue: 'From {{from}}', from: fmtDate(f.start) })
                    : t('staffing.not_set', { defaultValue: 'Not set' })}
                </td>
                <td className="px-3 py-2">
                  {f.status === 'anonymised' ? null : <ClearedBadge cleared={f.cleared_to_work} />}
                </td>
                <td className="px-3 py-2">
                  <ToneBadge tone={FILE_TONE[f.status]}>{vocab(t, FILE_STATUS, f.status)}</ToneBadge>
                </td>
                <td className="px-3 py-2 text-right">
                  {f.can.open.allowed ? (
                    <Button variant="secondary" size="sm" onClick={() => onOpen(f.id)} data-testid="open-file">
                      {t('staffing.people.open', { defaultValue: 'Open file' })}
                    </Button>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-content-tertiary" data-testid="file-closed">
                      <Lock size={12} aria-hidden />
                      {whyNot(labels.t, f.can.open) || t('staffing.file.no_access', { defaultValue: 'You cannot open this file.' })}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dialog}
    </div>
  );
}

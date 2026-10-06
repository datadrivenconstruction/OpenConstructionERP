// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The last screen when adding to an installed module: "Update module".
 *
 * It says what will be added, in the words the person used, and what happens
 * to what is already recorded: nothing. The files are one click away, as on
 * the create screen. A refusal from the server is shown above it by the
 * wizard, in plain words (see RefusalNotice).
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderTree, Link2, ListChecks, Loader2, Minus, PencilLine, Plus, Puzzle } from 'lucide-react';

import type { ModuleSpec, PreviewResponse } from '../api';
import { featuresOf } from '../draft';
import { FEATURE_TITLES, TARGET_NAMES, say } from '../copy';
import { hasAdditions, type Additions } from '../upgrade';
import { PreviewFiles } from './CreateScreen';
import { Disclosure, ModuleIcon, SectionHeading } from './shared';

interface UpdateScreenProps {
  spec: ModuleSpec;
  additions: Additions;
  preview: PreviewResponse | null;
  previewing: boolean;
  /** Nothing is recorded yet, so the register is set up again as shown. */
  empty?: boolean;
}

const chip = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium';

export function UpdateScreen({ spec, additions, preview, previewing, empty = false }: UpdateScreenProps) {
  const { t } = useTranslation();
  const [filesOpen, setFilesOpen] = useState(false);
  const firstStage = additions.features.includes('status') ? featuresOf(spec).status?.states[0]?.label : undefined;

  return (
    <div className="space-y-5" data-testid="module-builder-update-screen">
      <section className="rounded-2xl border border-border-light p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
            <ModuleIcon name={spec.icon} />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('module_builder.ready_to_update', { defaultValue: 'Ready to update' })}
            </p>
            <p className="break-words text-lg font-semibold text-content-primary">{spec.display_name}</p>
          </div>
        </div>

        {!hasAdditions(additions) ? (
          <p className="mt-4 text-sm text-content-secondary" data-testid="module-builder-update-nothing">
            {t('module_builder.update_nothing', {
              defaultValue: 'Nothing has changed yet. Go back and add a field, a check or a function.',
            })}
          </p>
        ) : (
          <div className="mt-4 space-y-3" data-testid="module-builder-update-additions">
            {additions.fields.length > 0 && (
              <div>
                <SectionHeading icon={<Plus size={12} />}>
                  {t('module_builder.update_new_fields', { defaultValue: 'New fields' })}
                </SectionHeading>
                <ul className="flex flex-wrap gap-1.5">
                  {additions.fields.map((field) => (
                    <li key={field.name} className={`${chip} bg-surface-secondary text-content-secondary`}>
                      {field.label || field.name}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {additions.links.length > 0 && (
              <div>
                <SectionHeading icon={<Link2 size={12} />}>
                  {t('module_builder.update_new_links', { defaultValue: 'New links' })}
                </SectionHeading>
                <ul className="flex flex-wrap gap-1.5">
                  {additions.links.map((field) => (
                    <li key={field.name} className={`${chip} bg-oe-blue/10 text-oe-blue-text`}>
                      {field.target ? say(t, TARGET_NAMES[field.target]) : field.label}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {additions.features.length > 0 && (
              <div>
                <SectionHeading icon={<Puzzle size={12} />}>
                  {t('module_builder.update_new_functions', { defaultValue: 'New functions' })}
                </SectionHeading>
                <ul className="flex flex-wrap gap-1.5">
                  {additions.features.map((name) => (
                    <li key={name} className={`${chip} bg-surface-secondary text-content-secondary`}>
                      {say(t, FEATURE_TITLES[name])}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {additions.removed.length > 0 && (
              <div data-testid="module-builder-update-removed">
                <SectionHeading icon={<Minus size={12} />}>
                  {t('module_builder.update_removed_fields', { defaultValue: 'Fields taken away' })}
                </SectionHeading>
                <ul className="flex flex-wrap gap-1.5">
                  {additions.removed.map((label) => (
                    <li key={label} className={`${chip} bg-surface-secondary text-content-tertiary line-through`}>
                      {label}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {additions.choices.length > 0 && (
              <div data-testid="module-builder-update-choices">
                <SectionHeading icon={<Plus size={12} />}>
                  {t('module_builder.update_new_choices', { defaultValue: 'New choices' })}
                </SectionHeading>
                <ul className="flex flex-wrap gap-1.5">
                  {additions.choices.map(({ field, choice }) => (
                    <li key={`${field}:${choice}`} className={`${chip} bg-surface-secondary text-content-secondary`}>
                      {t('module_builder.update_choice_in', { field, choice, defaultValue: '{{choice}} in {{field}}' })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {additions.stages.length > 0 && (
              <div data-testid="module-builder-update-stages">
                <SectionHeading icon={<Plus size={12} />}>
                  {t('module_builder.update_new_stages', { defaultValue: 'New stages' })}
                </SectionHeading>
                <ul className="flex flex-wrap gap-1.5">
                  {additions.stages.map((stage) => (
                    <li key={stage} className={`${chip} bg-surface-secondary text-content-secondary`}>
                      {stage}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {additions.reworded && (
              <p
                className="flex items-center gap-1.5 text-sm text-content-secondary"
                data-testid="module-builder-update-reworded"
              >
                <PencilLine size={14} className="shrink-0 text-content-tertiary" />
                {t('module_builder.update_reworded', {
                  defaultValue: 'Your changes to what is already there are saved too.',
                })}
              </p>
            )}
            {additions.rules.length > 0 && (
              <p className="flex items-center gap-1.5 text-sm text-content-secondary">
                <ListChecks size={14} className="shrink-0 text-content-tertiary" />
                {t('module_builder.update_new_checks', {
                  count: additions.rules.length,
                  defaultValue_one: '{{count}} new check runs every time an entry is saved.',
                  defaultValue_other: '{{count}} new checks run every time an entry is saved.',
                })}
              </p>
            )}
          </div>
        )}

        <p className="mt-4 text-xs text-content-tertiary" data-testid="module-builder-update-note">
          {empty
            ? t('module_builder.update_note_empty', {
                defaultValue: 'Nothing is recorded yet, so the register is set up again exactly as shown here.',
              })
            : t('module_builder.update_note', {
                defaultValue:
                  'Entries already recorded stay as they are. New fields start empty and new links unset, until someone fills them in.',
              })}
          {!empty && firstStage && (
            <>
              {' '}
              {t('module_builder.update_note_status', {
                stage: firstStage,
                defaultValue: 'Every existing entry starts at the stage “{{stage}}”.',
              })}
            </>
          )}
        </p>
      </section>

      <Disclosure
        open={filesOpen}
        onToggle={() => setFilesOpen(!filesOpen)}
        title={t('module_builder.what_changes', { defaultValue: 'What will change' })}
        hint={t('module_builder.what_changes_hint', {
          defaultValue: 'The files rewritten on this instance and the address the module answers on.',
        })}
        icon={<FolderTree size={15} />}
        testId="module-builder-what-changes"
      >
        {preview && !previewing ? (
          <PreviewFiles preview={preview} />
        ) : (
          <p className="flex items-center gap-2 text-xs text-content-tertiary">
            <Loader2 size={13} className="animate-spin" />
            {t('module_builder.preparing', { defaultValue: 'Preparing the files…' })}
          </p>
        )}
      </Disclosure>
    </div>
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Screen 3: "Create", and the screen after it.
 *
 * A short summary in plain words, and one button. The files the platform will
 * write and the address the module will answer on are one click away under
 * "What will be created", not on the way: the module-builder exception in the
 * platform rules rests on a person being able to see what is installed before
 * it is, and that stays true, without making a site engineer read file names.
 *
 * The preview behind this screen is bound to the exact specification by a
 * review token, and the wizard asks for a fresh one whenever the spec changed
 * since the last one, so what is installed is always what was rendered here.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, FileCode, FolderTree, Link2, Loader2, Puzzle } from 'lucide-react';

import type { InstalledModule, ModuleSpec, PreviewResponse } from '../api';
import { featuresOf } from '../draft';
import { FEATURE_TITLES, TARGET_NAMES, say } from '../copy';
import { Disclosure, ModuleIcon } from './shared';

interface CreateScreenProps {
  spec: ModuleSpec;
  /** The preview for this exact spec, or null while it is being made. */
  preview: PreviewResponse | null;
  previewing: boolean;
}

export function CreateScreen({ spec, preview, previewing }: CreateScreenProps) {
  const { t } = useTranslation();
  const [filesOpen, setFilesOpen] = useState(false);
  const features = featuresOf(spec);
  const links = spec.entity.fields.filter((f) => f.type === 'link' && f.target);
  const functions = (['status', 'due', 'export', 'comments'] as const).filter((name) => Boolean(features[name]));

  return (
    <div className="space-y-5" data-testid="module-builder-create">
      <section className="rounded-2xl border border-border-light p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
            <ModuleIcon name={spec.icon} />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('module_builder.ready_to_create', { defaultValue: 'Ready to create' })}
            </p>
            <p className="break-words text-lg font-semibold text-content-primary">{spec.display_name}</p>
            <p className="mt-1 text-sm text-content-secondary">
              {t('module_builder.create_summary_fields', {
                count: spec.entity.fields.length,
                defaultValue_one: 'Each entry holds {{count}} field.',
                defaultValue_other: 'Each entry holds {{count}} fields.',
              })}{' '}
              {t('module_builder.create_summary_checks', {
                count: spec.rules.length,
                defaultValue_one: '{{count}} check runs every time one is saved.',
                defaultValue_other: '{{count}} checks run every time one is saved.',
              })}
            </p>
          </div>
        </div>

        {(links.length > 0 || functions.length > 0) && (
          <ul className="mt-4 flex flex-wrap gap-1.5">
            {links.map((field) => (
              <li
                key={field.name}
                className="inline-flex items-center gap-1.5 rounded-full bg-oe-blue/10 px-2.5 py-1 text-xs font-medium text-oe-blue-text"
              >
                <Link2 size={12} />
                {field.target ? say(t, TARGET_NAMES[field.target]) : field.label}
              </li>
            ))}
            {functions.map((name) => (
              <li
                key={name}
                className="inline-flex items-center gap-1.5 rounded-full bg-surface-secondary px-2.5 py-1 text-xs font-medium text-content-secondary"
              >
                <Puzzle size={12} />
                {say(t, FEATURE_TITLES[name])}
              </li>
            ))}
          </ul>
        )}

        <p className="mt-4 text-xs text-content-tertiary">
          {t('module_builder.create_note', {
            defaultValue:
              'It appears in the menu straight away, no restart needed. A platform upgrade leaves it alone, and removing it later keeps what was recorded unless you ask otherwise.',
          })}
        </p>
      </section>

      <Disclosure
        open={filesOpen}
        onToggle={() => setFilesOpen(!filesOpen)}
        title={t('module_builder.what_created', { defaultValue: 'What will be created' })}
        hint={t('module_builder.what_created_hint', {
          defaultValue: 'The files written to this instance and the address the module answers on.',
        })}
        icon={<FolderTree size={15} />}
        testId="module-builder-what-created"
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

export function PreviewFiles({ preview }: { preview: PreviewResponse }) {
  const { t } = useTranslation();
  // The longest file sets the scale, so the bars compare the files with each
  // other rather than against a number nobody has in their head.
  const longest = preview.files.reduce((max, file) => Math.max(max, file.lines), 0);

  return (
    <div className="space-y-3" data-testid="module-builder-review">
      <p className="text-sm text-content-primary">
        {t('module_builder.review_summary', {
          files: preview.files.length,
          lines: preview.total_lines,
          defaultValue: '{{files}} files, {{lines}} lines. Nothing has been written yet.',
        })}
      </p>
      <p className="break-words text-xs text-content-tertiary">
        {t('module_builder.review_url', {
          path: preview.base_path,
          defaultValue: 'It will answer on {{path}} as soon as it is installed.',
        })}
      </p>
      <ul className="divide-y divide-border-light rounded-xl border border-border-light">
        {preview.files.map((file) => (
          <li key={file.path} className="flex items-center justify-between gap-3 px-3 py-1.5 text-xs">
            <span className="flex min-w-0 items-center gap-2 text-content-secondary">
              <FileCode size={13} className="shrink-0 text-content-quaternary" />
              <span className="truncate font-mono">{file.path}</span>
            </span>
            <span className="flex shrink-0 items-center gap-2 text-content-tertiary">
              <span aria-hidden className="hidden h-1 w-16 rounded-full bg-surface-tertiary sm:block">
                <span
                  className="block h-full rounded-full bg-oe-blue/50"
                  style={{ width: longest > 0 ? `${Math.max(4, (file.lines / longest) * 100)}%` : '0%' }}
                />
              </span>
              {/* Deliberately not a counted key: `count` would make i18next
                  demand a plural form per language for a string whose natural
                  rendering in several of them is "lines: 96". */}
              {t('module_builder.review_lines', { lines: file.lines, defaultValue: '{{lines}} lines' })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DoneScreen({ installed, updated = false }: { installed: InstalledModule; updated?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2 py-6 text-center" data-testid="module-builder-done">
      {/* The ring takes its alpha from the base hue rather than from `-bg`,
          because the dark-mode `-bg` value is already an rgba() wash and a
          modifier on it would read stronger than the plain class. */}
      <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-semantic-success-bg text-semantic-success ring-8 ring-semantic-success/20">
        <Check size={28} strokeWidth={2.5} />
      </span>
      <p className="pt-2 text-lg font-semibold text-content-primary">{installed.display_name}</p>
      <p className="text-sm text-content-secondary">
        {updated
          ? t('module_builder.done_updated', {
              defaultValue: 'Your register is updated. Entries already recorded are as they were.',
            })
          : t('module_builder.done_ready', { defaultValue: 'Your register is ready to use. No restart is needed.' })}
      </p>
      <p className="text-xs text-content-tertiary">
        {t('module_builder.create_summary_fields', {
          count: installed.field_count,
          defaultValue_one: 'Each entry holds {{count}} field.',
          defaultValue_other: 'Each entry holds {{count}} fields.',
        })}{' '}
        {t('module_builder.create_summary_checks', {
          count: installed.rule_count,
          defaultValue_one: '{{count}} check runs every time one is saved.',
          defaultValue_other: '{{count}} checks run every time one is saved.',
        })}
      </p>
    </div>
  );
}

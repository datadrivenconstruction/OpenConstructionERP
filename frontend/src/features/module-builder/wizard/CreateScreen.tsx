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
import {
  Check,
  ChevronRight,
  Database,
  FileCode,
  FolderTree,
  LayoutList,
  Link2,
  Loader2,
  Puzzle,
  ShieldCheck,
  Undo2,
  Users,
} from 'lucide-react';
import type { ReactNode } from 'react';
import clsx from 'clsx';

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

      </section>

      <InstallEffects spec={spec} />

      <Disclosure
        open={filesOpen}
        onToggle={() => setFilesOpen(!filesOpen)}
        title={t('module_builder.what_created_files', { defaultValue: 'The files, to read before you create it' })}
        hint={t('module_builder.what_created_files_hint', {
          defaultValue: 'Generated from your specification, not written by an AI. Open any file to read it line by line.',
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

/**
 * What pressing Create does, in plain words and always on screen.
 *
 * The platform rule that lets this one place install code at runtime rests on
 * the person knowing what they are installing. File names answer that for a
 * developer; this list answers it for everyone else, from the spec itself, so
 * it is right before the preview has even come back.
 */
export function InstallEffects({ spec }: { spec: ModuleSpec }) {
  const { t } = useTranslation();
  const plural = spec.entity.plural_name.trim() || spec.entity.display_name;
  const items: Array<{ icon: ReactNode; text: string; testId: string }> = [
    {
      icon: <Database size={14} />,
      testId: 'table',
      text: t('module_builder.install_effect_table', {
        entries: plural,
        defaultValue: 'A new table in the database for {{entries}}, with one column per field.',
      }),
    },
    {
      icon: <LayoutList size={14} />,
      testId: 'screen',
      text: t('module_builder.install_effect_screen', {
        defaultValue: 'A page with a searchable list and a form to add and edit entries, opened from the Module builder page.',
      }),
    },
    {
      icon: <ShieldCheck size={14} />,
      testId: 'checks',
      text: t('module_builder.install_effect_checks', {
        defaultValue: 'Its checks run on the server every time an entry is saved, and an entry that fails one is not saved.',
      }),
    },
    {
      icon: <Users size={14} />,
      testId: 'permissions',
      text: spec.entity.project_scoped
        ? t('module_builder.install_effect_permissions_project', {
            defaultValue: 'Entries belong to a project. Viewers can read them, editors add and change them, managers delete them.',
          })
        : t('module_builder.install_effect_permissions', {
            defaultValue: 'Viewers can read the entries, editors add and change them, managers delete them.',
          }),
    },
    {
      icon: <Undo2 size={14} />,
      testId: 'undo',
      text: t('module_builder.install_effect_undo', {
        defaultValue: 'No restart. You can add fields later, or remove the module; its entries are kept unless you choose to delete them.',
      }),
    },
  ];

  return (
    <section className="rounded-2xl border border-border-light p-4 sm:p-5" data-testid="module-builder-install-effects">
      <h3 className="text-sm font-semibold text-content-primary">
        {t('module_builder.install_effects_title', { defaultValue: 'What happens when you press Create module' })}
      </h3>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li
            key={item.testId}
            className="flex items-start gap-2.5 text-sm text-content-secondary"
            data-testid={`module-builder-install-effect-${item.testId}`}
          >
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-surface-secondary text-content-tertiary">
              {item.icon}
            </span>
            <span className="min-w-0">{item.text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PreviewFiles({ preview }: { preview: PreviewResponse }) {
  const { t } = useTranslation();
  // One file open at a time: the content can run to a couple of hundred
  // lines, and two of those stacked push the Create button out of reach.
  const [openPath, setOpenPath] = useState<string | null>(null);
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
        {preview.files.map((file) => {
          const isOpen = openPath === file.path;
          return (
            <li key={file.path} className="text-xs">
              <button
                type="button"
                onClick={() => setOpenPath(isOpen ? null : file.path)}
                aria-expanded={isOpen}
                className="flex w-full items-center justify-between gap-3 px-3 py-1.5 text-start hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                data-testid={`module-builder-file-${file.path}`}
              >
                <span className="flex min-w-0 items-center gap-2 text-content-secondary">
                  <ChevronRight
                    size={12}
                    aria-hidden
                    className={clsx('shrink-0 text-content-quaternary transition-transform', isOpen && 'rotate-90')}
                  />
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
              </button>
              {isOpen && (
                <pre
                  className="max-h-80 overflow-auto border-t border-border-light bg-surface-secondary/60 px-3 py-2 font-mono text-[11px] leading-relaxed text-content-secondary"
                  data-testid={`module-builder-file-content-${file.path}`}
                >
                  {file.content}
                </pre>
              )}
            </li>
          );
        })}
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
      {!updated && (
        <p className="mx-auto max-w-md text-sm text-content-secondary" data-testid="module-builder-done-next">
          {t('module_builder.done_next', {
            defaultValue:
              'Next, open it and add the first entry. To add a field or a function later, use Add fields and functions on its page. You will always find it on the Module builder page.',
          })}
        </p>
      )}
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

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Screen 1: "What do you want to keep track of?"
 *
 * One question, asked the way a site engineer would answer it: in a sentence,
 * or by pointing at a register they recognise. The sentence box is there only
 * when an AI provider is connected; the template cards and "start from
 * scratch" are there always, so the screen without AI is the same screen with
 * one box fewer, never a dead end.
 *
 * While the assistant drafts, the screen says how long it takes and shows the
 * shape of the next screen, so twenty seconds read as progress, not a hang.
 */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight, PenLine, Sparkles } from 'lucide-react';

import { Skeleton } from '@/shared/ui';

import { MODULE_TEMPLATES, type ModuleTemplate } from '../templates';
import { say } from '../copy';
import { ModuleIcon } from './shared';

/** How many characters a description needs before drafting is offered. */
export const MIN_DESCRIPTION = 10;

interface DescribeScreenProps {
  sentence: string;
  setSentence: (text: string) => void;
  drafting: boolean;
  assistantAvailable: boolean;
  onDraft: () => void;
  onTemplate: (template: ModuleTemplate) => void;
  onScratch: () => void;
  /** Dismisses the wizard when the reader leaves to connect a provider. */
  onClose: () => void;
}

export function DescribeScreen({
  sentence,
  setSentence,
  drafting,
  assistantAvailable,
  onDraft,
  onTemplate,
  onScratch,
  onClose,
}: DescribeScreenProps) {
  const { t } = useTranslation();

  if (drafting) return <DraftingState />;

  return (
    <div className="space-y-6">
      <div className="space-y-1.5 pt-1 text-center">
        <h2 className="text-xl font-semibold tracking-tight text-content-primary sm:text-2xl">
          {t('module_builder.hero_title', { defaultValue: 'What do you want to keep track of?' })}
        </h2>
        <p className="mx-auto max-w-xl text-sm text-content-tertiary">
          {assistantAvailable
            ? t('module_builder.hero_hint_ai', {
                defaultValue: 'Describe it in your own words, or start from a register other sites already keep.',
              })
            : t('module_builder.hero_hint_manual', {
                defaultValue: 'Start from a template or build it by hand. You can change every part on the next screen.',
              })}
        </p>
      </div>

      {assistantAvailable ? (
        <div className="rounded-2xl border border-border-light bg-surface-secondary/40 p-3 shadow-sm focus-within:border-oe-blue/50 sm:p-4">
          <label htmlFor="module-builder-description" className="sr-only">
            {t('module_builder.describe_heading', { defaultValue: 'Say what you need' })}
          </label>
          <textarea
            id="module-builder-description"
            value={sentence}
            rows={3}
            onChange={(e) => setSentence(e.target.value)}
            onKeyDown={(e) => {
              // Ctrl/Cmd+Enter drafts, the way a chat box sends.
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && sentence.trim().length >= MIN_DESCRIPTION) {
                e.preventDefault();
                onDraft();
              }
            }}
            placeholder={t('module_builder.describe_placeholder', {
              defaultValue:
                'A register of concrete pours: pour reference, date, volume in cubic metres, the mix, and who signed it off.',
            })}
            className="w-full resize-none rounded-xl border-0 bg-transparent px-1 py-1 text-base text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-0"
            data-testid="module-builder-description"
          />
          <p className="mt-1 flex items-start gap-1.5 px-1 text-xs text-content-tertiary">
            <Sparkles size={13} className="mt-px shrink-0 text-oe-blue-text" />
            {t('module_builder.describe_note_v2', {
              defaultValue: 'The AI suggests the fields and checks. Nothing is created until you confirm it.',
            })}
          </p>
        </div>
      ) : (
        // The by-hand path is not a degraded one, so this says what is missing
        // and where to fix it rather than sitting on a disabled control the
        // reader has to guess about. Leaving closes the wizard: the header
        // mounts it above every page, so a modal left open would follow the
        // reader onto the settings screen it just sent them to.
        <p className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 rounded-xl bg-surface-secondary/60 px-3 py-2 text-center text-xs text-content-tertiary">
          <span>
            {t('module_builder.no_assistant_v2', {
              defaultValue: 'No AI is connected, so describing in a sentence is off. Templates work the same way.',
            })}
          </span>
          <Link
            to="/settings?tab=ai"
            onClick={onClose}
            className="inline-flex items-center gap-1 font-medium text-oe-blue-text hover:text-oe-blue-hover"
            data-testid="module-builder-connect-ai"
          >
            {t('module_builder.connect_ai', { defaultValue: 'Connect an AI provider' })}
            <ArrowRight size={12} className="shrink-0" />
          </Link>
        </p>
      )}

      <div>
        <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('module_builder.templates_heading', { defaultValue: 'Or start from a template' })}
        </p>
        <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {MODULE_TEMPLATES.map((template) => (
            <li key={template.id}>
              <button
                type="button"
                onClick={() => onTemplate(template)}
                className="group flex h-full w-full items-start gap-3 rounded-xl border border-border-light bg-surface-primary p-3 text-start transition-all hover:-translate-y-px hover:border-oe-blue/50 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                data-testid={`module-builder-template-${template.id}`}
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
                  <ModuleIcon name={template.icon} size={18} />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-content-primary">{say(t, template.name)}</span>
                  <span className="mt-0.5 line-clamp-2 block text-xs text-content-tertiary">
                    {say(t, template.description)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={onScratch}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg px-1 py-1 text-xs font-medium text-content-secondary transition-colors hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          data-testid="module-builder-scratch"
        >
          <PenLine size={13} />
          {t('module_builder.start_scratch', { defaultValue: 'Start from scratch and build it by hand' })}
        </button>
      </div>
    </div>
  );
}

/** What screen 2 will look like, held still while the assistant writes it. */
function DraftingState() {
  const { t } = useTranslation();
  return (
    <div className="space-y-5" data-testid="module-builder-drafting" aria-busy="true">
      <p
        role="status"
        className="flex items-center justify-center gap-2 pt-2 text-sm text-content-secondary"
      >
        <Sparkles size={15} className="animate-pulse text-oe-blue-text" />
        {t('module_builder.drafting', { defaultValue: 'Drafting your register, this takes up to 20 seconds' })}
      </p>
      <div className="rounded-2xl border border-border-light p-5">
        <div className="flex items-center gap-3">
          <Skeleton className="h-11 w-11" rounded="lg" />
          <div className="flex-1 space-y-2">
            <Skeleton height={18} className="w-1/2" />
            <Skeleton height={12} className="w-3/4" />
          </div>
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          {[24, 20, 28, 16, 22].map((w, i) => (
            <Skeleton key={i} height={26} width={`${w * 4}px`} rounded="full" />
          ))}
        </div>
      </div>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <Skeleton height={64} rounded="lg" />
        <Skeleton height={64} rounded="lg" />
      </div>
    </div>
  );
}

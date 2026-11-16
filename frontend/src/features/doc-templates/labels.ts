// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Display names of document kinds, modules, blocks and languages. */

import { useTranslation } from 'react-i18next';

const LANG_CACHE: Record<string, string> = {};

export function languageLabel(code: string, uiLanguage: string): string {
  const key = `${uiLanguage}:${code}`;
  if (!LANG_CACHE[key]) {
    try {
      LANG_CACHE[key] = new Intl.DisplayNames([uiLanguage], { type: 'language' }).of(code) ?? code;
    } catch {
      LANG_CACHE[key] = code;
    }
  }
  return LANG_CACHE[key] ?? code;
}

const slug = (key: string) => key.replace(/[^a-z0-9]+/gi, '_').toLowerCase();

/** Translated kind name; the server's English label is the fallback for kinds the bundle does not know. */
export function useKindLabel(): (key: string, fallback: string) => string {
  const { t } = useTranslation();
  return (key, fallback) => t(`settings.document_templates.kind_${slug(key)}`, { defaultValue: fallback });
}

export function useModuleLabel(): (module: string) => string {
  const { t } = useTranslation();
  return (module) =>
    t(`settings.document_templates.module_${slug(module)}`, {
      defaultValue: module.charAt(0).toUpperCase() + module.slice(1).replace(/_/g, ' '),
    });
}

export function useBlockLabel(): (block: string) => string {
  const { t } = useTranslation();
  const defaults: Record<string, string> = {
    title: 'Title',
    intro: 'Intro',
    body: 'Body',
    closing: 'Closing',
    terms: 'Terms',
    signature: 'Signature',
    footer: 'Footer',
    subject: 'Subject',
    preheader: 'Heading',
    cta_label: 'Button label',
  };
  return (block) => t(`settings.document_templates.block_${block}`, { defaultValue: defaults[block] ?? block });
}

export function useFieldGroupLabel(): (group: string) => string {
  const { t } = useTranslation();
  const defaults: Record<string, string> = {
    project: 'Project',
    document: 'Document',
    company: 'Company',
    recipient: 'Recipient',
    sender: 'Sender',
  };
  return (group) => t(`settings.document_templates.group_${group}`, { defaultValue: defaults[group] ?? group });
}

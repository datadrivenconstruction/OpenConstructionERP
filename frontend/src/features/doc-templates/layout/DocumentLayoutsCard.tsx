// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings list of the record documents whose layout a firm can change, each
 * opening the same editor as "Customize document" on the record, at company
 * scope. Shows nothing while no enabled module offers a layout.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { SlidersHorizontal } from 'lucide-react';

import { listLayouts } from './layoutApi';
import { LayoutEditorDrawer } from './LayoutEditorDrawer';

export function DocumentLayoutsCard() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ['doc-layouts'], queryFn: listLayouts });
  const [openKey, setOpenKey] = useState<string | null>(null);
  if (!data || data.items.length === 0) return null;
  const opened = data.items.find((i) => i.key === openKey);
  return (
    <section className="mb-6 rounded-xl border border-border-light bg-surface-primary p-4" data-testid="document-layouts-card">
      <h3 className="text-sm font-semibold text-content-primary">
        {t('doc_layout.settings_title', { defaultValue: 'Document layouts' })}
      </h3>
      <p className="mt-0.5 text-xs text-content-secondary">
        {t('doc_layout.settings_hint', {
          defaultValue:
            'Arrange the sections, columns, texts and page of each document. A project can override the company layout from the document itself.',
        })}
      </p>
      <ul className="mt-3 divide-y divide-border-light">
        {data.items.map((item) => (
          <li key={item.key} className="flex items-center gap-3 py-2">
            <span className="flex-1 text-sm text-content-primary">
              {t(`doc_templates.kind.${item.key}`, { defaultValue: item.label })}
            </span>
            <span className="text-2xs text-content-tertiary">
              {item.published > 0
                ? t('doc_layout.custom_layout', { defaultValue: 'Custom layout' })
                : t('doc_layout.standard_layout', { defaultValue: 'Standard layout' })}
              {item.projects > 0 &&
                ` · ${t('doc_layout.project_overrides', { defaultValue: 'Project overrides: {{n}}', n: item.projects })}`}
            </span>
            <button
              type="button"
              onClick={() => setOpenKey(item.key)}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
              data-testid={`document-layout-open-${item.key}`}
            >
              <SlidersHorizontal size={13} />
              {data.can_edit
                ? t('doc_layout.customize', { defaultValue: 'Customize document' })
                : t('doc_layout.view', { defaultValue: 'View layout' })}
            </button>
          </li>
        ))}
      </ul>
      {opened && (
        <LayoutEditorDrawer
          open
          onClose={() => setOpenKey(null)}
          layoutKey={opened.key}
          title={t(`doc_templates.kind.${opened.key}`, { defaultValue: opened.label })}
        />
      )}
    </section>
  );
}

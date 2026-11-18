// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wires "Customize document" of an export menu to the layout editor drawer.
 *
 *   const customizer = useLayoutCustomizer('procurement.purchase_order');
 *   <RecordPdfButton ... onCustomize={customizer.open({ recordId: po.id, projectId: po.project_id })} />
 *   {customizer.drawer}
 *
 * The drawer is mounted only while open, so a register of fifty rows pays for
 * one editor at most.
 */
import { useCallback, useState, type ReactNode } from 'react';

import { LayoutEditorDrawer } from './LayoutEditorDrawer';

interface Opened {
  recordId?: string | null;
  projectId?: string | null;
  locale: string;
}

export function useLayoutCustomizer(
  layoutKey: string,
  title?: string,
): { open: (context: { recordId?: string | null; projectId?: string | null }) => (locale: string) => void; drawer: ReactNode } {
  const [opened, setOpened] = useState<Opened | null>(null);
  const open = useCallback(
    (context: { recordId?: string | null; projectId?: string | null }) => (locale: string) =>
      setOpened({ ...context, locale }),
    [],
  );
  const drawer = opened ? (
    <LayoutEditorDrawer
      open
      onClose={() => setOpened(null)}
      layoutKey={layoutKey}
      recordId={opened.recordId}
      projectId={opened.projectId}
      locale={opened.locale}
      title={title}
    />
  ) : null;
  return { open, drawer };
}

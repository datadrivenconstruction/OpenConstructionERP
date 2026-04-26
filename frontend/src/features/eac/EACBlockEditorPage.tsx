/**
 * `<EACBlockEditorPage>` — full-screen page that mounts the visual block
 * editor for a given EAC ruleset id (URL param `eacId`).
 *
 * Layout:
 *   ┌────────────┬─────────────────────────────────────────────┐
 *   │  Palette   │  Canvas (toolbar + xyflow surface)          │
 *   │ 220 px     │                                             │
 *   └────────────┴─────────────────────────────────────────────┘
 *
 * The page is the single owner of `<DndContext>` so palette items and the
 * canvas droppable share a common DnD surface. Drop translation is delegated
 * to the canvas itself via the HTML5 dataTransfer payload — `@dnd-kit` is
 * still in play for the palette item lift, but the actual drop coordinate
 * comes from the native browser drag (matches xyflow's expectations).
 */
import { DndContext } from '@dnd-kit/core';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { BlockCanvas } from './canvas';
import { EacBlockPalette } from './components/EacBlockPalette';

export function EACBlockEditorPage() {
  const { t } = useTranslation();
  const params = useParams<{ eacId?: string }>();
  const eacId = params.eacId ?? 'untitled';

  return (
    <DndContext>
      <div
        data-testid="eac-block-editor-page"
        data-eac-id={eacId}
        className="flex h-[calc(100vh-var(--oe-header-height,56px))] w-full overflow-hidden bg-surface-primary"
      >
        <EacBlockPalette />
        <main className="flex flex-1 flex-col overflow-hidden">
          <header className="border-b border-border bg-surface-secondary px-4 py-2">
            <h1 className="text-sm font-semibold text-content-primary">
              {t('eac.editor.title', { defaultValue: 'EAC Block Editor' })}
              <span className="ml-2 font-normal text-content-tertiary">· {eacId}</span>
            </h1>
          </header>
          <div className="flex-1">
            <BlockCanvas />
          </div>
        </main>
      </div>
    </DndContext>
  );
}

export default EACBlockEditorPage;

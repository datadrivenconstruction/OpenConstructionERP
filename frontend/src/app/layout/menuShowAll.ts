// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Show all modules" in the sidebar: every row, demo section trimming lifted; "Back" restores the view. */
import type { MenuModeId } from './menuLayout';
import { useMenuLayoutStore } from './useMenuLayoutStore';
import { useDemoSessionStore } from '@/stores/useDemoSessionStore';

export function showAllModules(): void {
  const layout = useMenuLayoutStore.getState();
  const demo = useDemoSessionStore.getState();
  if (demo.restoreMode === null) demo.setRestoreMode(layout.layout.activeMode);
  layout.dispatch({ type: 'setMode', mode: 'all' });
}

export function backToView(): void {
  const demo = useDemoSessionStore.getState();
  const mode: MenuModeId = demo.restoreMode ?? 'all';
  demo.setRestoreMode(null);
  useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode });
}

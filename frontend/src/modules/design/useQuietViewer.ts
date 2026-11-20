// Design module (ERP side of the design editor link).
import { useEffect } from 'react';
import { useBIMViewerStore } from '@/stores/useBIMViewerStore';

/**
 * Classes for the box around the viewer: its top toolbar is one unwrapped row, so in a narrow box the last
 * tools were cut off. Here it wraps and stays inside the box.
 */
export const VIEWER_FRAME =
  '[&_div.absolute.top-3.z-20.rounded-lg.p-1]:max-w-[calc(100%-1.5rem)] [&_div.absolute.top-3.z-20.rounded-lg.p-1]:flex-wrap';

/**
 * The viewer opens its model-summary panel over the model. On the revision pages the model is the point,
 * so the panel starts closed (the toolbar button still opens it) and the viewer's own default is put back
 * when the page is left.
 */
export function useQuietViewer(): void {
  useEffect(() => {
    const store = useBIMViewerStore;
    const before = store.getState().summaryPanelOpen;
    store.getState().setSummaryPanelOpen(false);
    return () => store.getState().setSummaryPanelOpen(before);
  }, []);
}

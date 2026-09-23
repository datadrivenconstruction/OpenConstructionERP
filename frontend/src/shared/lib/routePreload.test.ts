// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Opening the BOQ list for the first time in a session fetched 39 chunks and
// about 930 KB, two thirds of it ag-grid, three.js and the PDF export vendor,
// none of which the list uses. The list page itself was already in the main
// bundle. What fetched the rest was the sidebar's hover preloader: its '/boq'
// entry imported BOQEditorPage, and a click always hovers first.
//
// The takeoff case is the control. It shows the hover preloader does load a
// page in this test, so the BOQ assertion is not passing because nothing ever
// loads here.

import { describe, it, expect, vi, afterEach } from 'vitest';

const loads = vi.hoisted(() => ({ editor: 0, takeoff: 0 }));

vi.mock('@/features/boq/BOQEditorPage', () => {
  loads.editor += 1;
  return { BOQEditorPage: () => null };
});
vi.mock('@/features/takeoff/TakeoffPage', () => {
  loads.takeoff += 1;
  return { TakeoffPage: () => null };
});

import { preloadRouteOnHover } from './routePreload';

afterEach(() => {
  vi.useRealTimers();
});

async function hover(path: string): Promise<void> {
  vi.useFakeTimers();
  preloadRouteOnHover(path);
  await vi.advanceTimersByTimeAsync(200);
  vi.useRealTimers();
  await vi.dynamicImportSettled();
}

describe('hovering a sidebar item', () => {
  it('preloads the page the item opens', async () => {
    await hover('/takeoff');
    expect(loads.takeoff).toBe(1);
  });

  it('does not load the BOQ editor for the BOQ list', async () => {
    await hover('/boq');
    await hover('/boq?tab=templates');
    expect(loads.editor).toBe(0);
  });
});

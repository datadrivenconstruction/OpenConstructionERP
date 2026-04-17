/**
 * useWidgetSettingsStore — client-side feature toggles for UI widgets.
 *
 * Separate from `useModulesStore` (which tracks backend module install
 * state) because these flags are purely about presentation — whether the
 * project cards embed a map thumbnail, whether the detail page shows a
 * weather forecast, etc.  No server round-trip; persisted to localStorage
 * so the user's choice sticks across reloads.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface WidgetSettingsState {
  /** Show an OSM map thumbnail in project cards + full map on detail page. */
  projectMapEnabled: boolean;
  /** Show a 16-day weather forecast on the project detail page. */
  projectWeatherEnabled: boolean;

  toggleProjectMap: () => void;
  toggleProjectWeather: () => void;
  setProjectMap: (v: boolean) => void;
  setProjectWeather: (v: boolean) => void;
}

export const useWidgetSettingsStore = create<WidgetSettingsState>()(
  persist(
    (set) => ({
      projectMapEnabled: true,
      projectWeatherEnabled: true,

      toggleProjectMap: () =>
        set((s) => ({ projectMapEnabled: !s.projectMapEnabled })),
      toggleProjectWeather: () =>
        set((s) => ({ projectWeatherEnabled: !s.projectWeatherEnabled })),
      setProjectMap: (v) => set({ projectMapEnabled: v }),
      setProjectWeather: (v) => set({ projectWeatherEnabled: v }),
    }),
    { name: 'oe.widget-settings' },
  ),
);

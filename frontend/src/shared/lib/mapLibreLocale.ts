// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MapLibre's own control titles (zoom, compass, attribution, fullscreen) in
 * the reader's language. MapLibre ships English only and takes the rest
 * through the `locale` map option; scale units stay as MapLibre writes them.
 */

import { useMemo } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

const STRINGS: Record<string, [string, string]> = {
  'AttributionControl.ToggleAttribution': ['map.ui.toggle_attribution', 'Toggle attribution'],
  'AttributionControl.MapFeedback': ['map.ui.map_feedback', 'Map feedback'],
  'FullscreenControl.Enter': ['map.ui.fullscreen_enter', 'Enter fullscreen'],
  'FullscreenControl.Exit': ['map.ui.fullscreen_exit', 'Exit fullscreen'],
  'GeolocateControl.FindMyLocation': ['map.ui.find_my_location', 'Find my location'],
  'GeolocateControl.LocationNotAvailable': ['map.ui.location_not_available', 'Location not available'],
  'Map.Title': ['map.ui.map', 'Map'],
  'Marker.Title': ['map.ui.marker', 'Map marker'],
  'NavigationControl.ResetBearing': ['map.ui.reset_bearing', 'Drag to rotate map, click to reset north'],
  'NavigationControl.ZoomIn': ['map.ui.zoom_in', 'Zoom in'],
  'NavigationControl.ZoomOut': ['map.ui.zoom_out', 'Zoom out'],
  'Popup.Close': ['map.ui.close_popup', 'Close popup'],
  'CooperativeGesturesHandler.WindowsHelpText': ['map.ui.ctrl_scroll', 'Use Ctrl + scroll to zoom the map'],
  'CooperativeGesturesHandler.MacHelpText': ['map.ui.cmd_scroll', 'Use ⌘ + scroll to zoom the map'],
  'CooperativeGesturesHandler.MobileHelpText': ['map.ui.two_fingers', 'Use two fingers to move the map'],
};

/** The `locale` option for a MapLibre map, translated with `t`. */
export function mapLibreLocale(t: TFunction): Record<string, string> {
  return Object.fromEntries(Object.entries(STRINGS).map(([id, [key, def]]) => [id, String(t(key, { defaultValue: def }))]));
}

/** `mapLibreLocale` for the current language; pass it as `<Map locale={...}>`. */
export function useMapLibreLocale(): Record<string, string> {
  const { t, i18n } = useTranslation();
  return useMemo(() => mapLibreLocale(t), [t, i18n.language]);
}

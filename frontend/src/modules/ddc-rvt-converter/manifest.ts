import { Box } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'ddc-rvt-converter',
  name: 'DDC cad2data — Revit Converter',
  description:
    'Converts Autodesk Revit (.rvt) files into element data (DataFrame) and 3D geometry (COLLADA). Extracts families, types, parameters, quantities, and spatial structure using proprietary reverse-engineering technology — no Revit installation required.',
  version: '1.0.0',
  icon: Box,
  category: 'converter',
  defaultEnabled: false,
  depends: [],
  routes: [],
  navItems: [],
  searchEntries: [
    {
      label: 'Revit Converter (DDC cad2data)',
      path: '/modules',
      keywords: ['rvt', 'revit', 'converter', 'cad2data', 'ddc', 'bim', 'cad', 'autodesk', 'model'],
    },
  ],
  translations: {
    en: {
      'converter.rvt.name': 'DDC cad2data — Revit Converter',
      'converter.rvt.desc': 'Convert Revit (.rvt) files to DataFrame + COLLADA geometry',
    },
    de: {
      'converter.rvt.name': 'DDC cad2data — Revit Konverter',
      'converter.rvt.desc': 'Revit-Dateien (.rvt) in DataFrame + COLLADA-Geometrie konvertieren',
    },
    ru: {
      'converter.rvt.name': 'DDC cad2data — Revit Конвертер',
      'converter.rvt.desc': 'Конвертация файлов Revit (.rvt) в DataFrame + COLLADA геометрию',
    },
  },
};

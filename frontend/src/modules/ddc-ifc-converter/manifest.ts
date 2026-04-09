import { Box } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'ddc-ifc-converter',
  name: 'DDC cad2data — IFC Converter',
  description:
    'Converts IFC (Industry Foundation Classes) files into element data (DataFrame) and 3D geometry (COLLADA). Enables automatic extraction of walls, slabs, columns, beams, doors, windows, MEP elements with quantities, properties, and storey classification.',
  version: '1.0.0',
  icon: Box,
  category: 'converter',
  defaultEnabled: false,
  depends: [],
  routes: [],
  navItems: [],
  searchEntries: [
    {
      label: 'IFC Converter (DDC cad2data)',
      path: '/modules',
      keywords: ['ifc', 'converter', 'cad2data', 'ddc', 'bim', 'cad', 'building', 'model', 'import'],
    },
  ],
  translations: {
    en: {
      'converter.ifc.name': 'DDC cad2data — IFC Converter',
      'converter.ifc.desc': 'Convert IFC files to DataFrame + COLLADA geometry',
    },
    de: {
      'converter.ifc.name': 'DDC cad2data — IFC Konverter',
      'converter.ifc.desc': 'IFC-Dateien in DataFrame + COLLADA-Geometrie konvertieren',
    },
    ru: {
      'converter.ifc.name': 'DDC cad2data — IFC Конвертер',
      'converter.ifc.desc': 'Конвертация IFC файлов в DataFrame + COLLADA геометрию',
    },
  },
};

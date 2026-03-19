import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', name: 'English', flag: '🇬🇧' },
  { code: 'de', name: 'Deutsch', flag: '🇩🇪' },
  { code: 'ru', name: 'Русский', flag: '🇷🇺' },
  { code: 'fr', name: 'Français', flag: '🇫🇷' },
  { code: 'es', name: 'Español', flag: '🇪🇸' },
  { code: 'pt', name: 'Português', flag: '🇧🇷' },
  { code: 'it', name: 'Italiano', flag: '🇮🇹' },
  { code: 'nl', name: 'Nederlands', flag: '🇳🇱' },
  { code: 'pl', name: 'Polski', flag: '🇵🇱' },
  { code: 'cs', name: 'Čeština', flag: '🇨🇿' },
  { code: 'tr', name: 'Türkçe', flag: '🇹🇷' },
  { code: 'ar', name: 'العربية', flag: '🇸🇦', dir: 'rtl' },
  { code: 'zh', name: '简体中文', flag: '🇨🇳' },
  { code: 'ja', name: '日本語', flag: '🇯🇵' },
  { code: 'ko', name: '한국어', flag: '🇰🇷' },
  { code: 'hi', name: 'हिन्दी', flag: '🇮🇳' },
  { code: 'sv', name: 'Svenska', flag: '🇸🇪' },
  { code: 'no', name: 'Norsk', flag: '🇳🇴' },
  { code: 'da', name: 'Dansk', flag: '🇩🇰' },
  { code: 'fi', name: 'Suomi', flag: '🇫🇮' },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

export function getLanguageByCode(code: string) {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code) ?? SUPPORTED_LANGUAGES[0];
}

// Inline fallback translations — ensures UI works even without backend
const fallbackResources = {
  en: {
    translation: {
      'app.name': 'OpenEstimate',
      'app.tagline': 'Open-source construction cost estimation',
      'nav.dashboard': 'Dashboard',
      'nav.ai_estimate': 'AI Estimate',
      'nav.settings': 'Settings',
      'common.save': 'Save',
      'common.cancel': 'Cancel',
      'common.delete': 'Delete',
      'common.edit': 'Edit',
      'common.create': 'Create',
      'common.search': 'Search',
      'common.filter': 'Filter',
      'common.export': 'Export',
      'common.import': 'Import',
      'common.loading': 'Loading...',
      'common.error': 'Error',
      'common.success': 'Success',
      'projects.title': 'Projects',
      'projects.new_project': 'New Project',
      'projects.no_projects': 'No projects yet',
      'projects.project_name': 'Project Name',
      'boq.title': 'Bill of Quantities',
      'boq.position': 'Position',
      'boq.ordinal': 'Pos.',
      'boq.description': 'Description',
      'boq.quantity': 'Quantity',
      'boq.unit': 'Unit',
      'boq.unit_rate': 'Unit Rate',
      'boq.total': 'Total',
      'boq.add_position': 'Add Position',
      'boq.add_section': 'Add Section',
      'boq.subtotal': 'Subtotal',
      'boq.grand_total': 'Grand Total',
      'boq.direct_cost': 'Direct Cost',
      'boq.net_total': 'Net Total',
      'boq.gross_total': 'Gross Total',
      'boq.vat': 'VAT',
      'boq.add_markups': 'Add Markups',
      'boq.markup_name': 'Markup Name',
      'boq.markup_percent': 'Percentage',
      'boq.no_positions': 'No positions yet. Add a section to get started.',
      'boq.section_subtotal': 'Section subtotal',
      'boq.validate': 'Validate',
      'boq.export': 'Export',
      'boq.back_to_project': 'Back to project',
      'boq.confirm_delete': 'Delete this position?',
      'boq.confirm_delete_section': 'Delete this section and all its positions?',
      'boq.empty_section': 'No items in this section. Click "Add Position" to add one.',
      'costs.title': 'Cost Database',
      'assemblies.title': 'Assemblies',
      'validation.title': 'Validation',
      'validation.passed': 'Passed',
      'validation.warnings': 'Warnings',
      'validation.errors': 'Errors',
      'validation.score': 'Quality Score',
      'schedule.title': '4D Schedule',
      'nav.5d_cost_model': '5D Cost Model',
      'nav.templates': 'Templates',
      'takeoff.title': 'Quantity Takeoff',
      'tendering.title': 'Tendering',
      'modules.title': 'Modules',
      'dashboard.welcome': 'Welcome to OpenEstimate',
      'dashboard.subtitle': 'Your construction estimation workspace',
      'dashboard.quick_actions': 'Quick Actions',
      'dashboard.recent_projects': 'Recent Projects',
      'dashboard.system_status': 'System Status',
      'dashboard.modules_loaded': 'Modules loaded',
      'dashboard.validation_rules': 'Validation rules',
      'dashboard.languages': 'Languages',
      'auth.login': 'Log In',
      'auth.logout': 'Log Out',
      'auth.email': 'Email',
      'auth.password': 'Password',
    },
  },
};

i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: 'en',
    supportedLngs: SUPPORTED_LANGUAGES.map((l) => l.code),
    debug: false,
    interpolation: {
      escapeValue: false,
    },
    // Bundle English translations — always available as fallback
    // Backend translations merge on top but English keys are always there
    partialBundledLanguages: true,
    resources: fallbackResources,
    // Don't load English from backend (use bundled), load other languages from API
    backend: {
      loadPath: '/api/v1/i18n/{{lng}}',
      // Skip loading English from backend — bundled version is more complete
      request: (_options: Record<string, unknown>, url: string, _payload: unknown, callback: (err: unknown, data: { status: number; data: string }) => void) => {
        if (typeof url === 'string' && url.endsWith('/en')) {
          // Return empty for English — use bundled fallback
          callback(null, { status: 200, data: '{}' });
          return;
        }
        // For other languages, fetch from backend
        fetch(url as string)
          .then((r) => r.text())
          .then((data) => callback(null, { status: 200, data }))
          .catch((err) => callback(err, { status: 500, data: '' }));
      },
    },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
    },
  });

export default i18n;

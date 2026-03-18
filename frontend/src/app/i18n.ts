import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'de', name: 'Deutsch' },
  { code: 'ru', name: 'Русский' },
  { code: 'fr', name: 'Français' },
  { code: 'es', name: 'Español' },
  { code: 'pt', name: 'Português' },
  { code: 'it', name: 'Italiano' },
  { code: 'nl', name: 'Nederlands' },
  { code: 'pl', name: 'Polski' },
  { code: 'cs', name: 'Čeština' },
  { code: 'tr', name: 'Türkçe' },
  { code: 'ar', name: 'العربية', dir: 'rtl' },
  { code: 'zh', name: '简体中文' },
  { code: 'ja', name: '日本語' },
  { code: 'ko', name: '한국어' },
  { code: 'hi', name: 'हिन्दी' },
  { code: 'sv', name: 'Svenska' },
  { code: 'no', name: 'Norsk' },
  { code: 'da', name: 'Dansk' },
  { code: 'fi', name: 'Suomi' },
] as const;

// Inline fallback translations — ensures UI works even without backend
const fallbackResources = {
  en: {
    translation: {
      'app.name': 'OpenEstimate',
      'app.tagline': 'Open-source construction cost estimation',
      'nav.dashboard': 'Dashboard',
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
      'boq.title': 'Bill of Quantities',
      'costs.title': 'Cost Database',
      'validation.title': 'Validation',
      'validation.passed': 'Passed',
      'validation.warnings': 'Warnings',
      'validation.errors': 'Errors',
      'validation.score': 'Quality Score',
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
    // Use inline resources as fallback, backend as primary
    partialBundledLanguages: true,
    resources: fallbackResources,
    backend: {
      loadPath: '/api/v1/i18n/{{lng}}',
    },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
    },
  });

export default i18n;

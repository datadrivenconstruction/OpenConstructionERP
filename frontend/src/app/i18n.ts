import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', name: 'English', flag: '🇬🇧', country: 'gb' },
  { code: 'de', name: 'Deutsch', flag: '🇩🇪', country: 'de' },
  { code: 'ru', name: 'Русский', flag: '🇷🇺', country: 'ru' },
  { code: 'fr', name: 'Français', flag: '🇫🇷', country: 'fr' },
  { code: 'es', name: 'Español', flag: '🇪🇸', country: 'es' },
  { code: 'pt', name: 'Português', flag: '🇧🇷', country: 'br' },
  { code: 'it', name: 'Italiano', flag: '🇮🇹', country: 'it' },
  { code: 'nl', name: 'Nederlands', flag: '🇳🇱', country: 'nl' },
  { code: 'pl', name: 'Polski', flag: '🇵🇱', country: 'pl' },
  { code: 'cs', name: 'Čeština', flag: '🇨🇿', country: 'cz' },
  { code: 'tr', name: 'Türkçe', flag: '🇹🇷', country: 'tr' },
  { code: 'ar', name: 'العربية', flag: '🇸🇦', country: 'sa', dir: 'rtl' },
  { code: 'zh', name: '简体中文', flag: '🇨🇳', country: 'cn' },
  { code: 'ja', name: '日本語', flag: '🇯🇵', country: 'jp' },
  { code: 'ko', name: '한국어', flag: '🇰🇷', country: 'kr' },
  { code: 'hi', name: 'हिन्दी', flag: '🇮🇳', country: 'in' },
  { code: 'sv', name: 'Svenska', flag: '🇸🇪', country: 'se' },
  { code: 'no', name: 'Norsk', flag: '🇳🇴', country: 'no' },
  { code: 'da', name: 'Dansk', flag: '🇩🇰', country: 'dk' },
  { code: 'fi', name: 'Suomi', flag: '🇫🇮', country: 'fi' },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

export function getLanguageByCode(code: string) {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code) ?? SUPPORTED_LANGUAGES[0];
}

// Inline fallback translations — ensures UI works even without backend
const fallbackResources = {
  en: {
    translation: {
      'app.name': 'OpenEstimator.io',
      'app.tagline': 'Professional construction cost estimation platform',
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
      'takeoff.title': 'PDF Takeoff',
      'takeoff.subtitle': 'Upload construction drawings to extract quantities',
      'takeoff.drop_pdf_here': 'Drop your PDF drawing here',
      'takeoff.pdf_limit': '.pdf files up to {{size}}MB',
      'takeoff.upload_pdf': 'Upload PDF',
      'takeoff.uploaded_documents': 'Uploaded Documents',
      'takeoff.pages': 'pages',
      'takeoff.uploaded': 'Uploaded',
      'takeoff.just_now': 'Just now',
      'takeoff.minutes_ago': '{{count}} min ago',
      'takeoff.hours_ago': '{{count}}h ago',
      'takeoff.days_ago': '{{count}}d ago',
      'takeoff.analyze_with_ai': 'Analyze with AI',
      'takeoff.analyzing': 'Analyzing...',
      'takeoff.analyzing_document': 'Analyzing document with AI...',
      'takeoff.extract_tables': 'Extract Tables',
      'takeoff.extracting': 'Extracting...',
      'takeoff.view': 'View',
      'takeoff.ai_analysis_results': 'AI Analysis Results',
      'takeoff.found_elements': '{{count}} elements found',
      'takeoff.summary': 'Summary',
      'takeoff.total_quantity': 'total',
      'takeoff.selected': 'selected',
      'takeoff.select_all': 'Select all',
      'takeoff.deselect_all': 'Deselect all',
      'takeoff.add_selected_to_boq': 'Add {{count}} to BOQ',
      'takeoff.select_items_hint': 'Select items to add to BOQ',
      'takeoff.add_to_boq': 'Add to BOQ',
      'takeoff.added_to_boq_success': 'Items added to BOQ successfully',
      'takeoff.no_documents': 'No documents uploaded',
      'takeoff.no_documents_description': 'Upload PDF construction drawings to start extracting quantities with AI.',
      'takeoff.quick_measurements': 'Quick Measurements',
      'takeoff.quick_measurements_desc': 'Enter measurements manually:',
      'takeoff.description': 'Description',
      'takeoff.description_placeholder': 'e.g., External wall area',
      'takeoff.value': 'Value',
      'takeoff.unit': 'Unit',
      'takeoff.select_project': 'Project',
      'takeoff.select_project_placeholder': 'Choose a project...',
      'takeoff.select_boq': 'Bill of Quantities',
      'takeoff.select_boq_placeholder': 'Choose a BOQ...',
      'takeoff.select_project_first': 'Select a project first',
      'takeoff.select_boq_to_add': 'Select a project and BOQ above to add measurements.',
      'tendering.title': 'Tendering',
      'nav.reports': 'Reports',
      'reports.title': 'Reports',
      'reports.subtitle': 'Generate professional reports for your projects',
      'reports.boq_report': 'BOQ Report',
      'reports.boq_report_desc':
        'Full Bill of Quantities with sections, positions, markups, and totals. Available as PDF or Excel.',
      'reports.cost_report': 'Cost Report',
      'reports.cost_report_desc':
        'Cost breakdown by category with summary charts and detailed cost analysis.',
      'reports.gaeb_xml': 'GAEB XML',
      'reports.gaeb_xml_desc':
        'GAEB X83 tender export — the standard exchange format for the DACH construction market.',
      'reports.validation_report': 'Validation Report',
      'reports.validation_report_desc':
        'Compliance check report against DIN 276, NRM, or MasterFormat standards.',
      'reports.schedule_report': 'Schedule Report',
      'reports.schedule_report_desc':
        'Gantt chart with project timeline, milestones, and critical path.',
      'reports.5d_report': '5D Cost Report',
      'reports.5d_report_desc':
        'Budget vs. actual analysis with S-curve and cost forecasting.',
      'reports.coming_soon': 'Coming soon',
      'reports.download_format': 'Download {{format}}',
      'reports.download_success': 'Report downloaded successfully',
      'reports.download_error': 'Failed to generate report',
      'reports.select_boq_first': 'Please select a project and BOQ first',
      'reports.no_projects': 'No projects available',
      'reports.no_boqs': 'No BOQs in this project',
      'modules.title': 'Modules',
      'dashboard.welcome': 'Welcome to OpenEstimator.io',
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
      // Sustainability / CO2
      'nav.sustainability': 'Sustainability',
      'nav.takeoff': 'PDF Takeoff',
      'sustainability.title': 'Sustainability / CO2',
      'sustainability.subtitle': 'Select project and BOQ to analyze CO2 footprint',
      'sustainability.project': 'Project',
      'sustainability.boq': 'BOQ',
      'sustainability.area': 'Area (m2)',
      'sustainability.select_project': '-- Select project --',
      'sustainability.select_boq': '-- Select BOQ --',
      'sustainability.calculate': 'Calculate',
      'sustainability.total_co2': 'Total CO2',
      'sustainability.benchmark': 'Benchmark',
      'sustainability.rating': 'Rating',
      'sustainability.positions_matched': 'positions matched',
      'sustainability.project_area': 'project',
      'sustainability.no_area': 'Enter project area to see benchmark per m2',
      'sustainability.breakdown_title': 'Breakdown by Material',
      'sustainability.material': 'Material',
      'sustainability.export_pdf': 'Export CO2 Report PDF',
      'sustainability.empty_title': 'CO2 footprint analysis',
      'sustainability.empty_desc':
        'Select a project and BOQ above, then click Calculate to analyze CO2 emissions based on material types.',
      // Dashboard analytics
      'dashboard.analytics': 'Analytics',
      'dashboard.project_overview': 'Project Overview',
      'dashboard.total_projects': 'Total Projects',
      'dashboard.total_boqs': 'Total BOQs',
      'dashboard.total_value': 'Total Value',
      'dashboard.value_by_project': 'Value by Project',
      'dashboard.boq_status': 'BOQ Status',
      'dashboard.no_boq_data': 'No BOQ data available',
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

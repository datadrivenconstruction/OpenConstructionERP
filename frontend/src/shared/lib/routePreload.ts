// Hover-intent chunk preloader: when the user hovers a sidebar nav item,
// we fire the dynamic import() for that route's page component so the
// chunk is already in the browser cache by the time they click.
//
// Keys must match navCatalog `to:` values exactly. The import() call is
// idempotent — the bundler caches the module after the first resolve.

const preloaders: Record<string, () => void> = {
  // ── Estimation & BOQ ──
  // No '/boq' entry. That route renders BOQListPage, which App.tsx imports
  // statically, so it is already in the main bundle. The entry used to preload
  // BOQEditorPage instead, and with it ag-grid, three.js and the PDF export
  // vendor: about 900 KB fetched on every hover of the BOQ menu item, queued
  // ahead of the list's own requests, for an editor the user had not opened.
  '/takeoff': () => void import('@/features/takeoff/TakeoffPage'),
  '/dwg-takeoff': () => void import('@/features/dwg-takeoff/DwgTakeoffPage'),
  '/catalog': () => void import('@/features/catalog/CatalogPage'),
  '/norm-expansion': () => void import('@/features/norm-expansion/NormExpansionPage'),
  '/labor-rates': () => void import('@/features/labor-rates/LaborRatesPage'),
  '/waste-factors': () => void import('@/features/waste-factors/WasteFactorsPage'),
  '/price-index': () => void import('@/features/price-index/PriceIndexPage'),
  '/resource-summary': () => void import('@/features/resource-summary/ResourceSummaryPage'),
  '/cost-match': () => void import('@/features/cost-match'),
  '/supplier-catalogs': () => void import('@/features/supplier-catalogs'),
  '/assemblies': () => void import('@/features/assemblies/AssembliesPage'),
  '/allowances': () => void import('@/features/allowances'),
  '/quantities': () => void import('@/features/quantities'),
  '/preliminaries': () => void import('@/features/preliminaries'),
  '/costs': () => void import('@/features/costs'),
  '/cost-explorer': () => void import('@/features/cost-explorer'),
  '/5d': () => void import('@/features/costmodel/CostModelPage'),
  '/rom-estimate': () => void import('@/features/rom-estimate'),
  '/estimate-basis': () => void import('@/features/estimate-basis'),
  '/estimate-copilot': () => void import('@/features/estimate-copilot'),
  '/formwork': () => void import('@/features/formwork'),
  '/rebar-schedule': () => void import('@/features/rebar-schedule'),
  '/prefab': () => void import('@/features/prefab'),

  // ── Schedule & Planning ──
  '/schedule': () => void import('@/features/schedule/SchedulePage'),
  '/schedule-advanced': () => void import('@/features/schedule-advanced'),
  '/takt': () => void import('@/features/schedule-advanced'),
  '/deadlines': () => void import('@/features/deadlines/DeadlinesPage'),
  '/resources': () => void import('@/features/resources'),
  '/timeline': () => void import('@/features/timeline'),

  // ── BIM & CAD ──
  '/bim': () => void import('@/features/bim/BIMPage'),
  '/bim/federations': () => void import('@/features/bim/FederationsPage'),
  '/bim/rules': () => void import('@/features/bim/BIMQuantityRulesPage'),
  '/data-explorer': () => void import('@/features/cad-explorer/CadDataExplorerPage'),
  '/pointcloud': () => void import('@/features/pointcloud/PointCloudPage'),
  '/model-review': () => void import('@/features/bim/ModelReviewPage'),
  '/clash': () => void import('@/features/clash/ClashDetectionPage'),
  '/bcf': () => void import('@/features/bcf/BcfPage'),
  '/coordination': () => void import('@/features/coordination/CoordinationHubPage'),
  '/match-elements': () => void import('@/features/match-elements/MatchElementsPage'),
  '/geo': () => void import('@/features/geo-hub'),
  '/assets': () => void import('@/features/bim/AssetsPage'),
  '/architecture': () => void import('@/features/architecture/ArchitectureMapPage'),

  // ── Documents & Files ──
  '/files': () => void import('@/features/file-manager/FileManagerPage'),
  '/cde': () => void import('@/features/cde/CDEPage'),
  '/transmittals': () => void import('@/features/transmittals/TransmittalsPage'),
  '/markups': () => void import('@/features/markups/MarkupsPage'),
  '/plan-room': () => void import('@/features/plan-room/PlanRoomPage'),
  '/sheets': () => void import('@/features/file-manager/SheetsIndexPage'),
  '/photos': () => void import('@/features/documents/PhotoGalleryPage'),

  // ── Commercial & Finance ──
  '/finance': () => void import('@/features/finance/FinancePage'),
  '/funding': () => void import('@/features/funding/FundingPage'),
  '/contracts': () => void import('@/features/contracts'),
  '/tendering': () => void import('@/features/tendering/TenderingPage'),
  '/bid-management': () => void import('@/features/bid-management'),
  '/rfq-bidding': () => void import('@/features/rfq-bidding'),
  '/procurement': () => void import('@/features/procurement/ProcurementPage'),
  '/postcalc': () => void import('@/features/postcalc/PostCalcPage'),
  '/variations': () => void import('@/features/variations'),
  '/changeorders': () => void import('@/features/changeorders/ChangeOrdersPage'),
  '/payment-clock': () => void import('@/features/payment-clock'),
  '/tax-withholding': () => void import('@/features/tax-withholding'),
  '/tax-rates': () => void import('@/features/tax-rates'),
  '/full-evm': () => void import('@/features/full-evm'),
  '/fx': () => void import('@/features/fx'),
  '/change-intelligence': () => void import('@/features/change-intelligence'),
  '/claims-evidence': () => void import('@/features/claims-evidence'),
  '/value': () => void import('@/features/value'),
  '/reconciliation': () => void import('@/features/reconciliation'),
  '/einvoice-clearance': () => void import('@/features/einvoice-clearance'),
  '/certified-payroll': () => void import('@/features/certified-payroll/CertifiedPayrollPage'),

  // ── Field & Site ──
  '/field-reports': () => void import('@/features/fieldreports/FieldReportsPage'),
  '/field-time': () => void import('@/features/field-time'),
  '/daily-diary': () => void import('@/features/daily-diary'),
  '/safety': () => void import('@/features/safety/SafetyPage'),
  '/hse-advanced': () => void import('@/features/hse-advanced'),
  '/site-supervision': () => void import('@/features/site-supervision/SiteSupervisionPage'),
  '/site-prep': () => void import('@/features/site-prep/SitePrepPage'),
  '/site-inventory': () => void import('@/features/site-inventory/SiteInventoryPage'),
  '/temporary-works': () => void import('@/features/temporary-works/TemporaryWorksPage'),
  '/inspections': () => void import('@/features/inspections/InspectionsPage'),
  '/construction-control': () => void import('@/features/construction_control'),
  '/punchlist': () => void import('@/features/punchlist/PunchListPage'),
  '/ncr': () => void import('@/features/ncr/NCRPage'),
  '/moc': () => void import('@/features/moc/MoCPage'),
  '/defects-liability': () => void import('@/features/defects-liability'),
  '/commissioning': () => void import('@/features/commissioning/CommissioningPage'),
  '/closeout': () => void import('@/features/closeout/CloseoutPage'),
  '/site-logistics': () => void import('@/features/site-logistics'),

  // ── Communication & Collaboration ──
  '/correspondence': () => void import('@/features/correspondence/CorrespondencePage'),
  '/rfi': () => void import('@/features/rfi/RFIPage'),
  '/submittals': () => void import('@/features/submittals/SubmittalsPage'),
  '/meetings': () => void import('@/features/meetings/MeetingsPage'),
  '/inbox': () => void import('@/features/inbox'),
  '/contacts': () => void import('@/features/contacts/ContactsPage'),
  '/tasks': () => void import('@/features/tasks/TasksPage'),
  '/signing': () => void import('@/features/signing/SigningPage'),
  '/phone-log': () => void import('@/features/phonelog'),
  '/forms': () => void import('@/features/forms'),

  // ── Analytics & Reports ──
  '/analytics': () => void import('@/features/analytics/AnalyticsPage'),
  '/reports': () => void import('@/features/reports/ReportsPage'),
  '/reporting': () => void import('@/features/reporting/ReportingPage'),
  '/risks': () => void import('@/features/risk/RiskRegisterPage'),
  '/progress': () => void import('@/features/progress/ProgressPage'),
  '/project-controls': () => void import('@/features/project-controls'),
  '/bi-dashboards': () => void import('@/features/bi-dashboards'),
  '/dashboards': () => void import('@/features/dashboards'),
  '/project-intelligence': () => void import('@/features/project-intelligence/ProjectIntelligencePage'),

  // ── Portfolio & Management ──
  '/portfolio': () => void import('@/features/portfolio'),
  '/portfolio/capacity': () => void import('@/features/portfolio/CapacityPlanningPage'),
  '/portfolio/leveling': () => void import('@/features/portfolio/ResourceLevelingPage'),
  '/subcontractors': () => void import('@/features/subcontractors'),
  '/equipment': () => void import('@/features/equipment'),
  '/payroll': () => void import('@/features/payroll/PayrollPage'),
  '/crm': () => void import('@/features/crm'),
  '/carbon': () => void import('@/features/carbon'),
  '/accommodation': () => void import('@/features/accommodation'),
  '/property-dev': () => void import('@/features/property-dev'),
  '/property-dev/dashboards': () => void import('@/features/property-dev/dashboards'),
  '/interface-management': () => void import('@/features/interface-management'),
  '/service': () => void import('@/features/service'),
  '/connectors': () => void import('@/features/connectors'),
  '/inbound': () => void import('@/features/inbound'),
  '/inbound-email': () => void import('@/features/inbound-email'),
  '/source-data': () => void import('@/features/source-data/SourceDataPage'),
  '/project-route': () => void import('@/features/project-route/ProjectRoutePage'),
  '/authority-submissions': () => void import('@/features/authority-submission/AuthoritySubmissionPage'),
  '/review-authority': () => void import('@/features/review-authority/ReviewAuthorityPage'),
  '/qms': () => void import('@/features/qms'),
  '/teams': () => void import('@/features/teams'),
  '/esg': () => void import('@/features/esg'),
  '/jobs': () => void import('@/features/jobs'),
  '/portal': () => void import('@/features/portal'),
  '/credentials': () => void import('@/features/credentials/CredentialsPage'),
  '/cvr': () => void import('@/features/cvr'),
  '/design-options': () => void import('@/features/design-options'),
  '/saved-views': () => void import('@/features/saved-views'),
  '/issues': () => void import('@/features/issues/IssuesHubPage'),
  '/cases': () => void import('@/features/cases'),
  '/videos': () => void import('@/features/videos'),
  '/requirements/matrix': () => void import('@/features/requirements/RequirementsMatrixPage'),
  '/validation': () => void import('@/features/validation'),
  '/workflows': () => void import('@/features/enterprise-workflows'),
  // ── AI & Tools ──
  '/advisor': () => void import('@/features/ai/AdvisorPage'),
  '/chat': () => void import('@/features/erp-chat/full-page/ChatFullPage'),
  '/module-builder': () => void import('@/features/module-builder/ModuleBuilderPage'),
  '/pipelines': () => void import('@/features/pipelines/PipelinesPage'),
  '/ai-agents': () => void import('@/features/ai-agents'),
  '/ai-estimate': () => void import('@/features/ai/QuickEstimatePage'),
  '/ai-estimator': () => void import('@/features/ai-estimator/AiEstimatorPage'),
  '/find': () => void import('@/features/retrieval'),

  // ── Admin ──
  '/settings': () => void import('@/features/settings/SettingsPage'),
  '/governance': () => void import('@/features/governance'),
};

// Debounce: only preload if the pointer stays on the item for 80ms.
// This avoids firing imports when the user scrolls past many items.
const timers = new Map<string, ReturnType<typeof setTimeout>>();

export function preloadRouteOnHover(path: string): void {
  // Strip query params — navCatalog items like '/boq?tab=templates'
  // should match the '/boq' preloader.
  const qIdx = path.indexOf('?');
  const base = qIdx === -1 ? path : path.slice(0, qIdx);
  const loader = preloaders[base];
  if (!loader) return;
  if (timers.has(base)) return; // already scheduled
  timers.set(
    base,
    setTimeout(() => {
      timers.delete(base);
      loader();
    }, 80),
  );
}

export function cancelRoutePreload(path: string): void {
  const qIdx = path.indexOf('?');
  const base = qIdx === -1 ? path : path.slice(0, qIdx);
  const t = timers.get(base);
  if (t != null) {
    clearTimeout(t);
    timers.delete(base);
  }
}

import { Suspense, lazy, useState, useCallback, useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { AppLayout } from './layout';
import { DashboardPage } from '@/features/dashboard';
import { LoginPage, RegisterPage, ForgotPasswordPage } from '@/features/auth';
import { ProjectsPage, CreateProjectPage, ProjectDetailPage } from '@/features/projects';
import { BOQListPage, CreateBOQPage, TemplatesPage } from '@/features/boq';
import { CostsPage, ImportDatabasePage } from '@/features/costs';
import { OnboardingWizard } from '@/features/onboarding';
import { AssembliesPage, AssemblyEditorPage, CreateAssemblyPage } from '@/features/assemblies';
import { ValidationPage } from '@/features/validation';
import { QuantitiesPage } from '@/features/quantities';
import { ModulesPage } from '@/features/modules';
import { useModuleRouteElements } from '@/modules/ModuleRoutes';
import { SettingsPage } from '@/features/settings';
import { AboutPage } from '@/features/about/AboutPage';
import { QuickEstimatePage } from '@/features/ai';
import { Logo, ShortcutsDialog, CommandPalette, ToastContainer, ErrorBoundary, NotFoundPage } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { useKeyboardShortcuts } from '@/shared/hooks/useKeyboardShortcuts';
import { useTranslation } from 'react-i18next';
import { getLanguageByCode } from './i18n';
import { initErrorLogger } from '@/shared/lib/errorLogger';

// Lazy-loaded heavy pages — code-split into separate chunks
const BOQEditorPage = lazy(() =>
  import('@/features/boq/BOQEditorPage').then((m) => ({ default: m.BOQEditorPage }))
);
const CostModelPage = lazy(() =>
  import('@/features/costmodel/CostModelPage').then((m) => ({ default: m.CostModelPage }))
);
const SchedulePage = lazy(() =>
  import('@/features/schedule/SchedulePage').then((m) => ({ default: m.SchedulePage }))
);
const TakeoffPage = lazy(() =>
  import('@/features/takeoff/TakeoffPage').then((m) => ({ default: m.TakeoffPage }))
);
const TenderingPage = lazy(() =>
  import('@/features/tendering/TenderingPage').then((m) => ({ default: m.TenderingPage }))
);
const ReportsPage = lazy(() =>
  import('@/features/reports/ReportsPage').then((m) => ({ default: m.ReportsPage }))
);
const CatalogPage = lazy(() =>
  import('@/features/catalog/CatalogPage').then((m) => ({ default: m.CatalogPage }))
);
const AdvisorPage = lazy(() =>
  import('@/features/ai/AdvisorPage').then((m) => ({ default: m.AdvisorPage }))
);
const ChangeOrdersPage = lazy(() =>
  import('@/features/changeorders/ChangeOrdersPage').then((m) => ({ default: m.ChangeOrdersPage }))
);
const AnalyticsPage = lazy(() =>
  import('@/features/analytics/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage }))
);
const RiskRegisterPage = lazy(() =>
  import('@/features/risk/RiskRegisterPage').then((m) => ({ default: m.RiskRegisterPage }))
);
const DocumentsPage = lazy(() =>
  import('@/features/documents/DocumentsPage').then((m) => ({ default: m.DocumentsPage }))
);

function LoadingScreen() {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-secondary">
      <div className="flex flex-col items-center gap-3 animate-fade-in">
        <Logo size="lg" animate />
        <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-secondary">
          <div className="h-full w-8 animate-shimmer rounded-full bg-oe-blue opacity-60" />
        </div>
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function P({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AppLayout title={title}>
        <ErrorBoundary>{children}</ErrorBoundary>
      </AppLayout>
    </RequireAuth>
  );
}

/** Mounts global keyboard shortcuts, the shortcuts help dialog, and the command palette. */
function GlobalShortcuts() {
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const handleToggleShortcuts = useCallback(() => {
    setShortcutsOpen((prev) => !prev);
  }, []);

  // The `/` shortcut for search is already handled by Header's own keydown
  // listener, so we pass a no-op here to avoid duplicate triggers.
  const noop = useCallback(() => {}, []);

  useKeyboardShortcuts({
    onOpenSearch: noop,
    onToggleShortcutsDialog: handleToggleShortcuts,
  });

  // Ctrl+K / Cmd+K to open command palette
  // Ctrl+N to create new project
  // Ctrl+Shift+N to create new BOQ
  // Ctrl+Shift+V to run validation
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      if (mod && e.key === 'k') {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
      if (e.key === '/' && !mod) {
        e.preventDefault();
        setPaletteOpen(true);
      }
      if (mod && e.shiftKey && e.key === 'N') {
        e.preventDefault();
        navigate('/boq/new');
      } else if (mod && e.key === 'n') {
        e.preventDefault();
        navigate('/projects/new');
      }
      if (mod && e.shiftKey && e.key === 'V') {
        e.preventDefault();
        navigate('/validation');
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [navigate]);

  return (
    <>
      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}

// Run once at module load — synchronous, before any render
useAuthStore.getState().loadFromStorage();
useThemeStore.getState().init();

// Initialize the anonymized error logger (global handlers for unhandled errors)
initErrorLogger();

/** Keeps <html dir="..."> and lang attribute in sync with the active i18n language. */
function useDocumentDirection() {
  const { i18n } = useTranslation();

  // Set dir immediately on mount (not just on language change)
  useEffect(() => {
    const lang = getLanguageByCode(i18n.language);
    const dir = (lang && 'dir' in lang && lang.dir === 'rtl') ? 'rtl' : 'ltr';
    document.documentElement.dir = dir;
    document.documentElement.lang = i18n.language;
  }, [i18n.language]);

  // Also listen for runtime language changes
  useEffect(() => {
    const handler = (lng: string) => {
      const lang = getLanguageByCode(lng);
      const dir = (lang && 'dir' in lang && lang.dir === 'rtl') ? 'rtl' : 'ltr';
      document.documentElement.dir = dir;
      document.documentElement.lang = lng;
    };
    i18n.on('languageChanged', handler);
    return () => { i18n.off('languageChanged', handler); };
  }, [i18n]);
}

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  useDocumentDirection();

  // Dynamic routes from the module registry (lazy-loaded)
  const moduleRoutes = useModuleRouteElements({ Wrapper: P });

  return (
    <Suspense fallback={<LoadingScreen />}>
      {isAuthenticated && <GlobalShortcuts />}
      <Routes>
        {/* Auth — public */}
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route path="/register" element={isAuthenticated ? <Navigate to="/" replace /> : <RegisterPage />} />
        <Route path="/forgot-password" element={isAuthenticated ? <Navigate to="/" replace /> : <ForgotPasswordPage />} />

        {/* Onboarding — full-screen, no layout */}
        <Route path="/onboarding" element={
          <RequireAuth><OnboardingWizard /></RequireAuth>
        } />

        {/* App — all protected, all real pages */}
        <Route path="/" element={<P title="Dashboard"><DashboardPage /></P>} />

        <Route path="/ai-estimate" element={<P title="AI Quick Estimate"><QuickEstimatePage /></P>} />
        <Route path="/advisor" element={<P title="AI Cost Advisor"><AdvisorPage /></P>} />
        <Route path="/cad-takeoff" element={<P title="CAD/BIM Takeoff"><QuickEstimatePage /></P>} />

        <Route path="/projects" element={<P title="Projects"><ProjectsPage /></P>} />
        <Route path="/projects/new" element={<P title="New Project"><CreateProjectPage /></P>} />
        <Route path="/projects/:projectId" element={<P title="Project"><ProjectDetailPage /></P>} />
        <Route path="/projects/:projectId/boq/new" element={<P title="New BOQ"><CreateBOQPage /></P>} />

        <Route path="/boq" element={<P title="Bill of Quantities"><BOQListPage /></P>} />
        <Route path="/boq/:boqId" element={<P title="BOQ Editor"><BOQEditorPage /></P>} />
        <Route path="/templates" element={<P title="BOQ Templates"><TemplatesPage /></P>} />

        <Route path="/costs" element={<P title="Cost Database"><CostsPage /></P>} />
        <Route path="/costs/import" element={<P title="Import Cost Database"><ImportDatabasePage /></P>} />

        <Route path="/catalog" element={<P title="Resource Catalog"><CatalogPage /></P>} />

        <Route path="/assemblies" element={<P title="Assemblies"><AssembliesPage /></P>} />
        <Route path="/assemblies/new" element={<P title="New Assembly"><CreateAssemblyPage /></P>} />
        <Route path="/assemblies/:assemblyId" element={<P title="Assembly Editor"><AssemblyEditorPage /></P>} />

        <Route path="/validation" element={<P title="Validation"><ValidationPage /></P>} />

        <Route path="/quantities" element={<P title="Quantity Takeoff"><QuantitiesPage /></P>} />
        <Route path="/takeoff" element={<P title="PDF Takeoff"><TakeoffPage /></P>} />

        <Route path="/schedule" element={<P title="4D Schedule"><SchedulePage /></P>} />

        <Route path="/5d" element={<P title="5D Cost Model"><CostModelPage /></P>} />

        <Route path="/analytics" element={<P title="Analytics"><AnalyticsPage /></P>} />

        <Route path="/reports" element={<P title="Reports"><ReportsPage /></P>} />

        <Route path="/tendering" element={<P title="Tendering"><TenderingPage /></P>} />

        <Route path="/changeorders" element={<P title="Change Orders"><ChangeOrdersPage /></P>} />
        <Route path="/documents" element={<P title="Documents"><DocumentsPage /></P>} />

        <Route path="/risks" element={<P title="Risk Register"><RiskRegisterPage /></P>} />

        <Route path="/modules" element={<P title="Modules"><ModulesPage /></P>} />

        <Route path="/settings" element={<P title="Settings"><SettingsPage /></P>} />
        <Route path="/about" element={<P title="About"><AboutPage /></P>} />

        {/* Plugin module routes — lazy-loaded */}
        {moduleRoutes}

        {/* 404 — catch-all for unknown routes */}
        <Route path="*" element={isAuthenticated ? <P title="Not Found"><NotFoundPage /></P> : <Navigate to="/login" replace />} />
      </Routes>
      <ToastContainer />
    </Suspense>
  );
}

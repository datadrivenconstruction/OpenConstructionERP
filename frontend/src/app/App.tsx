import { Suspense, useEffect, useState, useCallback } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from './layout';
import { DashboardPage } from '@/features/dashboard';
import { LoginPage, RegisterPage, ForgotPasswordPage } from '@/features/auth';
import { ProjectsPage, CreateProjectPage, ProjectDetailPage } from '@/features/projects';
import { BOQListPage, BOQEditorPage, CreateBOQPage, TemplatesPage } from '@/features/boq';
import { CostsPage } from '@/features/costs';
import { AssembliesPage, AssemblyEditorPage, CreateAssemblyPage } from '@/features/assemblies';
import { ValidationPage } from '@/features/validation';
import { SchedulePage } from '@/features/schedule';
import { CostModelPage } from '@/features/costmodel';
import { TenderingPage } from '@/features/tendering';
import { ModulesPage } from '@/features/modules';
import { SettingsPage } from '@/features/settings';
import { QuickEstimatePage } from '@/features/ai';
import { Logo, ShortcutsDialog, ToastContainer } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { useKeyboardShortcuts } from '@/shared/hooks/useKeyboardShortcuts';

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
      <AppLayout title={title}>{children}</AppLayout>
    </RequireAuth>
  );
}

/** Mounts global keyboard shortcuts and the shortcuts help dialog. */
function GlobalShortcuts() {
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

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

  return <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />;
}

export default function App() {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  return (
    <Suspense fallback={<LoadingScreen />}>
      {isAuthenticated && <GlobalShortcuts />}
      <Routes>
        {/* Auth — public */}
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route path="/register" element={isAuthenticated ? <Navigate to="/" replace /> : <RegisterPage />} />
        <Route path="/forgot-password" element={isAuthenticated ? <Navigate to="/" replace /> : <ForgotPasswordPage />} />

        {/* App — all protected, all real pages */}
        <Route path="/" element={<P title="Dashboard"><DashboardPage /></P>} />

        <Route path="/ai-estimate" element={<P title="AI Quick Estimate"><QuickEstimatePage /></P>} />

        <Route path="/projects" element={<P title="Projects"><ProjectsPage /></P>} />
        <Route path="/projects/new" element={<P title="New Project"><CreateProjectPage /></P>} />
        <Route path="/projects/:projectId" element={<P title="Project"><ProjectDetailPage /></P>} />
        <Route path="/projects/:projectId/boq/new" element={<P title="New BOQ"><CreateBOQPage /></P>} />

        <Route path="/boq" element={<P title="Bill of Quantities"><BOQListPage /></P>} />
        <Route path="/boq/:boqId" element={<P title="BOQ Editor"><BOQEditorPage /></P>} />
        <Route path="/templates" element={<P title="BOQ Templates"><TemplatesPage /></P>} />

        <Route path="/costs" element={<P title="Cost Database"><CostsPage /></P>} />

        <Route path="/assemblies" element={<P title="Assemblies"><AssembliesPage /></P>} />
        <Route path="/assemblies/new" element={<P title="New Assembly"><CreateAssemblyPage /></P>} />
        <Route path="/assemblies/:assemblyId" element={<P title="Assembly Editor"><AssemblyEditorPage /></P>} />

        <Route path="/validation" element={<P title="Validation"><ValidationPage /></P>} />

        <Route path="/schedule" element={<P title="4D Schedule"><SchedulePage /></P>} />

        <Route path="/5d" element={<P title="5D Cost Model"><CostModelPage /></P>} />

        <Route path="/tendering" element={<P title="Tendering"><TenderingPage /></P>} />

        <Route path="/modules" element={<P title="Modules"><ModulesPage /></P>} />

        <Route path="/settings" element={<P title="Settings"><SettingsPage /></P>} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ToastContainer />
    </Suspense>
  );
}

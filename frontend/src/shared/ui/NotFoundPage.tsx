import { Link } from 'react-router-dom';
import { Home, ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * 404 Not Found page. Displayed for unknown routes instead of silently
 * redirecting to the dashboard.
 */
export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-primary p-8">
      <div className="max-w-md text-center">
        <div className="mb-6 text-9xl font-extrabold bg-gradient-to-r from-oe-blue to-violet-500 bg-clip-text text-transparent select-none animate-fade-in">404</div>
        <h1 className="mb-2 text-xl font-semibold text-content-primary">
          {t('error.not_found', { defaultValue: 'Page not found' })}
        </h1>
        <p className="mb-8 text-sm text-content-secondary">
          {t('error.not_found_desc', {
            defaultValue:
              'The page you are looking for does not exist or has been moved. Check the URL or go back to the dashboard.',
          })}
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => window.history.back()}
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-elevated px-4 py-2.5 text-sm font-medium text-content-primary transition-colors hover:bg-surface-secondary"
          >
            <ArrowLeft size={14} />
            {t('error.go_back', { defaultValue: 'Go back' })}
          </button>
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-oe-blue-dark"
          >
            <Home size={14} />
            {t('error.go_dashboard', { defaultValue: 'Dashboard' })}
          </Link>
        </div>
      </div>
    </div>
  );
}

import React from 'react';
import { AlertTriangle, RotateCcw, Home } from 'lucide-react';
import i18n from '@/app/i18n';
import { logError } from '@/shared/lib/errorLogger';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Catches React render errors and displays a recovery UI instead of a white screen.
 * Wraps page-level routes so a crash in one page doesn't break the whole app.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught render error:', error, info.componentStack);
    logError(error, 'react_error', {
      componentStack: info.componentStack ?? '',
    });
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  handleGoHome = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = '/';
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex min-h-[60vh] items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-semantic-error-bg">
              <AlertTriangle size={28} className="text-semantic-error" />
            </div>
            <h2 className="mb-2 text-xl font-semibold text-content-primary">
              {i18n.t('error.something_wrong')}
            </h2>
            <p className="mb-6 text-sm text-content-secondary">
              {i18n.t('error.unexpected_error')}
            </p>
            {this.state.error && (
              <details className="mb-6 rounded-lg border border-border-light bg-surface-secondary p-3 text-left">
                <summary className="cursor-pointer text-xs font-medium text-content-secondary">
                  {i18n.t('error.details')}
                </summary>
                <pre className="mt-2 overflow-x-auto text-xs text-semantic-error">
                  {this.state.error.message}
                </pre>
              </details>
            )}
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={this.handleReset}
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-elevated px-4 py-2 text-sm font-medium text-content-primary transition-colors hover:bg-surface-secondary"
              >
                <RotateCcw size={14} />
                {i18n.t('error.try_again')}
              </button>
              <button
                onClick={this.handleGoHome}
                className="inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-oe-blue-dark"
              >
                <Home size={14} />
                {i18n.t('error.go_dashboard')}
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

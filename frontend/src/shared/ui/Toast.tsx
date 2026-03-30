import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';
import type { Toast as ToastType } from '@/stores/useToastStore';

const iconMap = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
} as const;

const styleMap = {
  success: {
    bg: 'bg-semantic-success-bg',
    border: 'border-semantic-success/30',
    icon: 'text-semantic-success',
    title: 'text-content-primary',
    message: 'text-content-secondary',
  },
  error: {
    bg: 'bg-semantic-error-bg',
    border: 'border-semantic-error/30',
    icon: 'text-semantic-error',
    title: 'text-content-primary',
    message: 'text-content-secondary',
  },
  warning: {
    bg: 'bg-semantic-warning-bg',
    border: 'border-semantic-warning/30',
    icon: 'text-semantic-warning',
    title: 'text-content-primary',
    message: 'text-content-secondary',
  },
  info: {
    bg: 'bg-semantic-info-bg',
    border: 'border-semantic-info/30',
    icon: 'text-semantic-info',
    title: 'text-content-primary',
    message: 'text-content-secondary',
  },
} as const;

interface ToastProps {
  toast: ToastType;
  onDismiss: (id: string) => void;
}

export function Toast({ toast, onDismiss }: ToastProps) {
  const { t } = useTranslation();
  const Icon = iconMap[toast.type];
  const styles = styleMap[toast.type];

  const handleDismiss = useCallback(() => {
    onDismiss(toast.id);
  }, [onDismiss, toast.id]);

  const handleAction = useCallback(() => {
    toast.action?.onClick();
    onDismiss(toast.id);
  }, [toast.action, toast.id, onDismiss]);

  return (
    <div
      className={`flex items-start gap-3 w-80 rounded-xl border px-4 py-3 shadow-md animate-toast-in ${styles.bg} ${styles.border}`}
      role="alert"
    >
      <Icon size={18} className={`shrink-0 mt-0.5 ${styles.icon}`} />
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-medium ${styles.title}`}>{toast.title}</p>
        {toast.message && (
          <p className={`mt-0.5 text-xs ${styles.message}`}>{toast.message}</p>
        )}
        {toast.action && (
          <button
            onClick={handleAction}
            className="mt-1 text-xs font-semibold text-oe-blue hover:text-oe-blue-hover underline underline-offset-2 transition-colors"
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        onClick={handleDismiss}
        className="shrink-0 mt-0.5 h-5 w-5 flex items-center justify-center rounded text-content-tertiary hover:text-content-primary transition-colors"
        aria-label={t('common.close', 'Close')}
      >
        <X size={14} />
      </button>
    </div>
  );
}

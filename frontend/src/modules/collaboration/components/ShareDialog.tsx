import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check, X, Link2 } from 'lucide-react';

interface ShareDialogProps {
  roomName: string;
  isOpen: boolean;
  onClose: () => void;
}

export function ShareDialog({ roomName, isOpen, onClose }: ShareDialogProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const shareUrl = `${window.location.origin}${window.location.pathname}?room=${encodeURIComponent(roomName)}`;

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const input = document.createElement('input');
      input.value = shareUrl;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [shareUrl]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-96 rounded-xl border border-border bg-surface-elevated p-5 shadow-lg">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2">
            <Link2 size={16} className="text-oe-blue" />
            {t('collab.share_title', { defaultValue: 'Share Collaboration Link' })}
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <p className="text-xs text-content-tertiary mb-3">
          {t('collab.share_desc', {
            defaultValue: 'Share this link with collaborators. Anyone with the link can join and edit in real-time using peer-to-peer sync.',
          })}
        </p>

        <div className="flex items-center gap-2 mb-4">
          <input
            type="text"
            readOnly
            value={shareUrl}
            className="flex-1 rounded-lg border border-border bg-surface-secondary px-3 py-2 text-xs text-content-primary truncate"
          />
          <button
            onClick={handleCopy}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
              copied
                ? 'bg-emerald-500 text-white'
                : 'bg-oe-blue text-white hover:bg-oe-blue-hover'
            }`}
          >
            {copied ? (
              <>
                <Check size={12} />
                {t('common.copied', { defaultValue: 'Copied!' })}
              </>
            ) : (
              <>
                <Copy size={12} />
                {t('common.copy', { defaultValue: 'Copy' })}
              </>
            )}
          </button>
        </div>

        <div className="rounded-lg bg-surface-secondary p-3">
          <p className="text-2xs text-content-tertiary">
            <strong className="text-content-secondary">
              {t('collab.p2p_note_title', { defaultValue: 'Peer-to-peer sync' })}
            </strong>
            {' — '}
            {t('collab.p2p_note', {
              defaultValue: 'Changes sync directly between browsers via WebRTC. No data is stored on a server. All participants must be online simultaneously.',
            })}
          </p>
        </div>
      </div>
    </div>
  );
}

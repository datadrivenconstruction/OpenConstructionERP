import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Users, Wifi, Shield, Zap, Info } from 'lucide-react';
import { COLLAB_COLORS } from './types';

/**
 * Collaboration settings / info page.
 * Explains how real-time collaboration works and lets users configure preferences.
 */
export default function CollaborationModule() {
  const { t } = useTranslation();
  const [displayName, setDisplayName] = useState(
    () => localStorage.getItem('oe_collab_name') || 'User',
  );

  const handleSaveName = () => {
    localStorage.setItem('oe_collab_name', displayName);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-100 dark:bg-violet-900/30">
          <Users className="h-5 w-5 text-violet-600 dark:text-violet-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            {t('collab.title', { defaultValue: 'Real-time Collaboration' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('collab.subtitle', { defaultValue: 'Work together on estimates in real-time with your team' })}
          </p>
        </div>
      </div>

      {/* How it works */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <FeatureCard
          icon={<Wifi className="h-5 w-5 text-blue-500" />}
          title={t('collab.feature_sync', { defaultValue: 'Peer-to-Peer Sync' })}
          description={t('collab.feature_sync_desc', {
            defaultValue: 'Changes sync directly between browsers via WebRTC. No server required — works with just a signaling server for connection setup.',
          })}
        />
        <FeatureCard
          icon={<Zap className="h-5 w-5 text-amber-500" />}
          title={t('collab.feature_crdt', { defaultValue: 'CRDT Conflict Resolution' })}
          description={t('collab.feature_crdt_desc', {
            defaultValue: 'Built on Yjs — a battle-tested CRDT library. Concurrent edits merge automatically without conflicts. No data loss.',
          })}
        />
        <FeatureCard
          icon={<Shield className="h-5 w-5 text-emerald-500" />}
          title={t('collab.feature_presence', { defaultValue: 'Presence Awareness' })}
          description={t('collab.feature_presence_desc', {
            defaultValue: 'See who is online, what they are editing, and where their cursor is. Colored indicators show active collaborators.',
          })}
        />
      </div>

      {/* Display name settings */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <h3 className="text-sm font-semibold text-content-primary mb-3">
          {t('collab.settings', { defaultValue: 'Collaboration Settings' })}
        </h3>
        <div className="flex items-center gap-3 max-w-sm">
          <div className="flex-1">
            <label className="block text-xs text-content-tertiary mb-1">
              {t('collab.display_name', { defaultValue: 'Your display name' })}
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
              placeholder={t('collab.name_placeholder', { defaultValue: 'Your name' })}
              aria-label={t('collab.display_name', { defaultValue: 'Your display name' })}
            />
          </div>
          <button
            onClick={handleSaveName}
            className="mt-5 rounded-lg bg-oe-blue px-4 py-2 text-xs font-medium text-white hover:bg-oe-blue-hover transition-colors"
            aria-label={t('collab.save_name', { defaultValue: 'Save display name' })}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </button>
        </div>
      </div>

      {/* Color palette */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <h3 className="text-sm font-semibold text-content-primary mb-3">
          {t('collab.color_palette', { defaultValue: 'User Colors' })}
        </h3>
        <p className="text-xs text-content-tertiary mb-3">
          {t('collab.color_desc', {
            defaultValue: 'Colors are automatically assigned when you join a session. Each collaborator gets a unique color.',
          })}
        </p>
        <div className="flex gap-2">
          {COLLAB_COLORS.map((color) => (
            <div
              key={color}
              className="h-8 w-8 rounded-full border-2 border-surface-primary shadow-sm"
              style={{ backgroundColor: color }}
              role="presentation"
              aria-hidden="true"
            />
          ))}
        </div>
      </div>

      {/* How to use */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <h3 className="text-sm font-semibold text-content-primary mb-3">
          {t('collab.how_to', { defaultValue: 'How to Collaborate' })}
        </h3>
        <ol className="space-y-2 text-xs text-content-secondary">
          <li className="flex gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white text-2xs font-bold shrink-0">1</span>
            {t('collab.step1', { defaultValue: 'Open a BOQ in the editor' })}
          </li>
          <li className="flex gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white text-2xs font-bold shrink-0">2</span>
            {t('collab.step2', { defaultValue: 'Click "Share" in the collaboration bar above the grid' })}
          </li>
          <li className="flex gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white text-2xs font-bold shrink-0">3</span>
            {t('collab.step3', { defaultValue: 'Send the link to your teammates' })}
          </li>
          <li className="flex gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white text-2xs font-bold shrink-0">4</span>
            {t('collab.step4', { defaultValue: 'Edit together — changes appear in real-time' })}
          </li>
        </ol>
      </div>

      {/* Disclaimer */}
      <div className="flex items-start gap-2 text-xs text-content-quaternary">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>
          {t('collab.disclaimer', {
            defaultValue: 'Real-time collaboration uses peer-to-peer WebRTC connections. Data syncs directly between browsers. For persistent server-side sync, configure a WebSocket provider in production.',
          })}
        </p>
      </div>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-primary p-4">
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <h4 className="text-sm font-semibold text-content-primary">{title}</h4>
      </div>
      <p className="text-xs text-content-tertiary leading-relaxed">{description}</p>
    </div>
  );
}

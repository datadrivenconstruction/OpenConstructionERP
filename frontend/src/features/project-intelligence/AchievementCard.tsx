/**
 * AchievementCard — shows a completed achievement with a green check.
 */

import { CheckCircle2 } from 'lucide-react';

interface Achievement {
  domain: string;
  title: string;
  description: string;
}

interface AchievementCardProps {
  achievement: Achievement;
}

export function AchievementCard({ achievement }: AchievementCardProps) {
  return (
    <div className="flex items-start gap-2 py-1.5 px-1">
      <CheckCircle2 size={13} className="shrink-0 mt-0.5 text-green-400" />
      <div className="min-w-0">
        <p className="text-xs text-content-secondary leading-snug">{achievement.title}</p>
      </div>
    </div>
  );
}

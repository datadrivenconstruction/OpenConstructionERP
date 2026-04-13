/**
 * DomainBar — horizontal progress bar for a single domain score.
 *
 * Shows domain label, animated fill bar, and percentage.
 * Clickable to select/expand domain details.
 */

import { useState, useEffect } from 'react';
import clsx from 'clsx';

interface DomainBarProps {
  label: string;
  score: number; // 0-100
  color: string;
  onClick?: () => void;
  isSelected?: boolean;
}

export function DomainBar({ label, score, color, onClick, isSelected }: DomainBarProps) {
  const [animatedWidth, setAnimatedWidth] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => {
      setAnimatedWidth(Math.min(100, Math.max(0, score)));
    }, 100);
    return () => clearTimeout(timer);
  }, [score]);

  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full flex items-center gap-2 py-1 px-1 rounded-md transition-colors text-left',
        isSelected
          ? 'bg-surface-tertiary'
          : 'hover:bg-surface-tertiary/50'
      )}
      aria-label={`${label}: ${Math.round(score)}%`}
    >
      <span className="text-xs text-content-secondary w-20 shrink-0 truncate">
        {label}
      </span>
      <div className="flex-1 h-1.5 bg-border-light/40 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{
            width: `${animatedWidth}%`,
            backgroundColor: color,
          }}
        />
      </div>
      <span className="text-xs tabular-nums text-content-tertiary w-8 text-right shrink-0">
        {Math.round(score)}%
      </span>
    </button>
  );
}

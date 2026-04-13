/**
 * ScoreRing — animated SVG circular progress indicator.
 *
 * Draws a ring from 0 to the actual score on mount with ease-out animation.
 * Displays score number and grade letter in the center.
 */

import { useState, useEffect, useRef } from 'react';

interface ScoreRingProps {
  score: number; // 0-100
  grade: string; // "A" | "B" | "C" | "D" | "F"
  gradeColor: string;
  size?: number;
  strokeWidth?: number;
}

export function ScoreRing({
  score,
  grade,
  gradeColor,
  size = 160,
  strokeWidth = 10,
}: ScoreRingProps) {
  const [animatedScore, setAnimatedScore] = useState(0);
  const animRef = useRef<number | null>(null);

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;

  // Animate score from 0 to target
  useEffect(() => {
    const duration = 1200; // ms
    const start = performance.now();
    const target = Math.min(100, Math.max(0, score));

    function animate(now: number) {
      const elapsed = now - start;
      const progress = Math.min(1, elapsed / duration);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setAnimatedScore(Math.round(target * eased));

      if (progress < 1) {
        animRef.current = requestAnimationFrame(animate);
      }
    }

    animRef.current = requestAnimationFrame(animate);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [score]);

  const dashOffset = circumference - (animatedScore / 100) * circumference;

  return (
    <div
      className="relative inline-flex items-center justify-center"
      role="img"
      aria-label={`Project score: ${Math.round(score)} out of 100, grade ${grade}`}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="transform -rotate-90"
      >
        {/* Background ring */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-border-light opacity-30"
        />
        {/* Progress ring */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={gradeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          style={{
            transition: 'stroke 0.3s ease',
          }}
        />
      </svg>
      {/* Center text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="text-3xl font-bold tabular-nums"
          style={{ color: gradeColor }}
        >
          {animatedScore}
        </span>
        <span
          className="text-sm font-semibold -mt-0.5"
          style={{ color: gradeColor, opacity: 0.8 }}
        >
          {grade}
        </span>
      </div>
    </div>
  );
}

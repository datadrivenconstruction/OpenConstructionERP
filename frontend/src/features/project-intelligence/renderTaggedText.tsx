/**
 * renderTaggedText — parses plain text containing `[TAG]` patterns and replaces
 * them with colored badge spans.
 *
 * Supported tags:
 *   [CRITICAL] -> red badge
 *   [HIGH]     -> orange/amber badge
 *   [MEDIUM]   -> yellow badge
 *   [LOW]      -> green badge
 *   [INFO]     -> blue badge
 *   [BLOCKER]  -> red badge (alias for critical)
 *   [WARNING]  -> yellow badge (alias for medium)
 */

import React from 'react';

const TAG_STYLES: Record<string, string> = {
  CRITICAL: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  BLOCKER: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  HIGH: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  MEDIUM: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  WARNING: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  LOW: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  INFO: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
};

// Match [WORD] patterns where WORD is uppercase letters/underscores
const TAG_REGEX = /\[(CRITICAL|BLOCKER|HIGH|MEDIUM|WARNING|LOW|INFO)\]/gi;

/**
 * Parse text, find [TAG] patterns, and return React nodes with styled badge spans.
 */
export function renderTaggedText(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  // Reset regex state
  TAG_REGEX.lastIndex = 0;

  while ((match = TAG_REGEX.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    const tagName = (match[1] ?? '').toUpperCase();
    const style = TAG_STYLES[tagName] || TAG_STYLES.INFO;

    parts.push(
      <span
        key={`tag-${match.index}`}
        className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide ${style}`}
      >
        {tagName}
      </span>,
    );

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text after last match
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  // If no tags found, return original text
  if (parts.length === 0) {
    return text;
  }

  return <>{parts}</>;
}

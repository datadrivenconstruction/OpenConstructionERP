/**
 * Color tokens for EAC v2 visual block editor.
 *
 * Per RFC 35 §7 + spec §3.2, every block has a designated color *and* an icon
 * + label. This dual encoding satisfies AC-3.6 (don't rely on color alone for
 * meaning) and is what axe-core looks for in the Storybook a11y addon.
 *
 * Tailwind classes are emitted as static strings (no template interpolation)
 * so the JIT compiler can detect them at build time. If you change the palette,
 * verify the new classes are still in `tailwind.config.js` content paths.
 *
 * Light-mode and dark-mode variants are colocated. The `dark:` prefix is
 * Tailwind's `darkMode: 'class'` strategy (already configured in
 * `tailwind.config.js`).
 */
import type { ComponentType } from 'react';
import {
  Filter,
  GitBranch,
  Tag,
  Sliders,
  Variable,
  type LucideProps,
} from 'lucide-react';

import type { BlockColor } from './types';

/** Tailwind class set for one block color in both light and dark themes. */
export interface BlockClassSet {
  /** Background tint shown in palette and on the canvas. */
  bg: string;
  /** Background tint when block is selected (slightly stronger). */
  bgSelected: string;
  /** Border color (default state). */
  border: string;
  /** Border color (selected/focused state). */
  borderSelected: string;
  /** Foreground text color for the label. */
  text: string;
  /** Subdued/secondary foreground for value summaries. */
  textSubtle: string;
  /** Color of the icon glyph. */
  icon: string;
}

/**
 * Per-block visual identity. Each entry has classes for both themes plus an
 * icon component and a human label. Keep entries here (not inline in
 * components) so tests can introspect them.
 */
export interface BlockTokenEntry {
  classes: BlockClassSet;
  /** Lucide icon component. Rendered with size=16 by `<BlockShell>`. */
  Icon: ComponentType<LucideProps>;
  /** Short label used as the visible block heading. */
  label: string;
  /** Long label used for screen reader description / tooltips. */
  description: string;
}

/**
 * The canonical mapping of block color → visual tokens. Spec §3.2 ordering:
 * selector (gray) → logic (green) → attribute (purple) → constraint (blue)
 * → variable (yellow).
 */
export const BLOCK_COLORS: Record<BlockColor, BlockTokenEntry> = {
  selector: {
    classes: {
      bg: 'bg-gray-100 dark:bg-gray-800',
      bgSelected: 'bg-gray-200 dark:bg-gray-700',
      border: 'border-gray-300 dark:border-gray-600',
      borderSelected: 'border-gray-500 dark:border-gray-400',
      text: 'text-gray-900 dark:text-gray-100',
      textSubtle: 'text-gray-600 dark:text-gray-400',
      icon: 'text-gray-700 dark:text-gray-300',
    },
    Icon: Filter,
    label: 'Selector',
    description: 'Match elements by category, classification, or spatial container',
  },
  logic: {
    classes: {
      bg: 'bg-green-100 dark:bg-green-900/40',
      bgSelected: 'bg-green-200 dark:bg-green-800/60',
      border: 'border-green-300 dark:border-green-700',
      borderSelected: 'border-green-500 dark:border-green-500',
      text: 'text-green-900 dark:text-green-100',
      textSubtle: 'text-green-700 dark:text-green-300',
      icon: 'text-green-700 dark:text-green-300',
    },
    Icon: GitBranch,
    label: 'Logic',
    description: 'Combine predicates with AND, OR, or NOT',
  },
  attribute: {
    classes: {
      bg: 'bg-purple-100 dark:bg-purple-900/40',
      bgSelected: 'bg-purple-200 dark:bg-purple-800/60',
      border: 'border-purple-300 dark:border-purple-700',
      borderSelected: 'border-purple-500 dark:border-purple-500',
      text: 'text-purple-900 dark:text-purple-100',
      textSubtle: 'text-purple-700 dark:text-purple-300',
      icon: 'text-purple-700 dark:text-purple-300',
    },
    Icon: Tag,
    label: 'Attribute',
    description: 'Reference a property, alias, or regex pattern',
  },
  constraint: {
    classes: {
      bg: 'bg-blue-100 dark:bg-blue-900/40',
      bgSelected: 'bg-blue-200 dark:bg-blue-800/60',
      border: 'border-blue-300 dark:border-blue-700',
      borderSelected: 'border-blue-500 dark:border-blue-500',
      text: 'text-blue-900 dark:text-blue-100',
      textSubtle: 'text-blue-700 dark:text-blue-300',
      icon: 'text-blue-700 dark:text-blue-300',
    },
    Icon: Sliders,
    label: 'Constraint',
    description: 'Compare an attribute against a value or range',
  },
  variable: {
    classes: {
      bg: 'bg-yellow-100 dark:bg-yellow-900/40',
      bgSelected: 'bg-yellow-200 dark:bg-yellow-800/60',
      border: 'border-yellow-300 dark:border-yellow-700',
      borderSelected: 'border-yellow-600 dark:border-yellow-500',
      text: 'text-yellow-900 dark:text-yellow-100',
      textSubtle: 'text-yellow-700 dark:text-yellow-300',
      icon: 'text-yellow-700 dark:text-yellow-300',
    },
    Icon: Variable,
    label: 'Variable',
    description: 'Define a local or global variable with an aggregate function',
  },
};

/** Lookup helper — returns the entry or throws if the key is invalid. */
export function getBlockTokens(color: BlockColor): BlockTokenEntry {
  const entry = BLOCK_COLORS[color];
  if (!entry) {
    throw new Error(`Unknown block color: ${color}`);
  }
  return entry;
}

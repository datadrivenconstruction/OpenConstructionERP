// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fileDistributionGuide - "How it works" content for the file-distribution
// (W10) module. Consumed by <ModuleGuideButton content={fileDistributionGuide} />
// on GlobalSearchPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const fileDistributionGuide: ModuleGuideContent = {
  titleKey: 'guide.file_distribution.title',
  titleDefault: 'File Search and Distribution',
  introKey: 'guide.file_distribution.intro',
  introDefault:
    'Search for a document, sheet or photo by name across every project you can access, then open it in context. The same module also keeps reusable distribution lists and folder subscriptions so the right people are notified when files change.',
  sections: [
    {
      icon: 'Search',
      titleKey: 'guide.file_distribution.search.title',
      titleDefault: 'Search across all projects',
      bodyKey: 'guide.file_distribution.search.body',
      bodyDefault:
        'Type a name, drawing number or reference such as RFI-014 into the search box and run it. The module looks across every project you have access to in one pass, so you do not need to open each project to find a file. When a full-text index is installed the results also match content inside the files.',
      spotlightSelector: '[data-testid="global-search-input"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.file_distribution.filters.title',
      titleDefault: 'Narrow and sort the results',
      bodyKey: 'guide.file_distribution.filters.body',
      bodyDefault:
        'Use the filter rail to limit results to documents, sheets or photos, and to sort by relevance, name or project. Turn on Group by project to bundle the hits under each project heading so you can scan one job at a time.',
      spotlightSelector: '[data-testid="global-search-filter-rail"]',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.file_distribution.results.title',
      titleDefault: 'Open a file in context',
      bodyKey: 'guide.file_distribution.results.body',
      bodyDefault:
        'Each result card shows the file name, its kind and the project it belongs to, with a short snippet where one is available. Click a card to jump straight to the file inside its own project, already selected in the file manager.',
      spotlightSelector: '[data-testid="global-search-results"]',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.file_distribution.recent.title',
      titleDefault: 'Recent searches',
      bodyKey: 'guide.file_distribution.recent.body',
      bodyDefault:
        'Your last few searches are kept as chips above the results so you can re-run them with one click. The current search also lives in the page URL, which makes it easy to share a search with a colleague.',
      spotlightSelector: '[data-testid="global-search-recent"]',
    },
    {
      icon: 'Send',
      titleKey: 'guide.file_distribution.lists.title',
      titleDefault: 'Distribution lists',
      bodyKey: 'guide.file_distribution.lists.body',
      bodyDefault:
        'Build reusable distribution lists of recipients and tag each member with a role such as for review, FYI or for construction. Lists can be private or shared with the team, so issuing a set of files to the same group is a single step instead of retyping addresses each time.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.file_distribution.subscriptions.title',
      titleDefault: 'Folder subscriptions',
      bodyKey: 'guide.file_distribution.subscriptions.body',
      bodyDefault:
        'Subscribe to a file kind in a project to be notified when files there are created, updated or deleted. It is a quick way to stay current on a drawing set or photo log without checking the folder yourself.',
    },
  ],
  ctaKey: 'guide.file_distribution.cta',
  ctaDefault: 'Search across your projects',
};

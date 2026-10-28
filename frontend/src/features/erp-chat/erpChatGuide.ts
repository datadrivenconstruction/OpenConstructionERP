// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// erpChatGuide - "How it works" content for the ERP AI Chat module.
// Consumed by <ModuleGuideButton content={erpChatGuide} /> on the /chat page.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const erpChatGuide: ModuleGuideContent = {
  titleKey: 'guide.erp_chat.title',
  titleDefault: 'AI Chat',
  introKey: 'guide.erp_chat.intro',
  introDefault:
    'AI Chat is your whole construction ERP in one conversation. Ask anything about your projects in plain language and the assistant queries your real ERP data and renders the answer as interactive tables, charts and matrices.',
  sections: [
    {
      icon: 'Send',
      titleKey: 'guide.erp_chat.ask.title',
      titleDefault: 'Ask in plain language',
      bodyKey: 'guide.erp_chat.ask.body',
      bodyDefault:
        'Type a question or request in the input box on the left, with no special syntax. Press Enter to send and Shift+Enter for a new line. If you are not sure where to start, click one of the suggestion chips or example prompts.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.erp_chat.tools.title',
      titleDefault: 'Watch the tools run live',
      bodyKey: 'guide.erp_chat.tools.body',
      bodyDefault:
        'The assistant picks the right specialized tools for your question and calls them against live ERP data. Each tool call appears in the conversation as it executes, with its timing and details, so you can see exactly how the answer was built.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.erp_chat.results.title',
      titleDefault: 'See results on the right',
      bodyKey: 'guide.erp_chat.results.body',
      bodyDefault:
        'Answers render in the data panel on the right as interactive content, not screenshots: project grids, BOQ tables, Gantt schedules, validation reports, 5x5 risk matrices and cost model metrics. Drag the divider to resize the two panels.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.erp_chat.scope.title',
      titleDefault: 'Scope to a project',
      bodyKey: 'guide.erp_chat.scope.body',
      bodyDefault:
        'Select a project at the top to focus the assistant on that project. With no project selected it works across your whole portfolio, so it can compare projects or surface at-risk work.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.erp_chat.data.title',
      titleDefault: 'Query your ERP and cost data',
      bodyKey: 'guide.erp_chat.data.body',
      bodyDefault:
        'The assistant reaches projects and portfolio, BOQ and estimation, schedule and critical path, validation and quality, risk and earned value, and the CWICR cost database. Ask it to find zero-price items, compute totals, run validation or search cost rates by region.',
    },
    {
      icon: 'BookOpen',
      titleKey: 'guide.erp_chat.history.title',
      titleDefault: 'Resume past conversations',
      bodyKey: 'guide.erp_chat.history.body',
      bodyDefault:
        'Every conversation is saved. Open Recent conversations at the top of the left panel to resume one, which rebuilds the messages and the data panel exactly as you left them, or delete it. Use New chat to start fresh.',
    },
  ],
  ctaKey: 'guide.erp_chat.cta',
  ctaDefault: 'Ask your first question',
};

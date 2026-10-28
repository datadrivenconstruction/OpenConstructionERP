// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// aiAgentsGuide - "How it works" content for the AI Agents module.
// Consumed by <ModuleGuideButton content={aiAgentsGuide} /> on AgentsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const aiAgentsGuide: ModuleGuideContent = {
  titleKey: 'guide.ai_agents.title',
  titleDefault: 'AI Agents',
  introKey: 'guide.ai_agents.intro',
  introDefault:
    'AI Agents are autonomous assistants that reason over your project data, call tools, and propose actions for you to review. Use them to draft a BOQ, check quality, summarise documents, or automate a recurring task, with nothing applied until you approve it.',
  sections: [
    {
      icon: 'Sparkles',
      titleKey: 'guide.ai_agents.gallery.title',
      titleDefault: 'Pick an agent',
      bodyKey: 'guide.ai_agents.gallery.body',
      bodyDefault:
        'The gallery lists every agent available to you, each with a name, a short tagline, and one-click example prompts. Agents arrive with the modules that ship them, so the catalogue grows as you enable more of the platform. Click a card to open its run console.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.ai_agents.run.title',
      titleDefault: 'Describe the task and run',
      bodyKey: 'guide.ai_agents.run.body',
      bodyDefault:
        'In the run console, write what you want the agent to do in plain language, or tap a suggested prompt to start. If a project is active, the run is linked to it so the agent works against the right data; otherwise it runs globally. Running needs an AI provider configured in Settings, AI.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.ai_agents.timeline.title',
      titleDefault: 'Watch it reason live',
      bodyKey: 'guide.ai_agents.timeline.body',
      bodyDefault:
        'The run timeline shows every step as it happens: each thought, each tool call with its arguments, the observation it gets back, and the final answer. Iteration and token counters let you see how much work the agent did, and clear messages explain any run that fails.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.ai_agents.apply.title',
      titleDefault: 'Review and apply proposals',
      bodyKey: 'guide.ai_agents.apply.body',
      bodyDefault:
        'When an agent proposes BOQ positions, they are listed for you to check, never written automatically. Pick a BOQ and click Apply to add them as real positions, or copy them as JSON. Lines that do not match the project currency are skipped so totals stay clean.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.ai_agents.builder.title',
      titleDefault: 'Build your own agent',
      bodyKey: 'guide.ai_agents.builder.body',
      bodyDefault:
        'Create your own agent without writing a system prompt. Answer a few guided questions, who it acts as, what it should help with, who the answer is for, and how to shape it, then give it a name, icon, category, and example prompts. An advanced option lets a power user paste a raw prompt instead.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.ai_agents.automation.title',
      titleDefault: 'Automate and monitor',
      bodyKey: 'guide.ai_agents.automation.body',
      bodyDefault:
        'Give a custom agent tools so it can read your data, add a schedule to run it on a cron, or subscribe it to platform events so it fires on a trigger. Automated runs land in their own panel next to your recent runs, so you can reattach to any run and review what it did.',
    },
  ],
  ctaKey: 'guide.ai_agents.cta',
  ctaDefault: 'Create your own agent',
};

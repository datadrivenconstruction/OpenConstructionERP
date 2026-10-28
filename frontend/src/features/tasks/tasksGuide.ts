// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// tasksGuide - "How it works" content for the Tasks module.
// Consumed by <ModuleGuideButton content={tasksGuide} /> on TasksPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const tasksGuide: ModuleGuideContent = {
  titleKey: 'guide.tasks.title',
  titleDefault: 'Tasks',
  introKey: 'guide.tasks.intro',
  introDefault:
    'Tasks is a Kanban board for the lightweight action items, decisions and follow-ups that keep a project moving, separate from the 4D Schedule that plans the build timeline. Capture them with an assignee, due date, priority and checklist, then move them across columns as the work progresses.',
  sections: [
    {
      icon: 'ListChecks',
      titleKey: 'guide.tasks.board.title',
      titleDefault: 'The board and its columns',
      bodyKey: 'guide.tasks.board.body',
      bodyDefault:
        'Every task lives in a status column on the board: Draft, Open, In Progress and Completed. Each column header shows a live count of the cards inside it, so you can read the state of the work at a glance.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.tasks.create.title',
      titleDefault: 'Creating a task',
      bodyKey: 'guide.tasks.create.body',
      bodyDefault:
        'Click New Task to open the form. Give it a title, then pick a type, set a priority from Low to Urgent, name an assignee and choose a due date. A task can also carry a checklist whose progress shows on the card as a small bar.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.tasks.types.title',
      titleDefault: 'Types and categories',
      bodyKey: 'guide.tasks.types.body',
      bodyDefault:
        'Tasks come in five built-in types: Task, Topic, Information, Decision and Personal, each with its own colour and icon. Need something else? Add a custom category with its own colour, and it becomes a filter tab and a type choice on the form.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.tasks.move.title',
      titleDefault: 'Moving work along',
      bodyKey: 'guide.tasks.move.body',
      bodyDefault:
        'Drag a card to another column to change its status, or use the dropdown on the card. Only legal transitions are offered so a move is never rejected. Mark a task Complete from its card, and add your own custom columns to model a workflow that fits your team.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.tasks.find.title',
      titleDefault: 'Finding what matters',
      bodyKey: 'guide.tasks.find.body',
      bodyDefault:
        'Use the type tabs to focus the board on one kind of task, and the search box to filter by title, description or assignee. Turn on My Tasks to pull together everything assigned to you across every project in one cross-project list.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.tasks.io.title',
      titleDefault: 'Import, export and links',
      bodyKey: 'guide.tasks.io.body',
      bodyDefault:
        'Import brings tasks in from an Excel or CSV file using the provided template, and Export sends the current board out to Excel. Tasks also connect to the rest of the platform: raise them from meetings, RFIs or inspections, and pin them to BIM elements so View in BIM jumps to the geometry.',
    },
  ],
  ctaKey: 'guide.tasks.cta',
  ctaDefault: 'Create your first task',
};

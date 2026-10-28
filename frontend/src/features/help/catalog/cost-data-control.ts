// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog — Cost data + Scheduling + Cost control & risk.
// See ../types.ts for the ModuleExplanation shape and the key convention.

import type { ModuleExplanation } from '../types';

export const costDataControlModules: ModuleExplanation[] = [
  /* ── Cost data ────────────────────────────────────────────────────────── */
  {
    id: 'costs',
    route: '/costs',
    icon: 'Database',
    category: 'cost_data',
    keywords: 'cost database resource rates import catalog prices',
    titleKey: 'howto.costs.title',
    titleDefault: 'Cost Database',
    summaryKey: 'howto.costs.summary',
    summaryDefault: 'Your priced library of materials, labour and equipment rates.',
    whatKey: 'howto.costs.what',
    whatDefault:
      'The Cost Database is your own library of priced resources - materials, labour and equipment with rates. It is what the BOQ pulls from, so the better it is kept, the faster and more consistent every estimate becomes.',
    how: [
      { key: 'howto.costs.how.1', default: 'Import an existing price list, or add resources by hand with their unit and rate.' },
      { key: 'howto.costs.how.2', default: 'Organise resources by category so they are easy to find when pricing.' },
      { key: 'howto.costs.how.3', default: 'Pull items straight into a BOQ with From Database so descriptions and rates are filled for you.' },
    ],
    tips: [
      { key: 'howto.costs.tip.1', default: 'Keep one trusted catalog up to date rather than re-typing rates per estimate - it pays back on every job.' },
    ],
  },
  {
    id: 'catalog',
    route: '/catalog',
    icon: 'Library',
    category: 'cost_data',
    titleKey: 'howto.catalog.title',
    titleDefault: 'Resource Catalog',
    summaryKey: 'howto.catalog.summary',
    summaryDefault: 'Browse and manage the resources behind your prices.',
    whatKey: 'howto.catalog.what',
    whatDefault:
      'The Resource Catalog is the browseable view of your priced resources and any regional cost data you have loaded. Search it, compare rates and keep the underlying items tidy.',
    how: [
      { key: 'howto.catalog.how.1', default: 'Search or filter to find a resource by name, category or unit.' },
      { key: 'howto.catalog.how.2', default: 'Review and edit rates so they reflect current prices.' },
      { key: 'howto.catalog.how.3', default: 'Download regional cost data on demand when you need it for a market.' },
    ],
  },
  {
    id: 'assemblies',
    route: '/assemblies',
    icon: 'Boxes',
    category: 'cost_data',
    keywords: 'assembly composite recipe build-up unit rate',
    titleKey: 'howto.assemblies.title',
    titleDefault: 'Assemblies',
    summaryKey: 'howto.assemblies.summary',
    summaryDefault: 'Composite items that roll several resources into one priced build-up.',
    whatKey: 'howto.assemblies.what',
    whatDefault:
      'An assembly is a recipe: several resources combined into one priced item - for example a square metre of wall as its blockwork, mortar, labour and finish. Price the build-up once and reuse it as a single line wherever that work appears.',
    how: [
      { key: 'howto.assemblies.how.1', default: 'Create an assembly and add the component resources with their quantities per unit.' },
      { key: 'howto.assemblies.how.2', default: 'The assembly rate is computed from its components, so it updates when their rates change.' },
      { key: 'howto.assemblies.how.3', default: 'Add the assembly to a BOQ with From Assembly to drop in the whole build-up as one position.' },
    ],
    tips: [
      { key: 'howto.assemblies.tip.1', default: 'Save common build-ups to the assembly library so the team prices them the same way every time.' },
    ],
  },
  {
    id: 'benchmarks',
    route: '/benchmarks',
    icon: 'BarChart3',
    category: 'cost_data',
    keywords: 'benchmark cost per m2 percentile din 276 comparison',
    titleKey: 'howto.benchmarks.title',
    titleDefault: 'Cost Benchmarks',
    summaryKey: 'howto.benchmarks.summary',
    summaryDefault: 'Sanity-check your cost per m2 against typical ranges for the building type.',
    whatKey: 'howto.benchmarks.what',
    whatDefault:
      'Cost Benchmarks compares your estimate to typical planning values for the building type and region. It places your cost per square metre on the industry range and breaks it down by element group, so you can see whether you are high, low or about right - and where the difference sits.',
    how: [
      { key: 'howto.benchmarks.how.1', default: 'Pick the building type and region, then enter your floor area and total cost.' },
      { key: 'howto.benchmarks.how.2', default: 'Read where your cost per m2 lands on the range and your percentile against the market.' },
      { key: 'howto.benchmarks.how.3', default: 'Use the element breakdown to see how the cost splits across structure and finishes versus the typical split.' },
    ],
    tips: [
      { key: 'howto.benchmarks.tip.1', default: 'Benchmarks are typical planning values, not a guarantee - a big gap is a prompt to check, not proof of an error.' },
    ],
    whenKey: 'howto.benchmarks.when',
    whenDefault: 'Use it early to test a rough budget and late to defend the final number.',
  },

  /* ── Scheduling ───────────────────────────────────────────────────────── */
  {
    id: 'schedule',
    route: '/schedule',
    icon: 'CalendarDays',
    category: 'scheduling',
    keywords: '4d gantt timeline critical path tasks',
    titleKey: 'howto.schedule.title',
    titleDefault: '4D Schedule',
    summaryKey: 'howto.schedule.summary',
    summaryDefault: 'Plan the work in time and link it to the model for a 4D view.',
    whatKey: 'howto.schedule.what',
    whatDefault:
      'The 4D Schedule plans the job in time - tasks, durations, dependencies and the critical path - and can link tasks to model elements so you can watch the building come together over the programme.',
    how: [
      { key: 'howto.schedule.how.1', default: 'Add tasks with durations and link them with dependencies to form the sequence.' },
      { key: 'howto.schedule.how.2', default: 'Read the critical path to see which tasks drive the finish date.' },
      { key: 'howto.schedule.how.3', default: 'Link tasks to model elements to play the build as a 4D sequence.' },
    ],
  },
  {
    id: 'takt',
    route: '/takt',
    icon: 'GanttChartSquare',
    category: 'scheduling',
    keywords: 'takt lean flow zones rhythm',
    titleKey: 'howto.takt.title',
    titleDefault: 'Takt Planning',
    summaryKey: 'howto.takt.summary',
    summaryDefault: 'Plan repetitive work as a steady rhythm of crews moving through zones.',
    whatKey: 'howto.takt.what',
    whatDefault:
      'Takt Planning organises repetitive work into a steady beat: crews move through zones at a fixed rhythm. It makes flow visible and is a powerful way to shorten and stabilise programmes on repetitive buildings.',
    how: [
      { key: 'howto.takt.how.1', default: 'Define the zones the work repeats across and the takt time (the beat).' },
      { key: 'howto.takt.how.2', default: 'Lay out the trade sequence so each crew hands off to the next on rhythm.' },
      { key: 'howto.takt.how.3', default: 'Read the takt board to spot where flow breaks and rebalance.' },
    ],
  },
  {
    id: 'tasks',
    route: '/tasks',
    icon: 'ClipboardList',
    category: 'scheduling',
    titleKey: 'howto.tasks.title',
    titleDefault: 'Tasks',
    summaryKey: 'howto.tasks.summary',
    summaryDefault: 'The lightweight to-do list for getting things done on the project.',
    whatKey: 'howto.tasks.what',
    whatDefault:
      'Tasks is the simple action list for the project - assign work, set due dates and track what is open. It is for day-to-day follow-ups that do not need a full schedule.',
    how: [
      { key: 'howto.tasks.how.1', default: 'Create a task, assign it and give it a due date.' },
      { key: 'howto.tasks.how.2', default: 'Track status as work moves from open to done.' },
      { key: 'howto.tasks.how.3', default: 'Filter by assignee or due date to see what is on your plate.' },
    ],
  },

  /* ── Cost control & risk ──────────────────────────────────────────────── */
  {
    id: '5d',
    route: '/5d',
    icon: 'TrendingUp',
    category: 'cost_control',
    keywords: '5d cost model earned value budget actuals forecast',
    titleKey: 'howto.5d.title',
    titleDefault: '5D Cost Model',
    summaryKey: 'howto.5d.summary',
    summaryDefault: 'Track budget against actuals over time with earned-value insight.',
    whatKey: 'howto.5d.what',
    whatDefault:
      'The 5D Cost Model joins cost to time: it tracks budget, committed and actual spend across the programme and shows earned value, so you can see not just how much you have spent but whether you are getting the work you paid for.',
    how: [
      { key: 'howto.5d.how.1', default: 'Start from the BOQ budget and tie cost to schedule activities.' },
      { key: 'howto.5d.how.2', default: 'Record actuals and commitments as the job progresses.' },
      { key: 'howto.5d.how.3', default: 'Read earned-value indicators to see whether you are ahead or behind on cost and progress.' },
    ],
  },
  {
    id: 'progress',
    route: '/progress',
    icon: 'Activity',
    category: 'cost_control',
    keywords: 'progress physical percent complete s-curve period earned quantity variance field',
    titleKey: 'howto.progress.title',
    titleDefault: 'Progress',
    summaryKey: 'howto.progress.summary',
    summaryDefault: 'Track how much is actually built, not how much has been spent.',
    whatKey: 'howto.progress.what',
    whatDefault:
      'Progress is the physical view of delivery. Somebody records a percent-complete observation against a BOQ position or against the project as a whole, and the page turns those observations into an actual versus planned S-curve, what each period added, and a comparison of design quantity against earned quantity for every position. The project percentage is rolled up from the position readings weighted by design quantity, which means a position nobody has measured counts as zero and still occupies its share, so the headline cannot be flattered by one finished line.',
    how: [
      { key: 'howto.progress.how.1', default: 'Press Record progress and enter a percent, a period label and either one position or the whole project.' },
      { key: 'howto.progress.how.2', default: 'Read the S-curve to see cumulative actual against plan; the planned line only appears for periods that have a plan figure.' },
      { key: 'howto.progress.how.3', default: 'Use By period to see what each period added and where the running total stood at its end.' },
      { key: 'howto.progress.how.4', default: 'Check quantity variance to find positions running over or under their design quantity rather than merely late.' },
    ],
    tips: [
      { key: 'howto.progress.tip.1', default: 'Write the period label the same way every time, because everything on the page is grouped by it.' },
      { key: 'howto.progress.tip.2', default: 'Entries are append-only. Correct a reading by recording the corrected value again in the same period rather than editing the old one.' },
      { key: 'howto.progress.tip.3', default: 'A project-level reading is the fallback used only while no individual position has been measured; once positions are measured it keeps its row but does not move the headline.' },
    ],
    whenKey: 'howto.progress.when',
    whenDefault:
      'Use it when you need to answer how much is built rather than how much is spent, and when a client asks why the money is ahead of the work.',
  },
  {
    id: 'risks',
    route: '/risks',
    icon: 'Dices',
    category: 'cost_control',
    keywords: 'risk register monte carlo contingency sensitivity probability',
    titleKey: 'howto.risks.title',
    titleDefault: 'Risk Register',
    summaryKey: 'howto.risks.summary',
    summaryDefault: 'Log risks and run Monte Carlo to size a defensible contingency.',
    whatKey: 'howto.risks.what',
    whatDefault:
      'The Risk Register captures what could go wrong and how much it could cost, then runs Monte Carlo simulation over the estimate to turn that uncertainty into numbers: a probable cost range and the contingency you need to hit a chosen confidence level.',
    how: [
      { key: 'howto.risks.how.1', default: 'Log each risk with its likelihood and cost impact.' },
      { key: 'howto.risks.how.2', default: 'Open the Monte Carlo tab to simulate thousands of outcomes over the estimate.' },
      { key: 'howto.risks.how.3', default: 'Read the cost range and S-curve, then set contingency at the confidence level you need.' },
      { key: 'howto.risks.how.4', default: 'Use the sensitivity view to see which items drive the most uncertainty.' },
    ],
    tips: [
      { key: 'howto.risks.tip.1', default: 'A wider range is not worse - it is a more honest picture of an uncertain estimate.' },
    ],
    whenKey: 'howto.risks.when',
    whenDefault: 'Use it before committing a number, to price contingency on evidence instead of a flat percentage.',
  },
  {
    id: 'capacity',
    route: '/portfolio/capacity',
    icon: 'Gauge',
    category: 'cost_control',
    titleKey: 'howto.capacity.title',
    titleDefault: 'Capacity Planning',
    summaryKey: 'howto.capacity.summary',
    summaryDefault: 'See whether you have the people and plant to deliver across projects.',
    whatKey: 'howto.capacity.what',
    whatDefault:
      'Capacity Planning looks across projects to compare the resources the work demands against what you have. It flags where you are over-committed before it becomes a delivery problem.',
    how: [
      { key: 'howto.capacity.how.1', default: 'Review demand for resources across the portfolio over time.' },
      { key: 'howto.capacity.how.2', default: 'Spot periods where demand exceeds available capacity.' },
      { key: 'howto.capacity.how.3', default: 'Adjust plans or move work to smooth the peaks.' },
    ],
  },
  {
    id: 'leveling',
    route: '/portfolio/leveling',
    icon: 'Network',
    category: 'cost_control',
    titleKey: 'howto.leveling.title',
    titleDefault: 'Resource Leveling',
    summaryKey: 'howto.leveling.summary',
    summaryDefault: 'Smooth resource peaks so crews are used evenly, not in bursts.',
    whatKey: 'howto.leveling.what',
    whatDefault:
      'Resource Leveling reshuffles work within its float so the same crews and plant are used at a steady rate instead of spiking and idling. It turns a jagged resource profile into a workable one.',
    how: [
      { key: 'howto.leveling.how.1', default: 'Start from a schedule with resources assigned to tasks.' },
      { key: 'howto.leveling.how.2', default: 'Review the resource profile to see the peaks and troughs.' },
      { key: 'howto.leveling.how.3', default: 'Level within available float to flatten the profile without pushing the finish date.' },
    ],
  },
];

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ModuleGuideContent } from '@/shared/ui';

/**
 * "How it works" guide for Model Review.
 *
 * The page is a meeting surface, not a register, and the guide says so in the
 * first line: this is where a coordination review is held against the model,
 * and it ends in a hand-over. Every key carries its inline English default and
 * is consumed via `t(key, { defaultValue })`, so none of these keys live in a
 * locale file. Spotlight selectors point at live controls on ModelReviewPage.
 */
export const modelReviewGuide: ModuleGuideContent = {
  titleKey: 'guide.model_review.title',
  titleDefault: 'Model Review',
  introKey: 'guide.model_review.intro',
  introDefault:
    'Model Review is where a coordination meeting happens against the model itself: open the model, walk the open issues one by one with the camera following each, settle them in place, and leave with a record the other side can open in their own tool.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.model_review.what.title',
      titleDefault: 'What a model review is',
      bodyKey: 'guide.model_review.what.body',
      bodyDefault:
        'A review is the meeting and the record around a model. Issues are BCF topics: a title, a status, an owner, a due date, and a saved viewpoint that pins the camera and the elements the issue is about. The Issues page is the project-wide register of those topics; this page is where you work through them with the model in front of you.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.model_review.model.title',
      titleDefault: 'Pick the model under review',
      bodyKey: 'guide.model_review.model.body',
      bodyDefault:
        'Choose a model in the header. Models are converted in the BIM Hub, so if the list is empty, load one there first. The header then shows how many issues are open, how many are late, and how many belong to this model.',
      spotlightSelector: '[data-testid="review-model-select"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.model_review.checks.title',
      titleDefault: 'Run the automated checks first',
      bodyKey: 'guide.model_review.checks.body',
      bodyDefault:
        'Checks on the left run the rule engine over every element and score the model. Each finding can be shown in the 3D view and turned into a tracked issue with one click, so the meeting starts from evidence rather than opinion.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.model_review.filter.title',
      titleDefault: 'Narrow to what this meeting is about',
      bodyKey: 'guide.model_review.filter.body',
      bodyDefault:
        'Use the chips in the Issues dock to keep only what is open, late, unassigned, or raised against the model on screen, then search or filter by discipline, status, priority and assignee. The discipline list is built from the labels this project has actually used, so it also carries whatever else the team labels issues with, including the type and severity the clash check writes. Whatever you leave visible is what the guided walk and the hand-over will cover.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.model_review.walk.title',
      titleDefault: 'Walk the issues, settle them in place',
      bodyKey: 'guide.model_review.walk.body',
      bodyDefault:
        'Start review takes the visible issues one at a time and flies the camera to each saved viewpoint - the arrow keys page through them. Change the status, set an owner and a due date, and drop a note without leaving the model. Clicking any issue in the list does the same thing at your own pace.',
      spotlightSelector: '[data-testid="review-start-session"]',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.model_review.raise.title',
      titleDefault: 'Raise an issue from what you see',
      bodyKey: 'guide.model_review.raise.body',
      bodyDefault:
        'Select an element, then Raise issue here. The new issue records the camera, the selection and a snapshot of exactly what is on screen, so whoever picks it up lands on the same view you were looking at.',
      spotlightSelector: '[data-testid="review-raise-issue"]',
    },
    {
      icon: 'Database',
      titleKey: 'guide.model_review.handover.title',
      titleDefault: 'Leave with a record',
      bodyKey: 'guide.model_review.handover.body',
      bodyDefault:
        'Finish review closes the meeting with a summary of what was agreed: printable minutes for the file, and a .bcfzip of exactly the issues you walked. BCF is an open exchange format, so the other side opens it in whichever tool they use.',
    },
  ],
  ctaKey: 'guide.model_review.cta',
  ctaDefault: 'Start the review',
};

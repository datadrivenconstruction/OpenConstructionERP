// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// pointcloudGuide - "How it works" content for the Point Cloud / Reality
// Capture module. Consumed by <ModuleGuideButton content={pointcloudGuide} />
// on PointCloudPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const pointcloudGuide: ModuleGuideContent = {
  titleKey: 'guide.pointcloud.title',
  titleDefault: 'Point Cloud',
  introKey: 'guide.pointcloud.intro',
  introDefault:
    'Point Cloud is the reality-capture hub for your project. Import laser scans, photogrammetry and LiDAR clouds, view them, and use them to check what was actually built against the model you are pricing.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.pointcloud.what.title',
      titleDefault: 'What reality capture is',
      bodyKey: 'guide.pointcloud.what.body',
      bodyDefault:
        'A point cloud is a dense, georeferenced record of real site conditions, captured by a laser scanner, a drone survey or a LiDAR sensor. Registered against a project, it becomes your as-built reference for verifying quantities and documenting what was there on a given date.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.pointcloud.upload.title',
      titleDefault: 'Upload a scan',
      bodyKey: 'guide.pointcloud.upload.body',
      bodyDefault:
        'Pick the project, then drag a cloud onto the upload window or browse for one. Supported containers are LAS, LAZ, COPC and E57. Files upload straight to object storage, so even large scans register without a separate transfer step.',
      spotlightSelector: '[data-testid="pointcloud-upload-submit"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.pointcloud.metadata.title',
      titleDefault: 'Name, source and accuracy tier',
      bodyKey: 'guide.pointcloud.metadata.body',
      bodyDefault:
        'Give the scan a clear name, set its source as laser scan, photogrammetry, LiDAR or other, and pick the accuracy tier: survey grade, standard or coarse. The tier travels with the scan and gates what it is allowed to drive downstream, such as feeding earthwork volumes into the estimate.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.pointcloud.registry.title',
      titleDefault: 'Scan registry and viewer',
      bodyKey: 'guide.pointcloud.registry.body',
      bodyDefault:
        'Every uploaded scan lands in the registry with its format, accuracy tier, point count and a live status from uploaded through to ready. Once a scan is ready, click View to open it in the in-page cloud viewer and inspect the capture.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.pointcloud.value.title',
      titleDefault: 'What a scan unlocks',
      bodyKey: 'guide.pointcloud.value.body',
      bodyDefault:
        'Reality capture lets you verify built quantities against the model before you price them, push survey-grade cut and fill volumes into the BOQ with the accuracy tier attached, and keep a dated, georeferenced record of site conditions with the project.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.pointcloud.workflow.title',
      titleDefault: 'How it fits the workflow',
      bodyKey: 'guide.pointcloud.workflow.body',
      bodyDefault:
        'Scans sit alongside the BIM viewer and the BOQ. Use the links in the intro to jump to either while you work. Model registration and deviation analysis arrive in the next releases, so this module is marked beta today.',
    },
  ],
  ctaKey: 'guide.pointcloud.cta',
  ctaDefault: 'Upload your first scan',
};

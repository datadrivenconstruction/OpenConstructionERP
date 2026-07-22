// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Measure from a point cloud survey".
//
// Load a laser-scan point cloud of the existing conditions, measure the
// distances, areas and volumes you need, carry them into the takeoff and price
// the work. Content strings are key plus inline English default, only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "measure-from-a-point-cloud-survey",
  order: 1015,
  category: "bim",
  companyTypes: ["cost-consultant", "general-contractor", "bim-consultant"],
  icon: "Ruler",
  titleKey: "cases.measure_from_a_point_cloud_survey.title",
  titleDefault: "Measure from a point cloud survey",
  descKey: "cases.measure_from_a_point_cloud_survey.desc",
  descDefault:
    "Load a laser-scan point cloud of the existing conditions, measure the distances, areas and volumes you need straight off the survey, carry them into the takeoff and price the work.",
  longDescKey: "cases.measure_from_a_point_cloud_survey.longdesc",
  longDescDefault:
    "On refurbishment and existing-building work there are no reliable drawings, only what is actually there. A point cloud is the measured truth of the site, and measuring quantities directly from it beats scaling a drawing that may be forty years out of date.",
  estMinutes: 11,
  steps: [
    {
      id: "load",
      icon: "Box",
      inputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.load.in.scan", label: "Laser-scan survey" },
      ],
      outputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.load.out.cloud", label: "Loaded point cloud" },
      ],
      titleKey: "cases.measure_from_a_point_cloud_survey.step.load.title",
      titleDefault: "Load the survey",
      whatKey: "cases.measure_from_a_point_cloud_survey.step.load.what",
      whatDefault:
        "Load the point cloud of the existing conditions and orient yourself in it, checking the scan covers the areas you need to measure without big shadows or gaps.",
      whyKey: "cases.measure_from_a_point_cloud_survey.step.load.why",
      whyDefault:
        "A scan with a hole where you need a dimension is worse than no scan, because you only find out at measuring time. Checking coverage first saves a wasted return to site.",
      moduleLabel: "Point Cloud",
      moduleLabelKey: "nav.point_cloud",
      to: "/pointcloud",
    },
    {
      id: "measure",
      icon: "Ruler",
      inputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.measure.in.cloud", label: "Point cloud" },
      ],
      outputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.measure.out.dims", label: "Measured dimensions" },
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.measure.out.volumes", label: "Areas and volumes" },
      ],
      titleKey: "cases.measure_from_a_point_cloud_survey.step.measure.title",
      titleDefault: "Measure what you need",
      whatKey: "cases.measure_from_a_point_cloud_survey.step.measure.what",
      whatDefault:
        "Measure the distances, wall and floor areas, room heights and volumes you need directly on the cloud, reading them off the real geometry rather than a drawing.",
      whyKey: "cases.measure_from_a_point_cloud_survey.step.measure.why",
      whyDefault:
        "Existing buildings are never square or plumb the way a drawing pretends. Measuring the as-built reality is what keeps a refurbishment quantity honest and the price behind it safe.",
      moduleLabel: "Point Cloud",
      moduleLabelKey: "nav.point_cloud",
      to: "/pointcloud",
    },
    {
      id: "quantities",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.quantities.in.dims", label: "Measured dimensions" },
      ],
      outputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.quantities.out.takeoff", label: "Takeoff quantities" },
      ],
      titleKey: "cases.measure_from_a_point_cloud_survey.step.quantities.title",
      titleDefault: "Carry them into the takeoff",
      whatKey: "cases.measure_from_a_point_cloud_survey.step.quantities.what",
      whatDefault:
        "Bring the measured dimensions into the quantity takeoff as the source quantities for the work, keeping the link back to where each one was measured.",
      whyKey: "cases.measure_from_a_point_cloud_survey.step.quantities.why",
      whyDefault:
        "A quantity that traces back to a point on the survey is defensible. When someone questions a figure, you can open the cloud and show the measurement it came from.",
      moduleLabel: "Quantities",
      moduleLabelKey: "quantities.title",
      to: "/quantities",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.price.in.takeoff", label: "Takeoff quantities" },
      ],
      outputs: [
        { labelKey: "cases.measure_from_a_point_cloud_survey.step.price.out.priced", label: "Priced work" },
      ],
      titleKey: "cases.measure_from_a_point_cloud_survey.step.price.title",
      titleDefault: "Price the work",
      whatKey: "cases.measure_from_a_point_cloud_survey.step.price.what",
      whatDefault:
        "Price the measured work in the bill, so the survey-based quantities flow straight into a cost without a rekey in between.",
      whyKey: "cases.measure_from_a_point_cloud_survey.step.price.why",
      whyDefault:
        "Carrying scan measurements through to the bill keeps one unbroken chain from the real building to the price. Every manual copy in that chain is a chance to introduce an error.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
  ],
};

export default playbook;

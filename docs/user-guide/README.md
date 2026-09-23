# User guide

This guide covers the main workflows in OpenConstructionERP, one short page each. The pages are written for the person doing the work, an estimator pricing a job, a site engineer recording what happened, a project controls lead watching cost and time. Each page tells you what the feature is for, when to use it, the steps to do it, and how it connects to the rest of the platform.

You do not have to read them in order. The order below follows one common path: start from a drawing or a model, measure it, price it, check it, and then carry the job on through options, tender, programme and site.

## The workflows

1. [Quantity takeoff from drawings and models](./quantity-takeoff.md)
   Start here. Measure from PDF drawings, 2D DWGs and 3D BIM models, then send the measured quantities straight into BOQ positions.

2. [Estimating and the bill of quantities](./estimating-and-boq.md)
   Turn those quantities into a priced BOQ, with sections and positions, rates and assemblies, markups, allowances and preliminaries, exported tender-ready.

3. [BIM to cost and carbon (5D and 6D)](./bim-to-cost-and-carbon.md)
   Turn a model into structured, priced quantities without native IFC parsing, track cost over time as 5D, and account for embodied and operational carbon as 6D.

4. [Importing 3D models and mesh formats](./3d-model-formats.md)
   Bring in OBJ, STL, DAE, FBX, 3DS and other mesh files through the in-browser importer, confirm scale and orientation against a live preview, and measure areas and volumes from geometry that carries no BIM data.

5. [World cost bases and multi-base comparison](./world-cost-bases.md)
   Price the same scope against national cost databases, keep each currency honest, and see how a rate moves from one region to another.

6. [The validation pipeline](./validation.md)
   Run the traffic-light checks across imports and the estimate so problems surface early, with a quality score and a jump straight to the position that needs fixing.

7. [Design options comparison](./design-options.md)
   Load two or more design variants, give each its own priced BOQ, and compare them on total cost, by-trade differences and cost per square metre before you commit.

8. [Tendering and bid comparison](./tendering-and-bids.md)
   Package priced scope, invite subcontractors, collect their bids, and compare them side by side to support an award.

9. [Planning and cost control](./planning-and-cost-control.md)
   Schedule the work in 4D, track cost in 5D, and run earned value, forecasts, cash flow and change control as the job proceeds.

10. [Field and site operations](./field-and-site.md)
   Keep the daily diary, run inspections and safety, book deliveries, and build the contemporaneous record that protects the project.

11. [The AI assistant](./ai-assistant.md)
   Tell the assistant what needs doing and it prepares the change, a BOQ position, a task, an RFI, a risk, a punch item or schedule progress, for you to check and apply, with every change logged.

## A note on AI features

Several workflows offer AI help: drafting an estimate from a description or a photo, suggesting a cost match, ranking clashes, answering questions about your project data, preparing changes you describe to the [AI assistant](./ai-assistant.md). In every case the platform shows a confidence score and asks a person to confirm before anything lands in your estimate. Treat AI output as a fast first draft that a qualified estimator checks, not as a final answer. You connect your own model provider with an API key, and the AI features degrade gracefully when no key is set, so the rest of the platform works without them.

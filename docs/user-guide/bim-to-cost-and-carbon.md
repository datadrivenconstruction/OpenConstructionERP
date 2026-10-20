# BIM to cost and carbon (5D and 6D)

A BIM model already holds most of the quantities a project needs. This workflow turns that model into structured, priced quantities, tracks the cost over time, and accounts for the carbon the design carries. In the shorthand of the industry, adding cost to the 3D model is 5D and adding carbon and whole-life performance is 6D.

## What it is for

The point is to price and assess a design from the model itself, not from a re-measured copy of it. You bring in a model, the platform reads its elements and geometry into one canonical format, you match those elements to cost items, and you get a priced bill of quantities that stays linked to the model. From the same linked data you can then project cost across the programme and calculate the carbon footprint element by element.

## How models come in

All CAD and BIM formats, including RVT, IFC and DWG, are converted with DDC Converters 2.0 into a single structured format. The result is a federated model you can open in the browser, with a category and storey breakdown, and elements that carry quantities, properties and classification.

## The steps

1. Upload the model to the project and let the converter produce the canonical elements. Open the 3D viewer to check the model loaded and to browse it by category and level.
2. Match elements to cost. The element matching pipeline maps a model element to a cost position using a mix of vector, lexical and rule-based matching, and loads the scaled resources into the BOQ. You confirm each match, guided by a confidence score.
3. Take the quantities. Use the quantity picker to pull area, volume or length from linked elements into BOQ positions, and link groups of elements to single lines where they represent the same work. This is your 5D link: model to quantity to rate.
4. Track cost over time. The 5D cost model spreads the priced BOQ across the schedule to produce S-curves, cash-flow projections, budgets and earned value, so cost is a function of time and progress, not a single total.
5. Account for carbon. The carbon and sustainability workflow computes embodied and operational carbon across scopes 1, 2 and 3, matches materials to environmental product data, sets targets, and produces sustainability reporting aligned to recognised protocols. This is the 6D layer, and it reads the same model-linked quantities as the cost side.

## Coordination and requirements

Multi-discipline models need coordination. The clash and coordination tools find geometric clashes across the federation, cluster thousands of raw results into prioritised issues by zone and discipline, estimate the rework cost of an issue from your cost database, and round-trip issues through the open BCF standard so any compatible tool can read them. On the information side, BIM requirements support IDS and COBie import and export for owner data drops, so the model is checked against what was actually asked for.

## How it connects

This workflow sits between [takeoff](./quantity-takeoff.md), which also feeds it quantities, and the [bill of quantities](./estimating-and-boq.md), which holds the priced result. The 5D cost model shares its engine with [planning and cost control](./planning-and-cost-control.md), and the carbon account draws on the same linked quantities. The [validation pipeline](./validation.md) checks converted models for structure, completeness and required properties before they are priced.

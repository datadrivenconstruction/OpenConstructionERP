// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Who draws the Data paths button inside a PageHeader. The header sees its own
// actions: when a ModuleGuideButton is among them, the guide button draws it
// in the learning group ('guide'); otherwise the header appends it itself
// ('header') and a guide button nested deeper stays quiet. Outside a header
// (null) the guide button draws it. Exactly one button per header either way.

import { createContext } from 'react';

export type DataPathsSlot = 'guide' | 'header' | null;

export const DataPathsSlotContext = createContext<DataPathsSlot>(null);

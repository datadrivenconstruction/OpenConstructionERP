// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DashboardRollupContext — provides the result of `useDashboardRollup`
 * to every wave-2 widget so they don't each fetch independently.
 *
 * Mount once at the top of `DashboardPage`; child widgets call
 * `useDashboardRollupContext()` to read their slice. The context
 * intentionally exposes the same shape `useDashboardRollup` returns
 * (`{ data, isLoading, error, byWidget }`) so widget code is easy to
 * follow.
 *
 * Outside the provider, the hook returns a "null payload" stub so the
 * widget components remain safe to render in storybook / unit tests
 * without wiring up the provider — `byWidget(id)` returns `null` and
 * `isLoading=false`, matching the empty-state branch in each widget.
 */
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import {
  useDashboardRollup,
  type DashboardRollupPayload,
  type DashboardWidgetId,
  type UseDashboardRollupOptions,
  type WidgetPayloadMap,
} from '../hooks/useDashboardRollup';

interface RollupContextValue {
  data: DashboardRollupPayload | undefined;
  isLoading: boolean;
  error: unknown;
  byWidget: <K extends DashboardWidgetId>(id: K) => WidgetPayloadMap[K] | null;
}

const NULL_VALUE: RollupContextValue = {
  data: undefined,
  isLoading: false,
  error: null,
  byWidget: () => null,
};

const DashboardRollupContext = createContext<RollupContextValue>(NULL_VALUE);

export function DashboardRollupProvider({
  children,
  ...options
}: { children: ReactNode } & UseDashboardRollupOptions) {
  const query = useDashboardRollup(options);
  const value = useMemo<RollupContextValue>(
    () => ({
      data: query.data,
      isLoading: query.isLoading,
      error: query.error,
      byWidget: query.byWidget,
    }),
    [query.data, query.isLoading, query.error, query.byWidget],
  );
  return (
    <DashboardRollupContext.Provider value={value}>
      {children}
    </DashboardRollupContext.Provider>
  );
}

export function useDashboardRollupContext(): RollupContextValue {
  return useContext(DashboardRollupContext);
}

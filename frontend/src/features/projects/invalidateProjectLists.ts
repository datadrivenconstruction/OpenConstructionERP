import type { QueryClient } from '@tanstack/react-query';

// Every cached list a project appears in. The dashboard's portfolio overview
// and project cards, the analytics page and the portfolio tree each cache
// under their own key, so refreshing only ['projects'] after a delete left the
// deleted project on those screens until the page was reloaded.
export const PROJECT_LIST_QUERY_KEYS = [
  ['projects'],
  ['portfolio-analytics'],
  ['dashboard-project-cards'],
  ['analytics'],
  ['portfolio'],
] as const;

export function invalidateProjectLists(queryClient: QueryClient) {
  for (const queryKey of PROJECT_LIST_QUERY_KEYS) {
    queryClient.invalidateQueries({ queryKey: [...queryKey] });
  }
}

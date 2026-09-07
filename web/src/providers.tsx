import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement, ReactNode } from 'react'

/**
 * Build the query cache.
 *
 * A function rather than a module-level instance so every test gets an empty
 * one. A shared client would carry one test's session into the next, and the
 * failure looks like flakiness rather than like leaked state.
 *
 * Retries are off. The one request worth retrying -- a stale access cookie --
 * is already retried inside the fetch layer, once, after renewing the
 * session. Retrying on top of that turns one 401 into four requests and
 * delays every genuine error by several seconds before it reaches the screen.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

export function Providers({
  client,
  children,
}: {
  client: QueryClient
  children: ReactNode
}): ReactElement {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { detailOf } from './errors'
import type { components } from './schema'

export type Dashboard = components['schemas']['Dashboard']
/** One thing to do next; narrow it by `kind`. */
export type Step = Dashboard['steps'][number]

/**
 * The steps are chosen from resumes, postings, matches and interviews, so
 * every mutation of those marks this key stale. Imported by those modules,
 * never the other way round.
 */
export const dashboardKey = ['dashboard'] as const

/**
 * What to do next, most important first, and never empty.
 *
 * The API chooses the steps, not this page: "a posting you have not matched"
 * and "your best match without an interview" are questions about every row,
 * and the lists the client can read are paged.
 */
export function useDashboard(): UseQueryResult<Step[]> {
  return useQuery({
    queryKey: dashboardKey,
    queryFn: async () => {
      const { data, error } = await api.GET('/dashboard')

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read what to do next')
      }

      return data.steps
    },
  })
}

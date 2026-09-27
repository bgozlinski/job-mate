import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import type { Page } from './documents'
import { detailOf } from './errors'
import type { components } from './schema'

export const HISTORY_PAGE_SIZE = 20

export type HistoryItem = components['schemas']['HistoryItem']
export type HistoryKind = 'all' | 'matches' | 'interviews'

export const historyKey = ['history'] as const

/** One numbered page of your matches and interviews, newest first. */
export function useHistory(
  kind: HistoryKind,
  page: number,
  size: number = HISTORY_PAGE_SIZE,
): UseQueryResult<Page<HistoryItem>> {
  return useQuery({
    queryKey: [...historyKey, kind, page, size],
    queryFn: async () => {
      const { data, error } = await api.GET('/history', {
        params: { query: { kind, limit: size, offset: (page - 1) * size } },
      })

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read your history')
      }

      return data
    },
  })
}

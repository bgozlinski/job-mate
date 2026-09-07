import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { detailOf } from './errors'
import type { components } from './schema'

export type Match = components['schemas']['MatchRead']
export type MatchSummary = components['schemas']['MatchSummary']

export const matchesKey = ['matches'] as const

export const HISTORY_PAGE_SIZE = 20
export const MAX_HISTORY_PAGE_SIZE = 100

export interface Pairing {
  resumeId: string
  documentId: string
}

/**
 * Measure one resume against one posting (FR-3).
 *
 * The number comes back from the API and is never computed here. It is a
 * coverage ratio over what the posting asks for, worked out in Python so it
 * can be reproduced and explained; a score this page invented would be
 * neither.
 */
export function useMatch(): UseMutationResult<Match, Error, Pairing> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ resumeId, documentId }: Pairing) => {
      const { data, error, response } = await api.POST('/resumes/{resume_id}/match', {
        params: { path: { resume_id: resumeId } },
        body: { document_id: documentId },
      })

      if (!data) {
        throw new Error(reasonFor(error, response))
      }

      return data
    },
    onSuccess: async () => {
      // Every match is stored, so the history on the other screen is now one
      // row out of date (FR-2).
      await queryClient.invalidateQueries({ queryKey: matchesKey })
    },
  })
}

/**
 * Say why a match did not happen, in terms the person can act on.
 *
 * The rate limit is the one failure worth adding to: the API says "Too many
 * requests" and puts the wait in a header, and a message without it leaves
 * the user pressing the button to find out.
 */
function reasonFor(error: unknown, response: Response): string {
  const detail = detailOf(error) ?? `Could not match (${String(response.status)})`

  if (response.status !== 429) {
    return detail
  }

  const retryAfter = Number(response.headers.get('retry-after'))

  if (!Number.isFinite(retryAfter) || retryAfter <= 0) {
    return detail
  }

  return `${detail}. Try again in ${String(Math.ceil(retryAfter / 60))} minutes.`
}

/** The caller's own past matches, newest first (FR-2). */
export function useMatches(shown: number): UseQueryResult<MatchSummary[]> {
  return useQuery({
    queryKey: [...matchesKey, shown],
    queryFn: async () => {
      const { data, error } = await api.GET('/matches', {
        // From the top with a growing limit, for the reason the knowledge
        // base is read that way: a new match is inserted above the page, so
        // offset paging would show the row it displaced twice.
        params: { query: { limit: shown, offset: 0 } },
      })

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read your match history')
      }

      return data
    },
  })
}

/** One stored match in full, including what the model was shown. */
export function useMatchDetail(id: string): UseQueryResult<Match> {
  return useQuery({
    queryKey: [...matchesKey, 'detail', id],
    queryFn: async () => {
      const { data, error, response } = await api.GET('/matches/{match_id}', {
        params: { path: { match_id: id } },
      })

      if (!data) {
        throw new Error(
          detailOf(error) ?? `Could not read this match (${String(response.status)})`,
        )
      }

      return data
    },
  })
}

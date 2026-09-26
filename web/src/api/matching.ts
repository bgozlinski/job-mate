import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { dashboardKey } from './dashboard'
import { documentsKey } from './documents'
import { detailOf, reasonFor } from './errors'
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
        throw new Error(reasonFor(error, response, 'Could not match'))
      }

      return data
    },
    onSuccess: async () => {
      // Every match is stored, so the history on the other screen is now one
      // row out of date (FR-2), and the dashboard's steps with it -- and the
      // postings, which carry your stage and best score at each.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: matchesKey }),
        queryClient.invalidateQueries({ queryKey: dashboardKey }),
        queryClient.invalidateQueries({ queryKey: documentsKey }),
      ])
    },
  })
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

/** How many of a posting's own results its page lists before "see all". */
export const PER_POSTING = 5

/**
 * The caller's latest matches against one posting, for that posting's page.
 *
 * Under matchesKey, so a new match -- which invalidates the whole prefix --
 * shows up here too.
 */
export function usePostingMatches(documentId: string): UseQueryResult<MatchSummary[]> {
  return useQuery({
    queryKey: [...matchesKey, 'posting', documentId],
    queryFn: async () => {
      const { data, error } = await api.GET('/matches', {
        params: { query: { limit: PER_POSTING, offset: 0, document_id: documentId } },
      })

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read your matches')
      }

      return data
    },
  })
}

/**
 * One stored match in full, including what the model was shown.
 *
 * `enabled` is for a page that only sometimes has a match to read: a query
 * for an empty id would ask the API for /matches/.
 */
export function useMatchDetail(id: string, enabled = true): UseQueryResult<Match> {
  return useQuery({
    queryKey: [...matchesKey, 'detail', id],
    enabled,
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

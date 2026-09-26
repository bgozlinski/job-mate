import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type {
  QueryClient,
  UseMutationResult,
  UseQueryResult,
} from '@tanstack/react-query'

import { api } from './client'
import { dashboardKey } from './dashboard'
import { detailOf, reasonFor } from './errors'
import type { Pairing } from './matching'
import type { components } from './schema'

export type Interview = components['schemas']['SessionRead']
export type InterviewSummary = components['schemas']['SessionSummary']
export type InterviewMessage = components['schemas']['MessageRead']

export const interviewsKey = ['interviews'] as const

const listsKey = [...interviewsKey, 'list'] as const

function interviewKey(id: string): readonly string[] {
  return [...interviewsKey, 'detail', id]
}

/**
 * Store what the API sent back for one interview, and mark every list stale.
 *
 * A list row carries the status and the score, so starting, answering the
 * last question and finishing all change it; so does the dashboard, which
 * counts the answers. The interview itself is not read again: the response
 * already is its new state.
 */
async function remember(queryClient: QueryClient, interview: Interview): Promise<void> {
  queryClient.setQueryData(interviewKey(interview.id), interview)
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: listsKey }),
    queryClient.invalidateQueries({ queryKey: dashboardKey }),
  ])
}

/**
 * The question waiting for an answer, if there is one.
 *
 * An answer names the question it answers. The API refuses one for any other
 * question with 409 -- that is what stops a double click from being taken as
 * the answer to the next question too.
 */
export function openQuestion(interview: Interview): InterviewMessage | null {
  const last = interview.messages.at(-1)

  return interview.status === 'active' && last?.role === 'interviewer' ? last : null
}

/** Plan an interview on a posting and get its first question (FR-4). */
export function useStartInterview(): UseMutationResult<Interview, Error, Pairing> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ resumeId, documentId }: Pairing) => {
      const { data, error, response } = await api.POST('/sessions', {
        body: { resume_id: resumeId, document_id: documentId },
      })

      if (!data) {
        throw new Error(reasonFor(error, response, 'Could not start the interview'))
      }

      return data
    },
    onSuccess: async (interview) => {
      await remember(queryClient, interview)
    },
  })
}

export const INTERVIEWS_PAGE_SIZE = 20
export const MAX_INTERVIEWS_PAGE_SIZE = 100

/**
 * The caller's latest interviews on one posting, for that posting's page.
 *
 * Under the list key, so starting, answering and finishing -- which mark every
 * list stale -- refresh this one too.
 */
export function usePostingInterviews(
  documentId: string,
  limit: number,
): UseQueryResult<InterviewSummary[]> {
  return useQuery({
    queryKey: [...listsKey, 'posting', documentId],
    queryFn: async () => {
      const { data, error } = await api.GET('/sessions', {
        params: { query: { limit, offset: 0, document_id: documentId } },
      })

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read your interviews')
      }

      return data
    },
  })
}

/** The caller's own interviews, newest first, without their messages. */
export function useInterviews(shown: number): UseQueryResult<InterviewSummary[]> {
  return useQuery({
    queryKey: [...listsKey, shown],
    queryFn: async () => {
      const { data, error } = await api.GET('/sessions', {
        // From the top with a growing limit, as the match history does: a new
        // interview lands above the page, and offset paging would repeat a row.
        params: { query: { limit: shown, offset: 0 } },
      })

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read your interviews')
      }

      return data
    },
  })
}

/** One interview with every message so far. */
export function useInterview(id: string): UseQueryResult<Interview> {
  return useQuery({
    queryKey: interviewKey(id),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/sessions/{session_id}', {
        params: { path: { session_id: id } },
      })

      if (!data) {
        throw new Error(
          detailOf(error) ?? `Could not read this interview (${String(response.status)})`,
        )
      }

      return data
    },
  })
}

export interface Answer {
  questionId: string
  content: string
}

/**
 * Send an answer and get back the whole session: the answer, its evaluation,
 * and the next question or the summary.
 */
export function useAnswer(id: string): UseMutationResult<Interview, Error, Answer> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ questionId, content }: Answer) => {
      const { data, error, response } = await api.POST(
        '/sessions/{session_id}/answers',
        {
          params: { path: { session_id: id } },
          body: { question_id: questionId, content },
        },
      )

      if (!data) {
        throw new Error(reasonFor(error, response, 'Could not send the answer'))
      }

      return data
    },
    onSuccess: async (interview) => {
      await remember(queryClient, interview)
    },
    // A conflict means the session moved on without this page -- answered
    // in another tab, or finished. Reading it again shows where it is now.
    onError: async () => {
      await queryClient.invalidateQueries({ queryKey: interviewKey(id) })
    },
  })
}

/** End the interview now; the summary covers the answers judged so far. */
export function useFinishInterview(id: string): UseMutationResult<Interview, Error, void> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST('/sessions/{session_id}/finish', {
        params: { path: { session_id: id } },
      })

      if (!data) {
        throw new Error(
          detailOf(error) ?? `Could not finish the interview (${String(response.status)})`,
        )
      }

      return data
    },
    onSuccess: async (interview) => {
      await remember(queryClient, interview)
    },
  })
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { detailOf, reasonFor } from './errors'
import type { Pairing } from './matching'
import type { components } from './schema'

export type Interview = components['schemas']['SessionRead']
export type InterviewSummary = components['schemas']['SessionSummary']
export type InterviewMessage = components['schemas']['MessageRead']

export const interviewsKey = ['interviews'] as const

function interviewKey(id: string): readonly string[] {
  return [...interviewsKey, 'detail', id]
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
      queryClient.setQueryData(interviewKey(interview.id), interview)
      // Any list of interviews is now a row short; the one just stored is not
      // out of date, so it is left alone rather than read again.
      await queryClient.invalidateQueries({
        queryKey: interviewsKey,
        predicate: (query) => query.queryKey[1] !== 'detail',
      })
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
    onSuccess: (interview) => {
      queryClient.setQueryData(interviewKey(id), interview)
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
    onSuccess: (interview) => {
      queryClient.setQueryData(interviewKey(id), interview)
    },
  })
}

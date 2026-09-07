import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { detailOf } from './errors'
import type { components } from './schema'

export type Resume = components['schemas']['ResumeRead']

export const MAX_RESUME_LENGTH = 100_000
export const MAX_TARGET_ROLE_LENGTH = 200
/** Both mirror app/schemas/resume.py, so text that cannot be stored is
 *  refused here rather than after a round trip that can only be rejected. */

export const resumesKey = ['resumes'] as const

/**
 * The caller's own resumes, newest first.
 *
 * Not paged, unlike the knowledge base: a person has a handful of resumes,
 * and the route returns only theirs (NFR-1). It does return each one's full
 * text, which is why the page keeps that text collapsed rather than drawing
 * a hundred thousand characters per row.
 */
export function useResumes(): UseQueryResult<Resume[]> {
  return useQuery({
    queryKey: resumesKey,
    queryFn: async () => {
      const { data, error } = await api.GET('/resumes')

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read your resumes')
      }

      return data
    },
  })
}

function useResumeMutation<Input, Result>(
  send: (input: Input) => Promise<Result>,
): UseMutationResult<Result, Error, Input> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: send,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: resumesKey })
    },
  })
}

export interface Pasted {
  content: string
  targetRole: string
}

/** Store a resume somebody typed or pasted. */
export function useCreateResume(): UseMutationResult<Resume, Error, Pasted> {
  return useResumeMutation(async ({ content, targetRole }: Pasted) => {
    const { data, error, response } = await api.POST('/resumes', {
      // null rather than "": the column is nullable and an empty string is a
      // value, which would show as a resume targeting a role with no name.
      body: { content, target_role: targetRole.trim() || null },
    })

    if (!data) {
      throw new Error(
        detailOf(error) ?? `Could not store the resume (${String(response.status)})`,
      )
    }

    return data
  })
}

export interface Uploaded {
  file: File
  targetRole: string
}

/** Store a resume from a PDF, DOCX or text file (FR-1). */
export function useUploadResume(): UseMutationResult<Resume, Error, Uploaded> {
  return useResumeMutation(async ({ file, targetRole }: Uploaded) => {
    const role = targetRole.trim()
    const { data, error, response } = await api.POST('/resumes/upload', {
      // The declared type says string because openapi-typescript renders
      // `format: binary` that way; bodySerializer below is what actually
      // builds the request, so the value never reaches the default one.
      body: { file: file as unknown as string, target_role: role || null },
      bodySerializer: () => {
        const form = new FormData()
        // The name is passed explicitly. FormData only keeps a filename it is
        // given or one it recognises on a File, and anything it treats as a
        // plain Blob is sent as "blob" -- which the API stores as
        // original_filename, the only name an uploaded resume comes with.
        form.set('file', file, file.name)

        if (role) {
          form.set('target_role', role)
        }

        return form
      },
    })

    if (!data) {
      throw new Error(
        detailOf(error) ?? `Could not read the file (${String(response.status)})`,
      )
    }

    return data
  })
}

/** Delete one of the caller's resumes. */
export function useDeleteResume(): UseMutationResult<void, Error, string> {
  return useResumeMutation(async (id: string) => {
    const { error, response } = await api.DELETE('/resumes/{resume_id}', {
      params: { path: { resume_id: id } },
    })

    if (!response.ok) {
      throw new Error(
        detailOf(error) ?? `Could not delete the resume (${String(response.status)})`,
      )
    }
  })
}

import { useEffect, useRef, useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'
import { useParams } from 'react-router'

import {
  openQuestion,
  useAnswer,
  useFinishInterview,
  useInterview,
} from '../api/interview'
import type { Interview, InterviewMessage } from '../api/interview'
import {
  Alert,
  Button,
  Chip,
  Field,
  Meter,
  Muted,
  Sheet,
  Skeleton,
  Thinking,
  percentage,
} from '../ui'
import { BackToPosting } from './MatchDetail'

const CRITERIA: Record<string, string> = {
  on_topic: 'On topic',
  concrete_example: 'Concrete example',
  consistent_with_resume: 'Consistent with your resume',
}

const HEADING = 'text-sm font-semibold tracking-wide text-ink-soft uppercase'

function Question({ message }: { message: InterviewMessage }): ReactElement {
  return (
    <Sheet className="flex flex-col gap-1">
      <p className="text-xs text-ink-faint">Question · {message.requirement}</p>
      <p className="font-medium">{message.content}</p>
    </Sheet>
  )
}

function AnswerBubble({ message }: { message: InterviewMessage }): ReactElement {
  return (
    <div className="ml-auto max-w-prose rounded-card bg-accent-soft px-4 py-3 text-sm">
      <p className="sr-only">Your answer</p>
      <p className="whitespace-pre-wrap">{message.content}</p>
    </div>
  )
}

/**
 * One judged answer: the verdict on every criterion with the reason for it,
 * and the tip.
 *
 * The reasons are the point. The score is counted in Python from the verdicts
 * (D-3), so a candidate who disagrees with it disagrees with a verdict, and
 * can only do that if the reason is on the page.
 */
function Evaluation({ message }: { message: InterviewMessage }): ReactElement {
  const verdicts = Object.entries(message.verdicts ?? {})

  return (
    <section
      aria-label={`Evaluation of your answer on ${message.requirement ?? 'this requirement'}`}
      className="flex flex-col gap-3 rounded-card border border-line p-4"
    >
      <p className="text-sm">
        <span className="font-semibold">{percentage(message.score ?? 0)}</span> of the
        rubric met
      </p>
      <ul className="flex flex-col gap-2">
        {verdicts.map(([name, verdict]) => (
          <li key={name} className="flex flex-col gap-1">
            <Chip present={verdict.met}>{CRITERIA[name] ?? name}</Chip>
            {verdict.reason ? (
              <span className="pl-3 text-xs text-ink-faint">{verdict.reason}</span>
            ) : null}
          </li>
        ))}
      </ul>
      {message.content ? (
        <p className="text-sm">
          <span className="font-semibold">Tip:</span> {message.content}
        </p>
      ) : null}
    </section>
  )
}

function Message({ message }: { message: InterviewMessage }): ReactElement {
  if (message.role === 'interviewer') {
    return <Question message={message} />
  }

  if (message.role === 'candidate') {
    return <AnswerBubble message={message} />
  }

  return <Evaluation message={message} />
}

/** How the interview went, put together from the evaluations -- not by a model. */
function Summary({ interview }: { interview: Interview }): ReactElement {
  const { summary, score } = interview

  return (
    <Sheet className="flex flex-col gap-4">
      <h3 className="flex flex-wrap items-baseline gap-x-3">
        {score === null ? (
          <span className="text-lg font-medium">Interview finished</span>
        ) : (
          <>
            <span className="text-5xl font-bold tracking-tight text-accent">
              {percentage(score)}
            </span>{' '}
            <span className="text-lg font-medium">of the rubric met overall</span>
          </>
        )}
      </h3>

      {score === null ? (
        <Muted>No answer was judged, so there is nothing to sum up.</Muted>
      ) : (
        <Meter value={score} label="Rubric met overall" />
      )}

      {summary && summary.strengths.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h4 className={HEADING}>Strong answers</h4>
          <ul className="flex flex-wrap gap-2">
            {summary.strengths.map((requirement) => (
              <li key={requirement}>
                <Chip present>{requirement}</Chip>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {summary && summary.improvements.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h4 className={HEADING}>Worth practising</h4>
          <ul className="flex flex-col gap-2 text-sm">
            {summary.improvements.map((item) => (
              <li key={item.requirement}>
                <span className="font-medium">{item.requirement}:</span> {item.tip}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Sheet>
  )
}

/**
 * The answer box.
 *
 * What was typed survives a failed send. The API writes nothing when the model
 * fails (502) and the person is told to try again; a box that emptied itself
 * would make them type the answer a second time to do it.
 */
function AnswerForm({
  interview,
  question,
}: {
  interview: Interview
  question: InterviewMessage
}): ReactElement {
  const [draft, setDraft] = useState('')
  const answer = useAnswer(interview.id)
  const finish = useFinishInterview(interview.id)
  const busy = answer.isPending || finish.isPending
  const box = useRef<HTMLTextAreaElement>(null)
  const refocus = useRef(false)

  // The box is disabled while an answer is judged, which drops the cursor; once
  // the next question is in, it goes back, so answering is typing, not hunting
  // for the field with the mouse. A ref, not state: it only has to survive
  // until the box is enabled again, and nothing renders from it.
  //
  // Keyed on the question as well as on busy: a quick answer can land in the
  // same render that would have shown the box disabled, so busy never visibly
  // changes -- but the question always does.
  useEffect(() => {
    if (refocus.current && !busy) {
      box.current?.focus()
      refocus.current = false
    }
  }, [busy, question.id])

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (draft.trim()) {
      // Set on sending, not on success: the box is enabled again before the
      // mutation's own callbacks run. It goes back after a failure too, which
      // is where the person retries from.
      refocus.current = true
      answer.mutate(
        { questionId: question.id, content: draft },
        {
          onSuccess: () => {
            setDraft('')
          },
        },
      )
    }
  }

  return (
    <Sheet>
      <form aria-label="Answer" onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field id="interview-answer" label="Your answer">
          {(className, id) => (
            <textarea
              ref={box}
              id={id}
              rows={6}
              maxLength={5000}
              className={className}
              value={draft}
              disabled={busy}
              onChange={(event) => {
                setDraft(event.target.value)
              }}
            />
          )}
        </Field>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={busy || !draft.trim()}>
            Send answer
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              finish.mutate()
            }}
          >
            {finish.isPending ? 'Finishing…' : 'Finish the interview'}
          </Button>
        </div>

        {/* Judging an answer is a model call of several seconds; without a
            sentence the page looks stuck and "Send" gets pressed again. */}
        {answer.isPending ? <Thinking>Evaluating your answer…</Thinking> : null}
      </form>

      {answer.error ? <Alert>{answer.error.message}</Alert> : null}
      {finish.error ? <Alert>{finish.error.message}</Alert> : null}
    </Sheet>
  )
}

/** One interview: the conversation so far, and what can be done next. */
export function InterviewSession(): ReactElement {
  const { sessionId } = useParams()
  const interview = useInterview(sessionId ?? '')
  const data = interview.data
  const question = data ? openQuestion(data) : null
  const asked = data?.messages.filter((m) => m.role === 'interviewer').length ?? 0
  const answered = data?.messages.filter((m) => m.role === 'candidate').length ?? 0
  const finished = data?.status === 'finished'

  return (
    <>
      <BackToPosting
        documentId={data?.document_id ?? null}
        title={data?.document_title ?? null}
      />

      {interview.isPending ? (
        <Skeleton lines={3} label="Loading the interview…" />
      ) : null}
      {interview.error ? (
        <Alert
          onRetry={() => {
            void interview.refetch()
          }}
        >
          {interview.error.message}
        </Alert>
      ) : null}

      {data ? (
        <article aria-label="Interview" className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h2 className="text-2xl font-extrabold tracking-tight">
              Interview · {data.document_title ?? 'Untitled posting'}
            </h2>
            <Muted>
              {finished
                ? 'Finished'
                : `Question ${String(asked)} of ${String(data.question_count)}`}
            </Muted>
            {finished ? null : (
              <Meter
                value={data.question_count ? answered / data.question_count : 0}
                label="Questions answered"
              />
            )}
          </div>

          {/* Once it is over, how it went is what the page is for -- so the
              summary comes first, not after every message of the exchange. */}
          {finished ? <Summary interview={data} /> : null}

          <section aria-labelledby="conversation" className="flex flex-col gap-4">
            {finished ? (
              <h3 id="conversation" className="text-lg font-bold">
                The conversation
              </h3>
            ) : null}
            <ol
              aria-label="Conversation"
              className="flex flex-col gap-4"
            >
              {data.messages.map((message) => (
                <li key={message.id} className="flex flex-col">
                  <Message message={message} />
                </li>
              ))}
            </ol>
          </section>

          {question ? <AnswerForm interview={data} question={question} /> : null}
        </article>
      ) : null}
    </>
  )
}

import type { ReactElement } from 'react'

import type { Match } from '../api/matching'

export function percentage(score: number): string {
  return `${String(Math.round(score * 100))}%`
}

function Terms({
  title,
  terms,
  evidence,
}: {
  title: string
  terms: string[]
  evidence?: Record<string, string>
}): ReactElement | null {
  if (terms.length === 0) {
    return null
  }

  return (
    <section>
      <h3>
        {title} ({terms.length})
      </h3>
      <ul>
        {terms.map((term) => (
          <li key={term}>
            {term}
            {/* What the model quoted from the resume for a requirement it
                judged met. This is the half that lets a candidate disagree
                with the verdict instead of taking it on trust; it is empty
                for a term matched literally, and empty everywhere when no
                judge is configured. */}
            {evidence?.[term] ? <q>{evidence[term]}</q> : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * One match, shown the same way whether it has just been computed or read
 * back out of the history.
 *
 * suggestions and notes stay two lists. They come back separately on purpose:
 * suggestions are lines to put in the resume, notes are remarks about it, and
 * a page that ran them together would present "the resume does not evidence
 * Docker" as a bullet point to paste into it.
 */
export function MatchResult({ match }: { match: Match }): ReactElement {
  return (
    <article aria-label="Match result">
      <h2>
        {percentage(match.score)} match
        {match.document_title ? ` · ${match.document_title}` : null}
      </h2>

      <Terms
        title="Covered"
        terms={match.matched_keywords}
        evidence={match.matched_evidence}
      />
      <Terms title="Missing" terms={match.missing_keywords} />

      {match.suggestions.length > 0 ? (
        <section>
          <h3>Suggested bullet points</h3>
          <ul>
            {match.suggestions.map((suggestion) => (
              <li key={suggestion}>{suggestion}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {match.notes.length > 0 ? (
        <section>
          <h3>Notes on the resume</h3>
          <ul>
            {match.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Not decoration: the API returns which fragments the suggestions were
          built from so an answer can be checked against what the model
          actually saw (NFR-2). The ids themselves would be noise on a page;
          that there were any, and how many, is the part a reader can use. */}
      <p>
        Grounded in {String(match.retrieved_chunk_ids.length)} fragments of the
        posting.
      </p>
    </article>
  )
}

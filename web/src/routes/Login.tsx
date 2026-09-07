import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'
import { Navigate, useLocation } from 'react-router'

import { useLogin, useRegister, useSession } from '../auth/session'
import { Alert, Button, Field } from '../ui'

interface FromState {
  from?: string
}

/**
 * Log in, or create an account and log straight into it.
 *
 * One form for both, because the fields are the same and a separate
 * registration page would double the markup to change one verb.
 */
export function Login(): ReactElement {
  const session = useSession()
  const location = useLocation()
  const login = useLogin()
  const register = useRegister()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  // Somebody who is already logged in has no business here -- most often
  // arriving by pressing Back after signing in.
  if (session.data) {
    const state = location.state as FromState | null

    return <Navigate to={state?.from ?? '/'} replace />
  }

  const pending = login.isPending || register.isPending
  const failure = login.error ?? register.error

  // SyntheticEvent rather than FormEvent, which React 19's types deprecate
  // as a name for an event that does not exist. Naming SubmitEvent as the
  // native event is also what makes `submitter` readable below.
  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    // Which of the two buttons was pressed. Both submit the same form, so the
    // fields are validated by the browser either way -- two separate forms
    // would duplicate the markup to change one verb.
    const action = event.nativeEvent.submitter?.getAttribute('value')
    const mutation = action === 'register' ? register : login

    // mutate rather than mutateAsync: the result is read from the hook's own
    // state below, and an awaited call here would need its rejection caught
    // twice to avoid an unhandled rejection.
    mutation.mutate({ email, password })
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col justify-center gap-8 p-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Job<span className="text-accent">Mate</span>
        </h1>
        <p className="mt-1 text-sm text-ink-faint">
          Measure a resume against the job you want.
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field id="email" label="Email">
          {(className, id) => (
            <input
              id={id}
              name="email"
              type="email"
              autoComplete="email"
              required
              className={className}
              value={email}
              onChange={(event) => {
                setEmail(event.target.value)
              }}
            />
          )}
        </Field>

        <Field id="password" label="Password">
          {(className, id) => (
            <input
              id={id}
              name="password"
              type="password"
              autoComplete="current-password"
              required
              className={className}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value)
              }}
            />
          )}
        </Field>

        <div className="mt-2 flex flex-col gap-2">
          <Button type="submit" name="action" value="login" disabled={pending}>
            Log in
          </Button>
          <Button
            type="submit"
            name="action"
            value="register"
            variant="secondary"
            disabled={pending}
          >
            Create an account
          </Button>
        </div>
      </form>

      {failure ? <Alert>{failure.message}</Alert> : null}
    </main>
  )
}

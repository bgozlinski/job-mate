// Loaded before every test file (see vite.config.ts). It adds the DOM
// matchers -- toBeInTheDocument and its neighbours -- so a failed assertion
// reports what the document held rather than "expected null to be truthy".
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { server } from './server'

// jsdom keeps one document for the whole file, so a component left mounted
// by one test is still found by the next one's query -- which passes for the
// wrong reason, and only in a full run, never when the test is run alone.
afterEach(cleanup)

// 'error' rather than 'warn': a request no handler covers means the test is
// exercising a call it did not think about, and a warning in a passing run is
// something nobody reads.
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})
afterEach(() => {
  server.resetHandlers()
})
afterAll(() => {
  server.close()
})

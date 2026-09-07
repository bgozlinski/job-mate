import { setupServer } from 'msw/node'

/**
 * The API, intercepted at the network layer.
 *
 * MSW rather than a stubbed fetch, because the thing most worth testing here
 * is the fetch layer itself: how many requests a 401 produces, in what order,
 * and whether the retry carries its body. A test that replaces fetch can only
 * assert on the calls it was handed; this one asserts on what actually went
 * out.
 *
 * Handlers are added per test with server.use(); there are no defaults, so a
 * request nobody arranged for is an error rather than a silent 200.
 */
export const server = setupServer()

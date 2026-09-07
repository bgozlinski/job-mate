# JobMate web client

The browser client for the API in `../app`. Unlike `../ui`, which is a
Streamlit development tool, this is meant to be the interface people use.

```bash
npm install
npm run dev        # http://localhost:5173, proxying /api to the API
npm run typecheck  # tsc over both projects
npm run lint
npm test
npm run build      # typecheck, then dist/
npm run gen        # regenerate openapi.json and src/api/schema.d.ts
```

`npm run dev` expects the API to be up (`docker compose up`). It reads
`JOBMATE_API_URL` for where to find it, defaulting to `http://localhost:8000`.

`docker compose up` also runs this client, at the same address. That container
keeps its own `node_modules` in a named volume, because the host's tree is
built for the host's platform and `esbuild` and `rollup` ship native binaries:
mounting a Windows tree into Alpine produces `cannot execute binary file`
rather than a missing package. Docker seeds such a volume from the image only
while it is empty, so after adding a dependency `--build` alone changes
nothing and Vite reports `Failed to resolve import` for a package that is
plainly installed on the host. The container therefore runs `npm install`
before `npm run dev`; it costs a second when the tree already agrees and
removes the whole class of problem.

## Everything goes through /api on this origin

The dev server proxies `/api/*` to the API and strips the prefix; in
production nginx does the same in front of the built files. So the browser
only ever talks to one origin, and that is a security decision rather than a
deployment convenience.

The session lives in `httpOnly` cookies (see `../app/auth/cookies.py`), and
cookies belong to an origin. One origin means no CORS, no `SameSite=None`,
and `SameSite=Lax` is enough to stand in for a CSRF token. Pointing the app
straight at `:8000` would need all three of those loosened — and only in
development, which is how a login ends up working locally and nowhere else.

The API itself has no `/api` prefix: it serves `/auth`, `/documents` and
`/resumes` at the root. The prefix exists so this server can tell which
requests are not its own.

## Two generated files, both committed

`openapi.json` is written from the FastAPI application by
`../scripts/export_openapi.py`, and `src/api/schema.d.ts` is written from
that by `openapi-typescript`. Neither is edited by hand.

They are committed rather than generated on demand so that this project
builds with Node alone, and so that a schema change shows up as a diff.
CI regenerates both and fails if either moved — the Python job checks the
first, because it is the job that has uv, and the Node job checks the second.
Between them, a Pydantic model cannot change without the types beside it
changing too. A hand-written type would drift instead, and silently: nothing
tells you `DocumentRead` grew a field until the screen that needed it is
blank.

## TypeScript is pinned to 5.x

TypeScript 7 is released, and `typescript-eslint` does not support it yet —
its peer range stops below 6.1. The type-aware rules are worth more here than
being on the newest compiler: `tsc` catches what does not type-check, and
those rules catch what type-checks and is still wrong, such as a promise
nobody awaited. Unpin when `typescript-eslint` widens the range.

ESLint's config lives in `eslint.config.ts` rather than `.js` for a related
reason: a JavaScript config belongs to no `tsconfig`, so the type-aware rules
have no types for the one file that decides how everything else is linted.

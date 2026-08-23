# Manual API walk-through

Sample payloads for exercising the API by hand. They are fixtures for a human,
not test data: the automated suite builds its own.

## The quick way (PyCharm / IntelliJ)

Open `jobmate.http` and run the requests top to bottom with the green arrow.
The token, the document id and the resume id are captured by response handlers,
so nothing has to be copied between requests, and a few assertions run along the
way.

## With curl

```bash
BASE=http://localhost:8000

curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  --data-binary @examples/credentials.json

TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  --data-binary @examples/credentials.json |
  python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST $BASE/documents -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' --data-binary @examples/job-post.json

curl -s -X POST $BASE/documents -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' --data-binary @examples/article.json

curl -s -X POST $BASE/resumes -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' --data-binary @examples/resume.json

curl -s -X POST $BASE/resumes/<RESUME_ID>/match -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"document_id":"<DOCUMENT_ID>"}'
```

Send the bodies from these files rather than pasting them into a terminal: a
long line copied out of a terminal carries the line breaks the terminal added,
and a raw newline inside a JSON string is rejected with `Invalid control
character`.

On Windows use `curl.exe`; bare `curl` in PowerShell is an alias for
`Invoke-WebRequest`, which takes different flags.

## What the files are for

| File | Purpose |
|---|---|
| `credentials.json` | The throwaway account used by register and login |
| `job-post.json` | The posting a resume is matched against |
| `article.json` | Career advice; retrieval grounds the suggestions in it |
| `frontend-post.json` | An unrelated posting, which must not reach the prompt |
| `resume.json` | A resume that omits docker, kubernetes and kafka on purpose |

## What to look for

- `POST /documents` answers 201 the first time and 200 with the same id on a
  rerun: the content hash deduplicates it. Changing only the title changes
  nothing, the hash is computed from the content.
- `missing_keywords` should contain `docker`, `kubernetes` and `kafka`, and
  `score` should sit between 0 and 1.
- `retrieved_chunk_ids` should hold more than one id: the posting's own chunk
  and at least one chunk of advice. That list is the record of what the model
  was shown.
- The second `/match` on the same resume embeds nothing new -- the query
  vector comes from Redis:

  ```bash
  docker compose exec redis redis-cli KEYS 'emb:*'
  ```

- Register a second account and match against the first account's resume id:
  the answer is 404, never 403, because a different answer would confirm that
  the resume exists.

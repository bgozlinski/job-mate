# Etapy 2–3 — Pipeline RAG: ingestion, retrieval, dopasowanie CV

**Data:** 2026-08-23
**Etapy roadmapy:** 2 i 3 z 6 (`claude/wymagania-funkcjonalne.md`, sekcja 7)
**Rezultat:** dokumenty są przeszukiwalne, a dopasowanie CV do oferty (FR-3) działa end-to-end na prawdziwych modelach.
**Poprzedni dokument:** `2026-08-06-stage1-infra-design.md`

---

## 1. Co zostało zrobione

Jedenaście commitów, od `e6cde1d` do `315432f`.

### 1.1 Schemat danych (etap 2)

| Migracja | Zawartość |
|---|---|
| `6a427200d6e5` | `documents` — natywny ENUM `source_type`, `metadata` JSONB `NOT NULL DEFAULT '{}'`, **unikalny** indeks na `content_hash` |
| `2602641fd962` | `chunks` — `embedding vector(1536)`, indeks HNSW `vector_cosine_ops`, FK `ON DELETE CASCADE`, unikalne `(document_id, chunk_index)`; `CREATE EXTENSION vector` |
| `05239445d2bc` | indeks GIN `jsonb_path_ops` na `documents.metadata` |

Razem z etapem 1: `users` (`28548320470c`), `resumes` (`128f54098c8a`). Brakuje `sessions` i `messages` — to etap 4.

### 1.2 Warstwa serwisów

| Moduł | Odpowiedzialność | Kluczowe stałe |
|---|---|---|
| `app/services/chunking.py` | normalizacja, `content_hash` (sha256), podział na fragmenty | 750 tokenów ≈ 3000 znaków, overlap 100 tokenów |
| `app/services/embeddings.py` | embeddingi za cache'em w Redisie (NFR-2a) | TTL 30 dni, batch 128, float32+base64 |
| `app/services/ingestion.py` | dokument + chunki w jednej transakcji, deduplikacja | — |
| `app/services/retrieval.py` | wyszukiwanie hybrydowe: filtr JSONB / `source_type` + `<=>` | `DEFAULT_K = 5`, `MAX_K = 50` |
| `app/services/matching.py` | score deterministyczny + sugestie z LLM (FR-3) | `MAX_KEYWORDS = 40`, `ADVICE_CHUNKS = 5` |

### 1.3 API

Nowe w tych etapach: `POST /documents`, `POST /resumes/{resume_id}/match`.
Stan całości: `/`, `/health`, `/health/ready`, `/auth/register`, `/auth/login`, `/auth/me`, `/resumes` (POST, GET), `/resumes/{id}` (GET, PATCH, DELETE), `/documents` (POST), `/resumes/{id}/match` (POST).

### 1.4 Dostawcy

- **Embeddingi:** OpenAI `text-embedding-3-small` (1536 wymiarów natywnie — tyle, ile ma kolumna i indeks).
- **LLM:** Anthropic `claude-opus-5`, structured output przez `messages.parse`. Anthropic nie ma API embeddingów, więc dostawcy są z konieczności różni.
- Oba klucze są **opcjonalne**: aplikacja startuje bez nich, a endpointy, które ich wymagają, odpowiadają 503.

---

## 2. Decyzje projektowe

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Deduplikacja | unikalny indeks na `content_hash`, `IntegrityError` → pobranie zwycięzcy | `SELECT` przed `INSERT` przepuszcza dwa równoległe requesty; tylko baza to rozstrzyga. Lookup został jako optymalizacja (oszczędza wywołanie embeddingów). |
| Granica transakcji w ingestion | embeddingi **przed** otwarciem zapisu | Dokument bez chunków jest niewidoczny dla retrievalu, a jego hash blokuje ponowną próbę. Wywołanie sieciowe w otwartej transakcji trzymałoby połączenie z bazą. |
| Normalizacja treści | NFC → CRLF na LF → `rstrip` linii → `strip` | Zachowawczo: bez zwijania spacji i case foldingu, bo dwa ogłoszenia różniące się tym naprawdę są różne. **Zmiana tej funkcji unieważnia hashe w całej bazie.** |
| Klucz cache'a embeddingów | `emb:{model}:{dimensions}:{hash}` | Po zmianie modelu (FR-6) klucz z samego hasha serwowałby wektory starego modelu. |
| Serializacja wektora | float32 + base64 (~8 kB) | JSON ~4× większy bez zysku; pgvector i tak trzyma float32, a klient ma `decode_responses`. |
| Awaria Redisa | miss przy odczycie, ciche pominięcie przy zapisie | Redis jest cache'em, nie źródłem prawdy — nie może wywalić ingestion. |
| Klasa operatorów GIN | `jsonb_path_ops` | Filtr używa wyłącznie `@>`; wariant jest mniejszy i szybszy. Cena: brak wsparcia dla `?`/`?&`. |
| Źródło `score` | deterministyczne pokrycie słów kluczowych | Liczba wymyślona przez model jest nieodtwarzalna i nietestowalna. LLM dostaje wyłącznie sformułowania — i tak ugruntowane w chunkach (FR-3). |
| Źródła porad | tylko `article` i `qa` | Podsuwanie kandydatowi cudzego ogłoszenia to nie porada. |
| Uprawnienia do `POST /documents` | każdy zalogowany | FR-1 opisuje użytkownika wklejającego ogłoszenie, FR-3 każe mu je wybrać. Administracja (FR-6) zostaje adminowi. |
| Duplikat w API | 200 z istniejącym dokumentem, nie 409 | Intencja wołającego jest spełniona; ciało mówi, który to dokument. |
| Własność CV | zależność `OwnedResume` (filtr po właścicielu w zapytaniu) | Jedna ścieżka sprawdzania zamiast dwóch; cudze CV i nieistniejące CV dają identyczne 404 (NFR-1). |

---

## 3. Wykryte wady

Kolejność: od najbardziej wpływającej na jakość produktu.

### W-1. Szum w słowach kluczowych zaniża score (otwarte, odłożone)

`extract_keywords` bierze wszystko, co nie jest gramatycznym stopwordem, więc do listy trafiają `looking`, `join`, `team`, `take`, `part`, `requirements`, `responsibilities`, `build`, `write`, `review`, `code`. To nie są luki w CV — to proza ogłoszenia.

Dodatkowo terminy nie są normalizowane morfologicznie: `apis` dopasowane, `api` policzone jako brakujące; tak samo `endpoint`/`endpoints`.

**Dowód z ręcznego testu (2026-08-23):** dobre CV backendowca dostało **0.275** (11 z 40 słów). Realne luki to `docker`, `kubernetes`, kolejki komunikatów — reszta „brakujących" to szum.

**Skutek:** score systematycznie zaniżony, `missing_keywords` mało użyteczne dla użytkownika, a prompt dostaje zaszumioną listę luk.

**Warianty naprawy:**
| Wariant | Efekt | Koszt |
|---|---|---|
| (a) normalizacja liczby mnogiej + większa lista stopwords | usuwa najgorszy szum, naprawia `api`/`apis` | ~godzina, zero kosztu runtime |
| (b) IDF po korpusie `documents` | kalibruje się samo wraz z danymi | wymaga kilkudziesięciu ofert |
| (c) LLM wyciąga listę wymagań, potem deterministyczne dopasowanie | najbliżej intencji FR-3 | jedno dodatkowe wywołanie (wystarczy Haiku) |

**Rekomendacja:** (a) teraz, (c) docelowo. Score pozostaje deterministyczny; niepewna jest wyłącznie ekstrakcja listy, którą też da się testować na fake'u.

### W-2. LLM dokleja meta-komentarz do `bullet_points` (otwarte, odłożone)

Model zwrócił jako ostatni „punkt CV" zdanie zaczynające się od „Gap note: resume does not evidence Docker…". Informacja jest cenna, ale endpoint oddaje ją w `suggestions`, czyli klient wyrenderuje ją w CV.

**Rekomendacja:** rozszerzyć schemat wyjścia o `notes: list[str]` zamiast zakazywać tego promptem — treść jest wartościowa, tylko źle zaadresowana.

### W-3. Filtr działa po wyszukiwaniu HNSW (znane ograniczenie pgvectora)

`EXPLAIN ANALYZE` na 2000 chunkach potwierdził użycie `ix_chunks_embedding_hnsw`, ale filtr na `documents` jest nakładany **po** przejściu indeksu. Przy bardzo selektywnym filtrze można dostać mniej niż `k` wyników, mimo że pasujące chunki istnieją.

**Lekarstwo, gdy pojawi się wolumen:** podniesienie `hnsw.ef_search` albo `hnsw.iterative_scan` (pgvector ≥ 0.8).

### W-4. Brak `GET /documents` (luka funkcjonalna)

FR-3 zakłada, że użytkownik wybiera ogłoszenie, ale nie ma jak wylistować bazy wiedzy — `document_id` da się dziś zdobyć tylko z odpowiedzi na `POST /documents`, przez ponowne wysłanie tej samej treści (deduplikacja zwraca to samo `id`) albo z `psql`. Formalnie należy do FR-6 (etap 5), praktycznie blokuje wygodne użycie FR-3.

### W-5. `Settings` z `extra="ignore"` przemilcza literówki w `.env`

Klucz zapisany jako `OPEN_API_KEY` zamiast `OPENAI_API_KEY` został cicho zignorowany; objawem było mylące 503 na `/documents`. **Rozważyć `extra="forbid"`** — wtedy literówka wywala aplikację przy starcie z jasnym komunikatem. Cena: każda dodatkowa zmienna w środowisku kontenera musi być zadeklarowana.

### W-6. Obraz Dockera nie zawiera nowych zależności bez przebudowy

Konsekwencja niespójności scaffoldu opisanej w `CLAUDE.md` (`uv sync --no-install-project` przed `COPY . .`). Kontener `api` był padnięty od czasu commita z auth, bo w obrazie brakowało `pwdlib`. **Po każdym `uv add` konieczne `docker compose up -d --build api`**, a po edycji `.env` — `--force-recreate`.

---

## 4. Czego świadomie nie zrobiono

- **Langfuse (NFR-2)** — brak trace'ów wywołań LLM i retrievalu. Miejsce wpięcia zaznaczone w docstringu `AnthropicSuggestionWriter.write`.
- **Rate limiting (NFR-2)** — `/resumes/{id}/match` wydaje pieniądze dwukrotnie (embedding zapytania + LLM) i jest pierwszym kandydatem.
- **`db/schema.sql`** ze spec sekcji 5 nie istnieje i nie powstanie — źródłem prawdy dla schematu jest Alembic; spec należy przy okazji poprawić.
- **`AnthropicSuggestionWriter` i `OpenAIEmbeddingModel` nie mają testów** przeciwko prawdziwym API (brak kluczy w CI). Cała logika wokół nich jest testowana na fake'ach.

---

## 5. Co dalej

### Etap 4 — mock interview na LangGraph (FR-4)

1. Tabele `sessions` i `messages` + migracja. `messages.retrieved_chunk_ids` jest już zasilane po stronie logiki — `MatchResult` zbiera te identyfikatory.
2. Graf: `retrieve_questions → ask_question → collect_answer → evaluate_answer → (pętla | summarize)`; stan grafu: docelowa rola, zadane pytania, odpowiedzi, oceny cząstkowe.
3. Warunek zakończenia: limit pytań albo decyzja użytkownika.
4. API konwersacyjne + zapis pełnej historii sesji.

### Etap 5 — eksport i administracja (FR-5, FR-6)

- `GET /documents`, `DELETE /documents/{id}` (admin — `users.is_admin` istnieje i wciąż nie jest używany).
- Re-indeksacja po zmianie modelu embeddingów.
- Eksport CV do Markdown / PDF / DOCX.

### Backlog jakości (niezwiązany z kolejnością etapów)

| Pozycja | Skąd |
|---|---|
| Naprawa szumu w słowach kluczowych, wariant (a) | W-1 |
| Pole `notes` w schemacie sugestii | W-2 |
| `GET /documents` | W-4 |
| `extra="forbid"` w `Settings` | W-5 |
| Langfuse + rate limiting | sekcja 4 |
| Rozważyć usunięcie `langchain-text-splitters` (ciągnie `langsmith`, `requests`, `orjson`) | przegląd zależności przy chunkingu |

---

## 6. Stan weryfikacji

- **128 testów** przechodzi; `ruff check .`, `ruff format --check .`, `mypy --strict`, `bandit -r app` czyste.
- Każda migracja przeszła `upgrade` → `downgrade` → `upgrade`; `alembic check` nie wykrywa rozjazdu modeli ze schematem.
- Plany zapytań sprawdzone na 2000 chunkach (`EXPLAIN ANALYZE`, transakcja wycofana).
- Ręczny przebieg end-to-end przez Swagger UI na prawdziwych modelach: ingestion → retrieval → `/match` ze score, brakującymi słowami, sugestiami i `retrieved_chunk_ids`.
- Payloady do powtórzenia ręcznego testu leżą w `examples/` (`jobmate.http` dla klienta HTTP w PyCharmie).

### Pułapki, na które warto uważać przy powrocie

1. Migracje z natywnym ENUM-em: `DROP TABLE` **nie** usuwa typu — `downgrade` musi go skasować jawnie, inaczej kolejny `upgrade` pada na `DuplicateObject`.
2. Autogenerate renderuje `pgvector.sqlalchemy.vector.VECTOR`, ale **nie dodaje importu**, i nie widzi `CREATE EXTENSION` ani indeksu HNSW.
3. W kliencie `redis.asyncio` kolejkowanie komendy w pipeline jest korutyną — bez `await pipe.set(...)` pipeline idzie pusty.
4. `Redis.from_url(url, db=15)` ignoruje argument `db`; wygrywa ścieżka z URL-a.
5. `pre-commit run --all-files` pomija pliki nieśledzone przez gita — nowe pliki trzeba sprawdzić przez `ruff check .`.

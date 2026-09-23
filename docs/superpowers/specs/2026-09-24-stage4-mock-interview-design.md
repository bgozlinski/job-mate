# Etap 4 — Mock interview na LangGraph (FR-4)

**Data:** 2026-09-24
**Etap roadmapy:** 4 z 6 (`claude/wymagania-funkcjonalne.md`, sekcja 7)
**Rezultat:** użytkownik przechodzi rozmowę rekrutacyjną pod konkretne ogłoszenie i swoje CV: pytanie →
odpowiedź → ocena, a na końcu podsumowanie. Pełna historia jest zapisana, każde wywołanie modelu trace'owane.
**Poprzedni dokument:** `2026-09-07-scraper-cookie-auth-web-client.md`
**Status:** projekt zatwierdzony w rozmowie 2026-09-24; kod jeszcze nie istnieje.

---

## 1. Punkt wyjścia

- Etapy 1–3 i 5 są na `master`. Etap 4 był odłożony (spec, zmiana 2026-09-07) i wraca teraz.
- Spec wymagał jednej decyzji **przed pierwszą linijką kodu**: skąd pytania, skoro od 2026-09-02 baza wiedzy
  zawiera wyłącznie ogłoszenia i kategorii `qa` nie ma. Rozstrzygnięte w sekcji 2.
- Nie istnieją jeszcze: tabele `sessions` i `messages` (są w modelu danych specyfikacji, nie w migracjach),
  zależność `langgraph`, żaden endpoint ani ekran rozmowy.
- Istnieje i zostanie użyte: `documents.requirements` (wymagania odczytane przez LLM przy zapisie),
  `resumes.skills`, deterministyczna reguła dopasowania z FR-3 (`app/services/matching.py`: `requirements_of`,
  `evidence`, `cover`), odczyt chunków ogłoszenia (`_job_post_chunks`), prompt store w Langfuse
  (`app/core/prompts.py`), rate limiting (`app/services/rate_limit.py`).

## 2. Decyzje

| # | Pytanie | Decyzja | Odrzucone | Dlaczego |
|---|---|---|---|---|
| D-1 | Do czego przywiązana jest sesja? | **Do konkretnego ogłoszenia i CV** | ogólna rola; oba tryby | Produkt porównuje CV z ofertą. Pytania mają z czego wynikać (`requirements`, luki), więc są ugruntowane jak w FR-3. Tryb „rola ogólnie" wymagałby banku pytań albo swobodnej generacji. |
| D-2 | Skąd lista pytań? | **Plan z góry**: na starcie model układa N pytań z wymagań, luki pierwsze; każde pytanie wskazuje swoje wymaganie | adaptacyjnie po każdej odpowiedzi; plan + jedno dopytanie | Plan to lista — zapisywalna, pokazywalna, testowalna bez modelu. Jedno wywołanie na plan, jedno na ocenę. Dopytanie da się dołożyć później bez przebudowy. |
| D-3 | Jak ocenić odpowiedź? | **Rubryka**: model zwraca werdykty tak/nie z uzasadnieniem dla stałych kryteriów + jedną wskazówkę; **wynik liczy Python** | liczba 1–10 od modelu; sam opis | Ten sam wzorzec co w FR-3: liczba od modelu nie jest powtarzalna ani testowalna. |
| D-4 | Gdzie żyje stan między żądaniami? | **Nasze tabele są źródłem prawdy**; graf wykonuje jedną turę na żądanie, stan odtwarzany z bazy | checkpointer LangGraph w Postgresie; checkpointer w pamięci | Alembic zostaje jedynym źródłem schematu (checkpointer tworzy własne tabele przez `setup()`, które `alembic check` uznałby za zbędne). Brak podwójnego stanu. Historia to zwykłe wiersze. `MemorySaver` gubi rozmowy przy każdym `--reload`. |
| D-5 | Kształt HTTP | **Żądanie–odpowiedź**, bez strumieniowania | SSE / WebSocket | Ocena to jedno wywołanie modelu, kilka sekund. Strumieniowanie można dołożyć bez zmiany modelu danych. |

### Kryteria rubryki (D-3)

1. **`on_topic`** — odpowiedź dotyczy wymagania, o które pytano.
2. **`concrete_example`** — zawiera konkretny przykład (sytuacja, działanie, efekt), a nie deklarację.
3. **`consistent_with_resume`** — nie deklaruje doświadczenia, którego nie ma w CV. W prawdziwej rozmowie to częsta
   pułapka; tu wyłapuje ją ocena.

Wynik odpowiedzi = odsetek kryteriów spełnionych (0.0–1.0), liczony w Pythonie. Lista kryteriów to stała w kodzie;
prompt ją dostaje, a nie definiuje.

## 3. Model danych

Nazwy tabel jak w specyfikacji §5. Obie powstają w jednej migracji Alembic.

### `sessions`

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | uuid (uuid7) | |
| `user_id` | FK → `users`, `ON DELETE CASCADE`, indeks | własność (NFR-1) |
| `resume_id` | FK → `resumes`, `ON DELETE SET NULL`, nullable | sesja przeżywa usunięcie CV |
| `document_id` | FK → `documents`, `ON DELETE SET NULL`, nullable | sesja przeżywa usunięcie ogłoszenia (FR-6) |
| `document_title` | text, nullable | kopia tytułu, jak w `matches` |
| `status` | text, `CHECK (status IN ('active', 'finished'))` | **nie** natywny enum — spec §8 |
| `plan` | JSONB, `NOT NULL` | lista `{"question": str, "requirement": str}` |
| `score` | float, nullable | wynik sesji, ustawiany przy podsumowaniu |
| `summary` | JSONB, nullable | `{"strengths": [...], "improvements": [{"requirement", "tip"}]}` |
| `created_at` | timestamptz, `server_default now()` | |
| `finished_at` | timestamptz, nullable | |

Oba klucze obce dodawane do nowej tabeli mają **nazwy** (spec §8: `drop_constraint(None, …)` nie ma czego usunąć).

### `messages`

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | uuid (uuid7) | |
| `session_id` | FK → `sessions`, `ON DELETE CASCADE`, indeks | |
| `position` | int, `UNIQUE (session_id, position)` | jawna kolejność — `created_at` to czas startu transakcji (spec §8), a kilka wiadomości powstaje w jednej |
| `role` | text, `CHECK (role IN ('interviewer', 'candidate', 'evaluator'))` | pytanie / odpowiedź / ocena |
| `content` | text | treść pytania, odpowiedzi albo wskazówki |
| `requirement` | text, nullable | przy `interviewer` i `evaluator`: którego wymagania dotyczy |
| `verdicts` | JSONB, nullable | przy `evaluator`: `{kryterium: {"met": bool, "reason": str}}` |
| `score` | float, nullable | przy `evaluator`, liczony w Pythonie |
| `retrieved_chunk_ids` | JSONB, `NOT NULL DEFAULT '[]'` | audyt tego, co model widział (spec §5) |
| `input_tokens`, `output_tokens` | int, nullable | koszt, przy wiadomościach wytworzonych przez model |
| `created_at` | timestamptz, `server_default now()` | |

**Postęp wynika z danych:** indeks bieżącego pytania = liczba wiadomości `candidate`. Nie ma osobnego licznika,
który mógłby się rozjechać z historią. **Plan jest w `sessions`**, a pytanie trafia do `messages` dopiero, gdy
zostaje zadane.

Relacje (uzupełnienie specyfikacji §5): `users 1—N sessions 1—N messages`, `sessions N—1 resumes` (opcjonalnie),
`sessions N—1 documents` (opcjonalnie).

## 4. Graf (LangGraph)

Graf **nie dotyka bazy**. Dostaje stan, zwraca listę nowych wiadomości i ewentualne zmiany sesji; zapisuje serwis
(sekcja 5).

```
START ─(phase)─┬─ "start"  → retrieve_questions → ask_question → END
               ├─ "answer" → collect_answer → evaluate_answer ─┬─ zostały pytania → ask_question → END
               │                                               └─ koniec planu     → summarize → END
               └─ "finish" → summarize → END
```

**Stan** (`TypedDict`): `phase`, `target_role`, `resume_text`, `requirements`, `covered` (wymagania pokryte
regułą), `posting_chunks` (id + treść), `plan`, `asked` (liczba zadanych pytań), `evaluations` (dotychczasowe
wyniki z wymaganiami i wskazówkami), `pending_answer`, `new_messages`, `finished` (bool), `score`, `summary`.

| Węzeł | Model? | Co robi |
|---|---|---|
| `retrieve_questions` | tak (`QuestionPlanner`) | Porządkuje `requirements`: najpierw niepokryte przez regułę z FR-3 (bez sędziego LLM — nie płacimy dwa razy), potem pokryte; przycina do `INTERVIEW_QUESTIONS` (domyślnie 5). Jedno wywołanie formułuje po pytaniu na wymaganie na podstawie chunków ogłoszenia. Wynik: `plan`; `retrieved_chunk_ids` = id podanych chunków. |
| `ask_question` | nie | Bierze `plan[asked]`, dodaje wiadomość `interviewer` z `requirement`. |
| `collect_answer` | nie | Dodaje wiadomość `candidate` z `pending_answer`. |
| `evaluate_answer` | tak (`AnswerEvaluator`) | Pytanie + wymaganie + odpowiedź + CV → werdykty rubryki i wskazówka. Python liczy `score`. Dodaje wiadomość `evaluator`. |
| `summarize` | **nie** | Wynik sesji = średnia wyników ocen (brak ocen → `None`). Mocne strony = wymagania z wynikiem ≥ 2/3; do poprawy = pozostałe, z ich wskazówkami. `finished = True`. |

Podsumowanie bez modelu jest świadome: składa to, co już jest, więc jest tanie, deterministyczne i nie może
niczego dopisać.

Routing po `evaluate_answer`: `asked < len(plan)` → `ask_question`, inaczej `summarize`.

## 5. Serwisy

| Moduł | Odpowiedzialność |
|---|---|
| `app/services/interview_graph.py` | budowa i kompilacja grafu (raz na proces), węzły, routing; zależy tylko od protokołów |
| `app/services/interview.py` | **jedyne miejsce łączące graf z bazą**: wczytuje sesję z wiadomościami, buduje stan, uruchamia graf, zapisuje `new_messages` z kolejnymi `position` i aktualizuje sesję — w jednej transakcji |
| `app/services/interviewing.py` | protokoły `QuestionPlanner`, `AnswerEvaluator` i ich implementacje na Anthropic, na wzór `SkillExtractor` / `RequirementJudge`; `@observe` (Langfuse), liczniki tokenów do wiadomości |

Prompty `interview-plan` i `interview-evaluate` w Langfuse z domyślną wersją w `app/core/prompts.py`
(`TEMPLATES`), seedowane przez `scripts.seed_prompts`.

Wyjście modelu jest walidowane Pydanticiem (jak `Suggestions`). Planer musi zwrócić dokładnie jedno pytanie na
każde podane wymaganie, z tym samym `requirement` — inaczej błąd (502), nie cicha naprawa.

## 6. API

Router `app/api/sessions.py`, prefiks `/sessions`, wszystko za `get_current_user`.

| Metoda i ścieżka | Ciało | Odpowiedź |
|---|---|---|
| `POST /sessions` | `{resume_id, document_id}` | 201 — sesja z pierwszym pytaniem |
| `GET /sessions` | — | 200 — twoje sesje, najnowsze pierwsze: id, tytuł, status, wynik, liczba pytań, `created_at` |
| `GET /sessions/{id}` | — | 200 — sesja z wiadomościami w kolejności `position` |
| `POST /sessions/{id}/answers` | `{content}` (1–5000 znaków) | 200 — nowe wiadomości + stan sesji |
| `POST /sessions/{id}/finish` | — | 200 — sesja z podsumowaniem |

**Zasady:**

- **Własność (NFR-1):** cudza lub nieistniejąca sesja → 404. `resume_id` musi należeć do wołającego → inaczej
  404. Nieistniejące ogłoszenie → 404.
- **Ogłoszenie bez `requirements`** (`NULL` albo puste) → 422 z wyjaśnieniem; bez wymagań nie ma z czego ułożyć
  pytań.
- **Koszt (NFR-2):** `POST /sessions` i `/answers` za rate limitem w osobnym budżecie `interview`
  (`INTERVIEW_RATE_LIMIT`, domyślnie 60/h, wpis w `.env.example`). `/finish` nie woła modelu — bez limitu.
- **Sesja zakończona:** `/answers` i `/finish` → 409.
- **Równoległe odpowiedzi:** obsługa `/answers` zaczyna od `SELECT … FOR UPDATE` na wierszu sesji; drugie żądanie
  czeka i widzi stan po pierwszym. `UNIQUE (session_id, position)` jest ostatnią barierą: `IntegrityError` → 409.
- **Awaria modelu:** odpowiedź, ocena i następne pytanie zapisują się w jednej transakcji; wyjątek dostawcy →
  502, nic nie zostaje zapisane, użytkownik wysyła ponownie.
- **Brak klucza Anthropic:** 503, jak przy dopasowaniu.

Po każdej zmianie schematu: `npm run gen` (spec NFR-4).

## 7. Klient (`web/`)

- **Zakładka „Interview"**: wybór ogłoszenia i CV (wzorzec strony `Match`), start sesji.
- **Widok rozmowy** (`/interviews/:id`): pytania, twoje odpowiedzi, karty ocen (werdykty z uzasadnieniem, wynik,
  wskazówka), pole odpowiedzi ze stanem „oceniam…" (pole nie jest czyszczone po błędzie), przycisk „Zakończ",
  podsumowanie na końcu.
- **Historia sesji** (`/interviews`): lista z możliwością otwarcia.
- Typy z OpenAPI; testy na MSW.

## 8. Poza zakresem (YAGNI)

Usuwanie sesji, dopytania, strumieniowanie, rozmowy głosowe (etap 6), tryb „rola bez ogłoszenia",
wyszukiwanie wektorowe po bazie (pytania pochodzą z `requirements` jednego ogłoszenia; NFR-3 nadal nie ma
czytelnika).

## 9. Testy

| Poziom | Zakres |
|---|---|
| Graf — bez bazy, bez modelu | atrapy planera i oceniającego; przejścia dla `start`, `answer` (dalej / koniec planu), `finish` w trakcie; kolejność planu (luki pierwsze, przycięcie do N, krótszy plan przy mniejszej liczbie wymagań); podsumowanie i wynik deterministyczne; wynik odpowiedzi z werdyktów |
| Serwis — z bazą | kolejne `position`; atomowość przy awarii modelu; dwie równoległe odpowiedzi → jedna ocena; `SET NULL` po usunięciu CV albo ogłoszenia; planer niezgodny z wymaganiami → błąd |
| API | 201, 200, 401, 404 (cudza sesja, cudze CV, brak ogłoszenia), 409, 422 (brak wymagań, pusta odpowiedź), 429, 502, 503 |
| Klient | MSW: start, odpowiedź, błąd bez utraty tekstu, zakończenie, historia |

Ewaluacja rubryki na zbiorze z etykietami (wzorzec `evals/`) — po MVP, nie w nim.

## 10. Kolejność prac

Jedno zadanie = jeden PR, każde dyktowane osobno (tryb mentora, `CLAUDE.md`).

1. Spec: wpis „Zmiana" przy FR-4 z decyzjami D-1…D-5; §5 z kolumnami `sessions` i `messages`.
2. Modele i migracja `sessions` + `messages`.
3. Zależność `langgraph` i graf (`interview_graph.py`) na atrapach — bez bazy i bez modelu.
4. `interviewing.py`: implementacje na Anthropic, prompty w Langfuse z domyślną wersją w kodzie.
5. `interview.py`: odtwarzanie stanu, zapis, transakcja, blokada.
6. Endpointy, budżet `interview`, regeneracja OpenAPI.
7. Klient: start sesji i widok rozmowy.
8. Klient: historia sesji.

Kroki 3–5 nie wymagają klucza API — atrapy wystarczają do testów.

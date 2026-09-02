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
| `9fb0b6464575` | `resumes` — `file_hash`, `mime_type`, `original_filename` (nullable) + `UNIQUE (user_id, file_hash)`; pochodzenie wgranego pliku, deduplikacja per właściciel |
| `7c1776aa283c` | `documents.requirements` JSONB nullable — wymagania odczytane przez LLM (W-1 (c)) |
| `51b84c9a0089` | `resumes.skills` JSONB nullable — umiejętności odczytane z CV, druga strona porównania |

Razem z etapem 1: `users` (`28548320470c`), `resumes` (`128f54098c8a`). Brakuje `sessions` i `messages` — to etap 4.

Trzy ostatnie migracje są z 2026-08-30/31 i wszystkie kolumny w nich są **nullable** z tego samego powodu: opisują fakt, którego wiersz może nie mieć (dokument sprzed zmiany, brak klucza LLM, CV wklejone jako tekst), a brak tego faktu kosztuje jakość, nie funkcję.

### 1.2 Warstwa serwisów

| Moduł | Odpowiedzialność | Kluczowe stałe |
|---|---|---|
| `app/services/chunking.py` | normalizacja, `content_hash` (sha256), podział na fragmenty | 750 tokenów ≈ 3000 znaków, overlap 100 tokenów |
| `app/services/embeddings.py` | embeddingi za cache'em w Redisie (NFR-2a) | TTL 30 dni, batch 128, float32+base64 |
| `app/services/ingestion.py` | dokument + chunki w jednej transakcji, deduplikacja | — |
| `app/services/retrieval.py` | wyszukiwanie hybrydowe: filtr JSONB / `source_type` + `<=>` | `DEFAULT_K = 5`, `MAX_K = 50` |
| `app/services/matching.py` | score deterministyczny + sugestie z LLM (FR-3) | `MAX_KEYWORDS = 40`, `ADVICE_CHUNKS = 5` |
| `app/services/requirements.py` | ekstrakcja wymagań oferty i umiejętności z CV przez LLM (W-1 (c), 2026-08-31) | `MAX_REQUIREMENTS = 30`, `MAX_TERM_WORDS = 3` |
| `app/services/extraction.py` | plik → tekst: PDF, DOCX, TXT (2026-08-30) | `MAX_FILE_BYTES = 5 MiB`, `MIN_EXTRACTED_CHARS = 100` |
| `app/services/rate_limit.py` | budżet żądań per konto w Redisie (NFR-2, 2026-08-31) | `match` 20/h, `ingest` 60/h |
| `app/core/prompts.py` | teksty promptów i store, który czyta je z Langfuse albo z repozytorium (2026-09-02) | `CACHE_TTL_SECONDS = 300`, `FETCH_TIMEOUT_SECONDS = 3` |

### 1.3 API

Nowe w tych etapach: `POST /documents`, `POST /resumes/{resume_id}/match`.
Stan całości: `/`, `/health`, `/health/ready`, `/auth/register`, `/auth/login`, `/auth/me`, `/resumes` (POST, GET), `/resumes/upload` (POST), `/resumes/{id}` (GET, PATCH, DELETE), `/documents` (POST, GET — listowanie dołożone 2026-08-24 przy zamykaniu W-4), `/documents/upload` (POST), `/resumes/{id}/match` (POST). Obie trasy `upload` dołożone 2026-08-30/31: CV i ogłoszenie wchodzą jako PDF / DOCX / tekst.

### 1.4 Dostawcy

- **Embeddingi:** OpenAI `text-embedding-3-small` (1536 wymiarów natywnie — tyle, ile ma kolumna i indeks).
- **LLM:** Anthropic, structured output przez `messages.parse`. Anthropic nie ma API embeddingów, więc dostawcy są z konieczności różni. Domyślny model zmieniony 2026-08-24 z `claude-opus-5` na `claude-haiku-4-5` — patrz niżej.
- Oba klucze są **opcjonalne**: aplikacja startuje bez nich, a endpointy, które ich wymagają, odpowiadają 503.

### 1.5 Prompty w Langfuse (2026-09-02)

Teksty promptów wyszły z modułów, które je wysyłają, do `app/core/prompts.py`, a stamtąd do
Langfuse Prompt Management. Powodem jest W-1: otwarta pozycja „prompt ekstrakcji" wymaga
porównania dwóch brzmień, a to znaczy zmieniać tekst bez deployu i umieć odczytać koszt
oraz jakość **per wersja**, nie per commit. `update_current_generation(prompt=...)` podpina
wersję pod generację w trace'ie i to jest cała różnica między „ten prompt jest lepszy"
a liczbą.

Trzy prompty: `job-post-skills`, `resume-skills`, `match-suggestions` — ten ostatni to
instrukcja z `build_prompt` razem z nagłówkami sekcji; w kodzie została tylko ta część,
która jest decyzją kodu (numerowanie chunków, `"none"` w pustej sekcji). Store za
protokołem `PromptStore` z jedną metodą `render(name, /, **variables)`. Nazwa promptu jest
pozycyjna, bo dzieli sygnaturę ze zmiennymi — prompt ze zmienną `name` byłby inaczej nie do
wyrenderowania (złapane testem, nie recenzją).

Trzy decyzje warte zapamiętania:

- **Fallbackiem jest tekst z repozytorium.** Każde `get_prompt` niesie
  `fallback=TEMPLATES[name]`, więc nieosiągalny Langfuse kosztuje brzmienie z commita, a nie
  żądanie. Prompt spoza `TEMPLATES` nie ma podłogi i jest odrzucany, zamiast trafić do
  modelu jako pusta instrukcja.
- **Store dostaje klienta zbudowanego w lifespanie, nie `get_client()`.** Klient bez kluczy
  wyłącza się, a `get_prompt` na wyłączonym kliencie **rzuca zanim dojdzie do fallbacku**
  (`_resources is None`). `create_prompt_store(None)` odpowiada na ten sam warunek o krok
  wcześniej — statycznym store'em, na którym stoi CI i każda maszyna bez kluczy.
- **Nie używamy `compile()` z SDK.** `TemplateParser.compile_template` zostawia niewypełniony
  placeholder w tekście jako dosłowne `{{content}}`, czyli prompt bez dokumentu — a model
  odpowiada na to pustą listą, nie do odróżnienia od oferty bez wymagań. Renderuje własne
  `render_template`, dla którego niewypełniony placeholder **i** nieużyta zmienna to
  `ValueError`. Ta sama surowość obowiązuje tekst z serwera.

Cache ma TTL 300 s i jest rozgrzewany w lifespanie (`warm()`): `get_prompt` jest
synchroniczne, więc pierwsze pobranie blokuje pętlę zdarzeń, a na starcie nikt nie czeka.
Wpis wygasły SDK odświeża w wątku w tle i serwuje w tym czasie stary tekst, więc to jedyne
blokujące pobranie w procesie.

Seedowanie: `scripts/seed_prompts.py` pisze każdy tekst jako nową wersję z labelką
`production`, ale tylko gdy różni się od serwowanej — ponowny przebieg jest darmowy, a
historia wersji zostaje zapisem zmian, nie uruchomień. **Brak seedowania niczego nie psuje**:
aplikacja jedzie na fallbacku i nikt się nie dowie. To jest właśnie powód, żeby robić to
świadomie.

**Cena.** Prompt jest od teraz stanem zewnętrznym: `git checkout` starego commita nie
odtworzy zachowania, jeśli ktoś w międzyczasie przestawił labelkę `production`. Fallback
ratuje dostępność, nie reprodukowalność.

**Niedomknięte.** `render` wiesza wersję na bieżącej obserwacji. W ekstraktorach jest nią
generacja (`@observe(as_type="generation")`) i wychodzi dokładnie tak, jak trzeba; w `/match`
`build_prompt` woła się poza spanem writera, więc atrybuty promptu lądują na spanie `match` —
prawda, tylko mniej użyteczna. Domknięcie wymaga przeniesienia renderowania do
`AnthropicSuggestionWriter.write`, co zmienia protokół `SuggestionWriter` (dziś przyjmuje
gotowy tekst, na czym stoją testy dowodzące ugruntowania z FR-3). Osobna decyzja.

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

### W-1. Szum w słowach kluczowych zaniża score (zamknięte 2026-08-31, wariant (c))

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

**Naprawa (2026-08-24) — wariant (a), dwie połowy:**

1. `singular()` sprowadza obie strony porównania do jednej formy, więc `apis` w ofercie
   trafia na `api` w CV. Reguły są celowo małe (stemmer zrobiłby z `kubernetes` — `kubernet`),
   a terminy, których żadna reguła nie odgadnie, siedzą w `INVARIANT`: `aws`, `redis`,
   `postgres`, `devops`, `k8s`.
2. `BOILERPLATE` — druga lista obok `STOPWORDS`, z innym kryterium: słowa, których oferta
   używa, żeby być ofertą (zwroty rekrutacyjne, nagłówki sekcji, czasowniki obowiązków,
   wypełniacze, liczebniki, benefity). Filtrowana **po** złożeniu formy, więc jeden wpis
   pokrywa `responsibility` i `responsibilities`. Benefity mają własne uzasadnienie:
   `remote`, `training budget`, `conference ticket` to co pracodawca oferuje, a nie co
   kandydat ma udowodnić — biegną przez porównanie w przeciwną stronę.

Granica jest ta sama, co w docstringu `STOPWORD_LIST`: `experience`, `team` i nazwy
stanowisk zostają policzalne, bo oferta, która je akcentuje, coś o roli mówi.

**Pomiar na `examples/` (ten sam payload, co 2026-08-23):** score **0.275 (11/40) → 0.312
(10/32)**, a `missing_keywords` to dziś w istocie same luki: `docker`, `kubernetes`, `sql`,
`message queue`, `rabbitmq`, `kafka`, `redis`, `terraform`, `observability`, `prometheus`,
`grafana`. Kontrola negatywna: to samo CV na ofercie frontendowej daje 0.000 (0/12).

Uwaga na przyszłość: score jest ułamkiem, więc usuwanie szumu zabiera też trafienia —
`year` wypadło jako wypełniacz, choć było dopasowane (oferta „three years", CV „five
years"). Liczba rośnie mniej, niż sugeruje poprawa jakości listy. Próg `MAX_KEYWORDS = 40`
przestał przy okazji wiązać: krótka oferta ma 32 terminy treściowe.

**Naprawa (2026-08-31) — wariant (c), docelowy.** `app/services/requirements.py`: LLM
czyta ofertę i zwraca listę wymagań, `cover()` i score liczą się dalej w Pythonie z tej
listy. Model dostarcza dane, nie ocenę — to warunek z rekomendacji powyżej i jedyne, co
utrzymuje score powtarzalnym.

Ekstrakcja biegnie **raz, przy ingestion**, i ląduje w `documents.requirements` (JSONB,
nullable, migracja `7c1776aa283c`). Wymagania są własnością oferty, nie pary CV↔oferta:
w `/match` kosztowałyby wywołanie LLM na każdego kandydata i weszły w drogę NFR-3.
Tylko `job_post` — do artykułu nikt nic nie porównuje. Duplikat nie jest czytany drugi raz.

Osobna kolumna, nie `metadata`: `metadata` pochodzi od klienta i po niej filtruje
retrieval, więc wmieszanie wyjścia modelu pozwoliłoby podać własną listę jako
wyekstrahowaną albo trafić filtrem w umiejętność, której nikt nie wpisał.

Każdy sposób na brak listy kończy się tak samo — powrotem do heurystyki z wariantu (a):
brak klucza, awaria providera, dokument sprzed tej zmiany, pusta odpowiedź. `NULL` kosztuje
jakość, nie funkcję, a ingestion, która opłaciła już embeddingi, nie ginie przez milczenie
LLM. To dlatego wariant (a) zostaje w kodzie i nie jest długiem.

`cover()` uznaje wymaganie wielowyrazowe za spełnione, gdy CV ma **wszystkie** jego słowa,
niekoniecznie obok siebie: wymagania modelu to frazy (`message queues`, `ci/cd pipelines`),
a żądanie dokładnej sekwencji raportowałoby lukę wobec CV mówiącego „maintained the message
queue consumers".

**Pomiar na `examples/` (ten sam payload):** score **0.312 (10/32) → 0.267 (4/15)**.
Model zwrócił 15 wymagań zamiast 32 terminów: `python`, `fastapi`, `rest apis`,
`postgresql`, `sql`, `docker`, `kubernetes`, `ci/cd pipelines`, `rabbitmq`, `kafka`,
`redis`, `terraform`, `prometheus`, `grafana`, `automated testing`.

**Liczby nie są porównywalne** — mianownik zmienił znaczenie, a usuwanie szumu zabiera
trafienia razem z nim (ta sama pułapka, co przy wariancie (a), tylko mocniejsza).
Porównywalne jest to, że `missing_keywords` to dziś wyłącznie realne luki, bez `year`,
`engineer` i `team`.

**Wada widoczna w tym samym przebiegu:** model dał `sql` obok `postgresql`, mimo że prompt
zakazuje powtarzania tego samego pojęcia. `postgresql` się dopasowało, `sql` nie — jedno
wymaganie liczone dwa razy, raz jako luka. Zostawione świadomie: poprawka promptu wymaga
pomiaru tą samą drogą, nie zgadywania. Kandydat na dataset w Langfuse.

**Druga strona porównania (2026-08-31).** CV też jest czytane przez LLM, a wynik ląduje w
`resumes.skills` (JSONB, nullable, migracja `51b84c9a0089`). Bez tego lista wymagań trafiała
na surowe tokeny CV i `automated testing` z oferty nie miało jak spotkać „unit and
integration tests" z CV, a `kubernetes` — `k8s`.

Jeden protokół `SkillExtractor` dla obu stron, prompt jako argument konstruktora zamiast
podklasy: odczyty różnią się jednym stringiem, a dzielą wywołanie, tracing i czyszczenie.
Czytane tym samym słownikiem celowo — wymaganie i umiejętność, która na nie odpowiada,
muszą wrócić zapisane tak samo, inaczej porównanie jest bezwartościowe. Stąd jedyna
wyróżniająca instrukcja promptu CV: rozwiń skrót (`k8s` → `kubernetes`).

**`evidence()` to suma, nie zamiana.** Terminy, którymi CV odpowiada, to tokeny jego
własnego tekstu **∪** tokeny wyekstrahowanej listy. Lista modelu jest streszczeniem i może
pominąć słowo stojące w tekście wprost, więc zastąpienie tekstu listą gubiłoby dopasowania,
które dziś działają. Odczyt CV może wyłącznie dodać trafienie — pilnuje tego osobny test.

`PATCH` zmieniający `content` **czyści** `skills` zamiast czytać ponownie: opisywałyby tekst,
którego już nie ma, i odpowiadałyby na wymagania, których nowe CV nie spełnia. Czyszczenie
cofa do słów nowego tekstu (uczciwie), ponowny odczyt dokładałby wywołanie LLM do trasy,
która nigdy go nie miała, przy edycji mogącej być poprawką literówki. Zmiana samego
`target_role` umiejętności nie rusza.

Obie trasy zapisujące CV wydają teraz pieniądze, więc dostały budżet `ingest` (NFR-2).

**Pomiar na `examples/` (ten sam payload):** score **0.267 (4/15) → 0.333 (5/15)**. Zysk to
`automated testing`: wymagane przez ofertę, udowodnione w CV jako „unit and integration
tests", niewidoczne dla każdej wcześniejszej wersji tego porównania. Nic, co dopasowywało
się wcześniej, nie przestało. Model wyciągnął z CV: `python`, `rest apis`, `flask`,
`fastapi`, `postgresql`, `unit testing`, `integration testing`, `mentoring`,
`deployment automation`, `production monitoring`.

**Drugie znalezisko przy okazji:** model zwraca z CV umiejętności prawdziwe, ale takie, o
które żadna oferta nie zapyta w tych słowach (`mentoring`, `production monitoring`).
Nieszkodliwe, bo suma tylko dodaje — warte obserwacji, gdyby lista miała kiedyś służyć do
czegoś poza porównaniem.

### W-2. LLM dokleja meta-komentarz do `bullet_points` (zamknięte 2026-08-24)

Model zwrócił jako ostatni „punkt CV" zdanie zaczynające się od „Gap note: resume does not evidence Docker…". Informacja jest cenna, ale endpoint oddaje ją w `suggestions`, czyli klient wyrenderuje ją w CV.

**Rekomendacja:** rozszerzyć schemat wyjścia o `notes: list[str]` zamiast zakazywać tego promptem — treść jest wartościowa, tylko źle zaadresowana.

**Naprawa (2026-08-24):** `Suggestions` ma dwa pola (`notes` z domyślną pustą listą, żeby
model bez uwag nie wywracał walidacji), a `SuggestionWriter.write` zwraca cały obiekt
zamiast samej listy — nazwane pola nie mylą się przy rozpakowaniu i protokół nadal nie
zależy od Anthropica. Pole idzie przez `MatchResult` → `MatchRead` → odpowiedź HTTP.

Dwie rzeczy, które łatwo przeoczyć przy takiej zmianie: instrukcja w `build_prompt`
**musi** powiedzieć, do czego służy `notes`, bo pole schematu, którego prompt nie
wymienia, wraca puste i meta-komentarz znów jedzie w punktach; oraz `mypy --strict`
złapie protokół, ale nie to, że wartość nie została przepisana w `app/api/matching.py` —
stąd test endpointu asertujący `notes` w ciele odpowiedzi. `FakeSuggestionWriter`
domyślnie zwraca notatkę, żeby zgubione pole nie przeszło niezauważone. Ręczny scenariusz
w `examples/jobmate.http` sprawdza dodatkowo, że żaden punkt nie zaczyna się od
„Gap note" — to jedyne miejsce, gdzie widać prawdziwy model.

### W-3. Filtr działa po wyszukiwaniu HNSW (znane ograniczenie pgvectora)

`EXPLAIN ANALYZE` na 2000 chunkach potwierdził użycie `ix_chunks_embedding_hnsw`, ale filtr na `documents` jest nakładany **po** przejściu indeksu. Przy bardzo selektywnym filtrze można dostać mniej niż `k` wyników, mimo że pasujące chunki istnieją.

**Lekarstwo, gdy pojawi się wolumen:** podniesienie `hnsw.ef_search` albo `hnsw.iterative_scan` (pgvector ≥ 0.8).

### W-4. Brak `GET /documents` (zamknięte 2026-08-24)

FR-3 zakłada, że użytkownik wybiera ogłoszenie, ale nie ma jak wylistować bazy wiedzy — `document_id` da się dziś zdobyć tylko z odpowiedzi na `POST /documents`, przez ponowne wysłanie tej samej treści (deduplikacja zwraca to samo `id`) albo z `psql`. Formalnie należy do FR-6 (etap 5), praktycznie blokuje wygodne użycie FR-3.

**Naprawa (2026-08-24):** `GET /documents` z parametrami `source_type`, `limit` (domyślnie 20,
maksymalnie 100) i `offset`. Cztery decyzje warte zapamiętania:

| Decyzja | Wybór | Dlaczego |
|---|---|---|
| Treść w odpowiedzi | nie ma jej — `DocumentRead` i tak jej nie zawiera | strona listingu nie może rosnąć z długością artykułów |
| Uprawnienia | każdy zalogowany | tak samo jak `POST /documents`: bez tego FR-3 jest nieużywalny. Kasowanie zostaje adminowi (FR-6) |
| Sortowanie | `created_at DESC, id DESC` | dwa dokumenty z tej samej chwili nie mają inaczej ustalonej kolejności i paginacja po `offset` potrafi pokazać jeden z nich dwa razy; `id` to uuid7, więc rozstrzygnięcie biegnie zgodnie z czasem |
| `chunk_count` | jeden `outerjoin` + `GROUP BY` | `_read` liczy chunki osobnym zapytaniem na dokument; przepisane wprost na listing dałoby N+1 |

Paginacja jest od razu, bo dołożona później zmienia kształt odpowiedzi. Nie ma pola z sumą
wszystkich dokumentów — kosztowałoby drugie zapytanie na każde wywołanie, żeby powiedzieć to,
co następna strona mówi za darmo.

Nie zrobiono: filtrowania po `metadata` (indeks GIN już jest, więc to jedno `@>` w `where`,
gdy pojawi się potrzeba) ani `GET /documents/{id}` — czyli jedynego miejsca, gdzie treść
dokumentu miałaby wracać w całości.

### Zmiana domyślnego modelu LLM (2026-08-24)

`llm_model` domyślnie `claude-haiku-4-5` zamiast `claude-opus-5`. Powód jest strukturalny,
nie oszczędnościowy: podział pracy w FR-3 zostawia modelowi wyłącznie przeformułowanie
punktów CV — score, brakujące słowa i uziemienie w chunkach liczy Python. To zadanie o
wąskim zakresie, z narzuconym schematem wyjścia.

Dwa czynniki, nie jeden:

| | `claude-opus-5` | `claude-haiku-4-5` |
|---|---|---|
| Cena (wejście / wyjście za 1M) | 5 / 25 USD | 1 / 5 USD |
| Okno kontekstu | 1M | 200K |
| Myślenie | **adaptacyjne, włączone domyślnie** | brak |

Drugi wiersz od dołu jest tym, który naprawdę zmienia rachunek: na Opusie 5 myślenie jest
włączone, nawet gdy kod nie przekazuje parametru `thinking`, a tokeny myślenia są liczone
jak wyjściowe — po 25 USD za milion. Haiku ich nie generuje, więc na wyjściu zostają same
punkty CV.

200K kontekstu wystarcza z zapasem: prompt to ogłoszenie, CV i najwyżej dziesięć chunków.

Pułapka na przyszłość: **`output_config={"effort": ...}` zwraca błąd na Haiku 4.5.** Gdyby
jakość sugestii okazała się za niska, kolejność podnoszenia to `claude-sonnet-5`
(3 / 15 USD), potem `claude-opus-5` — i dopiero tam `effort` oraz `thinking` są dostępne.
Zmiana nie wymaga ruszania kodu, wystarczy `LLM_MODEL` w `.env`.

### W-5. `Settings` z `extra="ignore"` przemilcza literówki w `.env` (zamknięte, `71ec9ea`)

Klucz zapisany jako `OPEN_API_KEY` zamiast `OPENAI_API_KEY` został cicho zignorowany; objawem było mylące 503 na `/documents`. **Rozważyć `extra="forbid"`** — wtedy literówka wywala aplikację przy starcie z jasnym komunikatem. Cena: każda dodatkowa zmienna w środowisku kontenera musi być zadeklarowana.

**Naprawa (`71ec9ea`):** `extra="forbid"` plus dwa ograniczenia, które trzeba znać, bo są
udokumentowane testami, a nie tylko docstringiem. Sprawdzenie obejmuje **wyłącznie plik
`.env`** — zmienne środowiskowe są wiązane z polami po nazwie, więc nieznana jest dla
modelu niewidzialna; dlatego `docker-compose` montuje `.env` do kontenera (`:ro`), mimo
że `env_file` i tak podaje jego treść. Drugie: klucz z pustą wartością jest odrzucany
przed sprawdzeniem, bo tym właśnie jest niewypełniona linia w `.env.example`. Testy pilnują
też obu kierunków zawierania między `.env.example` a polami modelu.

### W-6. Obraz Dockera nie zawiera nowych zależności bez przebudowy

Konsekwencja niespójności scaffoldu opisanej w `CLAUDE.md` (`uv sync --no-install-project` przed `COPY . .`). Kontener `api` był padnięty od czasu commita z auth, bo w obrazie brakowało `pwdlib`. **Po każdym `uv add` konieczne `docker compose up -d --build api`**, a po edycji `.env` — `--force-recreate`.

---

## 4. Czego świadomie nie zrobiono

- ~~**Langfuse (NFR-2)**~~ — zrobione 2026-08-31, self-hosted w compose. Jeden trace na
  żądanie: `match` / `ingest` jako korzeń z `user_id`, pod nim `retrieval` (chunk_ids i
  dystanse), `embed_texts` (trafienia w cache i wywołania API — pomiar NFR-2a) oraz
  `write` (prompt, odpowiedź, tokeny). Score dopięty do korzenia. **Nie ma tokenów przy
  embeddingach**: `EmbeddingModel` zwraca same wektory, więc realny koszt wymaga
  rozszerzenia tego protokołu. Datasety i eksperymenty nietknięte — pierwsze zastosowanie
  to prompt ekstrakcji z W-1. **Prompt management dołożony 2026-09-02** (sekcja 1.5):
  wersje promptów są podpięte pod generacje, więc porównanie brzmień ma już na czym stanąć —
  brakuje datasetu.
- ~~**Rate limiting (NFR-2)**~~ — zrobione 2026-08-31. Per konto (nie per IP: za proxy w
  Dockerze wszystkie żądania mają ten sam adres), licznik w Redisie w namespace
  `ratelimit:*`, osobnym od cache'u embeddingów. Dwa budżety: `match` 20/h i `ingest` 60/h,
  żeby napełnianie bazy wiedzy nie odcinało od dopasowania. Awaria Redisa daje 503, nie
  przepuszcza — odwrotnie niż cache, bo limiter, który nie liczy, przestaje ograniczać
  wydatki. Okno stałe, więc realny sufit na granicy okien to dwukrotność limitu.
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

| Pozycja | Skąd | Status |
|---|---|---|
| ~~Pole `notes` w schemacie sugestii~~ | W-2 | zrobione 2026-08-24 |
| ~~`GET /documents`~~ | W-4 | zrobione 2026-08-24 |
| ~~Langfuse + rate limiting~~ | sekcja 4 | zrobione 2026-08-31 |
| Rozważyć usunięcie `langchain-text-splitters` (ciągnie `langsmith`, `requests`, `orjson`) | przegląd zależności przy chunkingu | otwarte |
| ~~Ekstrakcja wymagań przez LLM, wariant (c)~~ | W-1 | zrobione 2026-08-31 |
| ~~Ekstrakcja umiejętności z CV (druga strona porównania)~~ | W-1 | zrobione 2026-08-31 |
| Prompt ekstrakcji: `sql` obok `postgresql`, `mentoring` z CV | W-1 | otwarte — infrastruktura gotowa (1.5), brakuje datasetu |
| ~~Prompty do Langfuse: wersje, labelki, koszt per wersja~~ | W-1 | zrobione 2026-09-02 |
| Renderowanie promptu `/match` poza spanem writera — wersja ląduje na spanie `match` | sekcja 1.5 | otwarte |
| ~~Naprawa szumu w słowach kluczowych, wariant (a)~~ | W-1 | zrobione 2026-08-24 |
| ~~`extra="forbid"` w `Settings`~~ | W-5 | zrobione `71ec9ea` |

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

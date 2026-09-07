# JobMate — AI Resume & Interview Coach

**Autor:** Bartek Goźliński
**Data:** 05.08.2026
**Status:** v2 — po konsultacji z mentorem

---

## 1. Opis projektu

JobMate to asystent kariery oparty na architekturze RAG (Retrieval-Augmented Generation). System pobiera ogłoszenia o pracę, a następnie pomaga użytkownikowi dopasować CV do docelowej roli i przygotować się do rozmowy rekrutacyjnej. Odpowiedzi są ugruntowane w zapisanych dokumentach i w CV kandydata, a nie generowane swobodnie przez LLM — co ogranicza halucynacje i pozwala zweryfikować sugestie. Od 2026-09-02 baza wiedzy zawiera wyłącznie ogłoszenia (FR-1), więc dopasowanie CV nie korzysta już z wyszukiwania wektorowego, a serwis retrievalu został usunięty; wyszukiwanie wróci wraz z etapem 4, jeśli pytania na mock interview mają pochodzić z bazy.

**Cele:**
- Nauka i praktyczne zastosowanie pełnego pipeline'u RAG (ingestion → chunking → embedding → retrieval → generacja)
- Zbudowanie backendu w stylu produkcyjnym z użyciem znanego mi stacku (Python, FastAPI, PostgreSQL, Docker, CI/CD)

## 2. Stack technologiczny

| Warstwa | Technologia | Uzasadnienie |
|---|---|---|
| Backend API | FastAPI | Asynchroniczny, typowany, znany |
| Baza danych + wektory | PostgreSQL + pgvector | Jedna baza dla danych relacyjnych i embeddingów; bez osobnego vector store |
| LLM | OpenAI / Anthropic API | Usługa zarządzana, bez własnej infrastruktury GPU |
| Orkiestracja RAG | LangChain | Standardowe komponenty: loadery, splittery, retriever |
| Orkiestracja agenta | LangGraph | Stanowy graf konwersacji dla mock interview (FR-4) |
| Observability LLM | Langfuse | Trace'y wywołań, koszty tokenów, ewaluacja jakości |
| Cache | Redis | Cache embeddingów (hash treści → wektor) |
| Embeddingi | model text-embedding (1536 wymiarów) | Standardowy, tani |
| Konteneryzacja | Docker + docker-compose | Powtarzalne środowisko deweloperskie |
| CI/CD | GitHub Actions | Lint, testy, build |

## 3. Wymagania funkcjonalne

### FR-1. Ingestion dokumentów
- System przyjmuje **wyłącznie ogłoszenia o pracę**, na trzy sposoby: wklejony tekst, plik PDF / DOCX / TXT
  albo **adres URL ogłoszenia** w serwisie z allowlisty (warunki w NFR-5).
- Dokumenty są dzielone na chunki (500–1000 tokenów z overlapem), embedowane i zapisywane w bazie.
- Duplikaty są odrzucane na podstawie hasha treści.

> **Zmiana 2026-09-07.** Doszedł trzeci sposób wprowadzenia ogłoszenia: użytkownik podaje URL, a system
> odczytuje z tej strony treść oferty. Nie jest to nowa ścieżka ingestii — odczytana treść trafia do tego
> samego `SourceDocument` co wklejony tekst, więc chunking, embedding i deduplikacja po `content_hash`
> działają bez zmian. Warunki, na jakich wolno sięgnąć po stronę, opisuje NFR-5; to tam, a nie tutaj, jest
> granica tej funkcji.
>
> Deduplikacja ma tu znaną dziurę: ta sama oferta raz wklejona ręcznie, a raz pobrana z URL-a, ma inne
> białe znaki, więc inny hash i powstaje drugi dokument. Świadomie nie naprawiamy tego normalizacją
> agresywniejszą niż `normalize_content` — ta zmiana unieważniłaby hashe wszystkiego, co już jest w bazie.

> **Zmiana 2026-09-02.** Wcześniej baza wiedzy przyjmowała też artykuły z poradami kariery i wpisy Q&A
> (`documents.source_type`). Program ma porównywać CV z ofertą i nic poza tym, więc kolumna rozróżniała
> rodzaje źródeł, na które nic już nie reagowało — została usunięta razem z wierszami innymi niż ogłoszenia
> (migracja `7712a7f5bd98`). Konsekwencje dla FR-3 i FR-4 opisane przy tych wymaganiach.

### FR-2. Profil użytkownika
- Użytkownik może się zarejestrować i zalogować (uwierzytelnianie JWT).
- Użytkownik może przechowywać jedną lub więcej wersji CV (surowy tekst), opcjonalnie powiązanych z docelową rolą.

### FR-3. Dopasowanie CV do oferty
- Użytkownik wybiera ogłoszenie oraz jedno ze swoich CV.
- System zwraca:
  - wynik dopasowania (score),
  - brakujące słowa kluczowe i umiejętności,
  - proponowane bullet pointy dopasowane do ogłoszenia.
- Sugestie są ugruntowane w treści wybranego ogłoszenia i w CV kandydata, a nie w swobodnej generacji LLM: model nie może wymyślić pracodawcy, daty, technologii ani osiągnięcia, którego nie ma w żadnym z nich.
- Dopasowanie umiejętności rozstrzyga model, **wymaganie po wymaganiu**, cytując słowa CV, które je udowadniają (np. PostgreSQL odpowiada na SQL, Excel na arkusze kalkulacyjne, wózek widłowy na każdej zmianie na uprawnienia). Werdykt może dopasowanie wyłącznie **dodać** — trafienia reguły deterministycznej są nienaruszalne.
- Score i brakujące słowa kluczowe liczone są w Pythonie z listy werdyktów — liczba pochodząca od modelu nie byłaby powtarzalna, wytłumaczalna ani testowalna.
- Każde dopasowanie jest zapisywane i użytkownik może wrócić do swojej historii; widzi wyłącznie własne (NFR-1).

> **Zmiana 2026-09-02.** Wcześniej sugestie miały być oparte na top-k chunkach z ogłoszenia **i artykułów
> z poradami**. Po usunięciu artykułów (FR-1) wskazówki „jak pisać punkt CV" są częścią promptu
> `match-suggestions`, wersjonowanego w Langfuse. Ta sama porada obowiązuje przy każdym dopasowaniu, więc
> prompt jest dla niej właściwszym adresem niż baza wiedzy: jest wersjonowana i mierzalna, zamiast być tym,
> co akurat zwróciło wyszukiwanie najbliższych sąsiadów. Ceną jest to, że retrieval wektorowy nie bierze już
> udziału w FR-3.

### FR-4. Symulacja rozmowy rekrutacyjnej (LangGraph)
- System generuje pytania typowe dla docelowej roli, wyszukane w bazie wiedzy.
- Przebieg rozmowy zaimplementowany jako stanowy graf w LangGraph:
  - węzły: `retrieve_questions` → `ask_question` → `collect_answer` → `evaluate_answer` → (pętla lub `summarize`),
  - stan grafu: docelowa rola, zadane pytania, odpowiedzi, oceny cząstkowe,
  - warunek zakończenia: limit pytań lub decyzja użytkownika.
- Tryb konwersacyjny: pytanie → odpowiedź użytkownika → feedback od LLM.
- Pełna historia sesji jest zapisywana; każde wywołanie LLM trace'owane w Langfuse.

> **Do rozstrzygnięcia przed etapem 4 (2026-09-02).** Pytania miały pochodzić z wpisów `qa` w bazie wiedzy,
> a tej kategorii już nie ma (FR-1). Do wyboru: wyprowadzać pytania z ogłoszenia i CV, przywrócić osobną
> kategorię źródeł kolejną migracją, albo trzymać zestaw pytań w prompcie. Dopóki decyzji nie ma, pierwszy
> punkt wyżej opisuje zamiar, nie stan.

### FR-5. Eksport
- Użytkownik może wyeksportować poprawione CV do formatu Markdown / PDF / DOCX.

### FR-6. Administracja bazą wiedzy
- Administrator może przeglądać i usuwać źródła.
- Obsługiwana jest re-indeksacja po zmianie modelu embeddingów.

## 4. Wymagania niefunkcjonalne

- **NFR-1 Bezpieczeństwo:** uwierzytelnianie JWT; hasła przechowywane jako hashe; użytkownik ma dostęp wyłącznie do własnych danych.
- **NFR-2 Kontrola kosztów i observability:** każde wywołanie LLM i retrieval trace'owane w Langfuse (koszty tokenów, latencja, użyte chunki); rate limiting na endpointach LLM.
- **NFR-2a Cache embeddingów:** przed wywołaniem API embeddingów system sprawdza Redis (klucz = hash treści chunka); trafienie w cache pomija wywołanie API — oszczędność kosztów przy re-indeksacji i duplikatach.
- **NFR-3 Wydajność:** wyszukiwanie wektorowe poniżej 500 ms (indeks HNSW). *Od 2026-09-02 nic nie wykonuje wyszukiwania wektorowego — embeddingi i indeks HNSW są zapisywane i utrzymywane, ale czytelnik pojawi się dopiero z etapem 4. Wymaganie obowiązuje od tego momentu.*
- **NFR-4 Wdrożenie:** cały stack uruchamiany przez `docker-compose up`; CI uruchamia lint i testy przy każdym pushu.
- **NFR-5 Aspekty prawne:** brak scrapingu Indeed/LinkedIn (naruszenie regulaminów); dane pochodzą z ręcznego wprowadzania, z publicznych datasetów (np. zbiory ogłoszeń z Kaggle) albo z odczytu pojedynczej strony ogłoszenia w serwisie z allowlisty — na warunkach opisanych niżej.

> **Zmiana 2026-09-07.** Wymaganie mówiło „brak scrapingu" i pod tym hasłem mieściły się dwie różne rzeczy:
> przeczesywanie serwisu robotem i odczytanie jednej strony, którą użytkownik ma właśnie otwartą. Pierwsze
> nadal jest wykluczone. Drugie dopuszczamy, pod warunkami spisanymi poniżej — bo to jest ta sama czynność
> co „ręczne wprowadzanie", tylko bez przepisywania tekstu ręcznie.
>
> **Co robimy.** Jedno żądanie HTTP na jedną świadomą akcję użytkownika, pod adres, który sam podał.
> Odczytujemy wyłącznie blok `application/ld+json` typu `JobPosting` — dane strukturalne, które serwis
> publikuje celowo, żeby czytały je maszyny (Google Jobs). Nie zdejmujemy treści z HTML-a i nie interesuje
> nas nic poza tą jedną ofertą.
>
> **Czego nie robimy.** Nie crawlujemy: nie ma kolejki adresów, nie chodzimy po linkach, nie czytamy
> sitemap, nie pobieramy nic w tle ani według harmonogramu. Nie sięgamy po wewnętrzne API serwisu.
> Nie omijamy zabezpieczeń i nie podszywamy się pod przeglądarkę — wysyłamy własny User-Agent `JobMate/…`.
>
> **Na czym opieramy zgodę dla justjoin.it** (stan na 2026-09-07): `robots.txt` nie blokuje `/job-offer/`,
> a serwis sam publikuje `sitemaps/active-jobs.xml` i `sitemaps/expired-jobs.xml`, czyli wprost zaprasza
> roboty do indeksowania stron ofert. Blokuje za to `/api/` — dlatego czytamy publiczną stronę, a nie
> `api.justjoin.it`, mimo że API byłoby wygodniejsze.
>
> **Granica.** Lista dozwolonych hostów jest zamknięta i trzymana w konfiguracji (`SCRAPER_ALLOWED_HOSTS`).
> Dopisanie serwisu **nie jest zmianą kodu, tylko decyzją** i wymaga sprawdzenia jego `robots.txt` oraz
> regulaminu; sam fakt, że parser `ld+json` zadziała na dowolnym serwisie z danymi dla Google Jobs, nie jest
> podstawą, żeby po niego sięgać. Ta zgoda przestaje obowiązywać w chwili, gdy: serwis zablokuje ścieżkę
> ogłoszeń w `robots.txt`, jego regulamin zabroni automatycznego odczytu, pobieranie przestanie być
> wywoływane akcją użytkownika, albo zaczniemy obchodzić cokolwiek, co serwis postawił nam na drodze.
> **Indeed i LinkedIn pozostają wykluczone** i nie trafiają na allowlistę.
>
> Limity techniczne odczytu (timeout, rozmiar odpowiedzi, obsługa przekierowań) należą do NFR-1 i są opisane
> w `app/services/scraping.py`; tutaj chodzi o to, czy wolno, a nie jak.

## 5. Model danych (PostgreSQL + pgvector)

**Encje:**

- `users` — konta użytkowników (e-mail, hash hasła)
- `resumes` — wersje CV per użytkownik (surowy tekst, docelowa rola)
- `documents` — ogłoszenia o pracę (od 2026-09-02 baza wiedzy nie zawiera niczego innego, więc nie ma kolumny rozróżniającej rodzaj źródła); deduplikacja po `content_hash`; `metadata JSONB` (rola, seniority) umożliwia filtrowane wyszukiwanie hybrydowe; `requirements JSONB` — wymagania odczytane przez LLM przy zapisie
- `chunks` — fragmenty dokumentów z embeddingami `vector(1536)`; indeks HNSW z metryką kosinusową (Redis pełni rolę cache'a przed API embeddingów; Postgres pozostaje źródłem prawdy)
- `sessions` — sesje przeglądu CV lub mock interview per użytkownik
- `messages` — kolejne wypowiedzi w sesji; przechowuje `retrieved_chunk_ids` do audytu tego, co model faktycznie widział, oraz koszt tokenów
- `matches` — historia dopasowań per użytkownik (migracja `25dc29c14b4b`): score, listy trafień i luk, sugestie, notatki, cytaty z CV oraz `retrieved_chunk_ids`. Migawka, nie widok: kopiuje też tytuł ogłoszenia, a `resume_id` i `document_id` przechodzą w NULL, gdy to, na co wskazują, zostanie usunięte

**Relacje:**
```
users 1—N resumes
users 1—N matches
users 1—N sessions 1—N messages
documents 1—N chunks
sessions N—1 resumes (opcjonalnie)
```

Źródłem prawdy dla schematu jest Alembic (`migrations/versions/`); plik `db/schema.sql` nie istnieje i nie powstanie.

## 6. Architektura wysokopoziomowa

```
[Web UI] → [FastAPI]
              ├── Auth (JWT)
              ├── Serwis ingestion (LangChain) → chunking → Redis cache → API embeddingów → pgvector
              ├── Serwis generacji → API LLM (prompt = ogłoszenie + CV + prompt z Langfuse)
              └── Mock interview (LangGraph) → stanowy graf rozmowy
                        ↓                ↘
                  [PostgreSQL + pgvector]  [Langfuse — trace'y, koszty, ewaluacja]
```

## 7. Roadmapa

| Etap | Zakres | Rezultat |
|---|---|---|
| 1 | Setup projektu: Docker, szkielet FastAPI, Postgres + pgvector, Redis, Langfuse, CI | Działa `docker-compose up` |
| 2 | Pipeline ingestion: chunking, embeddingi, deduplikacja | Dokumenty przeszukiwalne |
| 3 | Retrieval + dopasowanie CV (FR-3) | Pierwsza funkcja RAG end-to-end |
| 4 | Tryb mock interview na LangGraph (FR-4) | Sesje konwersacyjne (graf stanowy) |
| 5 | Eksport + panel admina (FR-5, FR-6) | Gotowe MVP |
| 6 (bonus) | Rozmowy głosowe (speech-to-text), trendy wynagrodzeń | Cele dodatkowe |

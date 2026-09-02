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
- System przyjmuje **wyłącznie ogłoszenia o pracę** (wklejony tekst albo plik PDF / DOCX / TXT).
- Dokumenty są dzielone na chunki (500–1000 tokenów z overlapem), embedowane i zapisywane w bazie.
- Duplikaty są odrzucane na podstawie hasha treści.

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
- Score i brakujące słowa kluczowe liczone są w Pythonie z dwóch list, które da się obejrzeć — liczba pochodząca od modelu nie byłaby powtarzalna ani testowalna.

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
- **NFR-5 Aspekty prawne:** brak scrapingu Indeed/LinkedIn (naruszenie regulaminów); dane pochodzą z ręcznego wprowadzania lub publicznych datasetów (np. zbiory ogłoszeń z Kaggle).

## 5. Model danych (PostgreSQL + pgvector)

**Encje:**

- `users` — konta użytkowników (e-mail, hash hasła)
- `resumes` — wersje CV per użytkownik (surowy tekst, docelowa rola)
- `documents` — ogłoszenia o pracę (od 2026-09-02 baza wiedzy nie zawiera niczego innego, więc nie ma kolumny rozróżniającej rodzaj źródła); deduplikacja po `content_hash`; `metadata JSONB` (rola, seniority) umożliwia filtrowane wyszukiwanie hybrydowe; `requirements JSONB` — wymagania odczytane przez LLM przy zapisie
- `chunks` — fragmenty dokumentów z embeddingami `vector(1536)`; indeks HNSW z metryką kosinusową (Redis pełni rolę cache'a przed API embeddingów; Postgres pozostaje źródłem prawdy)
- `sessions` — sesje przeglądu CV lub mock interview per użytkownik
- `messages` — kolejne wypowiedzi w sesji; przechowuje `retrieved_chunk_ids` do audytu tego, co model faktycznie widział, oraz koszt tokenów

**Relacje:**
```
users 1—N resumes
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

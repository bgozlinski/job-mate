# JobMate — AI Resume & Interview Coach

**Autor:** Bartek Goźliński
**Data:** 05.08.2026
**Status:** v2 — po konsultacji z mentorem

---

## 1. Opis projektu

JobMate to asystent kariery oparty na architekturze RAG (Retrieval-Augmented Generation). System pobiera ogłoszenia o pracę, a następnie pomaga użytkownikowi dopasować CV do docelowej roli i przygotować się do rozmowy rekrutacyjnej. Odpowiedzi są ugruntowane w zapisanych dokumentach i w CV kandydata, a nie generowane swobodnie przez LLM — co ogranicza halucynacje i pozwala zweryfikować sugestie. Od 2026-09-02 baza wiedzy zawiera wyłącznie ogłoszenia (FR-1), więc dopasowanie CV nie korzysta już z wyszukiwania wektorowego, a serwis retrievalu został usunięty. Etap 4 go nie przywraca: pytania na mock interview powstają z wymagań jednego, wybranego ogłoszenia (FR-4, zmiana 2026-09-24).

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
| Frontend | React + TypeScript (Vite) | Klient w przeglądarce; typy generowane z OpenAPI, więc zmiana schematu w Pythonie psuje build, a nie ekran |

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
- Użytkownik wybiera ogłoszenie oraz jedno ze swoich CV. System układa z góry plan pytań z wymagań ogłoszenia
  (`documents.requirements`): najpierw te, których CV nie pokrywa, potem pozostałe; każde pytanie wskazuje
  wymaganie, którego dotyczy.
- Przebieg rozmowy zaimplementowany jako stanowy graf w LangGraph:
  - węzły: `retrieve_questions` (plan z wymagań — nie wyszukiwanie wektorowe) → `ask_question` → `collect_answer` → `evaluate_answer` → (pętla lub `summarize`),
  - stan grafu: ogłoszenie i CV, plan pytań, liczba zadanych pytań, odpowiedzi, oceny cząstkowe,
  - warunek zakończenia: koniec planu lub decyzja użytkownika.
- Tryb konwersacyjny: pytanie → odpowiedź użytkownika → ocena według rubryki z jedną wskazówką. Wynik odpowiedzi
  i podsumowanie sesji liczy Python, nie model.
- Pełna historia sesji jest zapisywana; każde wywołanie LLM trace'owane w Langfuse.

> **Do rozstrzygnięcia przed etapem 4 (2026-09-02) — rozstrzygnięte 2026-09-24, patrz zmiana niżej.**
> Pytania miały pochodzić z wpisów `qa` w bazie wiedzy, a tej kategorii już nie ma (FR-1). Do wyboru:
> wyprowadzać pytania z ogłoszenia i CV, przywrócić osobną kategorię źródeł kolejną migracją, albo trzymać
> zestaw pytań w prompcie. Wybrana została pierwsza droga.

> **Zmiana 2026-09-24. Decyzje etapu 4.** Pełny projekt: `docs/superpowers/specs/2026-09-24-stage4-mock-interview-design.md`.
>
> - **D-1. Sesja jest przywiązana do konkretnego ogłoszenia i CV**, nie do „roli ogólnie". Produkt porównuje
>   CV z ofertą, a pytania mają z czego wynikać — są ugruntowane tak jak sugestie w FR-3. Tryb ogólny
>   wymagałby banku pytań albo swobodnej generacji.
> - **D-2. Plan pytań powstaje z góry**, jednym wywołaniem modelu: luki pierwsze, przycięte do
>   `INTERVIEW_QUESTIONS` (domyślnie 5). Plan to lista — zapisywalna, pokazywalna i testowalna bez modelu.
>   Pytania adaptacyjne i dopytania da się dołożyć później bez przebudowy.
> - **D-3. Odpowiedź ocenia rubryka**: model zwraca werdykt tak/nie z uzasadnieniem dla stałych kryteriów
>   (`on_topic`, `concrete_example`, `consistent_with_resume`) i jedną wskazówkę, a **wynik liczy Python**
>   jako odsetek spełnionych kryteriów. Ten sam powód co w FR-3: liczba od modelu nie jest powtarzalna ani
>   testowalna.
> - **D-4. Źródłem prawdy są nasze tabele** (`sessions`, `messages`); graf wykonuje jedną turę na żądanie
>   i nie dotyka bazy, stan jest odtwarzany z wierszy. Checkpointer LangGraph w Postgresie odrzucony, bo tworzy
>   własne tabele poza Alembikiem (`alembic check` by je zakwestionował) i dublowałby stan; checkpointer
>   w pamięci gubi rozmowy przy każdym restarcie.
> - **D-5. HTTP żądanie–odpowiedź, bez strumieniowania.** Ocena to jedno wywołanie modelu, kilka sekund.
>   Strumieniowanie można dołożyć bez zmiany modelu danych — to unieważnia przewidywanie ze zmiany
>   2026-09-07 w §7, że FR-4 wymusi inny kształt warstwy HTTP.
>
> Konsekwencja dla wyszukiwania: pytania pochodzą z `requirements` jednego ogłoszenia, więc etap 4 **nie
> przywraca** wyszukiwania wektorowego (patrz NFR-3). Chunki ogłoszenia są czytane wprost, a ich ID trafiają
> do `messages.retrieved_chunk_ids`.

### FR-5. Eksport
- Użytkownik może wyeksportować poprawione CV do formatu Markdown / PDF / DOCX.

> **Zmiana 2026-09-23.** „Poprawione CV" to **wersja w `resumes`, którą użytkownik sam przygotował** na
> podstawie sugestii z dopasowania (FR-2 pozwala trzymać wiele wersji, `PATCH` je edytować). Eksport tylko
> konwertuje zapisaną wersję do pliku: nie woła modelu, więc nie może dopisać faktu, którego w CV nie ma
> (ta sama zasada co w FR-3). Odrzucone warianty: składanie CV z wybranych sugestii (CV to surowy tekst
> bez struktury, więc nie ma gdzie ich wstawić) i przepisywanie CV przez LLM (sprzeczne z FR-3, kosztowne,
> nietestowalne bez ewaluacji).
>
> `GET /resumes/{id}/export?format=md|docx|pdf` — Markdown to rola jako nagłówek i tekst CV dosłownie, DOCX
> to akapit na linię. Nazwa pliku to `resume-<id>.<format>`, nigdy tekst od użytkownika, bo ten trafiłby do
> nagłówka `Content-Disposition`.
>
> PDF powstaje w **fpdf2**, nie w WeasyPrint: czysty Python działa bez zmian w obrazie i na Windowsie, na
> którym chodzą testy, a WeasyPrint wymagałby Pango/GTK z systemu. Czcionki wbudowane w PDF znają tylko
> Latin-1, więc w repozytorium leży **PT Sans** (`app/assets/fonts/`, licencja OFL obok) — niezmodyfikowana,
> bo przycięcie większej czcionki pod limit 500 KB hooka byłoby wersją zmodyfikowaną, a zarezerwowana nazwa
> zabrania rozpowszechniania jej pod tą nazwą. Znaki, których czcionka nie ma (głównie emoji), są pomijane
> jawnie, zamiast zostawiać pustą lukę z ostrzeżeniem w logu.

### FR-6. Administracja bazą wiedzy
- Administrator może przeglądać i usuwać źródła.
- Obsługiwana jest re-indeksacja po zmianie modelu embeddingów.

> **Zmiana 2026-09-23.** Usuwanie ogłoszeń: `DELETE /documents/{id}`, tylko dla admina. Uprawnienia nadaje
> skrypt `scripts.grant_admin`, nie endpoint — pierwszego admina i tak nie dałoby się utworzyć przez API,
> a endpoint byłby nową drogą eskalacji uprawnień.
>
> Re-indeksacja to skrypt `scripts.reindex` (z `--dry-run`, który liczy chunki i szacuje tokeny bez
> wydawania pieniędzy), a nie endpoint: przeliczenie całej bazy przekracza czas żądania HTTP, a workera
> do zadań w tle nie ma od usunięcia FR-7. Nieaktualny jest chunk, którego `embedding_model` różni się od
> obecnego **albo jest `NULL`** (`IS DISTINCT FROM`, nie `!=`). Wektory są podmieniane w miejscu — ID chunków
> się nie zmieniają, więc `retrieved_chunk_ids` dalej wskazują na istniejące wiersze — z commitem po każdym
> dokumencie, więc przerwany przebieg można po prostu uruchomić ponownie. Model o innym wymiarze niż
> `vector(1536)` jest odrzucany przed pierwszym wywołaniem API: wymaga migracji schematu, nie re-indeksacji.

> **Zmiana 2026-09-10 (wieczorem). FR-7 usunięte.** Powstał kompletny automat pozyskiwania ofert: projekt
> Scrapy z pająkiem do feedów, tabela `sources`, staging, drenaż do ingestii z FR-1, worker w osobnym
> kontenerze i 80 testów. Wszystko przechodziło; usunięte mimo to.
>
> **Powód.** Automat nie miał czego czytać. NFR-5 wymaga, żeby host trafiał na allowlistę po sprawdzeniu
> jego `robots.txt` i regulaminu, a jedyny host na liście — justjoin.it — **nie publikuje feedu ofert**
> (sprawdzone: `/feed`, `/feed.xml`, `/rss` odpowiadają 404). Publikuje sitemapy, ale te przekierowują
> (307) na `public.justjoin.com`, czyli inną domenę rejestrowalną, której `robots.txt` zwraca 403 — więc
> sprawdzenia wymaganego przez NFR-5 **nie da się na nim wykonać**. Tabela `sources` stała pusta, a kod,
> który nigdy nie zobaczył danych, jest nieprzetestowany w tym jedynym znaczeniu, które się liczy.
>
> **Zanim ktoś napisze to drugi raz:** zacznij od znalezienia źródła, nie od pająka. Ranking względem CV
> — druga połowa tego pomysłu — nie zależy od żadnej decyzji regulaminowej i można go zbudować na
> ogłoszeniach wprowadzanych ręcznie.

## 4. Wymagania niefunkcjonalne

- **NFR-1 Bezpieczeństwo:** uwierzytelnianie JWT; hasła przechowywane jako hashe; użytkownik ma dostęp wyłącznie do własnych danych. Token dociera do API na dwa sposoby: nagłówkiem `Authorization: Bearer` albo ciasteczkiem `httpOnly` — szczegóły niżej.

> **Zmiana 2026-09-07.** Przygotowanie pod klienta w przeglądarce. Do tej pory jedynym klientem był
> Streamlit, który trzyma token po stronie serwera — w przeglądarce token nie lądował nigdy. Aplikacja
> działająca w przeglądarce nie ma takiego schowka: `localStorage` i każda zmienna dostępna z JavaScriptu
> są czytelne dla dowolnego skryptu, który trafi na stronę, więc jeden błąd XSS oddaje konto.
>
> **Co się zmieniło.** `/auth/login` poza tokenem w body ustawia dwa ciasteczka `httpOnly`: krótki `access`
> (`COOKIE_ACCESS_EXPIRE_MINUTES`) i `refresh` (`REFRESH_TOKEN_EXPIRE_DAYS`). `/auth/refresh` odnawia
> pierwsze z drugiego, `/auth/logout` kasuje oba. Uwierzytelnianie przyjmuje nagłówek **albo** ciasteczko,
> z pierwszeństwem nagłówka — Streamlit działa bez zmian.
>
> **Dwa czasy życia dla jednego rodzaju tokenu** wynikają z tego, co klient potrafi: przeglądarka odnawia
> sesję po cichu, klient na Bearerze nie potrafi i przestałby działać. Różnica jest w kliencie, nie w tokenie.
>
> **CSRF** — ciasteczkowa sesja musi na to odpowiedzieć, a odpowiedzią jest `SameSite=Lax`: przeglądarka
> nie dołącza tych ciasteczek do żądania POST zainicjowanego przez obcą stronę, a wszystko, co zmienia stan,
> jest tu POST-em, PATCH-em albo DELETE. **To działa, dopóki strona i API są pod jednym originem** (patrz
> topologia frontendu). Rozdzielenie ich wymaga innej odpowiedzi na CSRF, a nie luźniejszego `SameSite`.
>
> **Refresh token nie jest rotowany.** Rotacja ma sens, gdy serwer pamięta, co wydał — wtedy token użyty
> dwa razy zdradza kopię. Tu nic nie pamięta, więc rotacja kosztowałaby zapis przy każdym odnowieniu i nie
> wykrywałaby niczego, a przy okazji przesuwałaby siedmiodniowy limit w nieskończoność.
>
> **Czego to nie robi, świadomie.** Nie ma listy unieważnionych tokenów, więc: wylogowanie kończy sesję
> **na tym urządzeniu**, a token wydany wcześniej gdzie indziej działa do swojego wygaśnięcia; skradziony
> refresh token jest ważny do końca swoich siedmiu dni. Jedyne, co kończy sesję wcześniej, to usunięcie
> konta — `/auth/refresh` czyta użytkownika z bazy przy każdym odnowieniu właśnie po to. Prawdziwe
> unieważnianie wymaga stanu (Redis albo tabela) i jest osobną decyzją, nie oczywistym brakiem.
>
> Ciasteczka są `Secure` sterowane przez `COOKIE_SECURE`: wymuszone na produkcji, wyłączone lokalnie —
> `Secure` po `http://` powoduje, że przeglądarka po cichu odrzuca ciasteczko, co wygląda jak zepsute logowanie.
- **NFR-2 Kontrola kosztów i observability:** każde wywołanie LLM trace'owane w Langfuse (koszty tokenów, latencja, chunki podane modelowi); rate limiting na endpointach LLM.
- **NFR-2a Cache embeddingów:** przed wywołaniem API embeddingów system sprawdza Redis (klucz = hash treści chunka); trafienie w cache pomija wywołanie API — oszczędność kosztów przy re-indeksacji i duplikatach.
- **NFR-3 Wydajność:** wyszukiwanie wektorowe poniżej 500 ms (indeks HNSW). *Od 2026-09-02 nic nie wykonuje wyszukiwania wektorowego — embeddingi i indeks HNSW są zapisywane i utrzymywane, ale nie mają czytelnika. Etap 4 go nie przywraca (FR-4, zmiana 2026-09-24), a żaden inny etap roadmapy go nie planuje. Wymaganie jest zawieszone do chwili, gdy jakaś funkcja zacznie wyszukiwać.*
- **NFR-4 Wdrożenie:** cały stack uruchamiany przez `docker-compose up` — z klientem w przeglądarce włącznie; CI uruchamia lint i testy przy każdym pushu, w dwóch jobach (Python i Node).

> **Zmiana 2026-09-07.** Doszedł serwis `web`. W trybie deweloperskim jest to serwer Vite proxujący `/api`
> na kontener `api`; wariant produkcyjny (nginx z gotowym buildem) stoi za profilem `prod`, bo `docker
> compose up` ma podnosić środowisko deweloperskie. **Jeden origin dla przeglądarki nie jest wygodą
> deploymentu, tylko decyzją bezpieczeństwa** — od niego zależy, czy sesja w ciasteczkach działa bez CORS-a
> i bez `SameSite=None` (patrz NFR-1). Rozdzielenie strony i API na dwa originy wymaga innej odpowiedzi na
> CSRF, a nie luźniejszej konfiguracji ciasteczek.
>
> CI ma dwa joby, bo dwa toolchainy. Między nimi jest sprawdzenie, którego żaden nie zrobiłby sam:
> job Pythona regeneruje `web/openapi.json` z aplikacji i porównuje z zacommitowanym, job Node'a robi to
> samo dla `web/src/api/schema.d.ts` względem tego dokumentu. Razem **nie da się zmienić modelu Pydantic
> i zostawić frontendu z nieaktualnymi typami** — rozjazd psuje build, zamiast psuć ekran u użytkownika.
- **NFR-5 Aspekty prawne:** brak scrapingu Indeed/LinkedIn (naruszenie regulaminów); dane pochodzą z ręcznego wprowadzania, z publicznych datasetów (np. zbiory ogłoszeń z Kaggle), albo z odczytu pojedynczej strony ogłoszenia w serwisie z allowlisty — na warunkach opisanych niżej.

> **Zmiana 2026-09-10 (wieczorem). Zgoda na crawlowanie wycofana.** Tego samego dnia rozszerzyliśmy NFR-5
> o cykliczne pozyskiwanie ofert, łącznie z chodzeniem po linkach. Kod, dla którego to powstało (FR-7),
> został usunięty, więc **rozszerzenie przestaje obowiązywać w całości**. Obowiązuje stan ze zmiany
> 2026-09-07 opisanej niżej: jedno żądanie HTTP na jedną świadomą akcję użytkownika, bez kolejki, bez
> podążania za linkami, bez sitemap, bez harmonogramu.
>
> Zapisane wprost, bo zgoda regulaminowa, pod którą nic nie działa, jest gorsza niż jej brak: wygląda jak
> upoważnienie i ktoś kiedyś się na nią powoła.

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
- `chunks` — fragmenty dokumentów z embeddingami `vector(1536)`; indeks HNSW z metryką kosinusową (Redis pełni rolę cache'a przed API embeddingów; Postgres pozostaje źródłem prawdy); `embedding_model` — model, który wyliczył wektor (migracja `49572ac20106`), `NULL` dla wierszy starszych niż ta kolumna, czyli „nie wiadomo"
- `sessions` — sesje mock interview per użytkownik (FR-4, zmiana 2026-09-24): `user_id` (`CASCADE`); `resume_id` i `document_id` (`SET NULL` — sesja przeżywa usunięcie CV albo ogłoszenia) oraz kopia tytułu ogłoszenia, jak w `matches`; `status` (`active` / `finished`, ograniczenie `CHECK`, nie natywny enum — §8); `plan JSONB` — lista `{question, requirement}`; `score` i `summary JSONB` ustawiane przy podsumowaniu; `created_at`, `finished_at`
- `messages` — kolejne wypowiedzi w sesji: `position` (`UNIQUE (session_id, position)` — jawna kolejność, bo `created_at` nie rozróżnia wierszy z jednej transakcji, §8); `role` (`interviewer` / `candidate` / `evaluator`, `CHECK`); `content`; `requirement`, którego dotyczy pytanie lub ocena; przy ocenie `verdicts JSONB` i `score` liczony w Pythonie; `retrieved_chunk_ids` — ID chunków ogłoszenia podanych modelowi, do audytu tego, co faktycznie widział; `input_tokens` / `output_tokens` przy wiadomościach wytworzonych przez model. Postęp sesji wynika z danych (liczba odpowiedzi `candidate`), bez osobnego licznika
- `matches` — historia dopasowań per użytkownik (migracja `25dc29c14b4b`): score, listy trafień i luk, sugestie, notatki, cytaty z CV oraz `retrieved_chunk_ids`. Migawka, nie widok: kopiuje też tytuł ogłoszenia, a `resume_id` i `document_id` przechodzą w NULL, gdy to, na co wskazują, zostanie usunięte

**Relacje:**
```
users 1—N resumes
users 1—N matches
users 1—N sessions 1—N messages
documents 1—N chunks
sessions N—1 resumes (opcjonalnie)
sessions N—1 documents (opcjonalnie)
```

Źródłem prawdy dla schematu jest Alembic (`migrations/versions/`); plik `db/schema.sql` nie istnieje i nie powstanie.

## 6. Architektura wysokopoziomowa

```
Przeglądarka                              Testy, curl, Swagger
     │                                          │
     ▼                                          │
[nginx / Vite]                                  │
  /     → statyki React                         │
  /api  → ↓  (jeden origin: ciasteczka          │
             httpOnly bez CORS-a)               │
             │                                  │
             └──────────→ [FastAPI] ←───────────┘
                              │        nagłówek Bearer
                              │
     ├── Auth (JWT: ciasteczko httpOnly albo nagłówek Bearer)
     ├── Serwis ingestion (LangChain) → chunking → Redis cache → API embeddingów → pgvector
     │      źródła: wklejony tekst | plik PDF/DOCX/TXT | URL ogłoszenia (allowlista, NFR-5)
     ├── Serwis generacji → API LLM (prompt = ogłoszenie + CV + prompt z Langfuse)
     └── Mock interview (LangGraph, jedna tura na żądanie) → plan pytań z wymagań ogłoszenia, ocena rubryką
            stan: tabele sessions / messages (bez checkpointera, FR-4 D-4)
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

> **Zmiana 2026-09-07. Etap 4 został świadomie przeskoczony.** Po zamknięciu etapu 3 powstał klient
> w przeglądarce (React), którego nie było ani w roadmapie, ani w tabeli stacku — architektura wysokopoziomowa
> wspominała tylko `[Web UI]`, a `ui/` jest w swoim docstringu opisany jako narzędzie deweloperskie, nie
> produkt.
>
> **Powód.** API pod FR-1, FR-2 i FR-3 jest skończone i stabilne, więc frontend ma na czym stanąć już teraz.
> FR-4 zmienia natomiast kształt interfejsu na tyle mocno — rozmowa ze stanem, pętla pytanie/odpowiedź,
> strumieniowanie — że zbudowanie ekranów przed nim oznaczałoby zbudowanie ich dwa razy. Odwrotna kolejność,
> czyli mock interview przed jakimkolwiek interfejsem, dałaby funkcję, której nie da się użyć bez curla.
>
> **Cena, spisana świadomie.** Klient pokrywa FR-1, FR-2, FR-3 i przeglądanie bazy z FR-6. **Nie ma w nim
> miejsca na FR-4** i nie było próby jego przewidzenia — dorobienie mock interview będzie wymagało nowego
> ekranu i najpewniej innego kształtu warstwy HTTP (strumieniowanie zamiast żądanie-odpowiedź). To jest dług
> zaciągnięty z otwartymi oczami, nie przeoczenie.
>
> **Co dalej.** Kolejność w tabeli obowiązuje nadal; ten wpis jest jednorazowym wyjątkiem, a nie zniesieniem
> zasady. Następny jest etap 5 — patrz zmiana poniżej.

> **Zmiana 2026-09-07 (wieczorem). Etap 4 odłożony na dłużej.** Mock interview nie jest potrzebny do tego,
> żeby produkt działał — dopasowanie CV do oferty stoi samo. To przyjemny dodatek i wraca, gdy reszta
> będzie gotowa.
>
> **Odłożony, nie usunięty.** FR-4 zostaje w wymaganiach, LangGraph zostaje w tabeli stacku, a
> nierozstrzygnięta kwestia zapisana przy FR-4 czeka bez zmian: pytania miały pochodzić z wpisów `qa`,
> a tej kategorii nie ma od 2026-09-02. Do wyboru nadal trzy drogi, i **to jest decyzja do podjęcia przed
> pierwszą linijką kodu**, nie w trakcie.
>
> Kolejnym etapem jest więc **etap 5** (eksport i administracja, FR-5 i FR-6). Z klienta w przeglądarce
> brakuje do niego strony administracyjnej, a `DELETE /documents/{id}` nie istnieje w ogóle.
>
> Klient w przeglądarce nie zastępuje `ui/`. Streamlit zostaje jako narzędzie do ręcznego sprawdzania API —
> nic nie kosztuje, a daje działający punkt odniesienia, gdy React jest w remoncie.

> **Zmiana 2026-09-24. Etap 4 wraca.** Etapy 1–3 i 5 są zamknięte. Decyzja, która miała zapaść przed
> pierwszą linijką kodu, zapadła: pytania powstają z wymagań wybranego ogłoszenia, pod konkretne CV
> (FR-4, decyzje D-1…D-5). Dwie rzeczy przewidywane wyżej się nie sprawdzają: etap 4 nie przywraca
> wyszukiwania wektorowego (NFR-3 pozostaje zawieszone) i nie wymaga strumieniowania (D-5).

> **Zmiana 2026-09-26. Klient Streamlit (`ui/`) usunięty; jedynym frontendem jest React (`web/`).**
> Wpis z 2026-09-07 zostawiał Streamlit jako punkt odniesienia na czas remontu Reacta. Remont się skończył
> (przeprojektowanie w czterech częściach, PR #24–#40), a klient w przeglądarce robi wszystko, co robił Streamlit (konta, CV, ogłoszenia), i dużo więcej, więc
> drugi klient był już tylko kodem do utrzymania, zależnością w locku i osobną grupą w CI.
>
> **Co zostaje.** Uwierzytelnianie nagłówkiem `Authorization: Bearer` zostaje bez zmian — używają go testy,
> Swagger i curl. Do ręcznego sprawdzania API służy teraz `/docs`.
>
> **Otwarta kwestia.** Długi `ACCESS_TOKEN_EXPIRE_MINUTES` (1440) uzasadniał Streamlit, który nie umiał
> odnowić tokenu. Tego klienta już nie ma, ale skrócenie czasu życia tokenu to osobna decyzja pod NFR-1,
> nie część tej zmiany.

> **Zmiana 2026-09-26 (później). `ACCESS_TOKEN_EXPIRE_MINUTES` z 1440 na 60** — zamyka otwartą kwestię
> z wpisu wyżej. Token z odpowiedzi `/auth/login` (nagłówek Bearer) nie ma jak się odnowić, bo
> `/auth/refresh` czyta tylko ciasteczko; po Streamlicie korzystają z niego już tylko testy, Swagger i curl.
> Godzina wystarcza na sesję ręcznego sprawdzania API, a skradziony token traci ważność po godzinie,
> nie po dobie. Nadal jest dłuższy niż ciasteczko (15 min), które przeglądarka odnawia sama — dwa
> ustawienia zostają, bo dwa kanały dalej różnią się tym, czy umieją się odnowić.

> **Zmiana 2026-09-26 (wieczorem). Dashboard jako strona główna.** Poza roadmapą, jak klient w przeglądarce.
> Po zalogowaniu `/` przestaje przekierowywać na listę ogłoszeń i pokazuje jeden następny krok w rekrutacji
> („co dalej”), kilka kolejnych i skrót do ostatniej pracy. Kroki wybiera API (`GET /dashboard`), nie klient,
> bo reguły „ogłoszenie bez dopasowania” i „najlepsze dopasowanie bez rozmowy” są pytaniami o relacje między
> tabelami, a listy w API są stronicowane. Bez migracji i bez wywołań modelu. Projekt i decyzje DB-1…DB-6:
> `docs/superpowers/specs/2026-09-26-dashboard-design.md`.

> **Zmiana 2026-09-26 (noc). Nowa tożsamość wizualna: „Teczka rekrutacyjna”.** Wygląd z redesignu
> (ciepły, beże i teal, Nunito Sans) był według użytkownika generyczny i bez związku z tematem. Nowy kierunek
> bierze charakter z rekrutacji: ogłoszenie jako teczka z zakładką, etapy (Posting, Match, Interview, Applied)
> jako ścieżka, luki jak pieczątka; Public Sans, chłodny papier i granatowy atrament, ton rzeczowy. Zmienia
> decyzje U-1…U-4 z części 1. Jedyna zmiana w API to twój etap i najlepszy wynik przy ogłoszeniu, bo klient ma
> tylko stronicowane listy. Etap „Applied” to osobny, późniejszy projekt (śledzenie wysłanych aplikacji, tabela
> per użytkownik i ogłoszenie). Projekt i decyzje V-1…V-7: `docs/superpowers/specs/2026-09-26-ui-identity-design.md`.

## 8. Pułapki, których nie widać z kodu

Zapis z 2026-09-10, przy czyszczeniu komentarzy z kodu, przycięty wieczorem po usunięciu FR-7. Każdy punkt
niżej był wcześniej komentarzem albo akapitem docstringa i opisuje uproszczenie, które wygląda na oczywiste
i jest błędem. To jedyne miejsce poza historią gita, gdzie ta wiedza istnieje.

**Pobieranie strony z linku (FR-1, NFR-5)**

- `HttpPostingSource` chodzi po przekierowaniach **ręcznie** (`follow_redirects=False`) i waliduje host
  przy **każdym skoku**. httpx sprawdza adres, który dostał, a nie te, na które go potem wysłano —
  dozwolony host odpowiadający `302` na `http://169.254.169.254/` przeszedłby przez allowlistę prosto do
  metadanych chmury.
- Ciało odpowiedzi czytane jest porcjami i porzucane po przekroczeniu limitu, **po dekompresji**. Odczyt
  najpierw, a pomiar potem, czyni limit sugestią, a wrogą odpowiedź — pamięcią kontenera.
- Host dopasowywany jest **dokładnie**, nigdy sufiksem: `justjoin.it.example.com` kończy się dozwolonym
  hostem i należy do kogoś innego.
- Czytamy wyłącznie blok `application/ld+json` typu `JobPosting`, nigdy tekstu z HTML-a — i bierzemy
  **pierwszy** taki węzeł na stronie. Strona z listą kilku ofert da po cichu jedną.

**Migracje**

- Natywny enum PostgreSQL nie znika z `drop_table`. Migracja, która go tworzy, musi go usunąć jawnie,
  inaczej `downgrade` zostawia typ, a kolejny `upgrade` pada na „type already exists". W schemacie nie ma
  dziś żadnego natywnego enuma — ten punkt jest dla tego, kto doda pierwszy.
- `op.create_foreign_key(None, …)` przechodzi (Postgres sam nazwie ograniczenie), ale symetryczne
  `op.drop_constraint(None, …)` nie ma czego usunąć. Klucz obcy dodawany do istniejącej tabeli musi mieć
  nazwę.
- `created_at` ma `server_default=now()`, czyli znacznik **startu transakcji**. Wiersze wstawione w jednej
  transakcji mają identyczny czas i `ORDER BY created_at` ich nie rozróżnia.

**Runtime**

- `ingest_document` commituje sam. Wołający nie dzieli z nim transakcji i nie może liczyć na to, że jego
  własny zapis cofnie się razem z nieudaną ingestią.
- Deduplikacja rozstrzyga się na unikalnym indeksie `content_hash`, nie na `SELECT` przed `INSERT`: dwa
  równoległe żądania z tym samym tekstem przechodzą tamto sprawdzenie, a przegrany łapie `IntegrityError`
  i zwraca dokument zwycięzcy.
- Async psycopg wymaga `SelectorEventLoop` na Windowsie — stąd `pytest_asyncio_loop_factories`
  w `conftest.py`. Sama aplikacja tego nie obchodzi, bo chodzi w Dockerze na Linuksie.
- `jwt.encode` dla `alg="none"` dostaje `key=""`, nie `None`: `NoneAlgorithm.prepare_key` mapuje puste na
  `None` samo, a annotowana sygnatura PyJWT nie ma miejsca na `None`, gdy w środowisku jest `cryptography`.

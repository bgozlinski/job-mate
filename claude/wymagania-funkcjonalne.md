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
| Frontend | React + TypeScript (Vite) | Klient w przeglądarce; typy generowane z OpenAPI, więc zmiana schematu w Pythonie psuje build, a nie ekran |
| Klient deweloperski | Streamlit | Narzędzie do ręcznego dziurawienia API; nie jest częścią produktu |
| Harvester ofert (FR-7) | Scrapy | Obowiązki z NFR-5 — `robots.txt`, throttling, limit na domenę, cache warunkowy, bezpieczniki przebiegu — są konfiguracją frameworka, nie kodem do napisania. Wyłącznie w workerze; reaktor Twisted nie styka się z asyncio API |

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

### FR-7. Automatyczne pozyskiwanie ofert
- Użytkownik definiuje **zapisane wyszukiwanie**: rola, seniority, lokalizacja, słowa kluczowe, wskazane CV
  oraz próg score, powyżej którego oferta ma się pojawić.
- Worker **poza procesem API** cyklicznie odpytuje źródła z allowlisty (warunki w NFR-5) i wprowadza nowe
  ogłoszenia **tą samą ścieżką co FR-1**: `SourceDocument` → chunking → embedding → deduplikacja po
  `content_hash`. Automat nie jest nową ścieżką ingestii, tylko nowym wyzwalaczem istniejącej.
- Dla każdego nowego ogłoszenia i każdego aktywnego zapisanego wyszukiwania system liczy dopasowanie do
  wskazanego CV i zapisuje je w `matches`, oznaczone jako powstałe automatycznie. **FR-3 pozostaje bez
  zmian** — ten sam `match_resume`, ten sam zapis, inna przyczyna wywołania.
- Pełne dopasowanie woła LLM wymaganie po wymaganiu, więc poprzedza je **tani pre-filtr**: filtr po
  `documents.metadata` (rola, seniority) plus podobieństwo wektorowe CV↔ogłoszenie. Do LLM trafia wyłącznie
  top-k. Bez tego kroku koszt automatu rośnie liniowo z rynkiem, a nie z tym, co użytkownika interesuje.
- Użytkownik widzi ranking nowych ofert powyżej progu i wchodzi z niego w pełne dopasowanie z FR-3.
  Widzi wyłącznie własne (NFR-1).
- Każdy przebieg jest widoczny w Langfuse i w panelu admina (FR-6): źródło, liczba pobranych, odrzuconych
  jako duplikat i odrzuconych przez pre-filtr, liczba dopasowań, koszt tokenów.
- **Awaria jednego źródła nie zatrzymuje pozostałych** ani nie blokuje kolejnego przebiegu.

> **Jednostka harmonogramu.** Cykl chodzi **per źródło**, nie per zapisane wyszukiwanie. Ogłoszenia są
> wspólne dla wszystkich użytkowników i deduplikowane globalnie, więc odpytywanie źródła raz na przebieg
> jest jedyną wersją, która nie mnoży ruchu wobec cudzego serwera przez liczbę kont — a ten ruch jest tym,
> za co odpowiadamy w NFR-5. Zapisane wyszukiwanie jest jednostką **filtrowania i scoringu**, nie pobierania.

> **Edycja oferty.** Ogłoszenie o tym samym `(source_id, external_id)`, ale zmienionej treści, tworzy
> **nowy dokument**; poprzedni zostaje. Historyczne wpisy w `matches` dalej wskazują na treść, którą model
> faktycznie widział — ta sama zasada, dla której istnieje `messages.retrieved_chunk_ids`. Ceną jest
> rosnąca baza i to, że ranking musi jawnie pokazywać wyłącznie najnowszą wersję oferty; przycinanie
> starych wersji jest zadaniem administracyjnym (FR-6), nie skutkiem ubocznym pobierania.

> **Decyzja projektowa: Scrapy.** Harvester w FR-7 stoi na Scrapy, mimo że ścieżka URL z FR-1 stoi na httpx.
> Powód: obowiązki, które NFR-5 nakłada na automat — respektowanie `robots.txt`, własny User-Agent, odstęp
> między żądaniami, limit współbieżności na domenę, limit rozmiaru odpowiedzi, cache warunkowy po ETag —
> są w Scrapym **konfiguracją** (`ROBOTSTXT_OBEY`, `USER_AGENT`, `AUTOTHROTTLE_*`,
> `CONCURRENT_REQUESTS_PER_DOMAIN`, `DOWNLOAD_MAXSIZE`, `HTTPCACHE_POLICY`), a nie kodem do napisania
> i przetestowania od zera. Twarde bezpieczniki przebiegu (`CLOSESPIDER_ITEMCOUNT`, `CLOSESPIDER_TIMEOUT`,
> `DEPTH_LIMIT`) też są wbudowane. Przy pełnym crawlowaniu dopuszczonym w NFR-5 to właśnie te ustawienia
> są miejscem, w którym warunki zgody przestają być deklaracją, a stają się egzekwowalne.
>
> **Granica.** Scrapy uruchamia się wyłącznie w procesie workera. FastAPI nigdy nie importuje Scrapy'ego
> ani nie startuje reaktora Twisted — mieszanie reaktora z pętlą asyncio serwera jest wykluczone.
> Przekazanie wyniku do istniejącej ingestii idzie przez **staging** (tabela lub plik), a nie przez zapis
> do async SQLAlchemy z item pipeline'u; osobny krok asyncio zabiera stamtąd dane i wywołuje `ingestion`.
> Dwa runtime'y stykają się na danych, nie na wywołaniach.
>
> `allowed_domains` pająka wywodzi się z `SCRAPER_ALLOWED_HOSTS`, tej samej konfiguracji co ścieżka
> interaktywna — jedna allowlista, dwa konsumenty. `HttpPostingSource` na httpx zostaje nietknięty.

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
- **NFR-2 Kontrola kosztów i observability:** każde wywołanie LLM i retrieval trace'owane w Langfuse (koszty tokenów, latencja, użyte chunki); rate limiting na endpointach LLM.
- **NFR-2a Cache embeddingów:** przed wywołaniem API embeddingów system sprawdza Redis (klucz = hash treści chunka); trafienie w cache pomija wywołanie API — oszczędność kosztów przy re-indeksacji i duplikatach.
- **NFR-3 Wydajność:** wyszukiwanie wektorowe poniżej 500 ms (indeks HNSW). *Od 2026-09-02 nic nie wykonuje wyszukiwania wektorowego — embeddingi i indeks HNSW są zapisywane i utrzymywane, ale czytelnik pojawi się dopiero z etapem 4. Wymaganie obowiązuje od tego momentu.*
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
- **NFR-5 Aspekty prawne:** brak scrapingu Indeed/LinkedIn (naruszenie regulaminów); dane pochodzą z ręcznego wprowadzania, z publicznych datasetów (np. zbiory ogłoszeń z Kaggle), z odczytu pojedynczej strony ogłoszenia w serwisie z allowlisty albo z automatycznego pozyskiwania z serwisów z allowlisty (FR-7) — na warunkach opisanych niżej.

> **Zmiana 2026-09-10.** Wymaganie wykluczało pobieranie „w tle ani według harmonogramu" i przeczesywanie
> serwisu robotem. **Oba zakazy zostają uchylone** na rzecz FR-7. Zdania „nie crawlujemy: nie ma kolejki
> adresów, nie chodzimy po linkach, nie czytamy sitemap, nie pobieramy nic w tle ani według harmonogramu"
> ze zmiany 2026-09-07 **nie obowiązują**; zostają niżej jako zapis stanu, w którym powstała ścieżka URL
> z FR-1, i ta ścieżka nadal działa dokładnie tak, jak tam opisano.
>
> **Dlaczego mimo to nie jest to scraper Indeed.** Poprzednia wersja opierała granicę na jednym zdaniu:
> nie crawlujemy. Po jego uchyleniu granicy nie trzyma już deklaracja, tylko **warunki spisane niżej** —
> i tylko one. Jeśli którykolwiek przestanie być spełniany, zgoda znika razem z nim; nie ma wersji
> „w zasadzie przestrzegamy".
>
> **Co robimy.** Cyklicznie pozyskujemy ogłoszenia ze źródeł z zamkniętej allowlisty, w trzech formach,
> w kolejności pierwszeństwa: (1) udokumentowane publiczne API job boardów i systemów ATS, (2) feedy
> RSS/Atom, (3) crawl stron ogłoszeń — listy ofert i strony pojedynczych ofert — z kolejką adresów
> i podążaniem za linkami. Formy (1) i (2) mają pierwszeństwo zawsze, gdy źródło je udostępnia: crawl jest
> ostatecznością dla serwisów, które nie dają nic innego, a nie domyślnym sposobem pobierania.
>
> **Warunki, na których wolno crawlować.**
> - `robots.txt` jest rozstrzygający i sprawdzany przy każdym przebiegu (`ROBOTSTXT_OBEY`), razem
>   z `Crawl-delay`. Ścieżka zabroniona w `robots.txt` jest zabroniona — bez wyjątków i bez „tylko raz".
> - Jedno żądanie na domenę naraz (`CONCURRENT_REQUESTS_PER_DOMAIN = 1`), z odstępem i AutoThrottle.
>   Nie rozpędzamy się dlatego, że serwer odpowiada szybko.
> - `429` i `Retry-After` są respektowane. Powtarzające się `5xx` wyłączają źródło do czasu decyzji
>   człowieka, a nie uruchamiają ponawiania w pętli.
> - Zasięg ograniczony do ścieżek ogłoszeń: `DEPTH_LIMIT`, twarde bezpieczniki przebiegu
>   (`CLOSESPIDER_ITEMCOUNT`, `CLOSESPIDER_TIMEOUT`) i cache warunkowy (ETag / `If-Modified-Since`),
>   żeby kolejny przebieg nie pobierał ponownie tego, co się nie zmieniło.
> - Własny User-Agent `JobMate/…` z adresem kontaktowym. **Nie podszywamy się pod przeglądarkę.**
>
> **Czego nie robimy.** Nie omijamy niczego, co serwis postawił nam na drodze: ani CAPTCHY, ani wyzwań
> JavaScript, ani limitów, ani logowania — treść za logowaniem jest poza zasięgiem. Nie sięgamy po
> wewnętrzne API serwisu, którego `robots.txt` je blokuje; dotyczy to `api.justjoin.it`. Nie rotujemy
> adresów IP ani User-Agentów. Nie zbieramy danych osobowych rekruterów — pobieramy treść oferty,
> nie profile ludzi.
>
> **Granica.** Host trafia na allowlistę **decyzją, nie kodem** — po przeczytaniu jego regulaminu
> i `robots.txt`; sam fakt, że pająk zadziała, nie jest podstawą. Zgoda dla danego hosta wygasa
> natychmiast, gdy: serwis zablokuje ścieżkę ogłoszeń w `robots.txt`, jego regulamin zabroni
> automatycznego odczytu, serwis poprosi nas o zaprzestanie, albo złamiemy którykolwiek z warunków wyżej.
> **Indeed i LinkedIn pozostają wykluczone i nie trafiają na allowlistę w żadnej z trzech form.**

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

**Encje z FR-7:**

- `sources` — źródło automatu (migracja `d3ef2a2a7af4`): `host`, `kind` (`api` / `feed` / `crawl` — natywny enum `source_kind`), `endpoint`, `poll_interval_seconds`, `watermark`, `last_run_at`, `last_error`, `is_active`. Wyłączenie źródła jest stanem w bazie, nie zmianą kodu — tego wymaga „granica" z NFR-5. Harmonogram jest interwałem, a nie wyrażeniem cron, bo interwał jest tym, co konsumuje pętla workera, i nic w stacku nie parsuje crona
- `documents` — doszły `source_id` (FK → `sources`, `ON DELETE SET NULL`, NULL dla ręcznego wprowadzenia) i `external_id`, plus **nieunikalny** indeks `ix_documents_source_external` (ta sama migracja)
- `staging_postings` — surowe oferty zebrane przez pająka, zanim staną się dokumentami (migracja `ee4d321eaa67`): `source_id` (FK → `sources`, `ON DELETE CASCADE` — staging to praca w toku, nie wiedza), `external_id`, `url`, `title`, `content`, `content_hash`, `state` (`pending` / `ingested` / `failed`, natywny enum `staging_state`), `error`, `fetched_at`. Unikalność na `(source_id, content_hash)`, więc przebieg powtórzony po awarii nie dokłada duplikatów. To jest styk dwóch runtime'ów: pająk pisze tu synchronicznym psycopg, krok asyncio stąd czyta
- `saved_searches` — zapisane wyszukiwanie: `user_id`, `resume_id`, kryteria, próg score, aktywność *(jeszcze nie istnieje)*
- `matches` — dochodzi znacznik pochodzenia (na żądanie / automat) oraz `saved_search_id`, żeby ranking dało się odtworzyć i żeby historia z FR-3 nie zlała się z wynikami automatu *(jeszcze nie istnieje)*

> **Sprostowanie do zapisu z 2026-09-10.** Wcześniej stało tu, że para `(source_id, external_id)` ma mieć
> ograniczenie unikalności „razem z `content_hash`". To było niepotrzebne: `content_hash` jest już unikalny
> w całej tabeli, więc taka trójkolumnowa unikalność nic by nie dodała. Obowiązuje sama intencja tamtego
> zapisu — **para `(source_id, external_id)` nie może być unikalna**, bo edytowana oferta to zgodnie z FR-7
> nowy wiersz z tym samym `external_id`. Indeks nad tą parą służy do *znajdowania* wersji, nie do
> ograniczania ich do jednej; niezmienioną ofertę pobraną dwa razy zatrzymuje `content_hash`.

**Relacje:**
```
users 1—N resumes
users 1—N matches
users 1—N saved_searches
users 1—N sessions 1—N messages
documents 1—N chunks
sources 1—N documents (opcjonalnie — dokument może pochodzić z ręcznego wprowadzenia)
saved_searches 1—N matches (opcjonalnie — dopasowanie może powstać na żądanie)
sessions N—1 resumes (opcjonalnie)
```

Źródłem prawdy dla schematu jest Alembic (`migrations/versions/`); plik `db/schema.sql` nie istnieje i nie powstanie.

## 6. Architektura wysokopoziomowa

```
Przeglądarka                              Klient deweloperski
     │                                          │
     ▼                                          │
[nginx / Vite]                                  │
  /     → statyki React                         │
  /api  → ↓  (jeden origin: ciasteczka          │
             httpOnly bez CORS-a)               │
             │                                  │
             └──────────→ [FastAPI] ←───────────┘
                              │        Streamlit, nagłówek Bearer
                              │
     ├── Auth (JWT: ciasteczko httpOnly albo nagłówek Bearer)
     ├── Serwis ingestion (LangChain) → chunking → Redis cache → API embeddingów → pgvector
     │      źródła: wklejony tekst | plik PDF/DOCX/TXT | URL ogłoszenia (allowlista, NFR-5)
     ├── Serwis generacji → API LLM (prompt = ogłoszenie + CV + prompt z Langfuse)
     └── Mock interview (LangGraph) → stanowy graf rozmowy   [etap 4, jeszcze nie istnieje]
                    ↓                ↘
              [PostgreSQL + pgvector]  [Langfuse — trace'y, koszty, ewaluacja]
                    ▲
                    │  ten sam serwis ingestion, inny wyzwalacz
                    │
     [Worker FR-7]  ─┴─ harmonogram per źródło          [etap 7, jeszcze nie istnieje]
        └── Scrapy (Twisted) → staging → krok asyncio → ingestion → pre-filtr → match_resume
               źródła: publiczne API / feed RSS / crawl stron ofert (allowlista, NFR-5)
```

> Worker jest osobnym procesem. Strzałka do ingestii biegnie przez staging, nie przez wywołanie —
> FastAPI nie importuje Scrapy'ego i nie startuje reaktora Twisted (FR-7).

## 7. Roadmapa

| Etap | Zakres | Rezultat |
|---|---|---|
| 1 | Setup projektu: Docker, szkielet FastAPI, Postgres + pgvector, Redis, Langfuse, CI | Działa `docker-compose up` |
| 2 | Pipeline ingestion: chunking, embeddingi, deduplikacja | Dokumenty przeszukiwalne |
| 3 | Retrieval + dopasowanie CV (FR-3) | Pierwsza funkcja RAG end-to-end |
| 4 | Tryb mock interview na LangGraph (FR-4) | Sesje konwersacyjne (graf stanowy) |
| 5 | Eksport + panel admina (FR-5, FR-6) | Gotowe MVP |
| 6 (bonus) | Rozmowy głosowe (speech-to-text), trendy wynagrodzeń | Cele dodatkowe |
| 7 | Automat pozyskiwania ofert (FR-7): worker, harvester na Scrapy, zapisane wyszukiwania, pre-filtr przed dopasowaniem | Oferty same trafiają do rankingu |

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

## 8. Pułapki, których nie widać z kodu

Zapis z 2026-09-10, przy czyszczeniu komentarzy z kodu. Każdy punkt niżej był wcześniej komentarzem albo
akapitem docstringa. Kod bez nich nadal jest poprawny — ale każdy z nich opisuje uproszczenie, które
wygląda na oczywiste i jest błędem. To jest jedyne miejsce, gdzie ta wiedza teraz istnieje.

**Bezpieczeństwo i sieć**

- `HttpPostingSource` chodzi po przekierowaniach **ręcznie** (`follow_redirects=False`) i waliduje host
  przy **każdym skoku**. httpx sprawdza adres, który dostał, a nie te, na które go potem wysłano —
  dozwolony host odpowiadający `302` na `http://169.254.169.254/` przeszedłby przez allowlistę.
- Ciało odpowiedzi czytane jest porcjami i porzucane po przekroczeniu limitu, **po dekompresji**. Odczyt
  najpierw, a pomiar potem, czyni limit sugestią.
- Host dopasowywany jest **dokładnie**, nigdy sufiksem: `justjoin.it.example.com` kończy się dozwolonym
  hostem i należy do kogoś innego. Dotyczy `HttpPostingSource` i `FeedSpider.check_endpoint`.
- Żądania startowe Scrapy idą z `dont_filter=True`, więc `OffsiteMiddleware` **ich nie filtruje** —
  `allowed_domains` nie chroni endpointu, od którego pająk startuje. Stąd jawna kontrola w `from_crawler`.

**Scrapy i NFR-5**

- `ROBOTSTXT_OBEY` **nie stosuje `Crawl-delay`** — Scrapy dyrektywę parsuje, ale nic jej nie czyta.
  Robi to `PolitenessMiddleware`, trzymając podłogę na `slot.delay`.
- Podłoga musi być **potwierdzana przy każdym żądaniu**: AutoThrottle po każdej odpowiedzi przelicza
  `slot.delay` i ściąga go do `DOWNLOAD_DELAY`, więc ustawiona raz wyparowałaby po kilku odpowiedziach.
- `AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0` jest konieczne: bez tego AutoThrottle celuje we własną
  domyślną współbieżność i rozpędza się ponad `CONCURRENT_REQUESTS_PER_DOMAIN`.
- Domyślne `RETRY_HTTP_CODES` zawiera **429**, a `RetryMiddleware` ponawia bez czytania `Retry-After` —
  czyli odpowiada ruchem na prośbę o zwolnienie. Kod jest z tej listy usunięty celowo.
- `DOWNLOAD_DELAY_JITTER = 0.0`, bo domyślne ±50% zamienia podłogę w średnią.
- DSN **nie może** trafić do ustawień Scrapy: Scrapy loguje nadpisane ustawienia przy starcie, a DSN
  niesie hasło (NFR-1).

**Baza i migracje**

- Natywny enum PostgreSQL nie znika z `drop_table`. Migracja musi go usunąć jawnie, inaczej `downgrade`
  zostawia typ, a kolejny `upgrade` pada na „type already exists". Dotyczy `source_kind` i `staging_state`.
- `op.create_foreign_key(None, …)` przechodzi (Postgres sam nazwie), ale `op.drop_constraint(None, …)`
  nie ma czego usunąć. FK dodawany do istniejącej tabeli musi mieć nazwę.
- `documents.(source_id, external_id)` jest **nieunikalne** i musi takie zostać — patrz sprostowanie w §5.
- `created_at` ma `server_default=now()`, czyli znacznik **startu transakcji**. Wiersze wstawione razem
  mają identyczny czas i `ORDER BY created_at` ich nie rozróżnia.

**Runtime**

- `ingest_document` commituje sam, więc drenaż nie dzieli transakcji z zapisem dokumentu. Bezpieczne, bo
  ponowienie jest bezkosztowne: duplikat rozpoznawany po `content_hash` **przed** wydaniem na embeddingi.
- Item pipeline Scrapy działa pod Twistedem i **nie wolno** w nim dotknąć async SQLAlchemy. Stąd psycopg
  i tabela stagingu jako styk.
- `asyncio.create_subprocess_exec` nie działa na `SelectorEventLoop`, a async psycopg wymaga Selectora na
  Windowsie. Worker używa `subprocess.run` w wątku, żeby nie dyktować wyboru pętli.
- W `to_text` kolejność jest nośna: dekodowanie encji → zamiana końców bloków na nowe linie → usunięcie
  tagów. Odwrotnie eskejpowany HTML z Atoma zostawia dosłowne `<b>` w treści oferty.
- PyJWT z zainstalowanym `cryptography` zawęża typ `key`; dla `alg="none"` przekazuje się `""`, nie `None`.

# Scraper ogłoszeń, sesja w ciasteczkach i klient w przeglądarce

**Data:** 2026-09-07
**Etapy roadmapy:** poza kolejnością — praca po etapie 3, przed etapem 4 (`claude/wymagania-funkcjonalne.md`, sekcja 7)
**Rezultat:** ogłoszenie można dodać podając URL; sesja działa w przeglądarce na ciasteczkach `httpOnly`; istnieje klient React pokrywający FR-1, FR-2, FR-3 i przeglądanie bazy z FR-6.
**Poprzedni dokument:** `2026-08-23-stages-2-3-rag-pipeline.md`

---

## 1. Co zostało zrobione

Trzy PR-y (`#1`, `#2`, `#3`) i jeden commit poza nimi, wszystko na `master` poza wyglądem.

### 1.1 Odczyt ogłoszenia z jego adresu (FR-1, NFR-5)

`POST /documents/from-url` — trzecie wejście do bazy wiedzy obok wklejki i pliku. Poniżej
`_store` nic się nie zmienia, więc chunking, embedding i deduplikacja po `content_hash`
działają bez zmian.

Czytany jest blok `application/ld+json` typu `JobPosting` — dane strukturalne, które serwis
publikuje celowo dla Google Jobs. To nie jest wygoda, tylko jedyny sposób, żeby wziąć **tę
jedną ofertę**: strona ogłoszenia niesie ok. dwudziestu cudzych ofert w sekcji „podobne", a
każda heurystyka „głównej treści" wciąga je razem z właściwą.

Rekonesans przed pisaniem kodu (`justjoin.it`, 2026-09-07):

- `robots.txt` **nie** blokuje `/job-offer/`; serwis publikuje `sitemaps/active-jobs.xml`,
  czyli wprost zaprasza roboty do indeksowania stron ofert.
- `Disallow: /api/` — dlatego czytamy publiczną stronę, mimo że `api.justjoin.it` byłby
  wygodniejszy.
- Strona jest renderowana serwerowo: zwykły `curl` bez przeglądarskiego UA dostaje pełną
  treść. **Playwright niepotrzebny.**

Nie użyto żadnego „scrapera" w potocznym sensie: `httpx` + `html.parser` ze stdliba + `json`.
Scrapy to framework do crawlowania (czyli do tego, czego zabrania NFR-5) i stoi na Twisted,
obok asyncio. BeautifulSoup byłby potrzebny, gdybyśmy celowali selektorami CSS w klasy
`mui-1y6apb5` — wybór `ld+json` usuwa tę potrzebę.

**NFR-5 zmieniono jawnie**, z zapisaną granicą: jeden request na świadomą akcję, brak
crawlowania, uczciwy User-Agent `JobMate/0.1`, zamknięta allowlista, a dodanie hosta wymaga
sprawdzenia jego `robots.txt` — to decyzja człowieka, nie zmiana kodu. Indeed i LinkedIn
pozostają wykluczone.

Allowlista robi jednocześnie robotę przeciw SSRF (NFR-1): adres pochodzi od użytkownika, a
żądanie wychodzi z wnętrza sieci compose, obok Postgresa, Redisa i Langfuse. Przekierowania
są śledzone ręcznie, bo `httpx` sprawdza tylko adres wejściowy; ciało jest porzucane w trakcie
czytania po przekroczeniu limitu.

Zweryfikowane na żywej ofercie: `LinkedIn`, `169.254.169.254`, `langfuse-web:3000`,
`justjoin.it.evil.example.com` i `http://` → 422; prawdziwa oferta → 201; ta sama drugi
raz → 200.

### 1.2 Sesja w ciasteczkach `httpOnly` (NFR-1)

Do tej pory jedynym klientem był Streamlit, który trzyma token po stronie serwera — w
przeglądarce token nie lądował nigdy. Strona w przeglądarce nie ma takiego schowka:
`localStorage` i każda zmienna dostępna z JS są czytelne dla dowolnego skryptu, który trafi
na stronę.

- `/auth/login` poza tokenem w body ustawia `access` (15 min) i `refresh` (7 dni).
- `/auth/refresh` odnawia pierwsze z drugiego; `/auth/logout` kasuje oba.
- `get_current_user` przyjmuje nagłówek **albo** ciasteczko, z pierwszeństwem nagłówka —
  Streamlit i wszystkie istniejące testy nietknięte.

**Claim `typ` w tokenie** jest tu rzeczą, która się cicho psuje. Bez niego access token
przechodzi na `/auth/refresh`, czyli odnawia sesję w nieskończoność, a jego krótkie życie
staje się dekoracją: wszystko działa i nic nie wygasa. Token sprzed claimu jest czytany jako
access, nie odrzucany — dla podpisanego stringa, który ktoś trzyma, nie ma migracji, a
domyślna wartość to słabszy z dwóch rodzajów.

Dwa czasy życia dla jednego rodzaju tokenu wynikają z tego, co potrafi klient: przeglądarka
odnawia po cichu, klient na Bearerze nie potrafi i przestałby działać.

### 1.3 Klient w przeglądarce (React)

`web/` — Vite + React + TypeScript, TanStack Query, React Router, `openapi-fetch`. Ekrany:
logowanie, baza ogłoszeń (trzy sposoby dodania), CV (upload, wklejka, usuwanie), dopasowanie,
historia i pojedynczy zapisany wynik.

**Typy są generowane, a CI pilnuje, że są aktualne.** `web/openapi.json` powstaje z aplikacji
FastAPI (bez uruchamiania serwera, więc działa w CI bez bazy i kluczy), a `schema.d.ts` z
niego. Sprawdzenie jest rozbite na dwa joby, każdy w tym, który ma odpowiedni toolchain: job
Pythona porównuje dokument z aplikacją, job Node'a — typy z dokumentem. Razem nie da się
zmienić modelu Pydantic i zostawić frontendu z nieaktualnymi typami.

**Jeden origin to decyzja bezpieczeństwa, nie wygoda deploymentu.** Serwer Vite (dev) i nginx
(prod) serwują stronę i proxują `/api`, więc przeglądarka widzi jeden adres. Od tego zależy,
czy sesja w ciasteczkach działa bez CORS-a i bez `SameSite=None`; `SameSite=Lax` zastępuje
wtedy token CSRF.

**Cały koszt sesji w `httpOnly` to ~20 linii w `src/api/client.ts`**: żądanie → 401 → odnów →
powtórz raz. Odnowienia są sklejane (strona renderuje kilka paneli, więc wygaśnięcie
objawia się kilkoma 401 naraz), a żądanie jest klonowane przed pierwszą próbą, bo ciało
`Request` można odczytać tylko raz.

### 1.4 Wygląd (Tailwind 4)

Konfiguracja w CSS (`@theme`), bez `tailwind.config.js` i bez PostCSS. Powtarzalne kawałki
wyciągnięte do `src/ui/` (`Button`, `Field`, `Card`, `Chip`, `Meter`, `Alert`, `Status`),
żeby dziewięć komponentów nie zamieniło się w ścianę klas. Renderują te same znaczniki co
wcześniej, więc **40 testów przeszło bez dotknięcia ani jednego** — to był sprawdzian, że
zmienił się wygląd, nie zachowanie.

Wynik dopasowania: hero figure (liczba ≥48px) plus miernik, nie wykres słupkowy z jednym
słupkiem. Miernik ma jeden odcień na każdej wartości — pasek zmieniający się z czerwonego na
zielony byłby kodowaniem diverging i wracałby problem z W-11.

---

## 2. Decyzje projektowe

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Źródło treści ogłoszenia z URL | `ld+json` typu `JobPosting` | Strona niesie ~20 cudzych ofert; blok opisuje dokładnie tę jedną. Klasy CSS są generowane i zmienią się przy najbliższym buildzie, a `ld+json` to kontrakt z wyszukiwarką. |
| Które adresy wolno pobrać | zamknięta allowlista hostów | Jednocześnie zapis, które serwisy sprawdzono pod `robots.txt` (NFR-5), i jedyna szczelna obrona przed SSRF (NFR-1). Blokada adresów prywatnych jest dziurawa (DNS rebinding, IPv6, przekierowania). |
| Śledzenie przekierowań | ręcznie, walidacja hosta na każdym skoku | `httpx` z `follow_redirects=True` sprawdza tylko adres wejściowy; dozwolony host odpowiadający 302 na `169.254.169.254` przeszedłby. |
| Bogatsze dane oferty (seniority, stack) | **nie** parsujemy payloadu RSC | Podwójnie eskejpowany JSON pocięty na chunki z referencjami — parser pęknie przy zmianie wersji Next.js. Zmierzone: `SkillExtractor` odzyskuje z opisu te same terminy (`azure`, `api`, `ui`), które payload trzyma w `requiredSkills`. |
| Rozróżnienie access/refresh | claim `typ` w tokenie, sprawdzany w obie strony | Bez niego access token odnawia sesję bez końca. Token sprzed claimu czytany jako access — nie ma migracji dla podpisanego stringa, a domyślna wartość to słabszy rodzaj. |
| Rotacja refresh tokenu | **brak** | Rotacja wykrywa kopię tylko wtedy, gdy serwer pamięta, co wydał. Tu nic nie pamięta, więc kosztowałaby zapis przy każdym odnowieniu, nie wykrywała niczego i przesuwała siedmiodniowy limit w nieskończoność. |
| `/auth/logout` za uwierzytelnieniem | **nie** | Sesja, którą użytkownik najbardziej chce zakończyć, to ta z już wygasłym access tokenem; logout za bramką odpowiedziałby wtedy 401. |
| Ścieżka ciasteczka refresh | `COOKIE_PATH_PREFIX` + `/auth` | Path jest dopasowywany do adresu w pasku przeglądarki, nie do tego, co widzi FastAPI. Patrz W-7. |
| Topologia frontendu | jeden origin, proxy `/api` | Bez tego ciasteczka wymagają CORS-a z credentials i `SameSite=None`, czyli innej odpowiedzi na CSRF. |
| Typy TypeScript | generowane z OpenAPI, zacommitowane, sprawdzane w CI | Ręcznie pisane rozjeżdżają się po cichu — nic nie mówi, że `DocumentRead` urósł o pole, dopóki ekran nie jest pusty. |
| Stronicowanie list | rosnący `limit` od `offset=0` | Lista przesuwa się pod czytelnikiem (nowy wpis wchodzi na górę), więc `offset` pokazałby wypchnięty wiersz drugi raz. Cena: przepobieranie wierszy już na ekranie — listingi nie zawierają treści. |
| Pokryte/brakujące wymagania | wypełniony vs obrysowany chip + ikona | Zielony/czerwony ma ΔE 4.1 przy deuteranopii. Patrz W-11. |
| Usuwanie CV | dwa kliknięcia, nie `confirm()` | Jedyna nieodwracalna akcja. `window.confirm` nie jest zaimplementowany w jsdom, więc zabezpieczenie na nim byłoby niepokrywalne testem. |
| Przełącznik trybu ciemnego | **brak**, `prefers-color-scheme` | Przełącznik to stan do zapisania i kolejny ekran ustawień; system już wie, czego chce użytkownik. |
| TypeScript w `web/` | przypięty do 5.x | TS 7 jest wydany, ale `typescript-eslint` ma peer range `<6.1`. Reguły type-aware (np. niezaczekany promise) są tu warte więcej niż najnowszy kompilator. |

---

## 3. Wykryte wady

Numeracja kontynuuje `2026-08-23-stages-2-3-rag-pipeline.md` (tam W-1…W-6).

### W-7. Ścieżka ciasteczka refresh nie pasuje za proxy (zamknięte 2026-09-07)

Ciasteczko `refresh` było zapisywane z `Path=/auth`, a przeglądarka woła `/api/auth/refresh`.
`/api/auth/...` nie zaczyna się od `/auth`, więc **przeglądarka nigdy by go nie odesłała** —
każde odnowienie sesji kończyłoby się 401, nie do odróżnienia od wygaśnięcia. Nic by się nie
wysypało; nikt po prostu nie utrzymałby sesji dłużej niż 15 minut.

Niewykrywalne w etapie A: pojawia się dopiero, gdy strona i API są za wspólnym proxy.
Naprawa: `COOKIE_PATH_PREFIX` w `Settings`, puste domyślnie (Streamlit i testy nietknięte),
`/api` dla kontenera `api` w compose. **Musi zgadzać się z prefiksem zdejmowanym przez proxy;
nic tego nie sprawdza automatycznie.**

### W-8. `required` na `input[type=file]` blokuje submit w jsdom (obejście)

`userEvent.upload` ustawia pliki tak, że walidacja jsdom ich nie widzi, więc formularz **po
cichu nigdy się nie wysyła** i ścieżka uploadu jest niepokrywalna testem. Potwierdzone
osobną sondą. Atrybut usunięty — przycisk jest wyłączony bez pliku, a `onSubmit` wychodzi
wcześniej, więc nic nie gwarantował.

### W-9. `FormData.set()` bez nazwy gubi nazwę pliku (zamknięte 2026-09-07)

Bez trzeciego argumentu część multipart dostaje `filename="blob"`. API zapisuje nazwę pliku
jako **tytuł dokumentu** (`basename()` w `uploads.py`) i jako `resumes.original_filename` —
cała baza zapełniłaby się wpisami „blob". Naprawa: `form.set('file', file, file.name)`.

### W-10. `queryClient.clear()` w `onSettled` zabija własną mutację (zamknięte 2026-09-07)

`clear()` czyści też cache mutacji, w tym tej, w której trakcie jest wywoływany — kolejne
`setQueryData` już się nie wykonuje. Objaw: po wylogowaniu zostaje powłoka „Signed in as "
bez adresu. Zamienione na `setQueryData` + `removeQueries` z predykatem.

### W-11. Zielony/czerwony jest nieczytelny przy deuteranopii (zamknięte 2026-09-07)

Walidator palety: `#d03b3b` ↔ `#0ca30c` ma **ΔE 4.1** przy deuteranopii — dla ok. 6% mężczyzn
to ten sam kolor. Chipy „pokryte/brakujące" niosą różnicę na czterech kanałach: wypełnienie
vs przerywany obrys, ikona ✓/✗, osobna kolumna z nagłówkiem, i słowo. Żaden nie jest barwą.

### W-12. Kontrast przycisku w trybie ciemnym 2,50:1 (zamknięte 2026-09-07)

Biały tekst na jasnym akcencie `#6da7ec`. WCAG AA wymaga 4,5:1. Naprawione tokenem
`--color-on-accent` (ciemny atrament na jasnym akcencie: 6,96:1). Przy okazji szary tekst
podpisów miał 3,65:1 — przesunięty na `#6f6d65` (5,05:1) i `#9a978e` (5,96:1).
**Wykryte pomiarem, nie okiem** — na zrzucie „wyglądało spoko".

### W-13. Nazwany wolumen `node_modules` nie aktualizuje się przy `--build`

Docker zasiewa nazwany wolumen zawartością obrazu **tylko gdy jest pusty**. Po dodaniu
zależności `docker compose up --build` nic nie zmienia, a Vite zgłasza `Failed to resolve
import` dla pakietu, który na hoście jest zainstalowany. Obejście: kontener robi
`npm install` przed `npm run dev`. Tanie, gdy drzewo już się zgadza.

---

## 4. Czego świadomie nie zrobiono

- **Brak listy unieważnionych tokenów.** Konsekwencje spisane przy NFR-1 w specyfikacji:
  wylogowanie kończy sesję **na tym urządzeniu**, a skradziony refresh token żyje
  swoje siedem dni. Jedyne, co kończy sesję wcześniej, to usunięcie konta — `/auth/refresh`
  czyta użytkownika z bazy przy każdym odnowieniu właśnie po to. Prawdziwe unieważnianie
  wymaga stanu (Redis albo tabela) i jest osobną decyzją, nie oczywistym brakiem.
- **Pole `metadata` w formularzach klienta React.** Streamlit je ma, bo jest narzędziem
  deweloperskim. Nic nie filtruje po `documents.metadata` od usunięcia retrievalu w etapie 3,
  więc w kliencie produktowym byłoby kontrolką, która nic nie robi.
- **Bogatsze dane z payloadu RSC** (seniority, tryb pracy, chipy stacku) — patrz sekcja 2.
- **Rotacja refresh tokenu** — patrz sekcja 2.
- **`PATCH /resumes/{id}`** nie jest wystawiony w kliencie; Streamlit też go nie ma.
- **Motyw jasny nie został obejrzany w przeglądarce.** Kontrasty policzone i przechodzą,
  ale render widziałem wyłącznie w trybie ciemnym (taki jest system). Próba podmiany
  zapytania medialnego nie zadziałała — Vite serwował CSS z cache'u.
- **Testy `AnthropicSuggestionWriter` / `OpenAIEmbeddingModel`** przeciwko prawdziwym API —
  bez zmian względem poprzedniego dokumentu.

---

## 5. Co dalej

### Etap 4 — mock interview na LangGraph (FR-4): **odłożony** (decyzja 2026-09-07)

Nie jest to funkcja potrzebna do działania produktu, tylko przyjemny dodatek — wraca, gdy
reszta będzie gotowa. **Odłożony, nie usunięty:** FR-4 zostaje w specyfikacji, LangGraph
zostaje w tabeli stacku.

Nierozstrzygnięta kwestia czeka bez zmian: pytania miały pochodzić z wpisów `qa` w bazie
wiedzy, a ta kategoria została usunięta 2026-09-02. Do wyboru: wyprowadzać pytania z
ogłoszenia i CV, przywrócić osobną kategorię źródeł migracją, albo trzymać zestaw pytań w
prompcie. **To decyzja do podjęcia przed pierwszą linijką kodu**, nie w trakcie.

Klient React nie ma miejsca na FR-4 i nie było próby jego przewidzenia — dorobienie go będzie
wymagało nowego ekranu i najpewniej innego kształtu warstwy HTTP (strumieniowanie zamiast
żądanie-odpowiedź). To dług zaciągnięty z otwartymi oczami.

### Etap 5 — eksport i administracja (FR-5, FR-6)

Najbliższa rzecz do zrobienia. Z klienta React brakuje strony administracyjnej i usuwania
dokumentów; `GET /documents` jest, `DELETE` nie istnieje.

### Backlog jakości

- Motyw jasny do obejrzenia w przeglądarce (sekcja 4).
- `origin/feat/cookie-auth` i `origin/feat/web-client` wiszą po merge'ach — do skasowania.
- `examples/credentials.json` trzyma parę e-mail + hasło w pliku wyglądającym na
  konfigurację. Nic realnego nie wycieka (`manual-test@example.com` / to samo hasło co w
  testach), ale nazwa `credentials.example.json` zdjęłaby przyszły fałszywy alarm skanera
  sekretów.
- `tests/test_documents.py:1` importuje `httpx2` zamiast `httpx`. Działa (pakiet jest w
  venv), ale to niemal na pewno literówka.
- Job `web` w CI nie ma cache'a dla `node_modules` poza `actions/setup-node` — przy większym
  drzewie zależności warto sprawdzić czas.

---

## 6. Stan weryfikacji

- **396 testów Pythona** i **40 testów frontendu** przechodzi; `ruff check .`,
  `ruff format --check .`, `mypy --strict`, `bandit -r app`, `eslint`, `tsc -b` czyste.
- CI zielone na obu jobach (`quality`, `web`) dla PR-ów `#2` i `#3`.
- Regeneracja `web/openapi.json` i `web/src/api/schema.d.ts` nie daje różnicy — check
  świeżości ma sens i nie jest fałszywie czerwony.
- **Żaden test nie wchodzi do sieci**: `PostingSource` jest protokołem z fake'em wstawianym
  przez fiksturę `client`, testy fetchera odpowiadają przez `MockTransport`, a frontend
  przez MSW z `onUnhandledRequest: 'error'`.
- Ręcznie przez proxy na `:5173`, na prawdziwych modelach: rejestracja → logowanie →
  `/auth/me` → `/auth/refresh` → `/auth/logout` → 401; ingestia prawdziwej oferty
  justjoin.it (201, deduplikacja 200); upload pliku z nazwą trafiającą do tytułu; izolacja
  CV między kontami (404, nie 403); dopasowanie 50% z ośmioma pokrytymi wymaganiami i
  cytatami, których model użył jako uzasadnienia.
- Wariant produkcyjny (`--profile prod`, nginx) zbudowany i uruchomiony: fallback SPA,
  proxy `/api`, nagłówki cache assetów.

### Pułapki, na które warto uważać przy powrocie

1. **`| tail` maskuje kod wyjścia.** `git checkout master | tail -1 && git merge --ff-only`
   przesunęło niewłaściwą gałąź, bo `tail` zwrócił 0 mimo nieudanego checkoutu. Nie
   przepuszczać przez potok poleceń, których wynik warunkuje następne.
2. **Pliki generowane bywają „zmodyfikowane" samymi zakończeniami linii.** `git diff` nie
   pokazuje wtedy nic, a `git checkout` odmawia przełączenia gałęzi.
3. **`ruff` i `bandit` nie czytają swoich komentarzy nawzajem.** Literał wymaga
   `# noqa: S105  # nosec B105` — samo `noqa` przepuszcza ruffa i wywala commit na bandicie.
4. **Klient httpx w testach trzyma słoik ciasteczek.** Po zalogowaniu pominięcie nagłówka
   `Authorization` **nie** czyni żądania anonimowym — trzeba `client.cookies.clear()`.
   Dotknęło to `test_matching_requires_a_token`, które zaczęło przechodzić z 200.
5. **jsdom i undici mają różne klasy `File`.** `request.formData()` w handlerze MSW wywala
   się na własnym ciele; ciało trzeba czytać jako tekst. Dotyczy wyłącznie środowiska
   testowego.
6. **Select renderuje się przed danymi.** `findByLabelText` znajduje kontrolkę, gdy lista
   jest jeszcze w locie — czekać na **opcję**, nie na kontrolkę.
7. **Tailwind 4 nie ma `tailwind.config.js`.** Konfiguracja jest w CSS (`@theme`), bez
   PostCSS. Szukanie pliku konfiguracyjnego to strata czasu.

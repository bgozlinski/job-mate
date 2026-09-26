# Dashboard — strona główna „co dalej”

**Data:** 2026-09-26
**Zakres:** nowy endpoint `GET /dashboard` oraz strona `/` w `web/`
**Rezultat:** po zalogowaniu użytkownik widzi jeden następny krok w swojej rekrutacji, kilka kolejnych i skrót do
ostatniej pracy
**Status:** projekt zatwierdzony w rozmowie 2026-09-26; kod jeszcze nie istnieje

---

## 1. Cel i kontekst

Dziś `/` przekierowuje na `/documents`, więc po zalogowaniu użytkownik ląduje na liście ogłoszeń i sam musi
ustalić, od czego zacząć: czy ma CV, które ogłoszenia już dopasował, czy została mu niedokończona rozmowa.

**Odbiorca:** osoba aktywnie szukająca pracy, wracająca do aplikacji w trakcie rekrutacji.
**Zadanie strony:** w pierwszej sekundzie odpowiedzieć na pytanie „co mam teraz zrobić?”. Statystyki postępów
(liczby, średnie, trendy) są świadomie poza zakresem — nie mówią, co zrobić.

## 2. Decyzje

| # | Pytanie | Decyzja | Odrzucone | Dlaczego |
|---|---|---|---|---|
| DB-1 | Po co jest strona | **„Co dalej”**: jeden wyróżniony następny krok | przegląd postępów (kafelki z liczbami); sam skrót do ostatniej pracy | Użytkownikowi brakuje wskazania, od czego zacząć, nie liczb. Skrót do ostatniej pracy zostaje jako trzecia, cicha sekcja. |
| DB-2 | Kolejność reguł | **Brak CV → brak ogłoszeń → niedokończona rozmowa → ogłoszenie bez dopasowania → dopasowanie bez rozmowy → wszystko zrobione** | nowe ogłoszenie przed niedokończoną rozmową | Najpierw kończy się to, co zaczęte. Dwie pierwsze reguły blokują resztę, bo bez CV albo ogłoszeń nic innego nie działa. |
| DB-3 | Które dopasowanie bez rozmowy | **Najwyższy wynik** (najlepszy na ogłoszenie) | najnowsze | Najlepsza szansa na rozmowę jest tam, gdzie CV pasuje najbardziej. |
| DB-4 | Gdzie liczyć kroki | **W API**, `GET /dashboard` | tylko w kliencie; hybryda (filtr `unmatched` + `answered` w `SessionSummary`) | Reguły 4 i 5 to pytania o relacje między tabelami. Listy w API są stronicowane (maks. 100), więc klient przy większej liczbie danych po cichu dałby zły krok. W Pythonie reguły są testowane w pytest i zgodne z zasadą projektu, że decyduje Python, a nie interfejs. |
| DB-5 | Akcje na dashboardzie | **Match i Start interview działają od razu** (istniejące mutacje); reszta to linki | każda akcja jako link do strony ogłoszenia | Jeden klik zamiast dwóch; logika wywołań modelu nie jest powielana, bo używa `useMatch` i `useStartInterview`. |
| DB-6 | Nawigacja | **Zakładka Home na pierwszej pozycji**, logo linkiem do `/` | samo logo jako link | Samo logo jest mało widoczne jako droga powrotu. |

## 3. API: `GET /dashboard`

**Odpowiedź:** `Dashboard { steps: list[Step] }`, lista uporządkowana i **nigdy pusta**. `Step` to unia
rozróżniana polem `kind` (w OpenAPI `oneOf` z `discriminator`, w TS unia zawężana po `kind`).

| `kind` | pola | kiedy |
|---|---|---|
| `add_resume` | — | użytkownik nie ma żadnego CV |
| `add_posting` | — | baza ogłoszeń jest pusta |
| `continue_interview` | `session_id`, `document_id`, `document_title`, `answered`, `question_count` | rozmowa użytkownika ze `status = "active"`, której ogłoszenie istnieje |
| `match` | `document_id`, `document_title`, `resume_id` | ogłoszenie bez żadnego dopasowania użytkownika (do dowolnego jego CV); `resume_id` to jego najnowsze CV („main resume”, jak `newest()` w kliencie) |
| `practise` | `document_id`, `document_title`, `resume_id`, `score` | dopasowanie użytkownika z istniejącym ogłoszeniem i CV, bez żadnej jego rozmowy o tym ogłoszeniu |
| `add_another_posting` | — | żadna inna reguła nie pasuje |

**Budowanie listy:**

1. Jeśli pasuje `add_resume` lub `add_posting`, lista zawiera **tylko** te kroki (w tej kolejności).
2. W przeciwnym razie: `continue_interview` (najnowsze najpierw), potem `match` (najnowsze ogłoszenia najpierw),
   potem `practise` (malejąco po wyniku; przy kilku dopasowaniach do jednego ogłoszenia liczy się najlepsze —
   `DISTINCT ON (document_id) … ORDER BY document_id, score DESC`).
3. Najwyżej **3 kroki każdego rodzaju** (stała w module), żeby „Other things to do” nie stało się drugą listą
   ogłoszeń.
4. Jeśli po krokach 1–3 lista jest pusta, zwracana jest `[add_another_posting]`.

**`answered`** to liczba wiadomości z `role = "candidate"` w sesji — postęp liczony z wiadomości, nie z licznika,
jak w FR-4.

**Usunięte ogłoszenia i CV:** dopasowania i rozmowy są migawkami, a ich klucze obce przechodzą na NULL po
usunięciu. Wiersz z `document_id IS NULL` nie daje żadnego kroku; `practise` wymaga też `resume_id IS NOT NULL`,
bo bez CV nie da się zacząć rozmowy.

**Pliki:**

- `app/schemas/dashboard.py` — schematy kroków i odpowiedzi.
- `app/services/dashboard.py` — `next_steps(db, user_id) -> list[Step]`, jedno zapytanie na regułę.
- `app/api/dashboard.py` — cienki router z `CurrentUser`; bez rate limitu, bo nie woła modelu. Rejestracja
  w `app/main.py`.

Bez migracji i bez wywołań modelu.

**Bezpieczeństwo (NFR-1):** każde zapytanie o dopasowania, rozmowy i CV filtruje po `user_id`. Ogłoszenia są
wspólną bazą, ale „bez dopasowania” oznacza „bez dopasowania **tego** użytkownika”.

## 4. Frontend

**Trasy i nawigacja:**

- `App.tsx`: pod `/` zamiast `<Navigate to="/documents">` jest `<Dashboard />`. `Login` już przekierowuje na `/`.
- `Layout.tsx`: zakładka **Home** (`HouseIcon`) na pierwszej pozycji; logo „JobMate” staje się linkiem do `/`.
  Aktywność tej zakładki to **wyłącznie** `pathname === '/'` — warunek `startsWith` pasowałby do każdej strony.

**Pliki:** `web/src/api/dashboard.ts` (`useDashboard()`, klucz `['dashboard']`), `web/src/routes/Dashboard.tsx`,
`web/src/routes/Dashboard.test.tsx`; zregenerowane `web/openapi.json` i `web/src/api/schema.d.ts`
(`npm run gen`).

**Treść kroków:**

| `kind` | zdanie | szczegół | akcja |
|---|---|---|---|
| `add_resume` | Add your resume | Matching and interviews start from it. | link **Add resume** → `/resumes` |
| `add_posting` | Add a job posting | — | link **Add posting** → `/documents` |
| `continue_interview` | Finish your interview for {title} | {answered} of {question_count} questions answered. | link **Continue** → `/interviews/:id` |
| `match` | See how your resume fits {title} | — | przycisk **Match** → po wyniku `/matches/:id` |
| `practise` | Practise for {title} | Your resume matched {score}%. | przycisk **Start interview** (z `resume_id` kroku) → `/interviews/:id` |
| `add_another_posting` | You're up to date | Add another posting to keep going. | link **Add posting** → `/documents` |

**Układ** (wyrównany do lewej, szerokość jak w `Layout`, na telefonie jedna kolumna):

```
┌──────────────────────────────────────────────────────────┐
│ Practise for Senior Python Developer at Acme             │  Next: zdanie jako nagłówek,
│ Your resume matched 72%.                                 │  lewy pasek w accent,
│ [Start interview]                                        │  jedyny przycisk główny
├──────────────────────────────────────────────────────────┤
│ Other things to do                                       │  pozostałe kroki jako wiersze
│ See how your resume fits Backend Engineer    [Match]     │  na raised, przyciski
│ See how your resume fits Data Engineer       [Match]     │  drugorzędne
├──────────────────────────────────────────────────────────┤
│ Recently                               See all history   │  do 5 ostatnich dopasowań
│ Match 72%, Acme, yesterday                               │  i rozmów, po dacie
└──────────────────────────────────────────────────────────┘
```

1. **Next** — pierwszy krok. Zdanie `text-[1.75rem]` extrabold, lewy pasek `accent`, jedyny przycisk w wariancie
   głównym na stronie.
2. **Other things to do** — pozostałe kroki; sekcja znika, gdy ich nie ma.
3. **Recently** — do 5 ostatnich dopasowań i rozmów z istniejących `useMatches` / `useInterviews`, połączonych i
   posortowanych po dacie, z linkiem „See all history” → `/history`. Znika dla konta bez historii.

**Wygląd:** wyłącznie istniejące tokeny (`surface`, `raised`, `ink`, `ink-soft`, `accent`, `accent-soft`) i
Nunito Sans, więc nie ma nowych kontrastów do mierzenia. Zdanie zamiast liczby: liczba jest szczegółem w zdaniu,
nie kafelkiem. Bez animacji, bez siatki identycznych kart.

**Stany (istniejący słownik):** `Skeleton` podczas ładowania; `Alert` z `onRetry` przy nieudanym odczycie;
`Thinking` podczas dopasowania albo startu rozmowy; `Alert` przy nieudanej akcji. `EmptyState` nie jest potrzebny,
bo API nigdy nie zwraca pustej listy.

**Świeżość danych:** każda mutacja, która zmienia CV, ogłoszenia, dopasowania albo rozmowy, unieważnia
`['dashboard']` — także odpowiedź i zakończenie rozmowy, bo zmieniają `answered` i `status`. Miejsca, które dziś
unieważniają listy: `useResumeMutation` i `useDeleteResume` (`api/resumes.ts`), dodawanie i usuwanie ogłoszeń
(`api/documents.ts`), `useMatch` (`api/matching.ts`), `remember` (`api/interview.ts`).

## 5. Testy

**pytest** (`tests/test_dashboard.py`):

- każda reguła osobno daje swój krok z właściwymi polami;
- blokady: bez CV albo bez ogłoszeń lista zawiera tylko `add_resume` / `add_posting`;
- kolejność rodzajów i limit 3 na rodzaj;
- `practise`: najlepszy wynik na ogłoszenie, sortowanie malejąco;
- `match` zawiera najnowsze CV użytkownika;
- `continue_interview`: `answered` liczy tylko odpowiedzi kandydata;
- usunięte ogłoszenie albo CV (FK = NULL) nie daje kroku;
- izolacja (NFR-1): dopasowania i rozmowy innego użytkownika nie zmieniają kroków;
- `add_another_posting`, gdy wszystko zrobione;
- 401 bez uwierzytelnienia.

**vitest + msw** (`Dashboard.test.tsx`, `App.test.tsx`):

- każdy `kind` rysuje swoje zdanie i akcję;
- `Skeleton`, potem treść; błąd odczytu z „Try again”;
- „Start interview” wysyła `resume_id` i `document_id` z kroku i przechodzi do rozmowy;
- „Other things to do” i „Recently” znikają, gdy są puste;
- zakładka Home aktywna tylko na `/`;
- testy w `App.test.tsx`, które zakładają, że `/` pokazuje ogłoszenia, poprawione.

Elementy wyszukiwane po roli i etykiecie.

## 6. Poza zakresem

- Statystyki postępów (liczby, średnie wyniki, trendy).
- Powiadomienia i przypomnienia.
- Wybór CV na dashboardzie — `match` używa najnowszego, `practise` tego z dopasowania.
- Zmiany w bazie danych.

## 7. Kolejność prac

1. API: schematy, serwis `next_steps` z testami reguł, router, rejestracja; `npm run gen`.
2. Klient: `useDashboard` i unieważnianie `['dashboard']` w istniejących mutacjach.
3. Strona `Dashboard` (Next, Other things to do, Recently, stany) z testami.
4. Trasa `/`, zakładka Home, logo jako link; poprawione `App.test.tsx`.
5. Zapis w `CLAUDE.md` (stan projektu, układ `web/`).

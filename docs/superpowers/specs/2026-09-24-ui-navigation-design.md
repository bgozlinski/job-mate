# Frontend, część 2 — nawigacja i przepływ

**Data:** 2026-09-24
**Zakres:** `web/` oraz trzy małe rozszerzenia API (sekcja 5)
**Rezultat:** aplikacja zbudowana wokół ogłoszenia — trzy miejsca w nawigacji, strona ogłoszenia z akcjami
„dopasuj” i „przećwicz rozmowę”, wspólna historia dopasowań i rozmów
**Poprzedni dokument:** `2026-09-24-ui-foundation-design.md` (część 1)
**Status:** projekt zatwierdzony w rozmowie 2026-09-24; kod jeszcze nie istnieje

---

## 1. Cel i kontekst

Część 2 z czterech (podział w dokumencie części 1). Celem jest wygoda codziennego użycia: mniej skakania między
zakładkami i mniej ponownego wybierania tego samego.

**Jak wygląda typowa sesja użytkownika:** wokół ogłoszenia — znajduje ofertę, dodaje ją, dopasowuje do niej CV,
ćwiczy rozmowę pod nią. Ma **jedno główne CV**.

**Stan wyjściowy:** pięć zakładek (Job postings, Resumes, Match, History, Interview), nagłówek łamiący się na dwie
linie na szerokości laptopa. Ekrany są od siebie odizolowane: przy ogłoszeniu nie ma przejścia do dopasowania ani
rozmowy (trzeba zmienić zakładkę i wybrać parę od nowa), wynik dopasowania nie prowadzi do rozmowy, historia rozmów
jest dostępna tylko przez link na stronie „Interview”, a ogłoszenie nie ma własnej strony.

## 2. Decyzje

| # | Pytanie | Decyzja | Odrzucone | Dlaczego |
|---|---|---|---|---|
| N-1 | Główne miejsca w nawigacji | **Trzy: Postings, Resumes, History** | cztery (osobne Matches i Interviews); obecne pięć + skróty | Praca kręci się wokół ogłoszenia, więc dopasowanie i rozmowa są akcjami na nim, nie miejscami. Trzy pozycje mieszczą się w jednej linii nagłówka. |
| N-2 | Układ strony ogłoszenia | **Dwie kolumny**: ogłoszenie i wymagania po lewej, twoje dopasowania i rozmowy po prawej | jedna kolumna z zakładkami | Wszystko widać naraz, bez klikania. |
| N-3 | Gdzie wynik dopasowania | **Pełna strona wyniku** (`/matches/:id`) z powrotem do ogłoszenia | wynik rozwijany w prawej kolumnie | Wynik ma dużo treści (wymagania, cytaty, sugestie, notatki); w wąskiej kolumnie byłby ciasny. |
| N-4 | Które CV | **Najnowsze CV domyślnie**, z możliwością zmiany przy przyciskach | wybór CV przy każdej akcji | Użytkownik ma jedno główne CV; obowiązkowy wybór byłby zbędnym krokiem. |
| N-5 | Dane, których API nie daje | **Małe rozszerzenie API** (sekcja 5) | obejście tylko we froncie | Bez niego strona ogłoszenia nie pokaże treści ani wymagań, a dopasowania i rozmowy trzeba by filtrować w przeglądarce z ostatnich 100, gubiąc starsze. |

## 3. Struktura i trasy

**Nagłówek:** logo, **Postings**, **Resumes**, **History**; po prawej przełącznik motywu, adres e-mail (chowany na
wąskim ekranie) i „Log out”. Jedna linia na szerokości laptopa.

| Adres | Co jest | Zmiana |
|---|---|---|
| `/documents` | lista ogłoszeń + dodawanie | kafelek ogłoszenia staje się linkiem do jego strony; po dodaniu ogłoszenia przejście na jego stronę |
| `/documents/:id` | **strona ogłoszenia** | nowa |
| `/resumes` | CV | bez zmian |
| `/history` | dopasowania i rozmowy na jednej osi czasu | nowa, zastępuje `/matches` i `/interviews` |
| `/matches/:id` | wynik dopasowania | link wstecz do ogłoszenia; przycisk „Practise interview” |
| `/interviews/:id` | rozmowa | link wstecz do ogłoszenia |
| `/match`, `/interview` | strony wyboru pary | usunięte; przekierowanie do `/documents` |
| `/matches`, `/interviews` | stare listy historii | usunięte; przekierowanie do `/history` |

Adres `/documents` zostaje mimo etykiety „Postings”: zmiana nazwy dotknęłaby wszystkich testów i linków, nie dając
użytkownikowi nic.

**History:** jedna lista dopasowań i rozmów posortowana od najnowszych; filtr All / Matches / Interviews; wiersz ma
ikonę rodzaju, wynik albo status, tytuł ogłoszenia i datę. Klient pobiera obie listy (`/matches`, `/sessions`) i
łączy je sam; „Load more” zwiększa limit obu, od góry, jak dotychczasowe historie (nowy wpis wstawia się nad stroną,
więc stronicowanie przez `offset` pokazałoby jeden wiersz dwa razy). Limit API to 100 na listę.

## 4. Strona ogłoszenia i przepływy

**Nagłówek strony** (`PageHeader` z części 1): link „← All postings”; tytuł; pod nim domena źródła (link) i data
dodania. Po prawej **„Match my CV”** (primary) i **„Practise interview”** (secondary), a pod nimi „with: cv.pdf ▾” —
wybór CV wspólny dla obu akcji, domyślnie najnowsze (największe `created_at`).

**Lewa kolumna (szersza):** wymagania jako neutralne chipy (to jeszcze nie dopasowanie, więc bez ✓/✗); treść
ogłoszenia — początek i „Show all”.

**Prawa kolumna:** **Your matches** — do 5 najnowszych dopasowań tego ogłoszenia (wynik, data, link); **Your
interviews** — do 5 najnowszych rozmów (status albo wynik, data, „Continue” przy niedokończonej). Pod każdą listą
„See all in History”; pusta lista to `EmptyState` z jednym zdaniem.

Na wąskim ekranie kolumny układają się jedna pod drugą, w tej kolejności.

**Przepływy:**

| Sytuacja | Zachowanie |
|---|---|
| „Match my CV” | przycisk blokuje się, `Thinking` „Matching your CV…”, po sukcesie przejście na `/matches/:id` |
| „Practise interview” | jak wyżej, „Preparing questions…”, przejście na `/interviews/:id` |
| Jedna akcja trwa | druga też jest zablokowana |
| 429 / 503 / 422 | `Alert` pod przyciskami; przy 429 z czasem oczekiwania (`reasonFor`) |
| Brak CV | obie akcje zablokowane, obok zdanie z linkiem „Add a resume first” |
| Ogłoszenie bez wymagań | „Practise interview” zablokowany z wyjaśnieniem (API odpowiedziałoby 422); dopasowanie działa, bo ma regułę awaryjną na słowach kluczowych |
| Nieistniejące ogłoszenie | `Alert` z komunikatem API i link do listy |

**Wynik dopasowania** (`/matches/:id`): link wstecz „← {tytuł ogłoszenia}” do `/documents/:id`, a gdy ogłoszenie
usunięto (`document_id` = `null`) — do History. Przycisk „Practise interview” startuje rozmowę na tej samej parze;
zablokowany z wyjaśnieniem, gdy CV albo ogłoszenie usunięto.

**Rozmowa** (`/interviews/:id`): link wstecz do ogłoszenia albo, gdy go nie ma, do History.

**Usuwane:** `routes/Match.tsx`, `routes/Interview.tsx` (wybór pary), `routes/History.tsx` (lista dopasowań;
`MatchDetail` przenosi się do własnego pliku), `routes/InterviewHistory.tsx`, oraz ich testy — scenariusze przechodzą
do testów strony ogłoszenia i History.

## 5. Zmiany w API

| Zmiana | Szczegóły |
|---|---|
| `GET /documents/{id}` | nowy schemat `DocumentDetail` = pola `DocumentRead` + `content` + `requirements` (`list[str] \| null`). Każdy zalogowany, jak lista (baza ogłoszeń jest wspólna). Nieistniejące → 404. |
| `GET /matches?document_id=` | opcjonalny filtr, zawsze wewnątrz rekordów wołającego (NFR-1 bez zmian). Nieznane lub usunięte ogłoszenie → pusta lista, nie 404 — to filtr, nie zasób. |
| `GET /sessions?document_id=` | jak wyżej. |

Po zmianach: `npm run gen` (`web/openapi.json` + `schema.d.ts`), inaczej oba joby CI padają.

## 6. Testy

| Poziom | Zakres |
|---|---|
| API | szczegóły ogłoszenia (treść, wymagania, `null`), 404, 401; filtr zwraca tylko rekordy danego ogłoszenia; filtr nie ujawnia cudzych rekordów; nieznane ogłoszenie → pusta lista; bez filtra zachowanie bez zmian |
| Strona ogłoszenia | treść i wymagania; domyślnie najnowsze CV, zmiana CV; „Match my CV” wysyła wybraną parę i przechodzi do wyniku; to samo dla rozmowy; brak CV; brak wymagań; 429 i 503; listy dopasowań i rozmów, puste stany |
| History | łączenie i sortowanie obu list; filtr; „Load more” zwiększa limit obu |
| Nawigacja | trzy miejsca; przekierowania ze starych adresów |
| Wynik dopasowania | link wstecz do ogłoszenia albo History; „Practise interview” z tą samą parą; zablokowany po usunięciu CV lub ogłoszenia |

Weryfikacja: pełna, backendu i klienta (`CLAUDE.md`); w przeglądarce cała ścieżka — dodanie ogłoszenia →
dopasowanie → rozmowa → History.

## 7. Poza zakresem

- Stany ładowania i puste stany na pozostałych ekranach — część 3.
- Hierarchia listy ogłoszeń i strony CV — część 4.
- Usuwanie ogłoszenia zostaje na kafelku listy.
- Zmiana adresu `/documents` na `/postings`.

## 8. Kolejność prac

Jedno zadanie = jeden PR.

1. **API:** `GET /documents/{id}`, filtr `document_id` na `/matches` i `/sessions`, testy, regeneracja OpenAPI.
2. **Strona ogłoszenia:** `/documents/:id` z akcjami i listami; kafelki listy jako linki; przejście na stronę po
   dodaniu ogłoszenia.
3. **Nawigacja i History:** nagłówek z trzema miejscami, `/history`, przekierowania, usunięcie stron wyboru pary i
   starych historii, linki wstecz i „Practise interview” na stronie wyniku.

Strony „Match” i „Interview” znikają dopiero w zadaniu 3, gdy te same akcje są już na stronie ogłoszenia — funkcja
nie jest ani przez chwilę niedostępna.

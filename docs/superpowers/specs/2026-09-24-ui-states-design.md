# Frontend, część 3 — stany i informacja zwrotna

**Data:** 2026-09-24
**Zakres:** `web/`; API bez zmian
**Rezultat:** każdy ekran pokazuje ładowanie, pustkę, błąd, czekanie na model i sukces w jeden, ten sam sposób
**Poprzednie dokumenty:** `2026-09-24-ui-foundation-design.md` (część 1), `2026-09-24-ui-navigation-design.md` (część 2)
**Status:** projekt zatwierdzony w rozmowie 2026-09-24; kod jeszcze nie istnieje

---

## 1. Cel i kontekst

Część 3 z czterech. Problem wskazany przez użytkownika: ładowanie, czekanie na model, puste stany i błędy są mało
widoczne albo nijakie. Część 1 dała komponenty (`Skeleton`, `EmptyState`, `Spinner` / `Thinking`); strona
ogłoszenia, History i wynik dopasowania (część 2) już ich używają. Starsze ekrany — nie.

**Stan wyjściowy (przegląd 2026-09-24):**

- Lista ogłoszeń, lista CV i rozmowa pokazują ładowanie jako szare „Loading…”.
- Puste listy to zwykły szary tekst („Nothing in the knowledge base yet.”, „No resumes stored yet.”) bez akcji.
- Czekanie na model przy odpowiedzi w rozmowie, wczytywaniu ogłoszenia i uploadzie CV to tylko zmiana napisu na
  przycisku, choć trwa kilka sekund.
- Warunki wstępne („No resumes yet — add one first” na stronach Match i Interview) i „No chunks” przy ogłoszeniu
  są czerwonym `Alert`em — a od części 1 czerwień znaczy błąd.
- Błąd ładowania nie daje ponowienia; trzeba odświeżyć stronę.
- Usunięcie CV lub ogłoszenia nie daje potwierdzenia — wiersz znika bez słowa.

## 2. Decyzje

| # | Pytanie | Decyzja | Odrzucone | Dlaczego |
|---|---|---|---|---|
| S-1 | Potwierdzenie sukcesu | **Komunikat na miejscu** (`Status`), trzymany w stanie strony, znika przy następnej akcji w tym samym miejscu | toasty w rogu z „Undo”; brak potwierdzeń | Bez nowego mechanizmu, spójne z istniejącym `Status`. Bez timerów — znikający tekst łatwo przeoczyć. |
| S-2 | Sposób wdrożenia | **Stany jawnie na każdym ekranie** z gotowych komponentów + `Notice` + ponawianie w `Alert` | wspólny `QueryView` obsługujący ładowanie/błąd/pustkę | Zgodne z tym, co już działa; każdy stan widać w kodzie ekranu. Ekrany z kilkoma zapytaniami (strona ogłoszenia ma trzy) i tak wymagałyby obsługi ręcznej, więc wzorzec byłby niekonsekwentny. |

## 3. Słownik stanów

| Sytuacja | Komponent | Przykład |
|---|---|---|
| Ładowanie treści | `Skeleton` w kształcie tego, co nadchodzi | lista CV: 3 bloki |
| Pusta lista | `EmptyState` z akcją | „No resumes yet.” + przycisk przenoszący fokus do formularza |
| Błąd ładowania | `Alert` z przyciskiem **„Try again”** (nowe) | lista ogłoszeń się nie wczytała |
| Błąd akcji | `Alert` bez ponowienia — użytkownik powtarza akcję sam | upload odrzucony |
| Czekanie na model / pobieranie (sekundy) | `Thinking` obok zablokowanej akcji | „Evaluating your answer…”, „Reading the posting…” |
| Wskazówka, warunek wstępny | **`Notice`** (nowy) — neutralny | „No resumes yet — add one first”, „No chunks: …” |
| Sukces akcji | `Status` w miejscu akcji | „Resume deleted.” nad listą |

**`Notice`:** tło `sunken`, tekst `ink-soft`, ikona informacji; **bez** `role="alert"` — nie jest pilny, czytnik
ekranu nie powinien przerywać. Od `Alert` różni się kolorem, ikoną i rolą.

**`Alert` z `onRetry`:** opcjonalny przycisk „Try again” wywołujący ponowienie zapytania (`refetch` z React Query).
Bez `onRetry` — jak dziś.

**Zasady:**

- Czerwień wyłącznie dla tego, co się nie udało.
- `Thinking` tam, gdzie czeka się sekundy (model, pobranie strony, embeddingi). Czekanie krótsze niż sekunda (zapis
  bez modelu) zostaje przy zmianie napisu na przycisku.
- Potwierdzenia sukcesu dotyczą usunięć — przy nich wiersz po prostu znika. Dodanie CV i ogłoszenia ma już wyraźny
  sygnał (nowy wiersz, przejście na stronę ogłoszenia).

## 4. Zmiany na ekranach

| Ekran | Zmiany |
|---|---|
| Postings (lista) | ładowanie → `Skeleton` w siatce; błąd → „Try again”; pusta baza → `EmptyState` „The knowledge base is empty.” z przyciskiem przenoszącym fokus do pola adresu; wczytywanie (adres, plik, tekst) → `Thinking` („Reading the posting…”, „Reading the file…”, „Storing the posting…”); „No chunks” → `Notice`; po usunięciu → `Status` „Posting deleted.” nad listą |
| Resumes | ładowanie → `Skeleton`; błąd → „Try again”; brak CV → `EmptyState` „No resumes yet.” z przyciskiem przenoszącym fokus do wyboru pliku; upload i zapis wklejonego CV (odczyt umiejętności przez model) → `Thinking`; po usunięciu → `Status` „Resume deleted.” |
| Match, Interview (start) | „No resumes yet” i „Nothing in the knowledge base yet” → `Notice` |
| Rozmowa | ładowanie → `Skeleton`; błąd → „Try again”; wysłanie odpowiedzi → `Thinking` „Evaluating your answer…” pod formularzem; zakończenie (bez modelu) zostaje przy napisie na przycisku |
| Strona ogłoszenia, History, wynik dopasowania | mają szkielety i puste stany; dochodzi „Try again” przy błędach ładowania |
| Logowanie | bez zmian |

## 5. Testy

| Zakres | Co sprawdza |
|---|---|
| `Notice` | pokazuje tekst; nie ma `role="alert"` |
| `Alert` | z `onRetry` ma „Try again” i wywołuje je; bez — nie ma przycisku |
| ekrany (MSW) | szkielet w trakcie ładowania (`role="status"` z tekstem); pusty stan i jego akcja przenosząca fokus; „Try again” (pierwsza odpowiedź błąd, druga sukces — lista się pojawia); `Thinking` w trakcie oczekiwania (opóźniona odpowiedź); `Status` po usunięciu; wskazówki jako `Notice`, nie alert |

**Istniejące testy, które celowo się zmienią** (zmienia się zachowanie, opisane w PR-ach): pusty stan listy
ogłoszeń i listy CV (nowy tekst i akcja), „a posting with no chunks is called out” (szukał `role="alert"`, teraz
szuka tekstu wskazówki — to przestaje być błędem).

## 6. Poza zakresem

- Toasty i „Undo”.
- Wspólny `QueryView` (odrzucony w S-2).
- Zmiany w API.
- Hierarchia ekranów — część 4.

## 7. Kolejność prac

Jedno zadanie = jeden PR.

1. **Elementy:** `Notice`, `onRetry` w `Alert`, testy.
2. **Postings i Resumes:** szkielety, puste stany, ponawianie, `Thinking`, `Notice` przy „No chunks”, potwierdzenia
   usunięć.
3. **Pozostałe ekrany:** `Notice` na stronach startowych Match i Interview; rozmowa (szkielet, ponawianie, `Thinking`
   przy ocenie); „Try again” na stronie ogłoszenia, w History i przy wyniku.

Zadanie 3 zależy od przywrócenia stron Match i Interview (PR #32) — zaczyna się po jego merge'u.

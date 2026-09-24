# Frontend, część 4 — hierarchia ekranów

**Data:** 2026-09-24
**Zakres:** `web/` oraz jedno pole w API (sekcja 3)
**Rezultat:** na liście ogłoszeń, stronie CV i w rozmowie najważniejsze jest na górze, a reszta mniej zajmuje
**Poprzednie dokumenty:** `2026-09-24-ui-foundation-design.md`, `2026-09-24-ui-navigation-design.md`,
`2026-09-24-ui-states-design.md` (części 1–3)
**Status:** projekt zatwierdzony w rozmowie 2026-09-24; kod jeszcze nie istnieje

---

## 1. Cel i kontekst

Ostatnia z czterech części. Problem wskazany przez użytkownika: na ekranach nie widać od razu, co jest
najważniejsze; długie listy, wszystko wygląda tak samo, dużo przewijania.

**Przegląd 2026-09-24:**

- **Postings (lista):** na górze duży formularz dodawania, lista — główna treść i centrum pracy — dopiero pod nim;
  kafelki pokazują techniczne „2 chunks”; wszystkie wyglądają tak samo.
- **Resumes:** formularz na górze, choć użytkownik ma jedno główne CV; każda wersja ma tę samą wagę (podgląd, trzy
  pobrania, usuwanie), strona jest długa.
- **Rozmowa:** po zakończeniu podsumowanie jest na dole, pod całą rozmową; postęp to tylko tekst.
- Strona ogłoszenia, History, wynik dopasowania — przerobione w częściach 2–3, bez zmian. Logowanie — bez zmian.

## 2. Decyzje

| # | Pytanie | Decyzja | Odrzucone | Dlaczego |
|---|---|---|---|---|
| H-1 | Układ listy ogłoszeń | **Gęsta lista wierszy z akcjami „Match” i „Practise” w wierszu**, dodawanie w panelu po „+ Add posting” | pasek dodawania + kafelki; lista + stały panel dodawania z boku | Więcej ofert na ekranie i dopasowanie lub rozmowa bez wchodzenia na stronę ogłoszenia — praca kręci się wokół ogłoszenia (część 2). |
| H-2 | Układ strony CV | **Główne CV jako duża karta, starsze wersje zwinięte**, dodawanie w panelu po „+ Add resume” | wszystkie wersje jako wiersze z oznaczeniem „Main” | Użytkownik ma jedno główne CV; to ono powinno dominować, a stare wersje nie powinny wydłużać strony. |
| H-3 | Które CV jest główne | **Zawsze najnowsze** | ręczne „Make main” | Tak samo wybierają „Match” i „Practise”; ręczny wybór wymagałby nowego pola w bazie. Do dołożenia, jeśli zacznie przeszkadzać. |

Makiety z rozmowy: `.superpowers/brainstorm/` (poza repozytorium).

## 3. Lista ogłoszeń

**Nagłówek** (`PageHeader`): „Postings”, jedno zdanie opisu, po prawej **„+ Add posting”**.

**Panel dodawania:** rozwija się pod nagłówkiem po kliknięciu; trzy sposoby — adres (domyślny), plik, tekst. Otwarty
od razu przy pustej bazie (`EmptyState` zostaje, jego akcja otwiera panel). Po dodaniu — przejście na stronę
ogłoszenia jak dotąd.

**Wiersze** (jedna kolumna na karcie):

- **Tytuł** (link do strony ogłoszenia); pod nim **domena źródła lub „uploaded”, data względna** („3 days ago”),
  **liczba wymagań** („6 requirements”) — zamiast „2 chunks”; mówi, czy ogłoszenie jest „przeczytane”.
- Po prawej **„Match”** i **„Practise”** na najnowszym CV: w trakcie `Thinking` w wierszu i pozostałe akcje na liście
  zablokowane; po sukcesie przejście na wynik lub rozmowę; błąd w wierszu.
- „Practise” zablokowany z podpowiedzią bez wymagań (`requirement_count` = `null` lub 0).
- Bez CV — akcje zablokowane, nad listą `Notice` z „Add a resume first”.
- Administrator: „Delete” w wierszu, z dwuetapowym potwierdzeniem jak dziś.
- Ogłoszenie bez fragmentów: `Notice` w jego wierszu.
- „Load more” zostaje.

**API:** `DocumentRead` dostaje **`requirement_count: int | null`** (`null` = wymagań nikt nie odczytał). Bez niego
wiersz nie wie, czy zablokować „Practise”, a pobieranie szczegółów każdego ogłoszenia osobno byłoby kosztowne.
Regeneracja OpenAPI (`npm run gen`).

## 4. Strona CV

**Nagłówek:** „Resumes”, „Only yours: nobody else can read or delete them.”, **„+ Add resume”** — panel z uploadem
pliku i wklejonym tekstem; otwarty od razu przy braku CV.

**Karta głównego CV** (najnowsze): oznaczenie **„Main · used for matching”**; nazwa pliku jako tytuł, pod nią rola
docelowa, liczba znaków, data dodania; akcje — **pobieranie PDF / Word / Markdown**, „Show text” (rozwija podgląd),
„Delete” (dwuetapowo).

**Starsze wersje:** zwinięte pod kartą jako „Older versions (N)”; po rozwinięciu zwarte wiersze z tymi samymi
akcjami, mniejszymi. Przy jednym CV sekcji nie ma.

Stany z części 3 zostają: szkielet, „Try again”, `Thinking` przy dodawaniu, potwierdzenie usunięcia.

## 5. Rozmowa

- **W trakcie:** pod tytułem pasek postępu (`Meter`) z „Question 2 of 5” zamiast samego tekstu.
- **Po wysłaniu odpowiedzi** fokus wraca do pola odpowiedzi (dziś pole jest blokowane na czas oceny i traci fokus).
- **Po zakończeniu** podsumowanie **na górze**, pod tytułem; rozmowa pod nim z nagłówkiem „The conversation”.

## 6. Testy

| Zakres | Co sprawdza |
|---|---|
| API | `requirement_count` — liczba przy odczytanych wymaganiach, `null` przy nieodczytanych |
| Lista ogłoszeń | wiersz z domeną, datą względną, liczbą wymagań; „Match” / „Practise” z wiersza wysyłają najnowsze CV i przechodzą dalej; „Practise” zablokowany bez wymagań; bez CV `Notice`; panel dodawania otwiera się przyciskiem i jest otwarty przy pustej bazie |
| CV | najnowsze jest główne i oznaczone; starsze zwinięte, nieobecne przy jednym CV; akcje działają w obu miejscach |
| Rozmowa | podsumowanie przed rozmową; pasek postępu ma właściwą wartość; fokus wraca do pola po odpowiedzi |

Istniejące testy, które celowo się zmienią (np. dodawanie ogłoszenia przy niepustej bazie najpierw otwiera panel),
są opisane w PR-ach.

## 7. Poza zakresem

- Ręczne ustawianie głównego CV (H-3).
- Strona ogłoszenia, History, strony startowe Match / Interview, wynik dopasowania, logowanie.

## 8. Kolejność prac

Jedno zadanie = jeden PR.

1. **Lista ogłoszeń:** `requirement_count` w API, panel dodawania, wiersze z akcjami.
2. **Strona CV:** karta głównego CV, zwinięte starsze wersje, panel dodawania.
3. **Rozmowa:** postęp, fokus, podsumowanie na górze.

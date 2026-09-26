# Tożsamość wizualna — „Teczka rekrutacyjna”

**Data:** 2026-09-26
**Zakres:** `web/` (tokeny, krój, komponenty `ui/`, wszystkie ekrany) oraz jedno rozszerzenie odczytu w API
(sekcja 5)
**Rezultat:** aplikacja z charakterem wziętym z rekrutacji — ogłoszenie jako teczka z zakładką, etapy jako
ścieżka, luki jak pieczątka — zamiast generycznego ciepłego wyglądu
**Poprzedni dokument:** `2026-09-24-ui-foundation-design.md` (decyzje U-1…U-4, które ten dokument zmienia)
**Status:** zrealizowany 2026-09-26 (PR #46); odstępstwa od projektu wpisane w tekst

---

## 1. Cel i kontekst

Wygląd z części 1 redesignu (beże, morski akcent, Nunito Sans, zaokrąglone karty z miękkim cieniem, przyciski
jak pigułki) działa, ale według użytkownika jest **generyczny** i **nie ma związku z tematem** — mógłby być
dowolną aplikacją. Kremowe tło z jednym stonowanym akcentem i identyczne zaokrąglone karty z cieniem to dziś
jeden z najczęstszych domyślnych wyglądów.

**Ton:** rzeczowy, profesjonalny — jak narzędzie rekrutera, nie jak notatnik ani trener. To kariera
użytkownika; aplikacja ma porządkować, nie pocieszać.

**Źródło charakteru:** świat rekrutacji — teczka z dokumentami aplikacji, etapy procesu jako sekwencja,
pieczątka przy tym, czego brakuje.

**Założenia z części 1, które zostają:** kontrast tekstu ≥ 4.5:1 i granic kontrolek ≥ 3:1 w obu motywach,
mierzony i zapisany w komentarzu przy tokenie; kolor nigdy nie jest jedynym nośnikiem informacji; widoczny
fokus; testy znajdują elementy po roli i etykiecie; słownik stanów (`Skeleton`, `EmptyState`, `Alert`,
`Notice`, `Thinking`, `Status`) bez zmian w znaczeniu.

**Drugi projekt, osobno:** śledzenie aplikacji („Applied”) — nowa funkcja z tabelą per użytkownik i
ogłoszenie (ogłoszenia są wspólne, więc nie kolumna w `documents`). Ten dokument tylko przygotowuje dla niej
czwarte pole ścieżki etapów.

Makiety z rozmowy: `.superpowers/brainstorm/2122-1790390346/content/` (`directions.html`, `tokens.html`,
`screens.html`; poza repozytorium).

## 2. Decyzje

| # | Pytanie | Decyzja | Odrzucone | Dlaczego |
|---|---|---|---|---|
| V-1 | Kierunek | **Teczka rekrutacyjna**: arkusze z zakładką, ścieżka etapów, czerwień pieczątki tylko dla luk | tablica rekrutera (kolumny etapów, wąski krój, gęsto); zakreślacz (typografia CV, szeryfowe tytuły, zaznaczone wymagania) | Najbliżej procesu, przez który przechodzi użytkownik, i czytelny przy tonie „rzeczowy”. Zastępuje U-1. |
| V-2 | Krój | **Public Sans** w całej aplikacji, skala ~1.25: 31 / 20 / 15 / 13, wynik 40 z cyframi tabelarycznymi | Nunito Sans (U-2) | Krój z dokumentów urzędowych — poważny, neutralny, dobrze składa liczby. Jedna rodzina wystarcza; charakter niesie układ. |
| V-3 | Paleta | **Chłodny papier i granatowy atrament**, czerwień pieczątki (sekcja 3) | beże i teal | Zerwanie z najczęstszym domyślnym wyglądem; granat i czerwień to kolory dokumentu, nie aplikacji. |
| V-4 | Kształty | **Arkusz** z linią 1 px zamiast cienia, zaokrąglenie 6 px; przyciski i chipy 4 px; bieżąca zakładka nawigacji łączy się ze stroną | `rounded-card` 1 rem, `rounded-full`, `--card-shadow` | Papier i teczka, nie karty „unoszące się” nad tłem. |
| V-5 | Etapy | **Ścieżka na 4 pola**: Posting, Match, Interview, Applied; czwarte z przerywaną kreską, dopóki nie istnieje funkcja z drugiego projektu | trzy etapy; bez ścieżki | Użytkownik chce śledzić aplikacje; układ powstaje od razu gotowy na nie. |
| V-6 | Etap i wynik na liście ogłoszeń | **API zwraca twój `stage` i `best_score`** przy ogłoszeniu | tylko dashboard i strona ogłoszenia; liczenie w kliencie | Klient ma tylko stronicowane listy — ten sam powód, dla którego dashboard ma własny endpoint (DB-4). |
| V-7 | Metadane w wierszach | **Czas względny** (`ago()` z `time.ts`) i zwykłe zdania | `toLocaleString()` i „A · B · C” | Czytelniej, i bez szablonowych kropek. |

## 3. Tokeny

Nazwy tokenów zostają (`surface`, `raised`, `sunken`, `line`, `control`, `ink*`, `accent*`, `danger*`,
`on-*`), zmieniają się wartości — dzięki temu klasy Tailwinda w ekranach nie zmieniają się w części 1.
Kontrast policzony według WCAG 2.x; przy implementacji każda para trafia do komentarza przy tokenie.

| Token | Jasny | Ciemny | Do czego |
|---|---|---|---|
| `surface` | `#f3f5f8` | `#10151e` | tło strony — chłodny papier / nocne biurko |
| `raised` | `#ffffff` | `#192030` | arkusze, kontrolki |
| `sunken` | `#e8ecf1` | `#141a25` | wnętrza, tor ścieżki |
| `line` | `#d5dbe3` | `#2c3547` | linie arkuszy i podziały |
| `control` | `#7a8595` | `#6f7b8e` | granice pól (3.74 / 3.42 : 1 jasny; 3.80 / 4.27 : 1 ciemny) |
| `ink` | `#16202e` | `#e8ecf2` | tekst główny |
| `ink-soft` | `#465366` | `#b7c0cd` | tekst drugorzędny |
| `ink-faint` | `#5d6979` | `#8e99aa` | podpisy, daty (min. 4.70:1 na `sunken` jasnym) |
| `accent` | `#2a3b8f` | `#9fb0f5` | atrament: akcje, wynik, bieżący etap |
| `accent-strong` | `#1e2c6e` | `#c3cefa` | tekst na `accent-soft`, hover |
| `accent-soft` | `#e4e9f7` | `#243060` | tło spełnionego wymagania, bieżącego etapu |
| `on-accent` | `#ffffff` | `#10151e` | tekst na `accent` |
| `danger` | `#a3261e` | `#f28b82` | pieczątka luki, przycisk usuwania |
| `danger-soft` | `#fbe8e6` | `#3b1714` | tło komunikatu o błędzie |
| `danger-ink` | `#7a1a14` | `#f8c9c4` | tekst komunikatu o błędzie |
| `on-danger` | `#ffffff` | `#10151e` | tekst na `danger` |

Zmierzone pary (jasny / ciemny): `ink` na `surface` 15.02 / 15.43; `ink-soft` na `raised` 7.81 / 8.86;
`ink-faint` na `raised` 5.58 / 5.65, na `surface` 5.11 / 6.35, na `sunken` 4.70 / 6.05; `accent` na `raised`
9.90 / 7.75; `accent-strong` na `accent-soft` 10.54 / 8.12; `on-accent` na `accent` 9.90 / 8.71; `danger` na
`raised` 7.36 / 6.81; `on-danger` na `danger` 7.36 / 7.66; `danger-ink` na `danger-soft` 8.96 / 10.73;
`accent` na `accent-soft` (zrobiony etap w torze) 8.16 / 6.00.

**Kształty:** `--radius-card` 6 px (arkusz), nowy `--radius-control` 4 px (przyciski, chipy, pola);
`--card-shadow` znika w obu motywach — arkusz odróżnia od tła linia `line`.

## 4. Komponenty (`web/src/ui/`)

- **`Sheet`** zastępuje `Card`: `raised`, linia 1 px, 6 px. Opcjonalny `tab` — etykieta na zakładce nad
  lewym górnym rogiem (tytuł ogłoszenia, źródło); z zakładką lewy górny róg jest prosty.
- **`StageRail`**: pełna ścieżka jako `<ol aria-label="Stage">`, pozycje numerowane (to prawdziwa sekwencja),
  zrobione etapy w `accent`, bieżący z tłem `accent-soft`, pogrubieniem i `aria-current="step"`, przyszłe w
  `line`, niedostępny „Applied” z przerywaną kreską. Wersja `compact` (4 kreski) do wierszy list, z tekstem
  dla czytnika ekranu, np. „Stage 2 of 4: Match”.
- **`Chip`** dostaje warianty: `met` (tło `accent-soft`, ✓) i `gap` (ramka 1.5 px `danger`, bez tła) — luka
  różni się kształtem i ikoną, nie tylko kolorem.
- **`Score`**: wynik procentowy, 800, cyfry tabelaryczne, w `accent`; rozmiar duży (40) na stronie
  ogłoszenia i wyniku dopasowania, mały w wierszach.
- **`Button`, `ButtonLink`**: 4 px zamiast `rounded-full`; warianty bez zmian w znaczeniu.
- **Nawigacja w `Layout`**: bieżąca zakładka ma tło `surface`, linie z trzech stron i łączy się ze stroną
  (jak zakładka teczki); pozostałe bez tła. `aria-current` bez zmian.

## 5. Zmiana w API

`DocumentRead` (lista) i `DocumentDetail` (strona ogłoszenia) dostają dwa pola liczone **dla wywołującego**:

- `stage: int` — 1 zawsze (ogłoszenie istnieje); 2, gdy wywołujący ma dopasowanie do tego ogłoszenia;
  3, gdy ma rozmowę o nim (aktywną lub zakończoną). Wartość 4 („Applied”) dojdzie w drugim projekcie.
- `best_score: float | None` — najwyższy wynik jego dopasowań do tego ogłoszenia, `None` bez dopasowania.

Liczone w `app/services/stages.py` jednym zapytaniem dla całej strony listy (agregaty z `matches` i `sessions`
po `document_id`, filtrowane po `user_id`), nie zapytaniem na wiersz. Ogłoszenia są wspólne; etap i wynik —
nie (NFR-1): dla innego konta to samo ogłoszenie ma etap 1 i brak wyniku. Bez migracji, bez wywołań modelu.
Zmiana schematu wymaga `npm run gen`.

## 6. Ekrany

Kolejność według tego, jak często są używane:

1. **Nagłówek i dashboard** — Next jako arkusz z tytułem ogłoszenia na zakładce, pełną ścieżką i zdaniem;
   luki jako chipy `gap`. „Other things to do” z mini-ścieżką w wierszu. Recently z wynikiem przez `Score` i
   czasem względnym.
2. **Lista ogłoszeń** — wiersz: tytuł, źródło i wiek, mini-ścieżka, `best_score` (lub „—”), akcje.
3. **Strona ogłoszenia** — zakładka ze źródłem i datą, tytuł, pełna ścieżka; wymagania jako `met`/`gap`
   (według dopasowania z najlepszym wynikiem — tego samego, którego wynik pokazuje ścieżka; gdy nie ma go wśród ostatnich na stronie, wymagania zostają neutralne), obok „Your work on it”.
4. **Pozostałe** — Resumes, wynik dopasowania, rozmowa, History, Login: bez zmian układu, nowy wygląd przez
   komponenty.

## 7. Testy i weryfikacja

- Istniejące testy (po roli i etykiecie) przechodzą bez zmian; test, który trzeba poprawić, oznacza zmianę
  zachowania, nie wyglądu.
- Nowe: `StageRail` (nazwa, pozycje, `aria-current`, tekst wersji `compact`), warianty `Chip`; w pytest
  `stage` i `best_score` na liście i stronie ogłoszenia, łącznie z izolacją między kontami.
- Po każdej części sprawdzenie w przeglądarce: oba motywy, 390 px (ramka `iframe`, bo okna nie da się
  zmniejszyć), fokus z klawiatury.

## 8. Poza zakresem

- Funkcja „Applied” — drugi projekt, z własnym dokumentem i wpisem w spec.
- Nowe ekrany i zmiany przepływów.
- Animacje poza istniejącymi przejściami kolorów.

## 9. Kolejność prac

1. Fundament: tokeny, krój, kształty w istniejących komponentach.
2. Nowe komponenty: `Sheet`, `StageRail`, warianty `Chip`, `Score`; nawigacja jak zakładki.
3. API: `stage` i `best_score`, testy, `npm run gen`.
4. Ekrany: dashboard, lista ogłoszeń, strona ogłoszenia, pozostałe.
5. Zapis w `CLAUDE.md` (konwencje klienta: tokeny, kształty, nowe komponenty).

# Frontend, część 1 — fundament wizualny

**Data:** 2026-09-24
**Zakres:** `web/` (klient React + Tailwind 4); API, backend i model danych bez zmian
**Rezultat:** nowy wygląd całej aplikacji (paleta, czcionka, kształty, ikony), przełącznik motywu i zestaw
komponentów, na którym staną części 2–4
**Status:** projekt zatwierdzony w rozmowie 2026-09-24; kod jeszcze nie istnieje

---

## 1. Cel i kontekst

Frontend ma być **wygodniejszy w codziennym użyciu**; ładniejszy wygląd jest środkiem, nie celem. Dotyczy
wszystkich ekranów (ogłoszenia, CV, dopasowanie z historią, interview) i czterech problemów wskazanych przez
użytkownika: nawigacja i przepływ, hierarchia i czytelność, surowy wygląd, słabe stany (ładowanie, czekanie na
model, puste listy, błędy).

Całość podzielono na cztery części, każda z własnym projektem i zadaniami:

1. **Fundament wizualny** — ten dokument.
2. Nawigacja i przepływ — układ aplikacji, przejścia między ekranami (np. z ogłoszenia prosto do dopasowania
   lub interview z wybraną parą).
3. Stany i informacja zwrotna — użycie komponentów z części 1 na wszystkich ekranach.
4. Hierarchia ekranów — przegląd każdego ekranu po kolei.

**Stan wyjściowy:** Tailwind 4 z tokenami w `web/src/styles.css` (neutralne tło, jeden niebieski akcent, ciemny
motyw tylko wg ustawień systemu, kontrast mierzony ręcznie), czcionka systemowa, komponenty w
`web/src/ui/index.tsx` (`Button`, `Field`, `Card`, `Chip`, `Meter`, `Alert`, `Status`, `PageTitle`, `Muted`).

**Założenia, które zostają:**

- Kontrast sprawdzony w obu motywach: tekst ≥ 4.5:1, granice kontrolek ≥ 3:1.
- Kolor nigdy nie jest jedynym nośnikiem informacji (sprawdzanie przy zaburzeniach widzenia barw).
- Widoczny fokus na każdym elemencie interaktywnym.
- Testy znajdują elementy po roli i etykiecie — zmiana wyglądu nie może ich ruszyć.

## 2. Decyzje

| # | Pytanie | Decyzja | Odrzucone | Dlaczego |
|---|---|---|---|---|
| U-1 | Kierunek wizualny | **Ciepły, przyjazny**: beże, morski (teal) akcent, zaokrąglone kształty, miękkie cienie | spokojny profesjonalny (dopracowany obecny); gęsty narzędziowy (ciemny pasek, indygo, tabele) | Narzędzie wspiera w szukaniu pracy — mniej „biurowo”, bardziej osobiście, przy zachowaniu czytelności. |
| U-2 | Czcionka | **Nunito Sans** | Plus Jakarta Sans, Figtree | Najcieplejsza, najbliżej kierunku U-1. Cena: trochę szersza, mniej tekstu w linii. |
| U-3 | Motyw | **Oba motywy + przełącznik** (jasny / systemowy / ciemny) | tylko ciemny; ciemny domyślnie | Zostaje zachowanie wg systemu, a użytkownik może je nadpisać. |
| U-4 | Sposób budowy | **Rozbudowa własnego `ui/`** na Tailwindzie + `@fontsource-variable/nunito-sans` + `lucide-react` | shadcn/ui (Radix); same tokeny bez nowych komponentów | Pełna kontrola, ekrany i testy bez przepisywania, dwie małe zależności. shadcn to za dużo na tę skalę; same tokeny nie rozwiązują stanów ani ikon. Dialogi/menu dołożymy, gdy któraś część ich naprawdę potrzebuje. |

Makiety z rozmowy: `.superpowers/brainstorm/` (poza repozytorium).

## 3. Tokeny

Wartości w `web/src/styles.css`. Kolumny „jasny” i „ciemny” to punkt wyjścia z makiety; każda para tekst/tło jest
mierzona przy implementacji, a wynik trafia do komentarza przy tokenie. Kolor, który nie przejdzie pomiaru, zmienia
jasność — zasada zostaje.

| Token | Jasny | Ciemny | Do czego |
|---|---|---|---|
| `surface` | `#faf8f5` | `#1c1917` | tło strony |
| `raised` | `#ffffff` | `#292524` | karty, kontrolki |
| `sunken` *(nowy)* | `#f3efe9` | `#211e1c` | wnętrza: tor paska, obszary wcięte |
| `line` | `#e7e2da` | `#44403c` | obramowania |
| `ink` | `#292524` | `#f5f5f4` | tekst główny |
| `ink-soft` | `#57534e` | `#d6d3d1` | tekst drugorzędny |
| `ink-faint` | `#78716c` | `#a8a29e` | podpisy, daty |
| `accent` | `#0f766e` | `#2dd4bf` | akcent, wynik, pasek |
| `accent-strong` | `#115e59` | `#5eead4` | tekst na `accent-soft`, hover |
| `accent-soft` | `#ccfbf1` | `#134e4a` | tło chipów i komunikatów sukcesu |
| `on-accent` | `#ffffff` | `#1c1917` | tekst na `accent` |
| `danger` *(nowy)* | `#b91c1c` | `#f87171` | przycisk usuwania, ikona błędu |
| `danger-soft` *(nowy)* | `#fee2e2` | `#450a0a` | tło komunikatu o błędzie |
| `danger-ink` *(nowy)* | `#7f1d1d` | `#fecaca` | tekst komunikatu o błędzie |

Kształty i cień: `--radius-card: 1rem`; przyciski i chipy w pełni zaokrąglone (`rounded-full`); nowy token
`--shadow-card` (miękki cień z makiety, w ciemnym motywie zastąpiony subtelną ramką, bo cień tam słabo widać).

Błąd dostaje własny kolor, bo dziś wygląda jak zwykła ramka i łatwo go przeoczyć. Czerwień zawsze idzie z ikoną i
tekstem, nigdy sama.

## 4. Mechanizm motywu

- Kolory są **zmiennymi CSS** zdefiniowanymi w trzech miejscach:
  - `:root` — jasny,
  - `:root[data-theme="dark"]` — ciemny wybrany ręcznie,
  - `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }` — ciemny z systemu,
    o ile użytkownik nie wybrał jasnego.
- `@theme inline` w Tailwindzie wskazuje na te zmienne, więc `bg-accent`, `text-ink` itd. działają bez zmian w
  ekranach. `color-scheme` podąża za motywem (kontrolki natywne, paski przewijania).
- **`web/src/theme.ts`** — jedyne miejsce z logiką: typ `Theme = 'light' | 'dark' | 'system'`, odczyt i zapis
  w `localStorage` (klucz `jobmate-theme`), ustawienie lub usunięcie `data-theme` na `<html>`. Każdy dostęp do
  `localStorage` w `try/catch`: w trybie prywatnym może rzucić, a wtedy obowiązuje `system`.
- **Skrypt w `index.html`** (kilka linii, inline, przed skryptem aplikacji) ustawia `data-theme` przed pierwszym
  malowaniem. Bez niego strona w ciemnym motywie mignęłaby na biało przy każdym otwarciu. Duplikuje minimum logiki
  z `theme.ts` (klucz i dozwolone wartości) — z komentarzem wskazującym drugie miejsce.
- Motyw `system` obsługuje wyłącznie CSS; JavaScript nie słucha `matchMedia`.

## 5. Typografia i ikony

**Czcionka.** `@fontsource-variable/nunito-sans`, import w `main.tsx`; plik czcionki trafia do buildu (bez zapytań
do Google, działa offline). Jedna wersja variable na wszystkie grubości, podzbiór `latin` — interfejs jest po
angielsku, a znaki spoza podzbioru w treściach użytkownika (polskie litery w CV, odpowiedziach) dostarczy czcionka
systemowa ze stosu zapasowego. `--font-sans: 'Nunito Sans Variable', <obecny stos systemowy>`.

**Skala.**

| Rola | Klasy | Gdzie |
|---|---|---|
| Tytuł strony | `text-2xl font-extrabold` | `PageHeader` |
| Nagłówek sekcji | `text-lg font-bold` | karty, sekcje wyniku |
| Etykieta sekcji | `text-xs font-bold uppercase tracking-wide` | „Covered”, „Strong answers” |
| Tekst | `text-sm`–`text-base`, `leading-relaxed` | pytania, odpowiedzi, opisy |
| Liczba główna | `text-5xl font-extrabold tabular-nums` | wynik dopasowania i rozmowy |

`tabular-nums` przy każdej liczbie w listach, żeby procenty w historii stały w równej kolumnie.

**Ikony.** `lucide-react`, każda importowana osobno (w buildzie tylko użyte). Zasady:

- ikona obok tekstu jest dekoracją — `aria-hidden`;
- przycisk z samą ikoną ma `aria-label`;
- `Chip` dostaje `Check` / `X` zamiast znaków ✓ / ✗; rozróżnienie wypełnione/przerywane zostaje;
- ikona nigdy nie jest jedynym nośnikiem informacji.

## 6. Komponenty

`web/src/ui/` zostaje jednym punktem importu (`from '../ui'`), ale rozpada się na kilka plików (np. `controls.tsx`,
`feedback.tsx`, `layout.tsx`, `index.ts` z re-eksportem) — kilkanaście komponentów w jednym pliku przestałoby być
czytelne. Każdy komponent renderuje ten sam element HTML co dziś (przycisk to `<button>`, pole to `<label>` +
kontrolka), więc role i etykiety się nie zmieniają.

**Istniejące — nowy wygląd, te same role:**

| Komponent | Zmiana |
|---|---|
| `Button` | zaokrąglony; warianty `primary` / `secondary` / `quiet` + nowy `danger`; rozmiar `sm`; opcjonalna ikona przed etykietą |
| `Card` | `radius-card`, `shadow-card`, bez twardej ramki w jasnym motywie |
| `Chip` | ikony `Check` / `X` |
| `Meter` | grubszy pasek na torze `sunken` |
| `Alert` | `danger-soft` / `danger-ink` + ikona ostrzeżenia; nadal `role="alert"`, treść bez zmian |
| `Status` | `accent-soft` + ikona potwierdzenia; nadal `role="status"` |
| `Field` | API bez zmian; kontrolki: tło `raised`, zaokrąglenie, ramka w kolorze akcentu przy fokusie |
| `PageTitle`, `Muted` | nowa typografia |

**Nowe — tworzone i testowane w części 1; na ekranach od części 3, z wyjątkiem `ThemeToggle`, który od razu
trafia do nagłówka:**

| Komponent | Co robi |
|---|---|
| `PageHeader` | tytuł, opcjonalny opis, miejsce na akcje po prawej; zastąpi ręcznie składane układy „tytuł + link” |
| `EmptyState` | ikona, jedno zdanie, opcjonalna akcja (przycisk lub link) |
| `Skeleton` | pulsujące bloki zamiast „Loading…”; same bloki `aria-hidden`, kontener z tekstem dla czytnika ekranu |
| `Spinner` | kręcący się wskaźnik z tekstem w `role="status"` |
| `Thinking` | wariant na czekanie na model (kilka sekund): spinner + zdanie, np. „Evaluating your answer…” |
| `ThemeToggle` | trzy przyciski (jasny / systemowy / ciemny) w grupie z etykietą, stan przez `aria-pressed`; korzysta z `theme.ts` |

**Zmiany na ekranach w części 1 — tylko dwie:** `ThemeToggle` w nagłówku (`Layout.tsx`) i ikony w zakładkach
nawigacji. Wszystko inne na ekranach zmienia się wyłącznie przez nowy wygląd istniejących komponentów.

## 7. Testy

Vitest + Testing Library, jak dotąd.

| Zakres | Co sprawdza |
|---|---|
| `theme.ts` / `ThemeToggle` | wybór ustawia `data-theme` i zapisuje się; `system` usuwa atrybut; wybór jest odczytywany przy starcie; zablokowany `localStorage` (wyjątek przy odczycie i zapisie) nie wywraca aplikacji, obowiązuje `system`; aktywny przycisk ma `aria-pressed="true"` |
| `EmptyState` | renderuje tekst i akcję |
| `Skeleton` | bloki ukryte przed czytnikiem, kontener ma tekst ładowania |
| `Thinking` / `Spinner` | `role="status"` z tekstem |
| istniejące testy (67) | przechodzą **bez zmian**; test, który padnie, oznacza zmianę zachowania — poprawiany jest kod, nie test |

## 8. Weryfikacja

- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- Pomiar kontrastu wszystkich par tokenów w obu motywach, wyniki w komentarzach w `styles.css`.
- Przegląd w przeglądarce: każdy ekran w obu motywach, przełącznik motywu, brak białego błysku przy starcie w
  ciemnym motywie. Potwierdzenie użytkownika.

## 9. Poza zakresem

- Układ nawigacji, przejścia między ekranami, skróty typu „dopasuj to ogłoszenie” — część 2.
- Użycie `PageHeader`, `EmptyState`, `Skeleton`, `Thinking` na ekranach; treść komunikatów — część 3.
- Przebudowa hierarchii poszczególnych ekranów — część 4.
- Dialogi, menu rozwijane, powiadomienia typu toast — dopiero gdy któraś część ich potrzebuje.
- API, backend, `openapi.json` / `schema.d.ts`.

## 10. Kolejność prac

Jedno zadanie = jeden PR.

1. Tokeny i paleta B w obu motywach, mechanizm motywu (`theme.ts`, skrypt w `index.html`, `ThemeToggle` w
   nagłówku), czcionka Nunito Sans.
2. Nowy wygląd istniejących komponentów, `lucide-react`, ikony w komponentach i zakładkach; podział `ui/` na pliki.
3. Nowe komponenty: `PageHeader`, `EmptyState`, `Skeleton`, `Spinner` / `Thinking`.

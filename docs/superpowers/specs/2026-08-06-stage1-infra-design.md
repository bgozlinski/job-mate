# Etap 1 — Infrastruktura bazowa (Postgres + Redis + FastAPI + CI)

**Data:** 2026-08-06
**Etap roadmapy:** 1 z 6 (`claude/wymagania-funkcjonalne.md`, sekcja 7)
**Rezultat:** działa `docker compose up`, API odpowiada na `/health` i `/health/ready`, CI lintuje i testuje przy każdym pushu.

---

## 1. Zakres

**W zakresie:**
- Ujednolicenie roota pakietu na `app/` i usunięcie martwych katalogów.
- `docker compose` podnosi trzy usługi: `db` (pgvector/pg18), `redis`, `api`.
- FastAPI realnie łączy się z Postgresem i Redisem w `lifespan`.
- Dwa endpointy zdrowia: liveness i readiness.
- Jedno źródło prawdy dla konfiguracji (`.env` + `Settings`).
- CI: ruff (lint + format) i pytest.

**Poza zakresem (etap 2 i dalej):**
- Modele ORM, tabele, Alembic, `CREATE EXTENSION vector`.
- Cokolwiek związanego z LangChain, embeddingami, Langfuse.
- Uwierzytelnianie JWT (FR-2 / NFR-1).
- Persystencja czegokolwiek w Redisie — na tym etapie Redis tylko odpowiada na `PING`.

**Kryterium zamknięcia etapu:** świeży klon repozytorium + `.env` z `.env.example` → `docker compose up` → `curl localhost:8000/health/ready` zwraca 200 z `{"database": "ok", "redis": "ok"}`. CI zielone.

---

## 2. Decyzje projektowe

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Root pakietu | `app/` | Dockerfile ma już `WORKDIR /app` i `CMD app.main:app` — najmniej zmian; konwencja typowa dla FastAPI. |
| Instalacja projektu | projekt wirtualny — brak `[build-system]` | To aplikacja, nie biblioteka. uv instaluje wtedy wyłącznie zależności; `app` jest importowalny przez katalog roboczy. Mniej konfiguracji builda i mniej miejsc, w których lista pakietów może się rozjechać. |
| Sterownik Postgresa | psycopg 3 (`postgresql+psycopg://`) | Jeden sterownik obsługuje async w aplikacji i sync w Alembicu (etap 2) — nie utrzymujemy dwóch DSN-ów. Koła `cp314` (w tym `win_amd64`) są dostępne w 3.3.4, więc Python 3.14 zostaje. |
| Klient Redis | `redis.asyncio` z pakietu `redis>=8` | Oficjalny klient ma wbudowane asyncio; nie potrzeba `aioredis` (zarchiwizowany, wchłonięty do `redis-py`). |
| Konfiguracja | pydantic-settings | Walidacja typów przy starcie — literówka w env wywala aplikację od razu, a nie przy pierwszym zapytaniu do bazy. |
| Zasięg readiness | DB + Redis, z timeoutem | Bez timeoutu wisząca baza zawiesza request i Docker uznaje kontener za zdrowy aż do własnego timeoutu. |

### Odrzucone alternatywy

- **`src/` layout** — poprawniejszy przy pakowaniu bibliotek, ale to aplikacja, nie biblioteka; wymagałby zmian w Dockerfile, compose i konfiguracji builda bez realnego zysku.
- **asyncpg** — szybszy, ale wymusiłby drugi, synchroniczny sterownik na potrzeby Alembica w etapie 2.
- **Alembic już teraz** — należy do etapu 2 roadmapy; wprowadzenie go razem z resztą oznacza debugowanie kilku nowych rzeczy naraz.

---

## 3. Architektura

```
app/
├── __init__.py
├── main.py              # create app, lifespan, include_router
├── core/
│   ├── __init__.py
│   ├── config.py        # Settings — JEDYNE miejsce czytające os.environ
│   ├── db.py            # async engine (async_sessionmaker dopiero w etapie 2, z modelami)
│   └── redis.py         # fabryka klienta redis.asyncio
└── api/
    ├── __init__.py
    └── health.py        # APIRouter: /health, /health/ready
tests/
└── test_health.py
```

**Granice odpowiedzialności:** `core/` wie *jak* zestawić połączenie z zasobem, `api/` wie *co* wystawić na zewnątrz. Router nigdy nie tworzy engine'u ani klienta — dostaje je z `request.app.state`. Dzięki temu test może podmienić `app.state` bez dotykania importów.

**Cykl życia:** engine i klient Redis powstają raz w `lifespan`, przy zejściu wołamy `engine.dispose()` i `redis.aclose()`. Trzymamy je w `app.state`, **nie** w globalach modułu — globale są nietestowalne i tworzą połączenie w momencie importu, czyli także podczas zbierania testów.

### Kontrakt endpointów

| Endpoint | Semantyka | Zachowanie |
|---|---|---|
| `GET /health` | liveness — „proces żyje" | Zawsze 200, zero I/O. Używany przez healthcheck kontenera. |
| `GET /health/ready` | readiness — „mogę obsługiwać ruch" | `SELECT 1` + `PING`, każde z osobnym timeoutem 2 s. 200 gdy oba OK, 503 gdy którekolwiek pada. Body zawsze wymienia stan obu zależności. |

Rozdzielenie jest celowe: gdyby healthcheck kontenera pytał o readiness, chwilowa niedostępność bazy zrestartowałaby zdrowy proces API.

---

## 4. Konfiguracja — jedno źródło prawdy

Obecnie hasło do bazy występuje w trzech miejscach: `.env`, sekcja `environment:` w compose i healthcheck. Docelowo **tylko `.env`**, a compose interpoluje `${POSTGRES_USER}` itd.

Nazewnictwo: zmienne dostają prefiks `POSTGRES_*` (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`) zamiast obecnego `DB_*` — obraz `postgres` czyta dokładnie te nazwy, więc ten sam `env_file` obsłuży i bazę, i aplikację, bez duplikowania wartości.

`POSTGRES_HOST` musi być osobną zmienną, a nie częścią sklejonego URL-a, bo różni się między uruchomieniami: `db` wewnątrz compose, `localhost` przy `uv run uvicorn` na hoście. DSN składa `Settings`.

`.env.example` trafia do repozytorium z wartościami-atrapami; `.env` nigdy.

---

## 5. Testy

`httpx.ASGITransport` **nie uruchamia lifespanu**, więc test `/health` przechodzi bez jakiegokolwiek kontenera — CI zostaje szybkie i deterministyczne. Test `/health/ready` podstawia atrapy pod `app.state`, żeby sprawdzić obie ścieżki: 200 i 503.

Testy integracyjne na żywych kontenerach są świadomie odłożone — dopiero gdy będzie co testować poza pingiem.

---

## 6. CI

Jeden workflow, jeden job, wyzwalany na `push` i `pull_request`:

`checkout` → `astral-sh/setup-uv` (z cache) → `uv sync --frozen` → `ruff check .` → `ruff format --check .` → `pytest`

`--frozen` pilnuje, że `uv.lock` jest zsynchronizowany z `pyproject.toml` — rozjazd wywala CI, zamiast cicho instalować inne wersje niż lokalnie. Spełnia NFR-4 („CI uruchamia lint i testy przy każdym pushu").

---

## 7. Plan pracy — zadania w kolejności

Każde zadanie ma być osobnym commitem. Zadania Z-1 i Z-2 są blokujące dla reszty; Z-6a musi poprzedzać Z-6.

### Z-1. `.gitignore` i pierwszy commit
**Cel:** repozytorium nie ma ani jednego commita, a w katalogu leżą `.env` z hasłem, `.venv/` i `.idea/`. Pierwsze `git add .` wciągnie je wszystkie.
**Kryteria:** `git status --porcelain` nie pokazuje `.env`, `.venv/`, `.idea/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`. Pierwszy commit istnieje.
**Uwaga:** `.gitignore` musi powstać **przed** pierwszym `git add`. Jeśli plik trafi do indeksu, samo dopisanie wzorca go stamtąd nie usunie.

### Z-2. Konsolidacja roota pakietu
**Cel:** zostaje `app/`, znikają `src/` i pusty `services/`.
**Kryteria:** `app/__init__.py` i `app/main.py` istnieją, `src/` i `services/` nie. `uv run uvicorn app.main:app` startuje lokalnie.

### Z-3. Zależności i konfiguracja narzędzi w `pyproject.toml`
**Cel:** runtime — `sqlalchemy[asyncio]`, `psycopg[binary]`, `redis`, `pydantic-settings`. Dev (osobna grupa `dependency-groups`, nie główne zależności) — `ruff`, `pytest`, `pytest-asyncio`, `httpx`. Do tego sekcje `[tool.ruff]` i `[tool.pytest.ini_options]`.
**Kryteria:** `uv sync` przechodzi, `uv run ruff check .` i `uv run pytest` uruchamiają się (mogą nic nie znaleźć).
**Uwaga:** nie ustawiaj `target-version` w ruffie — ruff sam odczyta `requires-python` z `pyproject.toml`, więc jedna wersja mniej do rozjechania. W pytest ustaw `asyncio_mode = "auto"`, inaczej każdy test async wymaga dekoratora.

### Z-4. `app/core/config.py`
**Cel:** klasa `Settings` (pydantic-settings) z polami `POSTGRES_*` i `REDIS_URL`, plus property składające DSN SQLAlchemy.
**Kryteria:** import `Settings` przy brakującej zmiennej środowiskowej rzuca `ValidationError` z nazwą brakującego pola.
**Uwaga:** DSN musi mieć schemat `postgresql+psycopg://`. Samo `postgresql://` wybierze domyślny, synchroniczny sterownik i async engine wywali się dopiero przy pierwszym połączeniu.

### Z-5. `.env.example` i ujednolicenie zmiennych
**Cel:** przemianowanie `DB_*` → `POSTGRES_*`, usunięcie zahardkodowanych wartości z sekcji `environment:` w compose, dodanie `REDIS_URL`.
**Kryteria:** `docker compose config` renderuje poprawne wartości, nigdzie w `docker-compose.yml` nie ma literału hasła.

### Z-6a. `.dockerignore`
**Cel:** ograniczyć kontekst builda i nie wpuścić sekretów do obrazu. Plik nie istnieje, a Z-6 zawiera `COPY . .`.
**Kryteria:** `.env`, `.venv/`, `.git/`, `.idea/`, `__pycache__/` i cache'e narzędzi nie trafiają do obrazu. Rozmiar kontekstu builda (pierwsza linia wyjścia `docker build`) liczony w megabajtach, nie setkach megabajtów.
**Uwaga:**
- **Docker nie czyta `.gitignore`.** To, że plik jest ignorowany przez gita, nie znaczy nic dla `COPY`.
- `.env` w obrazie to nie tylko zły styl — warstwy obrazu są czytelne dla każdego, kto go pobierze, także po nadpisaniu pliku w późniejszej warstwie. Konfigurację wstrzykuje `env_file` w compose, w czasie uruchomienia, nie budowania.
- Skopiowany `.venv/` z hosta jest dodatkowo szkodliwy: zawiera ścieżki i binaria z Windows, więc mógłby przesłonić venv zbudowany w obrazie.

### Z-6. Naprawa `Dockerfile`
**Cel:** obraz, który faktycznie uruchamia aplikację.
**Do naprawienia:**
- `RUN apt-get update && apt-get install -y` — bez nazwy pakietu, nie instaluje niczego. Healthcheck woła `curl`, którego w `python:3.14-slim` nie ma. Albo doinstaluj `curl` i posprzątaj `/var/lib/apt/lists`, albo zrezygnuj z curla i oprzyj healthcheck na `python -c` z `urllib`.
- `--no-install-project` w `uv sync` można zostawić: przy projekcie wirtualnym (bez `[build-system]`) uv i tak nie instaluje samego projektu, a flaga jasno komunikuje intencję. Pakiet `app` jest importowalny, bo `WORKDIR /app` zawiera katalog `app/` i trafia na `sys.path`. Drugi `uv sync` po `COPY . .` **nie** jest potrzebny.
- `ENV PYTHONDONTWRITEBYTECODE 1` — składnia bez `=` jest przestarzała i generuje ostrzeżenie builda.
- Ustaw `PATH` na `/app/.venv/bin`, żeby `CMD` wołał `uvicorn` bezpośrednio, bez narzutu `uv run` przy każdym starcie.

**Kryteria:** `docker build .` przechodzi bez ostrzeżeń, a `docker run` na zbudowanym obrazie podnosi uvicorna.

### Z-7. `docker-compose.yml` — usługa Redis i healthchecki
**Cel:** trzy usługi, poprawne zależności startowe.
**Kryteria:** `docker compose up` → wszystkie trzy kontenery `healthy`. `api` startuje dopiero po `db` i `redis`.
**Uwaga:**
- Mount jest dziś `./app:/src/` — ani to workdir, ani lokalizacja kodu. Powinno być `./app:/app/app`.
- Redis nie potrzebuje wolumenu — to cache, nie źródło prawdy (sekcja 5 specyfikacji).
- Healthcheck api ma pytać o `/health`, nie `/health/ready` (uzasadnienie w sekcji 3).
- **Nie** zmieniaj mountu `postgres_data:/var/lib/postgresql/` na `/data`. Jest poprawny dla pg18: w Postgresie 18 `PGDATA` przeniesiono do `/var/lib/postgresql/18/docker`, a deklarowanym wolumenem jest katalog nadrzędny.

### Z-8. `app/core/db.py`, `app/core/redis.py` i `lifespan`
**Cel:** engine i klient tworzone raz przy starcie, zamykane przy zejściu, dostępne przez `app.state`.
**Kryteria:** start API przy wyłączonej bazie **nie** wywala procesu (silnik łączy się leniwie); logi zamknięcia pokazują zwolnienie zasobów.
**Uwaga:** `create_async_engine` nie łączy się od razu — nie próbuj „zweryfikować połączenia" w lifespanie, bo zrobisz z bazy twardą zależność startową i API nie wstanie, dopóki Postgres się nie podniesie. Od sprawdzania jest readiness.

### Z-9. `app/api/health.py`
**Cel:** router z `/health` i `/health/ready`, podpięty w `main.py`.
**Kryteria:** przy zatrzymanym kontenerze `redis` → `/health/ready` zwraca 503 z `{"redis": "unavailable"}`, a `/health` dalej 200.
**Uwaga:** owiń oba pingi w timeout. Zwracaj 503 tak, żeby ciało odpowiedzi zachowało pełny słownik stanów — samo `raise HTTPException(503)` zgubi informację, która zależność padła.

### Z-10. Testy
**Cel:** `tests/test_health.py` — liveness plus obie ścieżki readiness (200 i 503) na podstawionym `app.state`.
**Kryteria:** `uv run pytest` zielone przy wyłączonym Dockerze.

### Z-11. Workflow CI
**Cel:** `.github/workflows/ci.yml` wg sekcji 6.
**Kryteria:** push na branch → job zielony. Celowe złamanie formatowania → job czerwony.

---

## 8. Dług techniczny świadomie zostawiony

- Brak testów integracyjnych na żywych kontenerach — do rozważenia, gdy pojawi się warstwa danych.
- Kontener API działa jako root — do poprawy przed jakimkolwiek wdrożeniem poza lokalnym.
- Brak `db/schema.sql`, na który powołuje się sekcja 5 specyfikacji — powstanie w etapie 2.
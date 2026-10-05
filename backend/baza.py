"""
Pamięć narzędzia — SQLite.

Do tej pory zbadane firmy żyły wyłącznie w pamięci przeglądarki: odświeżenie strony
albo zamknięcie karty kasowało cały dzień pracy. Research jednej firmy to ~30 sekund
i kilka groszy, więc utrata dwudziestu to realna strata.

Dlaczego SQLite, a nie Postgres: to narzędzie jednego działu, jeden użytkownik naraz,
dane idą i tak do Pipedrive. Jeden plik, zero konfiguracji, wbudowany w Pythona.

UWAGA PRZY WDROŻENIU: dysk na Render jest efemeryczny — plik bazy zniknie przy
każdym deployu. Lokalnie to nie problem, ale przed wdrożeniem trzeba albo podpiąć
dysk trwały, albo przenieść się na Postgres. Zapisane w ROADMAP.

Plik trafia do .gitignore razem z fixtures — trzyma NIP-y, maile i telefony firm.
"""

from pathlib import Path
import json
import sqlite3
import threading
from datetime import datetime

PLIK = Path(__file__).resolve().parent / "dane.db"

# sqlite3 nie lubi dzielenia połączenia między wątkami, a Starlette woła nas
# z puli wątków (asyncio.to_thread). Jedno połączenie + zamek jest tu prostsze
# i zupełnie wystarczające przy jednym użytkowniku.
_zamek = threading.Lock()
_polaczenie: sqlite3.Connection | None = None


def _polacz() -> sqlite3.Connection:
    global _polaczenie
    if _polaczenie is None:
        _polaczenie = sqlite3.connect(PLIK, check_same_thread=False)
        _polaczenie.row_factory = sqlite3.Row
        _polaczenie.execute("PRAGMA journal_mode=WAL")
        _utworz(_polaczenie)
        _przenies_konkurent_na_ma_seo(_polaczenie)
        _dodaj_kategorie_do_kolejki(_polaczenie)
        _dodaj_etap_do_firm(_polaczenie)
    return _polaczenie


def _dodaj_kategorie_do_kolejki(db: sqlite3.Connection) -> None:
    """Migracja: kolumna `kategoria` w kolejce.

    CREATE TABLE IF NOT EXISTS nie dopisuje kolumn do tabeli, ktora juz istnieje —
    u kazdego, kto uzywal narzedzia wczesniej, kolejka zostalaby bez tego pola
    i kazdy INSERT konczylby sie bledem. Stad jawny ALTER, wykonywany raz.
    """
    kolumny = {r["name"] for r in db.execute("PRAGMA table_info(kolejka)")}
    if "kategoria" not in kolumny:
        db.execute("ALTER TABLE kolejka ADD COLUMN kategoria TEXT")
        db.commit()


# Etapy lejka partnera. Kolejność ma znaczenie: przycisk „dalej" przesuwa o jeden.
# „nie_teraz" stoi poza kolejnością — partner, który odmówił albo ucichł, nie może
# wisieć w „rozmowie" i zasłaniać tych, którymi trzeba się zająć.
ETAPY = ("zbadany", "material", "rozmowa", "wspolpraca", "nie_teraz")


def _dodaj_etap_do_firm(db: sqlite3.Connection) -> None:
    """Migracja: etap lejka, data jego zmiany i jednozdaniowa notatka.

    Osobne kolumny, nie pole w JSON-ie firmy: ponowny research nadpisuje `dane`
    w całości, a etap to nasza praca z partnerem — nie może zniknąć dlatego, że
    ktoś odświeżył dane z jego strony.
    """
    kolumny = {r["name"] for r in db.execute("PRAGMA table_info(firmy)")}
    for nazwa in ("etap", "etap_data", "notatka"):
        if nazwa not in kolumny:
            db.execute(f"ALTER TABLE firmy ADD COLUMN {nazwa} TEXT")
    db.commit()


def _przenies_konkurent_na_ma_seo(db: sqlite3.Connection) -> None:
    """Migracja: pole `konkurent` (osąd) → `ma_seo` (fakt).

    Firmy zbadane przed zmianą mają w JSON-ie `konkurent` i `konkurent_uzasadnienie`.
    Bez tego karta takiej firmy pokazywałaby pustą flagę, a eksport CSV pustą kolumnę.

    Przepisanie jest zachowawcze: `konkurent = true` znaczyło „SEO jest rdzeniem
    oferty", więc firma na pewno SEO ma. Ale `konkurent = false` NIE znaczyło „nie ma
    SEO" — znaczyło „SEO nie jest rdzeniem". Takiej firmy nie umiemy zaklasyfikować
    ze starych danych, więc zostawiamy ma_seo = false i mówimy o tym w seo_zakres,
    zamiast zmyślać. Ponowny research nadpisze to prawdziwą odpowiedzią.

    NIE dopisujemy tu niczego z listy usług. Próbowałem 04.09.2026 i było to błędne:
    „pozycjonowanie" jako jedna z dziesięciu pozycji nie znaczy, że firma sprzedaje
    SEO — Tebim i Devisu robią audyty, a nie usługę. Wartość ustala człowiek albo
    pełny research całej strony, nie dopasowanie słowa w liście.
    """
    do_zmiany = []
    for r in db.execute("SELECT url, dane FROM firmy"):
        d = json.loads(r["dane"])
        if "ma_seo" in d or "konkurent" not in d:
            continue
        byl_konkurentem = bool(d.pop("konkurent"))
        stare = (d.pop("konkurent_uzasadnienie", "") or "").strip()
        d["ma_seo"] = byl_konkurentem
        d["seo_zakres"] = (stare if byl_konkurentem else
                           "Dane sprzed zmiany pola — zbadaj firmę ponownie, "
                           "żeby ustalić, czy ma SEO w ofercie."
                           + (f" Wcześniejsza notatka: {stare}" if stare else ""))
        do_zmiany.append((json.dumps(d, ensure_ascii=False), r["url"]))

    if do_zmiany:
        db.executemany("UPDATE firmy SET dane = ? WHERE url = ?", do_zmiany)
        db.commit()
        print(f"[baza] migracja konkurent -> ma_seo: {len(do_zmiany)} firm")


def _utworz(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS firmy (
            url        TEXT PRIMARY KEY,
            tryb       TEXT NOT NULL DEFAULT 'partner',
            nazwa      TEXT,
            dane       TEXT NOT NULL,          -- cała firma jako JSON
            w_koszyku  INTEGER NOT NULL DEFAULT 0,
            zbadana    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_firmy_tryb ON firmy(tryb);

        CREATE TABLE IF NOT EXISTS audyty (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            url      TEXT NOT NULL,
            tryb     TEXT NOT NULL DEFAULT 'partner',
            dostawca TEXT,
            raport   TEXT NOT NULL,            -- gotowy raport jako JSON
            data     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audyty_url ON audyty(url);

        -- Kolejka kandydatow: firmy znalezione w wyszukiwaniu, jeszcze NIE zbadane.
        -- Bez niej wyniki znikaly razem z zapytaniem: user znajdowal 12 firm, badal
        -- trzy, a dziewiec przepadalo — lacznie z frazą, ktora je znalazla.
        -- Trzymamy tu tylko to, co dalo wyszukiwanie (nazwa, opis, tag SEO), bo
        -- reszta powstaje dopiero przy researchu.
        CREATE TABLE IF NOT EXISTS kolejka (
            url      TEXT PRIMARY KEY,
            tryb     TEXT NOT NULL DEFAULT 'partner',
            nazwa    TEXT,
            opis     TEXT,
            ma_seo   INTEGER NOT NULL DEFAULT 0,
            zrodlo   TEXT,                     -- wyszukiwarka / mapy
            zapytanie TEXT,                    -- fraza, ktora ja znalazla
            -- Kategoria, POD KTORA firma zostala znaleziona. Nie jest tym samym co
            -- `kategoria` zbadanej firmy: ta powstaje z researchu, a ta mowi tylko,
            -- czego wtedy szukalismy. Do czasu researchu to jedyna informacja
            -- porzadkujaca kolejke — bez niej 180 wpisow to jedna plaska lista.
            kategoria TEXT,
            dodana   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_kolejka_tryb ON kolejka(tryb);

        -- Biblioteka maili. Do tej pory draft żył tylko w przegladarce: zamkniecie
        -- karty kasowalo go bezpowrotnie, a napisanie maila kosztuje tokeny i czas.
        -- Trzymamy KAZDA wersje, nie tylko ostatnia — poprawianie w czacie ma sens
        -- wtedy, gdy da sie wrocic do poprzedniej, gdy nowa wyjdzie gorzej.
        CREATE TABLE IF NOT EXISTS maile (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            url      TEXT NOT NULL,          -- firma, do ktorej pisany
            tryb     TEXT NOT NULL DEFAULT 'partner',
            styl     TEXT,                   -- rzeczowy / partnerski / ekspercki / poprawiony
            tresc    TEXT NOT NULL,
            polecenie TEXT,                  -- co user kazal poprawic (puste przy pierwszej wersji)
            wyslany  INTEGER NOT NULL DEFAULT 0,
            data     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_maile_url ON maile(url);

        -- Wygenerowane dokumenty (materiał, raport z audytu). Do 05.10.2026 żyły
        -- tylko w przeglądarce: zamknięcie karty kasowało plik, a ponowne pobranie
        -- znaczyło nowy pomiar i nowe pisanie — czyli nowy rachunek. HTML trzymamy
        -- w całości, bo to dokładnie ten plik, który poszedł do klienta.
        CREATE TABLE IF NOT EXISTS dokumenty (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT NOT NULL,         -- strona, której dotyczy (klient)
            nazwa       TEXT,                  -- nazwa klienta
            partner_url TEXT,                  -- kto wysyła (pusty: wysyła ICEA)
            partner_nazwa TEXT,
            rodzaj      TEXT NOT NULL,         -- material / raport
            audyt_id    INTEGER,               -- pomiar, z którego powstał
            plik        TEXT,
            html        TEXT NOT NULL,
            data        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dokumenty_url ON dokumenty(url);
    """)
    db.commit()


def _teraz() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ══════════════════════════════════════════════════════════════════
#  FIRMY
# ══════════════════════════════════════════════════════════════════
def zapisz_firme(firma: dict, tryb: str = "partner") -> None:
    """Wstawia albo aktualizuje. Klucz to URL, bo ta sama firma zbadana ponownie
    ma nadpisać stare dane, a nie utworzyć duplikat. `w_koszyku` celowo NIE jest
    tu ruszane — ponowny research nie może wyrzucić firmy z eksportu."""
    url = (firma.get("url") or "").strip()
    if not url:
        return
    with _zamek:
        db = _polacz()
        db.execute("""
            INSERT INTO firmy (url, tryb, nazwa, dane, zbadana)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                tryb = excluded.tryb,
                nazwa = excluded.nazwa,
                dane = excluded.dane,
                zbadana = excluded.zbadana
        """, (url, tryb, firma.get("nazwa") or "",
              json.dumps(firma, ensure_ascii=False), _teraz()))
        db.commit()


def firmy(tryb: str | None = None) -> list[dict]:
    with _zamek:
        db = _polacz()
        if tryb:
            w = db.execute("SELECT * FROM firmy WHERE tryb = ? ORDER BY zbadana", (tryb,))
        else:
            w = db.execute("SELECT * FROM firmy ORDER BY zbadana")
        # Firma bez etapu to firma zbadana — od dnia researchu.
        return [{**json.loads(r["dane"]), "tryb": r["tryb"],
                 "w_koszyku": bool(r["w_koszyku"]), "zbadana": r["zbadana"],
                 "etap": r["etap"] or "zbadany", "etap_data": r["etap_data"] or r["zbadana"],
                 "notatka": r["notatka"] or ""}
                for r in w.fetchall()]


def usun_firme(url: str) -> None:
    with _zamek:
        db = _polacz()
        db.execute("DELETE FROM firmy WHERE url = ?", (url,))
        db.commit()


def ustaw_koszyk(url: str, w_koszyku: bool) -> None:
    with _zamek:
        db = _polacz()
        db.execute("UPDATE firmy SET w_koszyku = ? WHERE url = ?",
                   (1 if w_koszyku else 0, url))
        db.commit()


def ustaw_etap(url: str, etap: str | None = None, notatka: str | None = None) -> dict:
    """Zmienia etap (i datę zmiany) albo samą notatkę. Ten sam etap kliknięty
    drugi raz nie przestawia daty — „od 12 dni w rozmowie" ma zostać prawdą."""
    if etap is not None and etap not in ETAPY:
        raise ValueError(f"Nieznany etap: {etap}")
    with _zamek:
        db = _polacz()
        r = db.execute("SELECT etap, etap_data, zbadana FROM firmy WHERE url = ?",
                       (url,)).fetchone()
        if not r:
            raise ValueError("Nie ma takiej firmy.")
        if etap is not None and etap != (r["etap"] or "zbadany"):
            db.execute("UPDATE firmy SET etap = ?, etap_data = ? WHERE url = ?",
                       (etap, _teraz(), url))
        if notatka is not None:
            db.execute("UPDATE firmy SET notatka = ? WHERE url = ?",
                       (notatka.strip()[:300], url))
        db.commit()
        r = db.execute("SELECT etap, etap_data, zbadana, notatka FROM firmy WHERE url = ?",
                       (url,)).fetchone()
        return {"etap": r["etap"] or "zbadany", "etap_data": r["etap_data"] or r["zbadana"],
                "notatka": r["notatka"] or ""}


# ══════════════════════════════════════════════════════════════════
#  AUDYTY
# ══════════════════════════════════════════════════════════════════
def zapisz_audyt(url: str, raport: dict, tryb: str = "partner",
                 dostawca: str = "") -> int:
    """Historia, nie nadpisywanie: audyt tej samej domeny sprzed miesiąca i dzisiejszy
    to dwa różne pomiary i porównanie ich jest właśnie tym, co pokazuje postęp.
    Zwraca id — dokument zrobiony z tego pomiaru zapamiętuje, z którego powstał."""
    with _zamek:
        db = _polacz()
        c = db.execute(
            "INSERT INTO audyty (url, tryb, dostawca, raport, data) VALUES (?, ?, ?, ?, ?)",
            (url, tryb, dostawca, json.dumps(raport, ensure_ascii=False), _teraz()))
        db.commit()
        return c.lastrowid


# Nazwa badanej firmy i partner wyciągane z JSON-a raportu przez SQLite, nie
# w Pythonie — lista ma zostać lekka. Audyt klienta partnera zapisuje się pod
# adresem KLIENTA (trafika.pl), więc bez partnera w nagłówku widok „Audyty" nie
# wiedziałby, do której karty partnera prowadzić.
_NAGLOWKI_AUDYTU = ("SELECT id, url, tryb, dostawca, data, "
                    "json_extract(raport, '$.firma.nazwa') AS nazwa, "
                    "json_extract(raport, '$.partner.nazwa') AS partner_nazwa, "
                    "json_extract(raport, '$.partner.url') AS partner_url FROM audyty ")


def audyty(url: str | None = None, limit: int = 50) -> list[dict]:
    """Same nagłówki, bez treści raportów — lista nie potrzebuje megabajtów JSON-a."""
    with _zamek:
        db = _polacz()
        if url:
            w = db.execute(_NAGLOWKI_AUDYTU + "WHERE url = ? ORDER BY data DESC LIMIT ?",
                           (url, limit))
        else:
            w = db.execute(_NAGLOWKI_AUDYTU + "ORDER BY data DESC LIMIT ?", (limit,))
        return [dict(r) for r in w.fetchall()]


def audyt(id_: int) -> dict | None:
    with _zamek:
        db = _polacz()
        r = db.execute("SELECT raport FROM audyty WHERE id = ?", (id_,)).fetchone()
        return json.loads(r["raport"]) if r else None


# ══════════════════════════════════════════════════════════════════
#  DOKUMENTY
# ══════════════════════════════════════════════════════════════════
def zapisz_dokument(url: str, nazwa: str, rodzaj: str, html: str, plik: str,
                    partner: dict | None = None, audyt_id: int | None = None) -> int:
    partner = partner or {}
    with _zamek:
        db = _polacz()
        c = db.execute(
            "INSERT INTO dokumenty (url, nazwa, partner_url, partner_nazwa, rodzaj, "
            "audyt_id, plik, html, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (url, nazwa, partner.get("url") or "", partner.get("nazwa") or "", rodzaj,
             audyt_id, plik, html, _teraz()))
        db.commit()
        return c.lastrowid


def dokumenty(limit: int = 200) -> list[dict]:
    """Same nagłówki — pliki mają po pół megabajta (zdjęcia osadzone w HTML)."""
    with _zamek:
        db = _polacz()
        w = db.execute("SELECT id, url, nazwa, partner_url, partner_nazwa, rodzaj, "
                       "audyt_id, plik, data FROM dokumenty ORDER BY data DESC LIMIT ?",
                       (limit,))
        return [dict(r) for r in w.fetchall()]


def dokument(id_: int) -> dict | None:
    with _zamek:
        db = _polacz()
        r = db.execute("SELECT * FROM dokumenty WHERE id = ?", (id_,)).fetchone()
        return dict(r) if r else None


def statystyki() -> dict:
    with _zamek:
        db = _polacz()
        f = db.execute("SELECT tryb, COUNT(*) n FROM firmy GROUP BY tryb").fetchall()
        a = db.execute("SELECT COUNT(*) n FROM audyty").fetchone()
        return {"firmy": {r["tryb"]: r["n"] for r in f}, "audyty": a["n"] if a else 0}


# ══════════════════════════════════════════════════════════════════
#  KOLEJKA — kandydaci przed researchem
# ══════════════════════════════════════════════════════════════════
def dodaj_do_kolejki(firmy: list[dict], tryb: str = "partner",
                     zrodlo: str = "", zapytanie: str = "",
                     kategoria: str = "") -> int:
    """Dopisuje kandydatow. Zwraca ile REALNIE doszlo.

    Firma juz zbadana do kolejki nie trafia — kolejka ma pokazywac robote do
    zrobienia, a nie mieszac jej ze zrobiona. Powtorne dodanie tego samego
    adresu nie nadpisuje wpisu: liczy sie moment, w ktorym trafil na liste.
    """
    if not firmy:
        return 0
    with _zamek:
        db = _polacz()
        zbadane = {r["url"] for r in db.execute("SELECT url FROM firmy")}
        doszlo = 0
        for f in firmy:
            url = (f.get("url") or "").strip()
            if not url or url in zbadane:
                continue
            # Kategoria z wiersza wygrywa z ta podana dla calej partii: przy
            # imporcie z jednego zrodla kazda firma moze byc z innej branzy.
            kat = (f.get("kategoria") or kategoria or "").strip()
            kur = db.execute("""
                INSERT INTO kolejka (url, tryb, nazwa, opis, ma_seo, zrodlo,
                                     zapytanie, kategoria, dodana)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO NOTHING
            """, (url, tryb, f.get("nazwa") or "", (f.get("opis") or "")[:600],
                  1 if f.get("ma_seo") else 0, zrodlo, zapytanie, kat, _teraz()))
            doszlo += kur.rowcount or 0
        db.commit()
        return doszlo


def kolejka(tryb: str | None = None) -> list[dict]:
    """Kolejka z nazwami FIRM, nie tytułami stron.

    Nazwę liczymy przy odczycie, a nie tylko przy zapisie: w bazie leżą wpisy
    sprzed poprawki, z tytułami artykułów zamiast nazw. Przeliczenie jest
    idempotentne — nazwa już poprawna („Adlife" na adlife.pl) przechodzi
    bez zmian — więc nie potrzeba osobnej migracji.
    """
    from nazwy import nazwa_firmy
    with _zamek:
        db = _polacz()
        if tryb:
            w = db.execute("SELECT * FROM kolejka WHERE tryb = ? ORDER BY dodana DESC", (tryb,))
        else:
            w = db.execute("SELECT * FROM kolejka ORDER BY dodana DESC")
        return [{**dict(r), "ma_seo": bool(r["ma_seo"]),
                 "nazwa": nazwa_firmy(r["nazwa"] or "", r["url"])} for r in w.fetchall()]


def usun_z_kolejki(url: str) -> None:
    with _zamek:
        db = _polacz()
        db.execute("DELETE FROM kolejka WHERE url = ?", (url,))
        db.commit()


# ══════════════════════════════════════════════════════════════════
#  MAILE — biblioteka draftow
# ══════════════════════════════════════════════════════════════════
def zapisz_mail(url: str, styl: str, tresc: str, tryb: str = "partner",
                polecenie: str = "") -> int:
    """Dopisuje wersje maila. Zwraca jej id — front potrzebuje go do poprawiania."""
    with _zamek:
        db = _polacz()
        kur = db.execute(
            "INSERT INTO maile (url, tryb, styl, tresc, polecenie, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (url, tryb, styl, tresc, polecenie, _teraz()))
        db.commit()
        return kur.lastrowid


def maile(url: str | None = None, tryb: str | None = None, limit: int = 200) -> list[dict]:
    """Najnowsze u gory — biblioteka sluzy do siegania po to, co wlasnie napisane."""
    with _zamek:
        db = _polacz()
        warunki, param = [], []
        if url:
            warunki.append("url = ?"); param.append(url)
        if tryb:
            warunki.append("tryb = ?"); param.append(tryb)
        gdzie = ("WHERE " + " AND ".join(warunki)) if warunki else ""
        param.append(limit)
        w = db.execute(f"SELECT * FROM maile {gdzie} ORDER BY id DESC LIMIT ?", param)
        return [{**dict(r), "wyslany": bool(r["wyslany"])} for r in w.fetchall()]


def mail(id_: int) -> dict | None:
    with _zamek:
        db = _polacz()
        r = db.execute("SELECT * FROM maile WHERE id = ?", (id_,)).fetchone()
        return {**dict(r), "wyslany": bool(r["wyslany"])} if r else None


def oznacz_wyslany(id_: int, wyslany: bool = True) -> None:
    """Zaznaczenie „wyslany" to jedyny slad, ze mail poszedl — narzedzie nie ma
    dostepu do skrzynki i nie bedzie udawac, ze wie wiecej."""
    with _zamek:
        db = _polacz()
        db.execute("UPDATE maile SET wyslany = ? WHERE id = ?", (1 if wyslany else 0, id_))
        db.commit()


def usun_mail(id_: int) -> None:
    with _zamek:
        db = _polacz()
        db.execute("DELETE FROM maile WHERE id = ?", (id_,))
        db.commit()

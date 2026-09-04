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
    return _polaczenie


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
        return [{**json.loads(r["dane"]), "tryb": r["tryb"],
                 "w_koszyku": bool(r["w_koszyku"]), "zbadana": r["zbadana"]}
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


# ══════════════════════════════════════════════════════════════════
#  AUDYTY
# ══════════════════════════════════════════════════════════════════
def zapisz_audyt(url: str, raport: dict, tryb: str = "partner",
                 dostawca: str = "") -> None:
    """Historia, nie nadpisywanie: audyt tej samej domeny sprzed miesiąca i dzisiejszy
    to dwa różne pomiary i porównanie ich jest właśnie tym, co pokazuje postęp."""
    with _zamek:
        db = _polacz()
        db.execute(
            "INSERT INTO audyty (url, tryb, dostawca, raport, data) VALUES (?, ?, ?, ?, ?)",
            (url, tryb, dostawca, json.dumps(raport, ensure_ascii=False), _teraz()))
        db.commit()


def audyty(url: str | None = None, limit: int = 50) -> list[dict]:
    """Same nagłówki, bez treści raportów — lista nie potrzebuje megabajtów JSON-a."""
    with _zamek:
        db = _polacz()
        if url:
            w = db.execute("SELECT id, url, tryb, dostawca, data FROM audyty "
                           "WHERE url = ? ORDER BY data DESC LIMIT ?", (url, limit))
        else:
            w = db.execute("SELECT id, url, tryb, dostawca, data FROM audyty "
                           "ORDER BY data DESC LIMIT ?", (limit,))
        return [dict(r) for r in w.fetchall()]


def audyt(id_: int) -> dict | None:
    with _zamek:
        db = _polacz()
        r = db.execute("SELECT raport FROM audyty WHERE id = ?", (id_,)).fetchone()
        return json.loads(r["raport"]) if r else None


def statystyki() -> dict:
    with _zamek:
        db = _polacz()
        f = db.execute("SELECT tryb, COUNT(*) n FROM firmy GROUP BY tryb").fetchall()
        a = db.execute("SELECT COUNT(*) n FROM audyty").fetchone()
        return {"firmy": {r["tryb"]: r["n"] for r in f}, "audyty": a["n"] if a else 0}

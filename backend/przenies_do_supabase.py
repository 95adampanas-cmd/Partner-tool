"""
Jednorazowe przeniesienie danych z dane.db (SQLite) do Supabase.

    python przenies_do_supabase.py

Bierze adres z DATABASE_URL w .env i NIGDY go nie wypisuje. Przenosi wszystkie
tabele z tymi samymi id — dokumenty wskazują na audyty po audyt_id, więc nowa
numeracja zerwałaby to powiązanie.

Odmawia, jeśli w Supabase już coś jest: drugi przebieg zdublowałby audyty,
maile i dokumenty (te tabele nie mają naturalnego klucza, tylko licznik).
dane.db zostaje nietknięte — to kopia zapasowa.
"""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

KATALOG = Path(__file__).resolve().parent
load_dotenv(KATALOG / ".env", override=True)

import baza  # noqa: E402 — po wczytaniu .env


def main() -> int:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("Brak DATABASE_URL w .env — nie ma dokąd przenosić.")
        return 1
    if not baza.PLIK.exists():
        print(f"Brak pliku {baza.PLIK.name} — nie ma czego przenosić.")
        return 1

    zrodlo = sqlite3.connect(baza.PLIK)
    zrodlo.row_factory = sqlite3.Row
    cel = baza._polacz()          # tworzy tabele w Supabase, jeśli ich nie ma
    if not baza._postgres(cel):
        print("baza.py nie połączyła się z Postgresem — przerywam.")
        return 1

    niepuste = [t for t in baza.TABELE
                if cel.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]]
    if niepuste:
        print(f"W Supabase są już dane ({', '.join(niepuste)}). Przerywam, żeby "
              f"niczego nie zdublować.")
        return 1

    for tabela in baza.TABELE:
        kol_zrodla = [r["name"] for r in zrodlo.execute(f"PRAGMA table_info({tabela})")]
        kol_celu = {r["column_name"] for r in cel.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?", (tabela,))}
        # Tylko kolumny obecne po obu stronach: stary plik może nie mieć
        # najnowszych, a w Supabase są już wszystkie.
        kolumny = [k for k in kol_zrodla if k in kol_celu]
        wiersze = [tuple(r[k] for k in kolumny)
                   for r in zrodlo.execute(f"SELECT {', '.join(kolumny)} FROM {tabela}")]
        if wiersze:
            cel.executemany(f"INSERT INTO {tabela} ({', '.join(kolumny)}) "
                            f"VALUES ({', '.join('?' * len(kolumny))})", wiersze)
        if "id" in kolumny:
            # Id wstawione ręcznie nie przesuwają licznika — bez tego pierwszy
            # nowy audyt dostałby id = 1 i zderzył się z przeniesionym.
            cel.execute(f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
                        f"GREATEST((SELECT MAX(id) FROM {tabela}), 1))", ())
        jest = cel.execute(f"SELECT COUNT(*) AS n FROM {tabela}").fetchone()["n"]
        znak = "OK  " if jest == len(wiersze) else "BŁĄD"
        print(f"  {znak} | {tabela:<10} SQLite {len(wiersze):>5}  →  Supabase {jest:>5}")

    zrodlo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

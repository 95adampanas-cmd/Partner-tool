"""
Test bazy na prawdziwym Postgresie (Supabase).

    python test_baza_pg.py

test_filtr.py sprawdza baza.py wyłącznie na SQLite. Tu te same operacje idą
do Supabase — ale w schemacie tymczasowym, kasowanym na końcu, więc prawdziwe
tabele zostają nietknięte. Odpalać po każdej zmianie SQL-a w baza.py i przed
wdrożeniem. Adresu bazy nie wypisuje nigdy.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

import baza  # noqa: E402

SCHEMAT = "test_partner_tool"


def _do_schematu(polaczenie) -> None:
    polaczenie.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMAT}; SET search_path TO {SCHEMAT}")


def main() -> int:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("Brak DATABASE_URL w .env — nie ma czego testować.")
        return 1
    baza._Postgres.przygotuj = staticmethod(_do_schematu)
    bledy = 0

    def sprawdz(ok, opis):
        nonlocal bledy
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
        bledy += not ok

    try:
        db = baza._polacz()
        sprawdz(baza._postgres(db), "połączenie idzie do Postgresa")
        schemat = db.execute("SELECT current_schema() AS s", ()).fetchone()["s"]
        sprawdz(schemat == SCHEMAT, "test pisze do schematu tymczasowego")
        if schemat != SCHEMAT:
            return 1

        aid = baza.zapisz_audyt("https://trafika.pl", {"firma": {"nazwa": "Trafika"},
                                "partner": {"nazwa": "Tebim", "url": "https://tebim.pro"}},
                                "partner", "material")
        did = baza.zapisz_dokument("https://trafika.pl", "Trafika", "material",
                                   "<html>plik</html>", "material-trafika.html",
                                   {"nazwa": "Tebim", "url": "https://tebim.pro"}, aid)
        a = baza.audyty()
        sprawdz(isinstance(aid, int) and a[0]["nazwa"] == "Trafika"
                and a[0]["partner_url"] == "https://tebim.pro"
                and baza.audyt(aid)["partner"]["nazwa"] == "Tebim",
                "audyt: id po zapisie, nazwa i partner wyciągnięte z JSON-a")
        lista = baza.dokumenty()
        sprawdz(len(lista) == 1 and "html" not in lista[0] and lista[0]["audyt_id"] == aid
                and baza.dokument(did)["html"] == "<html>plik</html>"
                and baza.dokument(999999) is None, "dokument: zapis, lista bez HTML, pobranie")

        baza.zapisz_firme({"url": "https://tebim.pro", "nazwa": "Tebim"})
        e1 = baza.ustaw_etap("https://tebim.pro", "material")
        e2 = baza.ustaw_etap("https://tebim.pro", "material", "wysłany 05.10")
        baza.zapisz_firme({"url": "https://tebim.pro", "nazwa": "Tebim", "opis": "nowy"})
        baza.ustaw_koszyk("https://tebim.pro", True)
        f = baza.firmy()[0]
        sprawdz(f["etap"] == "material" and e2["etap_data"] == e1["etap_data"]
                and f["notatka"] == "wysłany 05.10" and f["opis"] == "nowy" and f["w_koszyku"],
                "firma: upsert, etap i notatka zostają po researchu, koszyk")

        n = baza.dodaj_do_kolejki([{"url": "https://a.pl", "nazwa": "A"},
                                   {"url": "https://a.pl", "nazwa": "A2"},
                                   {"url": "https://tebim.pro"}], kategoria="sklepy")
        k = baza.kolejka()
        sprawdz(n == 1 and len(k) == 1 and k[0]["kategoria"] == "sklepy"
                and k[0]["ma_seo"] is False, "kolejka: bez duplikatów i bez zbadanych")

        mid = baza.zapisz_mail("https://tebim.pro", "rzeczowy", "Dzień dobry")
        baza.oznacz_wyslany(mid)
        sprawdz(baza.mail(mid)["wyslany"] is True and len(baza.maile("https://tebim.pro")) == 1,
                "maile: zapis i oznaczenie wysłanego")
        sprawdz(baza.statystyki() == {"firmy": {"partner": 1}, "audyty": 1}, "statystyki")

        # Zerwane połączenie (pooler zamyka bezczynne) — następne zapytanie
        # ma przejść na nowym, a nie wywalić błąd 500.
        db.c.close()
        sprawdz(len(baza.firmy()) == 1, "po zerwanym połączeniu baza łączy się ponownie")
    finally:
        if baza._polaczenie is not None:
            baza._polaczenie.execute(f"DROP SCHEMA IF EXISTS {SCHEMAT} CASCADE")
            baza._polaczenie.close()
    print(f"\n{'Wszystko OK' if not bledy else f'{bledy} błędów'}")
    return 1 if bledy else 0


if __name__ == "__main__":
    sys.exit(main())

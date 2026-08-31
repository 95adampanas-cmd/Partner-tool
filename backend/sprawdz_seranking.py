"""
Sonda do SE Ranking — pokazuje, jak NAPRAWDĘ wyglądają odpowiedzi ich API.

Po co: moduł seranking.py jest napisany na podstawie dokumentacji, a nie realnych
odpowiedzi. Zgadywanie struktury danych to dokładnie ta klasa błędu, przez którą
raport potrafił pokazać same zera. Zanim uznamy parsery za działające, musimy
zobaczyć prawdziwy JSON.

Uruchomienie (z folderu backend/):
    python sprawdz_seranking.py elektromaniacy.pl

Zużywa ok. 500 kredytów z trialu (100 000), czyli pół procenta.
Każda odpowiedź ląduje w fixtures/, więc parsery dopracujemy już offline.
"""

import io
import json
import sys

import seranking as sr

DOMENA = sys.argv[1] if len(sys.argv) > 1 else "elektromaniacy.pl"
RAPORT = "_seranking.txt"


def opisz(nazwa: str, dane, glebokosc: int = 0) -> list[str]:
    """Wypisuje strukturę odpowiedzi: nazwy pól i typy, bez zalewania wartościami."""
    wciecie = "  " * glebokosc
    if isinstance(dane, dict):
        out = [f"{wciecie}{nazwa}: obiekt ({len(dane)} pól)"]
        for k, v in list(dane.items())[:14]:
            if isinstance(v, (dict, list)) and glebokosc < 2:
                out += opisz(k, v, glebokosc + 1)
            else:
                skrot = str(v)[:52]
                out.append(f"{wciecie}  {k} = {skrot}")
        return out
    if isinstance(dane, list):
        out = [f"{wciecie}{nazwa}: lista ({len(dane)} pozycji)"]
        if dane:
            out += opisz("[0]", dane[0], glebokosc + 1)
        return out
    return [f"{wciecie}{nazwa} = {str(dane)[:52]}"]


PROBY = [
    ("Przegląd domeny", "domain/overview/db", {"source": sr.KRAJ_PL, "domain": DOMENA}),
    ("Frazy", "domain/keywords",
     {"source": sr.KRAJ_PL, "domain": DOMENA, "limit": 5}),
    ("Konkurenci", "domain/competitors",
     {"source": sr.KRAJ_PL, "domain": DOMENA, "limit": 5}),
    ("Podstrony", "domain/pages",
     {"source": sr.KRAJ_PL, "target": DOMENA, "scope": "domain", "limit": 5}),
    ("Marka", "ai-search/discover-brand", {"domain": DOMENA}),
    ("Prompty AI Overview", "ai-search/prompts-by-target",
     {"target": DOMENA, "engine": "ai-overview", "limit": 3}),
]


def main() -> None:
    wynik = [f"SONDA SE RANKING — {DOMENA}", "=" * 64, ""]
    for tytul, sciezka, params in PROBY:
        wynik.append(f"### {tytul}   ({sciezka})")
        try:
            odp = sr._get(sciezka, params, f"sonda_{sciezka.replace('/', '_')}")
            wynik += opisz("odpowiedź", odp)
        except Exception as e:
            wynik.append(f"  BŁĄD: {type(e).__name__}: {str(e)[:220]}")
        wynik.append("")
    io.open(RAPORT, "w", encoding="utf-8").write("\n".join(wynik))
    print(f"gotowe -> {RAPORT}")


if __name__ == "__main__":
    main()

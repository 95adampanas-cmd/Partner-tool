"""
Przepisanie starej marki w zapisanych szkicach maili — jednorazowo, po zmianie
Last Agency → ICEA.

DLACZEGO W OGÓLE. Prompty i profil zmieniły się od razu, więc każdy NOWY mail
wychodzi już pod nową marką. W bazie leżą jednak szkice wygenerowane wcześniej
i one się nie przepiszą same. Szkic w zakładce „Maile" jest po to, żeby go
skopiować i wysłać — wysłany z nazwą, która już nie istnieje, jest gorszy niż
brak szkicu, bo wygląda na kopiuj-wklej z cudzego narzędzia.

TO NIE JEST FAŁSZOWANIE HISTORII. W tabeli `maile` leżą szkice do wysłania, a nie
zapis tego, co zostało wysłane — narzędzie nie wysyła maili. Zmieniamy nazwę
agencji w tekście, nie treść propozycji.

Kopia bazy leci przed pierwszym zapisem, tak samo jak przy migracji kategorii.
Domyślnie skrypt tylko POKAZUJE, co by zrobił:

    python migracja_marki.py            # podgląd
    python migracja_marki.py --zapisz   # przepisanie szkiców
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

BAZA = Path(__file__).resolve().parent / "dane.db"
KOPIA = BAZA.with_suffix(".db.przed-marka-icea")

# Kolejność jak przy zamianie w kodzie: najpierw adresy, potem nazwa. Odwrotnie
# „lastagency.pl" zostałoby rozbite na „ICEA.pl".
ZAMIANY = [
    ("lastagency.pl", "grupa-icea.pl"),
    ("Last Agency", "ICEA"),
    ("LAST AGENCY", "ICEA"),
    ("lastagency", "grupa-icea"),
]


def przepisz(tekst: str) -> str:
    for stare, nowe in ZAMIANY:
        tekst = tekst.replace(stare, nowe)
    return tekst


def main() -> int:
    zapis = "--zapisz" in sys.argv

    db = sqlite3.connect(BAZA)
    db.row_factory = sqlite3.Row
    wiersze = db.execute("SELECT id, styl, tresc FROM maile").fetchall()

    do_zmiany = [w for w in wiersze if przepisz(w["tresc"]) != w["tresc"]]

    print("=" * 74)
    print(f"Szkiców maili w bazie: {len(wiersze)} | ze starą marką: {len(do_zmiany)}")
    print("=" * 74)

    for w in do_zmiany[:5]:
        stary = w["tresc"]
        for stare, _ in ZAMIANY:
            if stare in stary:
                i = stary.index(stare)
                print(f"  #{w['id']:<4} {w['styl']:<12} …{stary[max(0, i - 45):i + 45]}…")
                break
    if len(do_zmiany) > 5:
        print(f"  … i {len(do_zmiany) - 5} dalszych")

    if not do_zmiany:
        print("Nic do zrobienia.")
        return 0

    if not zapis:
        print("=" * 74)
        print("Nic nie zapisano. Uruchom z --zapisz, żeby przepisać szkice.")
        return 0

    if not KOPIA.exists():
        shutil.copy2(BAZA, KOPIA)
        print(f"Kopia bazy: {KOPIA.name}")

    for w in do_zmiany:
        db.execute("UPDATE maile SET tresc = ? WHERE id = ?", (przepisz(w["tresc"]), w["id"]))
    db.commit()

    zostalo = sum(1 for w in db.execute("SELECT tresc FROM maile")
                  if przepisz(w["tresc"]) != w["tresc"])
    print("=" * 74)
    print(f"Przepisano: {len(do_zmiany)} | zostało ze starą marką: {zostalo}")
    return 1 if zostalo else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Krajowy Rejestr Sądowy — oficjalne dane spółki.

CO TO DAJE. Dane ze stopki strony bywają niepełne albo nieaktualne; tu mamy
źródło urzędowe: pełną nazwę prawną, NIP, REGON, adres rejestrowy, datę wpisu
i klasyfikację PKD. Dla rekordu w Pipedrive to różnica między „Devisu" a
„DEVISU SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ, NIP 9372668199".

CZEGO NIE DAJE — i to ograniczenie warto znać, zanim ktoś zaplanuje na tym funkcję:

  1. API przyjmuje WYŁĄCZNIE numer KRS. Sprawdzone empirycznie 11.09.2026:
     po NIP-ie, po nazwie i po REGON-ie zwraca 404. Nie da się więc „znaleźć
     firmy w KRS" — trzeba już mieć jej numer. U nas bierze się on ze stron
     prawnych firmy (patrz dane_rejestrowe w app.py).

  2. Nazwiska zarządu są ZAMASKOWANE (K*******, D*****) — otwarte API anonimizuje
     je ze względu na RODO. Osoby decyzyjnej stąd nie wyciągniemy.

  3. KRS obejmuje spółki. Jednoosobowa działalność jest w CEIDG — osobny rejestr,
     osobne API. Część agencji to JDG, więc trafność nigdy nie będzie pełna.

Rejestr jest publiczny i darmowy, bez klucza i bez rejestracji.
"""

from pathlib import Path
import json
import re

import requests

ENDPOINT = "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{numer}"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# P = rejestr przedsiębiorców, S = stowarzyszeń. Agencje siedzą w P; gdyby numer
# tam nie istniał, próbujemy S, zanim uznamy, że numeru nie ma.
REJESTRY = ("P", "S")

RE_KRS = re.compile(r"^[0-9]{10}$")


class BladKRS(Exception):
    """Awaria rejestru. Rzucamy zamiast zwracać pustkę — brak danych i brak
    odpowiedzi to dwie różne rzeczy, a mylenie ich kosztowało nas już raport
    pełen zer."""


def poprawny_numer(numer: str) -> str | None:
    """KRS to dokładnie 10 cyfr. Bywa zapisany ze spacjami albo bez wiodących zer."""
    czysty = re.sub(r"[^0-9]", "", numer or "")
    if not czysty:
        return None
    czysty = czysty.zfill(10)
    return czysty if RE_KRS.match(czysty) else None


def _adres(a: dict) -> str:
    """Adres w jednej linii, w kolejności czytelnej dla człowieka."""
    ulica = " ".join(x for x in (a.get("ulica"), a.get("nrDomu")) if x)
    if a.get("nrLokalu"):
        ulica += "/" + a["nrLokalu"]
    miasto = " ".join(x for x in (a.get("kodPocztowy"), a.get("miejscowosc")) if x)
    return ", ".join(x for x in (ulica, miasto) if x)


def odpis(numer: str) -> dict | None:
    """Aktualny odpis z KRS. None = numeru nie ma w żadnym rejestrze.

    Odpowiedź zapisujemy do fixtures — ta sama zasada, co przy płatnych API:
    parser rozwijamy offline, na prawdziwych danych.
    """
    nr = poprawny_numer(numer)
    if not nr:
        return None

    ostatni_blad = None
    for rejestr in REJESTRY:
        try:
            r = requests.get(ENDPOINT.format(numer=nr), timeout=20,
                             params={"rejestr": rejestr, "format": "json"})
        except Exception as e:
            ostatni_blad = f"{type(e).__name__}: {e}"
            continue
        if r.status_code == 404:
            continue                      # nie ma w tym rejestrze — próbujemy następnego
        if r.status_code != 200:
            ostatni_blad = f"HTTP {r.status_code}"
            continue
        try:
            dane = r.json()
        except Exception:
            ostatni_blad = "odpowiedź nie jest JSON-em"
            continue

        try:
            FIXTURES.mkdir(exist_ok=True)
            (FIXTURES / f"krs_{nr}.json").write_text(
                json.dumps(dane, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass                          # zapis fixture nie może wywrócić researchu

        return _wyciagnij(dane)

    if ostatni_blad:
        raise BladKRS(f"Rejestr KRS nie odpowiedział poprawnie ({ostatni_blad}).")
    return None                           # 404 w obu rejestrach = numeru po prostu nie ma


def _wyciagnij(dane: dict) -> dict:
    """Z pełnego odpisu bierzemy tylko to, co trafia na kartę firmy."""
    o = (dane.get("odpis") or {})
    d = (o.get("dane") or {})
    dz1 = d.get("dzial1") or {}
    podmiot = dz1.get("danePodmiotu") or {}
    ident = podmiot.get("identyfikatory") or {}
    adres = (dz1.get("siedzibaIAdres") or {}).get("adres") or {}

    pkd = ((d.get("dzial3") or {}).get("przedmiotDzialalnosci") or {})
    glowne = (pkd.get("przedmiotPrzewazajacejDzialalnosci") or [{}])[0]

    # REGON w odpisie bywa dopełniony zerami do 14 znaków — zostawiamy 9, bo tak
    # zapisuje się go w dokumentach i tak wygląda w CSV.
    regon = (ident.get("regon") or "").strip()
    if len(regon) == 14 and regon.endswith("00000"):
        regon = regon[:9]

    return {
        "krs": (o.get("naglowekA") or {}).get("numerKRS") or "",
        "nazwa_prawna": podmiot.get("nazwa") or "",
        "forma_prawna": podmiot.get("formaPrawna") or "",
        "nip": ident.get("nip") or "",
        "regon": regon,
        "adres": _adres(adres),
        "miasto": adres.get("miejscowosc") or "",
        "data_rejestracji": (o.get("naglowekA") or {}).get("dataRejestracjiWKRS") or "",
        "pkd": (glowne.get("opis") or "").strip(),
    }

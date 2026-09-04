"""
Google Maps jako ŹRÓDŁO ADRESÓW — nic więcej.

PO CO. Tavily znajduje to, co jest wypozycjonowane. Firma, która nie inwestuje
w SEO, po prostu tam nie wychodzi — a przy ścieżce KLIENTÓW to właśnie ona jest
najlepszym tropem („im słabsza widoczność, tym większy potencjał", PRD).
Na Mapach jest każdy, kto ma wizytówkę, niezależnie od widoczności.

CO POBIERAMY. Wyłącznie `id` i `websiteUri`. Ani nazwy, ani adresu, ani telefonu,
ani oceny — mimo że Google by je oddał w tym samym zapytaniu i za te same pieniądze.

Powód jest regulaminowy, nie oszczędnościowy. Zasady Places API zabraniają
przechowywania treści z Places we własnej bazie; wyjątkiem jest `place_id`, który
wolno trzymać bezterminowo. Bierzemy więc z Map sam ADRES STRONY, a wszystkie dane
o firmie zbiera nasz scraper z JEJ WŁASNEGO serwisu. W bazie lądują nasze dane,
nie Google'a. Nie prosząc o pola, których nie wolno nam zapisać, nie mamy nawet
okazji pomylić się później.

KOSZT (sprawdzony w cenniku 04.09.2026, nie z pamięci):
  - `websiteUri` należy do poziomu ENTERPRISE, a Google nalicza według najwyższego
    SKU w zapytaniu — jesteśmy więc w Enterprise, choćbyśmy prosili o dwa pola.
  - Text Search Enterprise: 1 000 zapytań miesięcznie za darmo, potem $35/1000.
  - JEDNO zapytanie zwraca do 20 firm, więc darmowy próg to ~20 000 firm/miesiąc.
    PRD zakłada 20 mikroaudytów miesięcznie — nie zbliżymy się do limitu.

Droga naokoło (darmowy Text Search po same ID + Place Details po `websiteUri`)
wychodzi DROŻEJ, bo Details płaci się od firmy, a nie od zapytania.
"""

from pathlib import Path
import json
import os
import time

import requests

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
KATALOG = Path(__file__).resolve().parent
FIXTURES = KATALOG / "fixtures"

# Tylko to, co wolno nam zapisać i czego naprawdę potrzebujemy.
POLA = "places.id,places.websiteUri,nextPageToken"

# Komunikaty zamiast surowego kodu HTTP — przy DataForSEO nauczyliśmy się, że
# „błąd 402" nic nie mówi, a „brak środków" mówi wszystko.
BLEDY_HTTP = {
    400: "Google odrzucił zapytanie jako niepoprawne (sprawdź frazę i miasto).",
    401: "Klucz API odrzucony — sprawdź GOOGLE_MAPS_API_KEY w .env.",
    403: ("Brak dostępu. Najczęstsze przyczyny: nie włączono Places API (New) "
          "w projekcie Google Cloud albo klucz ma ograniczenie, które nas blokuje."),
    429: "Przekroczony limit zapytań Google — spróbuj za chwilę.",
}


class BladMap(Exception):
    """Błąd po stronie Map. Rzucamy zamiast zwracać pustą listę — pusty wynik
    i awaria wyglądają na ekranie identycznie, a to dwie różne rzeczy."""


def klucz() -> str | None:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or None


def dostepne() -> bool:
    """Czy w ogóle możemy pytać Mapy. Front pyta o to, zanim pokaże tę opcję."""
    return bool(klucz())


def _zapytaj(tresc: dict) -> dict:
    k = klucz()
    if not k:
        raise BladMap("Brak GOOGLE_MAPS_API_KEY w .env — wyszukiwanie po Mapach wyłączone.")
    odp = requests.post(
        ENDPOINT, json=tresc, timeout=25,
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": k,
                 "X-Goog-FieldMask": POLA},
    )
    if odp.status_code != 200:
        opis = BLEDY_HTTP.get(odp.status_code, f"Google zwrócił HTTP {odp.status_code}.")
        # Google wkłada powód do body — bez niego diagnoza to zgadywanie.
        try:
            szczegol = (odp.json().get("error") or {}).get("message") or ""
        except Exception:
            szczegol = (odp.text or "")[:200]
        raise BladMap(f"{opis} {szczegol}".strip())
    return odp.json()


def _zapisz_fixture(nazwa: str, dane: dict) -> None:
    """Każda odpowiedź ląduje na dysku — parsery rozwijamy offline, bez płacenia
    za kolejne zapytania. Ta sama zasada, co przy DataForSEO."""
    try:
        FIXTURES.mkdir(exist_ok=True)
        (FIXTURES / f"mapy_{nazwa}.json").write_text(
            json.dumps(dane, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:                                   # zapis fixture nie może
        print(f"[mapy] nie zapisano fixture {nazwa}: {e}")   # wywrócić wyszukiwania


def szukaj(fraza: str, miasto: str = "", stron: int = 2) -> dict:
    """Zwraca adresy stron firm z Map.

    `stron` to liczba PŁATNYCH zapytań: każde oddaje do 20 firm. Domyślnie dwa,
    czyli do 40 firm — więcej i tak nie przerobisz w jednej sesji, a każda strona
    liczy się do limitu osobno.

    Zwracamy też `bez_strony`: ile firm Google znalazł, ale nie podał adresu.
    Takiej firmy nasz pipeline nie obsłuży (nie ma czego scrapować), więc musi
    być policzona, a nie po cichu zgubiona.
    """
    zapytanie = " ".join(f"{fraza} {miasto}".split())
    tresc = {"textQuery": zapytanie, "languageCode": "pl", "regionCode": "PL", "pageSize": 20}

    adresy, place_id, bez_strony, zapytan = [], [], 0, 0
    for nr in range(max(1, stron)):
        dane = _zapytaj(tresc)
        zapytan += 1
        _zapisz_fixture(f"{zapytanie[:40].replace(' ', '_')}_{nr + 1}", dane)

        for m in dane.get("places") or []:
            url = (m.get("websiteUri") or "").strip()
            if url:
                adresy.append(url)
                if m.get("id"):
                    place_id.append(m["id"])   # jedyne pole, które wolno przechować
            else:
                bez_strony += 1

        token = dane.get("nextPageToken")
        if not token:
            break
        tresc = {**tresc, "pageToken": token}
        time.sleep(1.2)   # token bywa aktywny z opóźnieniem

    return {"adresy": adresy, "place_id": place_id,
            "bez_strony": bez_strony, "zapytan": zapytan, "zapytanie": zapytanie}

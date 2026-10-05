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

# Osobna maska do rozpoznawania obszaru — pytamy wtedy o granice, nie o firmy.
POLA_OBSZAR = "places.displayName,places.viewport"

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


def _zapytaj(tresc: dict, pola: str = POLA) -> dict:
    k = klucz()
    if not k:
        raise BladMap("Brak GOOGLE_MAPS_API_KEY w .env — wyszukiwanie po Mapach wyłączone.")
    odp = requests.post(
        ENDPOINT, json=tresc, timeout=25,
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": k,
                 "X-Goog-FieldMask": pola},
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


# Raz rozpoznany obszar zapamiętujemy na czas życia procesu. Granice Poznania się
# nie zmieniają, a każde rozpoznanie to osobne płatne zapytanie.
_OBSZARY: dict[str, dict | None] = {}


def obszar(nazwa: str) -> dict | None:
    """Zamienia NAZWĘ miejsca na prostokąt, w którym Google potrafi szukać.

    PO CO TO ISTNIEJE — to była najdroższa pomyłka w tym module. Miasto dokładaliśmy
    do treści zapytania („doradztwo e-commerce poznań") i Places dopasowywał je
    DOSŁOWNIE: szukał wizytówek, które mają Poznań w nazwie albo opisie. Przy wąskiej
    frazie zostawała jedna firma. Zmierzone 22.09.2026 na „doradztwo e-commerce":

        miasto w tekście zapytania ...........  1 firma
        obszar Poznania (locationBias) ....... 22 firmy

    Mapy w przeglądarce nigdy nie szukają „po tekście z miastem" — szukają w WYCINKU
    MAPY. Tu robimy to samo: nazwa idzie do rozpoznania granic, a do frazy NIE.

    Google zna granice miast, powiatów i województw. Zwraca je jako `viewport`,
    czyli prostokąt: Poznań ~24x23 km, Leszno ~8x7 km, Wielkopolska ~283x225 km.

    Zwraca None, gdy nie rozpozna — wtedy wołający ma wrócić do starego sposobu
    i POWIEDZIEĆ o tym użytkownikowi, zamiast po cichu zawęzić wyniki.
    """
    klucz_pam = nazwa.strip().lower()
    if not klucz_pam:
        return None
    if klucz_pam in _OBSZARY:
        return _OBSZARY[klucz_pam]

    dane = _zapytaj({"textQuery": nazwa, "languageCode": "pl",
                     "regionCode": "PL", "pageSize": 1}, POLA_OBSZAR)
    miejsce = (dane.get("places") or [{}])[0]
    widok = miejsce.get("viewport") or {}
    lo, hi = widok.get("low") or {}, widok.get("high") or {}
    if not (lo.get("latitude") and hi.get("latitude")):
        _OBSZARY[klucz_pam] = None
        return None

    # Prostokąt o zerowej powierzchni to nie obszar, tylko punkt. Google zwraca coś
    # takiego, gdy „rozpozna" nazwę, której nie ma — wpisane „Kostrzyca Dolna" dało
    # „Kostrzyca" o wymiarach 0x0 km. Szukanie w punkcie nie ma sensu, a wyglądałoby
    # na działające: wróciłyby trzy przypadkowe firmy. Najmniejsze realne miasto
    # (Leszno) ma 8x7 km, więc próg jest bezpieczny.
    if (hi["latitude"] - lo["latitude"]) * 111 < 1:
        _OBSZARY[klucz_pam] = None
        return None

    # Rozmiar podajemy użytkownikowi, bo rozpoznanie bywa nietrafione: „powiat
    # leszczyński" Google rozumie jako „Powiat Leszno" i oddaje prostokąt 8x7 km,
    # czyli samo miasto. Bez pokazania obszaru wyniki cicho zmieniają znaczenie.
    wynik = {
        "nazwa": (miejsce.get("displayName") or {}).get("text") or nazwa,
        "prostokat": {"low": lo, "high": hi},
        "km_ns": round((hi["latitude"] - lo["latitude"]) * 111),
        # 0.61 to cosinus szerokości geograficznej Polski — południki zbiegają się
        "km_we": round((hi["longitude"] - lo["longitude"]) * 111 * 0.61),
    }
    _OBSZARY[klucz_pam] = wynik
    return wynik


def szukaj(fraza: str, miasto: str = "", stron: int = 3) -> dict:
    """Zwraca adresy stron firm z Map.

    `stron` to liczba PŁATNYCH zapytań: każde oddaje do 20 firm. Domyślnie dwa,
    czyli do 40 firm — więcej i tak nie przerobisz w jednej sesji, a każda strona
    liczy się do limitu osobno.

    Zwracamy też `bez_strony`: ile firm Google znalazł, ale nie podał adresu.
    Takiej firmy nasz pipeline nie obsłuży (nie ma czego scrapować), więc musi
    być policzona, a nie po cichu zgubiona.
    """
    fraza = fraza.strip()
    gdzie = obszar(miasto) if miasto.strip() else None

    if gdzie:
        # Miasto NIE idzie do frazy — idzie jako obszar. To jest cała poprawka.
        zapytanie = fraza
        tresc = {"textQuery": fraza, "languageCode": "pl", "regionCode": "PL",
                 "pageSize": 20,
                 # BIAS, nie RESTRICTION: firma tuż za granicą miasta to nadal dobry
                 # trop, a twarde odcięcie by ją wyrzuciło. Zmierzone: bias 22 firmy,
                 # restriction 21 — różnicą są właśnie te z obrzeży.
                 "locationBias": {"rectangle": gdzie["prostokat"]}}
    else:
        # Nie rozpoznaliśmy obszaru (albo nie podano miasta) — stary sposób.
        # Wołający ma o tym POWIEDZIEĆ użytkownikowi: przy nierozpoznanej nazwie
        # wyniki potrafią spaść do jednej firmy i nikt nie wie dlaczego.
        zapytanie = " ".join(f"{fraza} {miasto}".split())
        tresc = {"textQuery": zapytanie, "languageCode": "pl",
                 "regionCode": "PL", "pageSize": 20}

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

    # `zapytan` NIE obejmuje wywołania rozpoznającego obszar — tamto jest cache'owane
    # i liczone osobno, żeby licznik zapytań wyszukiwania pozostał porównywalny.
    return {"adresy": adresy, "place_id": place_id,
            "bez_strony": bez_strony, "zapytan": zapytan, "zapytanie": zapytanie,
            "obszar": gdzie,
            "obszar_nierozpoznany": bool(miasto.strip()) and gdzie is None}


# ── DIAGNOSTYKA (tymczasowa, 05.10.2026) ────────────────────────────────
# Na Renderze to samo zapytanie co lokalnie zwracało 6 firm zamiast 46 —
# ten sam klucz, ten sam region UE. Porównujemy warianty zapytania z obu
# miejsc, po jednej stronie każdy. Do usunięcia po wyborze wariantu.
def diagnoza(fraza: str, miasto: str) -> dict:
    gdzie = obszar(miasto)
    prost = gdzie["prostokat"]
    srodek = {"latitude": (prost["low"]["latitude"] + prost["high"]["latitude"]) / 2,
              "longitude": (prost["low"]["longitude"] + prost["high"]["longitude"]) / 2}
    baza = {"textQuery": fraza, "languageCode": "pl", "regionCode": "PL", "pageSize": 20}
    warianty = {
        "bias_prostokat": {**baza, "locationBias": {"rectangle": prost}},
        "restriction_prostokat": {**baza, "locationRestriction": {"rectangle": prost}},
        "bias_kolo_15km": {**baza, "locationBias": {"circle": {"center": srodek, "radius": 15000}}},
        "miasto_w_tekscie": {**baza, "textQuery": f"{fraza} {miasto}"},
        "bias_bez_jezyka": {"textQuery": fraza, "pageSize": 20,
                            "locationBias": {"rectangle": prost}},
    }
    wynik = {}
    for nazwa, tresc in warianty.items():
        try:
            d = _zapytaj(tresc)
            wynik[nazwa] = {"firm": len(d.get("places") or []),
                            "kolejna_strona": bool(d.get("nextPageToken"))}
        except BladMap as e:
            wynik[nazwa] = {"blad": str(e)[:120]}
    return wynik

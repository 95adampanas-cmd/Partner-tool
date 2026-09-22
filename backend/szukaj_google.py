"""
Google jako trzecie źródło firm — przez Custom Search JSON API.

DLACZEGO OSOBNE ŹRÓDŁO, SKORO MAMY TAVILY. Bo to nie jest to samo. Tavily ma własny
indeks i własnego robota; na frazę „agencja digital advisory" jego pierwsza dziewiątka
pokrywała się z pierwszą dziesiątką Google zaledwie w trzech domenach. Żadne z nich
nie jest „lepsze" — po prostu widzą inny wycinek internetu, więc razem dają więcej
kandydatów niż każde osobno.

DLACZEGO NIE DATAFORSEO, KTÓRE JUŻ MAMY. Ich endpoint `serp/google/organic` zwraca
prawdziwy Google i kosztuje $0,002 za zapytanie, ale rozliczenie wymaga depozytu
minimum $50. Custom Search daje 100 zapytań dziennie za darmo — przy czterech
wariantach frazy to 25 wyszukiwań dziennie bez płacenia niczego. Gdyby ten limit
zaczął uwierać, DataForSEO jest gotowe w dfs.py i wystarczy przepiąć.

CZEGO SIĘ SPODZIEWAĆ. Custom Search to osobny silnik oparty na indeksie Google, nie
kopia google.com — wyniki bywają lekko inne niż to, co widzisz w przeglądarce.
Zwraca maksymalnie 10 pozycji na zapytanie; kolejne dziesiątki to kolejne zapytania
liczone do limitu, dlatego domyślnie bierzemy dwie strony.
"""

from __future__ import annotations

import os

import requests

ENDPOINT = "https://www.googleapis.com/customsearch/v1"

# Limit darmowy: 100 zapytań/dobę. Jedna strona = 10 wyników = 1 zapytanie.
# Dwie strony na frazę przy czterech wariantach to 8 zapytań na wyszukiwanie,
# czyli ~12 wyszukiwań dziennie za darmo. Świadomy kompromis między zasięgiem
# a limitem — podniesienie STRON bije w to wprost.
STRON = 2
NA_STRONE = 10

BLEDY_HTTP = {
    400: "Google odrzucił zapytanie jako niepoprawne (sprawdź GOOGLE_CSE_ID).",
    403: ("Odmowa dostępu. Najczęstsze przyczyny: nie włączono Custom Search API "
          "w projekcie Google Cloud, wyczerpany limit 100 zapytań na dobę, "
          "albo klucz ma ograniczenie, które nas blokuje."),
    429: "Przekroczony limit zapytań Google — spróbuj jutro albo włącz rozliczenia.",
}


class BladGoogle(Exception):
    """Awaria po stronie Google. Rzucamy zamiast zwracać pustkę — pusty wynik
    i awaria wyglądają na ekranie identycznie, a to dwie różne rzeczy."""


def klucz() -> str | None:
    return os.environ.get("GOOGLE_CSE_KEY") or None


def silnik() -> str | None:
    return os.environ.get("GOOGLE_CSE_ID") or None


def dostepne() -> bool:
    """Czy możemy w ogóle pytać. Front pyta o to, zanim pokaże tę opcję —
    lepiej nie pokazać przycisku niż pokazać taki, który zawsze zwraca błąd."""
    return bool(klucz() and silnik())


def szukaj(fraza: str, miasto: str = "", stron: int = STRON) -> dict:
    """Wyniki organiczne Google dla jednej frazy.

    Zwraca kształt zgodny z tym, co oddaje Tavily (`url`, `title`, `content`),
    żeby dalej szedł tym samym filtrem — jedno miejsce decyduje, co jest firmą,
    niezależnie od tego, skąd przyszedł wynik.

    Miasto doklejamy do frazy, INACZEJ niż w Mapach. Tam było to błędem, bo Places
    dopasowuje tekst dosłownie do wizytówki; tutaj szukamy w treści stron, więc
    „Leszno" w zapytaniu działa tak, jak człowiek by tego oczekiwał.
    """
    if not dostepne():
        raise BladGoogle(
            "Brak GOOGLE_CSE_KEY lub GOOGLE_CSE_ID w .env — szukanie przez Google wyłączone.")

    zapytanie = " ".join(f"{fraza} {miasto}".split())
    wyniki, zapytan = [], 0

    for nr in range(max(1, stron)):
        params = {
            "key": klucz(), "cx": silnik(), "q": zapytanie,
            "num": NA_STRONE, "start": nr * NA_STRONE + 1,
            # gl + lr: wyniki dla polskiego użytkownika i w języku polskim.
            # Ta sama lekcja co przy Tavily — bez ograniczenia geograficznego
            # angielskie terminy branżowe ściągają globalne strony, bo wygrywają
            # autorytetem. Zmierzone tam: 1 polska domena na 20 bez parametru,
            # 8 na 19 z parametrem.
            "gl": "pl", "lr": "lang_pl", "hl": "pl",
        }
        try:
            odp = requests.get(ENDPOINT, params=params, timeout=25)
        except Exception as e:
            raise BladGoogle(f"Brak połączenia z Google: {e}") from e
        zapytan += 1

        if odp.status_code != 200:
            opis = BLEDY_HTTP.get(odp.status_code, f"Google zwrócił HTTP {odp.status_code}.")
            try:
                szczegol = ((odp.json().get("error") or {}).get("message") or "")
            except Exception:
                szczegol = (odp.text or "")[:200]
            raise BladGoogle(f"{opis} {szczegol}".strip())

        dane = odp.json()
        pozycje = dane.get("items") or []
        for p in pozycje:
            wyniki.append({
                "url": p.get("link") or "",
                "title": p.get("title") or "",
                "content": p.get("snippet") or "",
            })
        # Google przestaje oddawać kolejne strony, gdy wyników jest mniej niż prosimy.
        if len(pozycje) < NA_STRONE:
            break

    return {"wyniki": wyniki, "zapytanie": zapytanie, "zapytan": zapytan}

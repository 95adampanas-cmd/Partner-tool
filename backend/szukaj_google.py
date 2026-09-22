"""
Google jako trzecie źródło firm — przez SERP API DataForSEO.

DLACZEGO OSOBNE ŹRÓDŁO, SKORO MAMY TAVILY. Bo to nie jest to samo. Tavily ma własny
indeks i własnego robota; na frazie „agencja digital advisory" jego pierwsza dziewiątka
pokrywała się z pierwszą dziesiątką Google zaledwie w trzech domenach. Żadne z nich
nie jest „lepsze" — po prostu widzą inny wycinek internetu, więc razem dają więcej
kandydatów niż każde osobno.

DLACZEGO NIE CUSTOM SEARCH API, OD KTÓREGO ZACZYNALIŚMY. Bo Google je wygasza i sam
tego nie ukrywa. Sprawdzone w ich dokumentacji 22.09.2026:

  * od 20.01.2026 NOWE wyszukiwarki nie mogą już włączyć „przeszukiwania całej sieci"
    — a bez tego przeszukują wyłącznie podaną listę witryn, maksymalnie 50 domen;
  * całe Custom Search JSON API przestaje działać 01.01.2027;
  * kto ma starą wyszukiwarkę z włączoną całą siecią, może jej używać do tej daty,
    ale po jednorazowym wyłączeniu przełącznika nie da się go włączyć z powrotem.

Napisaliśmy pod nie moduł, zanim to sprawdziliśmy — i to była lekcja: przy integracji
z cudzym API najpierw sprawdzasz, czy ono nadal robi to, co pamiętasz, a dopiero potem
piszesz kod. Wersja na Custom Search działała poprawnie i była bezużyteczna.

CO ZAMIAST. DataForSEO mamy już zintegrowane (dfs.py) i ich endpoint SERP zwraca
prawdziwe wyniki Google z polską lokalizacją. Koszt ~$0,002 za frazę. Rozliczenie
z depozytu — ten sam, z którego korzysta audyt, więc doładowanie odblokowuje obie
rzeczy naraz.
"""

from __future__ import annotations

import os

import audyt
import dfs

# Ile pozycji SERP-a pobieramy na frazę. Głębiej nie ma sensu: dalsze wyniki to
# w praktyce katalogi i rankingi, które i tak odsiewa filtr, a cena rośnie.
GLEBOKOSC = 30


class BladGoogle(Exception):
    """Awaria po stronie dostawcy. Rzucamy zamiast zwracać pustkę — pusty wynik
    i awaria wyglądają na ekranie identycznie, a to dwie różne rzeczy."""


def dostepne() -> bool:
    """Czy mamy czym pytać. Front pyta o to, zanim pokaże przycisk — opcja, która
    na pewno zwróci błąd, nie powinna być klikalna.

    Sprawdzamy TYLKO obecność danych logowania, nie saldo. Saldo wymagałoby żądania
    sieciowego przy każdym otwarciu strony, a i tak potrafi się skończyć w trakcie
    pracy. Brak środków zgłasza samo wyszukiwanie, czytelnym komunikatem z dfs.py.
    """
    return bool(os.environ.get("DATAFORSEO_LOGIN")
                and os.environ.get("DATAFORSEO_PASSWORD"))


def szukaj(fraza: str, miasto: str = "", nazwa_fixture: str = "") -> dict:
    """Wyniki organiczne Google dla jednej frazy.

    Zwraca kształt zgodny z tym, co oddaje Tavily (`url`, `title`, `content`),
    żeby dalej szedł tym samym filtrem — jedno miejsce decyduje, co jest firmą,
    niezależnie od tego, skąd przyszedł wynik.

    Miasto doklejamy do frazy, INACZEJ niż w Mapach. Tam było to błędem, bo Places
    dopasowuje tekst dosłownie do wizytówki; tutaj przeszukujemy treść stron, więc
    „Leszno" w zapytaniu działa tak, jak człowiek by tego oczekiwał.
    """
    zapytanie = " ".join(f"{fraza} {miasto}".split())
    if not zapytanie:
        return {"wyniki": [], "zapytanie": "", "koszt": 0.0}

    try:
        odp = dfs.wywolaj(
            "serp/google/organic/live/advanced",
            [{"keyword": zapytanie, "location_code": audyt.LOKALIZACJA_PL,
              "language_name": audyt.JEZYK_PL, "device": "desktop",
              "depth": GLEBOKOSC}],
            nazwa_fixture or None,
        )
    except dfs.BladAPI as e:
        # Przepakowujemy, żeby wołający nie musiał znać dostawcy — ale treść
        # zostawiamy, bo to ona mówi „brak środków" zamiast „HTTP 402".
        raise BladGoogle(str(e)) from e

    zadanie = (odp.get("tasks") or [{}])[0]
    wynik = (zadanie.get("result") or [{}])[0]
    pozycje = wynik.get("items") or []

    wyniki = []
    for p in pozycje:
        # Interesują nas WYŁĄCZNIE wyniki organiczne. SERP zawiera też sekcje
        # „people_also_ask", „popular_products", „video" i podobne — to nie są
        # firmy, tylko elementy strony wyników.
        if p.get("type") != "organic":
            continue
        adres = p.get("url") or ""
        if not adres:
            continue
        wyniki.append({
            "url": adres,
            "title": p.get("title") or "",
            "content": p.get("description") or "",
        })

    return {"wyniki": wyniki, "zapytanie": zapytanie,
            "koszt": float(zadanie.get("cost") or 0)}

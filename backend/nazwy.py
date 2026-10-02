"""
Nazwa firmy z tego, co oddaje wyszukiwarka.

PROBLEM. Wyszukiwarka zwraca tytuł STRONY, a nie nazwę firmy. Do kolejki trafiały
więc nagłówki artykułów: „Jak agencja marketingu internetowego buduje sprzedaż,
a ...", „Tworzenie dynamicznych reklam w Google Ads". Firma z Map dostawała z kolei
sam adres („mkgrow.pl"), bo z Map nie wolno nam przechowywać nazwy wizytówki
(warunki Places API pozwalają trzymać tylko place_id). Jedna lista, trzy różne
rodzaje nagłówków — i żaden z nich nie był nazwą partnera.

ZASADA. Nazwą firmy jest ta część tytułu, która ZGADZA SIĘ Z DOMENĄ. Domena to
jedyna rzecz, którą firma na pewno wybrała sama. „Dlaczego Adlife? Agencja
marketingu online" na adlife.pl → „Adlife". „Agencja Medio — oferta" na
agencjamedio.pl → „Agencja Medio" (sklejone słowa też się liczą). Gdy tytuł nie
zawiera nazwy z domeny, bierzemy samą domenę i podajemy ją po ludzku: silesion.pl →
„Silesion". Nie zgadujemy niczego, czego nie ma ani w tytule, ani w adresie.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

# Końcówki domen, które nie są częścią nazwy. Wystarczy te, które realnie widzimy
# w polskich wynikach — reszta i tak spadnie do „pierwszej etykiety domeny".
_KONCOWKI = ("com.pl", "net.pl", "org.pl", "co.uk", "pl", "com", "eu", "io", "dev",
             "net", "org", "agency", "studio", "digital", "online", "info", "app",
             "co", "biz", "media", "marketing", "design", "tech", "group", "shop")


def _bez_ogonkow(tekst: str) -> str:
    return "".join(z for z in unicodedata.normalize("NFKD", tekst)
                   if not unicodedata.combining(z))


def _klucz(tekst: str) -> str:
    """Postać do porównań: małe litery, bez ogonków, same litery i cyfry."""
    return re.sub(r"[^a-z0-9]", "", _bez_ogonkow(tekst.lower()))


def _domena(url: str) -> str:
    d = urlparse(url if "//" in url else "//" + url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def rdzen_domeny(url: str) -> str:
    """Nazwa z adresu bez końcówki: adlife.pl → adlife, seo-www.pl → seo-www."""
    d = _domena(url)
    for k in sorted(_KONCOWKI, key=len, reverse=True):
        if d.endswith("." + k):
            d = d[: -len(k) - 1]
            break
    return d.split(".")[-1] if d else ""


def _z_domeny(url: str) -> str:
    """Domena podana po ludzku: silesion.pl → Silesion, seo-www.pl → Seo Www.

    Krótki rdzeń (non.agency → „non") nie jest nazwą — wtedy cała domena jest
    czytelniejsza niż trzy litery.
    """
    rdzen = rdzen_domeny(url)
    if len(_klucz(rdzen)) <= 3:
        return _domena(url)
    czesci = [_rozklej(cz) for cz in re.split(r"[-_]+", rdzen) if cz]
    return " ".join(cz[:1].upper() + cz[1:] for cz in " ".join(czesci).split())


# Sklejone domeny („agencjamedio", „cyrekdigital") rozbijamy tylko na znanych
# słowach na początku albo na końcu. Bez słownika nie da się rozkleić
# „pozycjonowaniestron" czy „michalmartyniuk" i nie próbujemy — źle rozklejona
# nazwa jest gorsza niż sklejona, bo wygląda na pewną.
_NA_POCZATKU = ("agencja", "studio", "grupa")
_NA_KONCU = ("digital", "media", "agency", "studio", "marketing", "consulting",
             "partners", "group", "hub", "labs", "growth", "design")


def _rozklej(slowo: str) -> str:
    for p in _NA_POCZATKU:
        if slowo.startswith(p) and len(slowo) - len(p) >= 3:
            return p + " " + slowo[len(p):]
    for k in _NA_KONCU:
        if slowo.endswith(k) and len(slowo) - len(k) >= 3:
            return slowo[: -len(k)] + " " + k
    return slowo


def nazwa_firmy(tytul: str, url: str) -> str:
    """Nazwa firmy: fragment tytułu zgodny z domeną, a w ostateczności sama domena."""
    rdzen = _klucz(rdzen_domeny(url))
    tytul = " ".join((tytul or "").split())
    if not rdzen or len(rdzen) < 3:
        return _z_domeny(url)

    # Słowa tytułu z zachowaniem pisowni. Szukamy ciągu 1–4 kolejnych słów, który
    # po sklejeniu daje dokładnie rdzeń domeny — to łapie „Future Mind"
    # (futuremind.com), „4 REAL" (4real.pl) i „Agencja Medio" (agencjamedio.pl).
    # Samotny myślnik czy kropka z tytułu to nie słowo: liczony jako słowo
    # doklejał się do nazwy („- AdsOn") i psuł dopasowanie („4 REAL -").
    slowa = [w for w in re.findall(r"[\w&+.'-]+", tytul, flags=re.UNICODE)
             if re.search(r"\w", w)]
    # Od najkrótszego: jedno słowo zgodne z domeną jest pewniejsze niż cztery,
    # w których nazwa tylko się mieści.
    for dlugosc in (1, 2, 3, 4):
        for i in range(len(slowa) - dlugosc + 1):
            kawalek = slowa[i:i + dlugosc]
            if _klucz("".join(kawalek)) == rdzen:
                nazwa = " ".join(kawalek).strip(".'- ")
                # Tytuł pisany wielkimi literami („TWORZENIE STRON") nie jest nazwą
                # własną, tylko krzykiem — wtedy forma z domeny jest czytelniejsza.
                if nazwa.isupper() and len(nazwa) > 6:
                    return _z_domeny(url)
                return nazwa

    return _z_domeny(url)

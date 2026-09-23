"""
Audyt GEO bez płatnych dostawców danych — wszystko na kluczach, które już mamy.

DLACZEGO OSOBNY MODUŁ, A NIE ROZBUDOWA audyt.py. Bo to inny produkt, nie inny wariant.
Mikroaudyt w `audyt.py` mierzy SEO i GEO razem, opiera się na DataForSEO i pada, gdy
skończą się środki. Ten mierzy WYŁĄCZNIE widoczność w odpowiedziach AI i nie dotyka
żadnego płatnego dostawcy danych — płacimy tylko za tokeny modeli, które i tak mamy.
Trzymanie obu w jednym pliku skończyłoby się gałęziami `if tryb ==` w każdej funkcji,
a pierwszy audyt ma zostać nietknięty.

CZEGO TU NIE MA I DLACZEGO. AI Overviews i AI Mode wymagają odpytania Google, a tego
nie da się zrobić bez płatnego pośrednika. Sprawdzone 24.09.2026: zwykłe pobranie
adresu wyników zwraca HTTP 200 i 92 tys. znaków, w których NIE MA ani jednego wyniku
— Google ukrywa treść (`table,div,span,p{display:none}`) i renderuje ją JavaScriptem.
Obejście wymaga headless browsera, rotacji proxy i łamania regulaminu Google, czyli
osobnego projektu utrzymaniowego. Te dwie sekcje zostają w audycie 1, gdzie robi to
DataForSEO.

Perplexity i Gemini są pominięte, bo nie mamy do nich kluczy. Dokładanie rachunków
bez pytania nie jest naszą decyzją.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import re

import requests

# Nieudokumentowany, ale publiczny i darmowy endpoint podpowiedzi Google. Bez klucza
# i bez limitu, którego dałoby się sensownie dotknąć przy kilkunastu zapytaniach.
PODPOWIEDZI = "https://suggestqueries.google.com/complete/search"

# Dłuższe podpowiedzi są cenniejsze: „ile kosztuje wdrożenie erp" to pytanie, które
# ktoś naprawdę zadaje, a „erp" to tylko kategoria. Poniżej tego progu odrzucamy.
MIN_SLOW = 3


def podpowiedzi_google(fraza: str, limit: int = 20) -> list[str]:
    """Podpowiedzi wyszukiwania Google dla frazy — realne pytania realnych ludzi.

    PO CO TO, SKORO MODEL UMIE WYMYŚLIĆ PYTANIA. Bo model wymyśla, jak ludzie MOGLIBY
    pytać, a to jest lista tego, jak pytają NAPRAWDĘ — z częstotliwością wbudowaną
    w kolejność. Przy audycie dla klienta to różnica między „wygenerowaliśmy pytania"
    a „to są pytania z Google".

    ILE TEGO BĘDZIE — zmierzone 24.09.2026, bo różnica jest duża i warto ją znać
    z góry: „wdrożenie erp" dało 10 podpowiedzi, w tym „ile kosztuje wdrożenie erp"
    i „ile trwa wdrożenie erp". „agencja prestashop" dało 2. Google podpowiada tylko
    to, co ludzie NAPRAWDĘ wpisują, więc przy wąskich frazach B2B bywa pusto — i tak
    ma być. To źródło UZUPEŁNIA prompty z modelu, nie zastępuje ich.

    Rozszerzamy rdzeń o litery, nie o słowa pytające. Sprawdzone: „fraza + jak"
    bywa tak rzadka, że Google nie ma dla niej danych i zwraca zero, podczas gdy
    „fraza + i" albo „fraza + c" otwierają realne gałęzie.
    """
    rdzen = " ".join((fraza or "").split())
    if not rdzen:
        return []

    zapytania = [rdzen] + [f"{rdzen} {x}" for x in "abcdgijkmnoprstwz"]

    def pobierz(q: str) -> list[str]:
        try:
            r = requests.get(PODPOWIEDZI, timeout=12,
                             params={"client": "firefox", "hl": "pl", "gl": "pl", "q": q})
            if r.status_code != 200:
                return []
            return json.loads(r.text)[1] or []
        except Exception:
            # Podpowiedzi to dodatek, nie fundament — awaria nie może wywrócić audytu.
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        partie = list(pool.map(pobierz, zapytania))

    widziane, wynik = set(), []
    for partia in partie:
        for s in partia:
            s = " ".join(str(s).split())
            klucz = s.lower()
            if klucz in widziane or len(s.split()) < MIN_SLOW:
                continue
            widziane.add(klucz)
            wynik.append(s)
    return wynik[:limit]


# ══════════════════════════════════════════════════════════════════════
#  Czy klient jest tam, skąd AI bierze odpowiedzi
# ══════════════════════════════════════════════════════════════════════
def obecnosc_w_zrodlach(wiersze: list[dict], marka: str, domena: str,
                        ile: int = 8) -> list[dict]:
    """Sprawdza, czy marka figuruje na stronach, które AI cytuje najczęściej.

    TO JEST NAJMOCNIEJSZY WNIOSEK CAŁEGO AUDYTU i jedyny, który od razu daje
    rekomendację. Sama lista cytowanych domen mówi „model czyta ranking X". Dopiero
    sprawdzenie, czy klient na tym rankingu JEST, zamienia to w zdanie: „model składa
    odpowiedź z listy, na której Was nie ma — trzeba się tam znaleźć".

    Koszt zero: to nasz scraper, te same żądania HTTP co przy researchu firmy.

    Pomijamy własną domenę klienta — jej obecność na własnej stronie niczego nie
    dowodzi, a zajmowałaby miejsce w zestawieniu.
    """
    from app import domena_z_url, pobierz, tekst_ze_strony

    licznik = Counter()
    adresy: dict[str, str] = {}
    for w in wiersze:
        for u in (w.get("zrodla") or []):
            d = domena_z_url(u)
            if not d or d == domena:
                continue
            licznik[d] += 1
            adresy.setdefault(d, u)        # pierwszy cytowany URL z tej domeny

    najczestsze = [d for d, _ in licznik.most_common(ile)]
    if not najczestsze:
        return []

    warianty = _warianty_marki(marka, domena)

    def sprawdz(d: str) -> dict:
        url = adresy[d]
        html = pobierz(url)
        if not html:
            # Nie udało się pobrać — to NIE znaczy „nie ma tam marki". Mylenie
            # tych dwóch rzeczy dałoby rekomendację opartą na awarii scrapera.
            return {"domena": d, "url": url, "cytowan": licznik[d],
                    "stan": "nie_sprawdzono", "typ": "?"}

        tytul = _tytul(html)
        tresc = tekst_ze_strony(html).lower()
        jest = any(w in tresc for w in warianty)

        # ROZRÓŻNIENIE, KTÓRE DECYDUJE O WARTOŚCI TEJ SEKCJI. Zmierzone na Tebimie:
        # z sześciu cytowanych stron pięć należało do KONKURENTÓW. To, że Sellision
        # nie wymienia Tebimu, nie jest rekomendacją — tak działa konkurencja.
        # Rekomendacją jest nieobecność na RANKINGU albo w katalogu, bo tam da się
        # wejść. Bez tego podziału lista wygląda alarmująco i nie da się z niej nic
        # zrobić. Ranking rozpoznajemy tym samym wzorcem, którym filtrujemy wyniki
        # wyszukiwania — „10 najlepszych agencji", „Top 5", „ranking".
        from app import LISTICLE
        ranking = bool(LISTICLE.search(tytul)) or any(
            s in tytul.lower() for s in ("ranking", "najlepsz", "porówna", "katalog"))

        return {"domena": d, "url": url, "cytowan": licznik[d], "tytul": tytul,
                "stan": "jest" if jest else "brak",
                "typ": "ranking" if ranking else "strona firmy"}

    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(sprawdz, najczestsze))


def _tytul(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    return " ".join(m.group(1).split())[:160] if m else ""


def _warianty_marki(marka: str, domena: str) -> list[str]:
    """Nazwa firmy bywa zapisana różnie — szukamy kilku form, nie jednej."""
    rdzen = (domena or "").split(".")[0].lower()
    formy = {(marka or "").lower().strip(), rdzen}
    # Nazwa bez sufiksów prawnych i bez spacji: „Tebim Sp. z o.o." -> „tebim"
    czysta = re.sub(r"\b(sp\.?\s*z\s*o\.?\s*o\.?|s\.a\.|sp\.j\.|z\.o\.o)\b", "",
                    (marka or "").lower()).strip()
    formy.add(czysta)
    formy.add(czysta.replace(" ", ""))
    return [f for f in formy if len(f) >= 3]

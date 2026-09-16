"""
Test filtra wyszukiwania.

    python test_filtr.py           # regresja offline — bez sieci, bez kosztów
    python test_filtr.py --live    # dodatkowo audyt na żywych wynikach Tavily

DWIE CZĘŚCI, BO SŁUŻĄ DO CZEGO INNEGO.

Regresja offline sprawdza REGUŁY na zestawie z etykietami: czy to, co ma wypaść,
wypada, i czy to, co ma zostać, zostaje. Uruchamiana po każdej zmianie w filtrze.
Ta część istnieje, bo poprzedni test miał WŁASNĄ KOPIĘ reguł z app.py. Kopia się
rozjechała: wołała funkcję usuniętą przy przebudowie filtra konkurentów i nie
znała reguł poddomen ani końcówek publicznych. Test przechodził na wersji, której
już nie było. Teraz wszystko idzie przez prawdziwe funkcje z app.py.

Audyt na żywo (--live) mierzy JAKOŚĆ na prawdziwych wynikach — ile śmieci wpada
mimo reguł. Kosztuje wywołania Tavily, więc nie jest domyślny. Wynik ląduje
w raport_filtr.txt. Przydatny przy KPI z PRD: „szukaj podobnych" — trafność 60%.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from collections import Counter

import app

# ══════════════════════════════════════════════════════════════════════
#  REGRESJA OFFLINE
# ══════════════════════════════════════════════════════════════════════
# Przypadki wzięte z realnych przebiegów, nie wymyślone. Każdy „ZOSTAJE"
# to firma, która naprawdę pojawiła się w wynikach i naprawdę jest kandydatem —
# dlatego pułapki w rodzaju govtech-polska.pl czy edukacja-firma.pl są tu celowo:
# mają „gov" i „edu" w nazwie i muszą przejść.

ADRESY = [
    # (url, czy ma zostać odrzucony, opis)
    ("https://rejestr.io/firma/x",                  True,  "rejestr KRS"),
    ("https://www.bizraport.pl/krs/1",              True,  "rejestr KRS"),
    ("https://www.skool.com/g/ecommerce",           True,  "platforma społecznościowa"),
    ("https://mapa.iab.org.pl/agencje",             True,  "mapa izby branżowej"),
    ("https://www.startupblink.com/top",            True,  "katalog startupów"),
    ("https://uslugirozwojowe.parp.gov.pl/x",       True,  "baza rządowa"),
    ("https://www.gov.pl/x",                        True,  "domena publiczna bez poddomeny"),
    ("https://dictionary.cambridge.org/sh",         True,  "słownik"),
    ("https://docs.johnsoncontrols.com/a",          True,  "dokumentacja producenta"),
    ("https://support.shopify.com/a",               True,  "pomoc techniczna"),
    ("https://www.reddit.com/r/x",                  True,  "forum"),
    ("https://www.capterra.pl/x",                   True,  "porównywarka oprogramowania"),
    ("https://www.yelp.com/biz/x",                  True,  "katalog firm"),
    ("https://clutch.co/pl/agencies",               True,  "katalog agencji"),

    ("https://empressia.pl",                        False, "agencja"),
    ("https://sellision.pl/o-nas",                  False, "agencja, link głęboki"),
    ("https://convertis.pl",                        False, "agencja"),
    ("https://refix.pl",                            False, "agencja"),
    ("https://obfitosc.com",                        False, "agencja"),
    ("https://agencja.com",                         False, "agencja"),
    ("https://sii.pl",                              False, "firma IT"),
    ("https://ideo.pl",                             False, "agencja interaktywna"),
    ("https://shoper.pl",                           False, "platforma e-commerce"),
    ("https://govtech-polska.pl",                   False, "PUŁAPKA: 'gov' w nazwie firmy"),
    ("https://edukacja-firma.pl",                   False, "PUŁAPKA: 'edu' w nazwie firmy"),
    ("https://softwarestudio.com.pl",               False, "firma, nie dokumentacja"),
    ("https://seo-www.pl/blog/x",                    False, "PUŁAPKA: 'www.' w ŚRODKU nazwy"),
    ("https://wwwtest.pl",                           False, "PUŁAPKA: 'www' bez kropki"),
]

# Domena bez przedrostka www. Osobno od odrzucania, bo tu chodzi o POPRAWNOŚĆ
# adresu, a nie o to, czy w ogóle przechodzi. `netloc.replace("www.", "")` wycinało
# "www." także ze środka: seo-www.pl stawało się nieistniejącym "seo-pl" i pod takim
# adresem szło zarówno na listę firm, jak i do PŁATNEGO API audytu.
DOMENY = [
    ("https://seo-www.pl/blog/x",  "seo-www.pl"),
    ("https://www.seo-www.pl/x",   "seo-www.pl"),
    ("https://www.empressia.pl",   "empressia.pl"),
    ("https://empressia.pl",       "empressia.pl"),
    ("https://wwwtest.pl",         "wwwtest.pl"),
    ("https://firma.www.pl",       "firma.www.pl"),
    ("HTTPS://WWW.Tebim.PRO/a",    "tebim.pro"),
]

TYTULY = [
    # (tytuł, czy to zestawienie/ranking, opis)
    ("50 agencji digital",                                      True,  "zestawienie"),
    ("Top 5 Najlepszych agencji",                               True,  "ranking"),
    ("15 najlepszych agencji e-commerce w Polsce",              True,  "ranking"),
    ("Strony internetowe Warszawa: 20 firm i agencji, które warto znać",
                                                                True,  "liczba w ŚRODKU tytułu"),
    ("71 Top E-commerce Companies in Poland",                   True,  "dwa słowa przerwy"),
    ("10 best software houses in Poland",                       True,  "zestawienie po angielsku"),
    ("Top 50 E-Commerce Photo Studio Professionals",            True,  "'top N' + dowolny rzeczownik"),

    ("360agencja.pl",                                           False, "liczba w nazwie"),
    ("Grupa 3 Agencja Reklamowa",                               False, "PUŁAPKA: liczba + l. pojedyncza"),
    ("K2 Agencja Interaktywna",                                 False, "liczba w nazwie"),
    ("Studio 102 - agencja kreatywna",                          False, "liczba + myślnik"),
    ("7 Group | Software House",                                False, "liczba + nazwa"),
    ("Topsi Agencja Reklamowa",                                 False, "PUŁAPKA: 'Top' w nazwie"),
    ("Stoptech 24",                                             False, "PUŁAPKA: 'top' w środku słowa"),
    ("Laptop 4 You",                                            False, "PUŁAPKA: 'top' + liczba"),
]

# Tag „prowadzi kampanie SEO". FAKT, nie ocena — żadna firma przez niego nie wypada
# z listy ani nie jest ukrywana. Czy agencja z SEO jest konkurentem, czy partnerem,
# rozstrzyga zespół.
#
# Definicja zawężona 04.09.2026 na polecenie Adama: liczą się KAMPANIE, czyli ciągła
# usługa pozycjonowania. NIE liczą się audyt SEO, „optymalizacja SEO" przy wdrożeniu,
# SEO copywriting ani kampanie płatne (Google Ads to nie jest SEO).
SYGNALY = [
    ("Grupa iCEA - Skuteczne pozycjonowanie i SEO", "Pozycjonowanie stron, link building.", True),
    ("Delante - SEO & SEM Agency",       "Agencja SEO/SEM. Pozycjonowanie, audyty SEO.", True),
    ("Agencja X",                        "Prowadzimy kampanie pozycjonowania dla sklepów.", True),
    ("Q",                                "Pozycjonowanie stron oraz audyt SEO i optymalizacja.", True),

    ("Convertis | Agencja eCommerce",    "Sklepy internetowe, wdrożenia, audyt SEO sklepu.", False),
    ("wecanfly | Shopify Plus",          "Shopify Development, UX/UI, Shopify SEO Optimization.", False),
    ("brantt | Agencja kreatywna",       "Branding, strony www, copywriting, SEO copywriting.", False),
    ("When | Agencja marketingowa",      "Kampanie Google Ads, Meta Ads, LinkedIn Ads.", False),
    ("Oficjalna agencja PrestaShop",     "Wdrażamy sklepy B2C i B2B.",        False),
    ("Sii Polska",                       "7000 inżynierów, cloud, testy.",    False),
    ("Obfitość | Kreatywna agencja e-commerce", "Projektujemy sklepy i marki.", False),
]


def sprawdz_kategorie() -> int:
    """Czy nazwy kategorii w backendzie i we froncie są identyczne.

    Backend przypisuje firmę do kategorii przy researchu, front grupuje po niej
    listy. Gdy jedna strona zmieni nazwę, firma wyląduje w kategorii, której nie
    ma na liście wyboru — i po prostu zniknie z widoku, bez żadnego błędu.
    Dokładnie tak rozjechał się poprzednio ten test i nikt nie zauważył
    przez trzy commity.
    """
    import re
    from pathlib import Path

    plik = Path(__file__).resolve().parent.parent / "frontend" / "app.js"
    if not plik.exists():
        print("  POMINIĘTE — nie znaleziono frontend/app.js")
        return 0

    tresc = plik.read_text(encoding="utf-8")
    poczatek = tresc.index("partner: [")
    koniec = tresc.index("klient: [")
    we_froncie = re.findall(r'\["([^"]+)",\s*"', tresc[poczatek:koniec])

    brakuje = [k for k in app.KATEGORIE_PARTNEROW if k not in we_froncie]
    nadmiar = [k for k in we_froncie if k not in app.KATEGORIE_PARTNEROW]
    for k in brakuje:
        print(f"  BŁĄD | w backendzie jest, we froncie NIE MA: {k!r}")
    for k in nadmiar:
        print(f"  BŁĄD | we froncie jest, w backendzie NIE MA: {k!r}")
    if not brakuje and not nadmiar:
        print(f"  OK   | {len(we_froncie)} kategorii, nazwy zgodne po obu stronach")
    return len(brakuje) + len(nadmiar)


def sprawdz_modele() -> int:
    """Czy praca idzie na Claude, a pomiar GEO został na OpenAI.

    Dwie rzeczy, które łatwo zepsuć w dobrej wierze:

    1. Ktoś „ujednolica" agent_pytajacy i przenosi go na Claude. Nic nie wybucha,
       testy przechodzą, raport dalej pokazuje tabelkę — tyle że mierzy widoczność
       w Claude zamiast w ChatGPT. Klienci partnera pytają ChatGPT, więc od tego
       momentu cała sekcja GEO odpowiada na inne pytanie, niż głosi jej nagłówek.

    2. Ktoś skraca blok stały poniżej progu cache. Anthropic nie zgłasza wtedy
       błędu — cache_control jest po prostu ignorowany. Kod wygląda identycznie,
       rachunek rośnie dwukrotnie i nie ma jak tego zauważyć bez sprawdzenia.
    """
    import claude

    bledy = 0
    zadania = [getattr(app, n) for n in dir(app) if n.startswith("zadanie_")]
    zadania += app.zadania_mail

    for z in zadania:
        if z.model.startswith("claude-"):
            print(f"  OK   | {z.nazwa:16} -> {z.model}")
        else:
            print(f"  BŁĄD | {z.nazwa:16} nie jest na Claude: {z.model}")
            bledy += 1

    if app.agent_pytajacy.model == app.MODEL_POMIARU_GEO and "gpt" in app.MODEL_POMIARU_GEO:
        print(f"  OK   | {'pytajacy (GEO)':16} -> {app.MODEL_POMIARU_GEO} "
              f"— mierzy ChatGPT, ma tu zostać")
    else:
        print(f"  BŁĄD | pytajacy przestał mierzyć ChatGPT: {app.agent_pytajacy.model}")
        bledy += 1

    # synergie.md to szablon FORMATU WYJSCIA. Bez ograniczenia zakresu zamienia
    # kazda odpowiedz w rozpisana liste — takze odpowiedz na „czy obsluguja B2B?",
    # i kazdy mail w ulotke. Oba miejsca musza niesc wlasne zastrzezenie.
    if "TYLKO WTEDY" in app.CZAT_SYNERGIE.split("##")[0]:
        print("  OK   | czat: format synergii ograniczony do pytan o synergie")
    else:
        print("  BŁĄD | czat: brak ograniczenia — format wycieknie na kazde pytanie")
        bledy += 1
    if "NIE PRZENOŚ TEGO FORMATU" in app.MAIL_SYNERGIE:
        print("  OK   | mail: bierze sposob myslenia, nie format")
    else:
        print("  BŁĄD | mail: brak zastrzezenia — mail wyjdzie jako lista synergii")
        bledy += 1

    for z in zadania:
        if not z.staly:
            continue
        prog = claude.PROGI_CACHE[z.model]
        tok = len(z.staly) / claude.ZNAKI_NA_TOKEN
        wlaczony = "cache_control" in claude._system(z)[0]
        if wlaczony and tok >= prog:
            print(f"  OK   | cache {z.nazwa:16} ~{tok:.0f} tok (próg {prog})")
        elif not wlaczony:
            # To NIE jest błąd — tak ma działać, gdy blok jest za krótki. Ma być
            # tylko widoczne, żeby nikt nie żył w przekonaniu, że cache działa.
            print(f"  UWAGA| cache {z.nazwa:16} WYŁĄCZONY, ~{tok:.0f} tok < {prog}")
        else:
            print(f"  BŁĄD | cache {z.nazwa:16} włączony mimo ~{tok:.0f} tok < {prog}")
            bledy += 1
    return bledy


def sprawdz_regresje() -> int:
    """Zwraca liczbę błędów. 0 = wszystko zgodne z oczekiwaniem."""
    bledy = 0

    print("=" * 74)
    print("MODELE — praca na Claude, pomiar GEO na OpenAI")
    print("=" * 74)
    bledy += sprawdz_modele()
    print()

    print("=" * 74)
    print("KATEGORIE — czy backend i frontend nazywają je tak samo")
    print("=" * 74)
    bledy += sprawdz_kategorie()
    print()

    print("=" * 74)
    print("ADRESY — czy normalizuj_url() odrzuca to, co powinno")
    print("=" * 74)
    for url, ma_wypasc, opis in ADRESY:
        powod = app.powod_odrzucenia(url)
        wypadl = powod is not None
        # spójność: normalizuj_url musi zgadzać się z powod_odrzucenia
        if (app.normalizuj_url(url) is None) != wypadl:
            print(f"  NIESPÓJNOŚĆ normalizuj_url vs powod_odrzucenia: {url}")
            bledy += 1
        ok = wypadl == ma_wypasc
        bledy += not ok
        stan = "odrzucony" if wypadl else "przechodzi"
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {stan:10} | {opis:38} | {powod or ''}")

    print()
    print("=" * 74)
    print("DOMENY — czy 'www.' znika TYLKO z przedrostka, nie ze środka nazwy")
    print("=" * 74)
    for url, oczekiwana in DOMENY:
        wyszlo = app.domena_z_url(url)
        ok = wyszlo == oczekiwana
        bledy += not ok
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {url:32} -> {wyszlo}"
              f"{'' if ok else f'  (oczekiwano {oczekiwana})'}")

    print()
    print("=" * 74)
    print("TYTUŁY — czy LISTICLE rozpoznaje zestawienia, nie myląc ich z nazwami firm")
    print("=" * 74)
    for tytul, ma_trafic, opis in TYTULY:
        trafil = bool(app.LISTICLE.search(tytul))
        ok = trafil == ma_trafic
        bledy += not ok
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {'zestawienie' if trafil else 'nazwa firmy':11} "
              f"| {opis:36} | {tytul[:34]}")

    print()
    print("=" * 74)
    print("TAG SEO — czy firma PROWADZI KAMPANIE. Audyt i optymalizacja się nie liczą")
    print("=" * 74)
    for tytul, opis_firmy, ma_isc in SYGNALY:
        idzie = app.ma_sygnal_seo(tytul, opis_firmy)
        ok = idzie == ma_isc
        bledy += not ok
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {'kampanie' if idzie else 'bez tagu':8} | {tytul[:52]}")

    print()
    print("=" * 74)
    print(f"REGRESJA: {'PRZESZŁA' if bledy == 0 else f'{bledy} BŁĘDÓW'} "
          f"({len(ADRESY) + len(DOMENY) + len(TYTULY) + len(SYGNALY)} przypadków)")
    print("=" * 74)
    return bledy


# ══════════════════════════════════════════════════════════════════════
#  AUDYT NA ŻYWO (--live)
# ══════════════════════════════════════════════════════════════════════
ZAPYTANIA = [
    "agencja kreatywna branding",
    "agencja e-commerce PrestaShop",
    "software house tworzenie stron WordPress",
    "agencja social media",
]


def audyt_na_zywo():
    linie, licznik = [], Counter()
    wszystkie_ok = []

    for zapytanie in ZAPYTANIA:
        linie.append("=" * 78)
        linie.append(f"ZAPYTANIE: {zapytanie}")
        linie.append("=" * 78)

        wyniki = app.tavily_search(zapytanie, max_results=15)
        widziane = set()

        for r in wyniki:
            url, tytul = r.get("url", ""), (r.get("title") or "").strip()
            powod = app.powod_odrzucenia(url)

            if powod:
                licznik[f"ODRZUT: {powod}"] += 1
                linie.append(f"  [X] {powod:26} {tytul[:38]}")
                linie.append(f"      {url[:88]}")
                continue

            strona = app.normalizuj_url(url)
            domena = urlparse(strona).netloc
            if domena in widziane:
                licznik["ODRZUT: duplikat domeny"] += 1
                linie.append(f"  [X] {'duplikat domeny':26} {tytul[:38]}")
                continue
            widziane.add(domena)

            if any(f in tytul.lower() for f in app.TYTULY_ODRZUCAJACE):
                licznik["ODRZUT: tytuł rankingu/ogłoszenia"] += 1
                linie.append(f"  [X] {'tytuł rankingu':26} {tytul[:38]}")
                continue

            uciety = bool(urlparse(url).path.strip("/"))
            zestawienie = bool(app.LISTICLE.search(tytul))
            licznik["PRZECHODZI"] += 1
            if uciety:
                licznik["  (w tym ucięte do str. głównej)"] += 1
            if zestawienie:
                licznik["  (w tym tytuł zestawienia -> pokażemy domenę)"] += 1
            if app.ma_sygnal_seo(tytul, r.get("content") or ""):
                licznik["  (w tym z sygnałem SEO -> idzie do oceny modelu)"] += 1
            linie.append(f"  [OK]{' UCIETY ->' if uciety else '          '} {tytul[:38]}")
            linie.append(f"      {url[:88]}")
            if uciety:
                linie.append(f"      => {strona}")
            wszystkie_ok.append(strona)

        linie.append("")

    linie.append("=" * 78)
    linie.append("KONTROLA ŻYWOTNOŚCI (na zaakceptowanych stronach)")
    linie.append("=" * 78)
    with ThreadPoolExecutor(max_workers=12) as pool:
        stany = list(pool.map(app.sprawdz_zywotnosc, wszystkie_ok))
    for strona, stan in zip(wszystkie_ok, stany):
        licznik[f"ŻYWOTNOŚĆ: {stan}"] += 1
        if stan != "zywa":
            znacznik = "[X] MARTWA " if stan == "martwa" else "[?] NIEPEWNA"
            linie.append(f"  {znacznik} {strona}")

    linie.append("")
    linie.append("=" * 78)
    linie.append("PODSUMOWANIE")
    linie.append("=" * 78)
    for klucz, ile in licznik.most_common():
        linie.append(f"  {ile:4}  {klucz}")

    przeszlo = licznik["PRZECHODZI"]
    martwe = licznik["ŻYWOTNOŚĆ: martwa"]
    linie.append("")
    linie.append(f"  FINALNIE NA LIŚCIE: {przeszlo - martwe} firm "
                 f"(przeszło filtr: {przeszlo}, odpadło jako martwe: {martwe})")
    linie.append("  UWAGA: odsiew konkurentów tu nie działa — wymaga modelu i jest async.")

    with open("raport_filtr.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(linie))
    print("\nRaport z audytu na żywo zapisany: raport_filtr.txt")


def main():
    bledy = sprawdz_regresje()
    if "--live" in sys.argv:
        audyt_na_zywo()
    else:
        print("\n(audyt na żywych wynikach Tavily: python test_filtr.py --live)")
    sys.exit(1 if bledy else 0)


if __name__ == "__main__":
    main()

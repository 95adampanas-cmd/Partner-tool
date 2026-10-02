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

import inspect

import app
import profil

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


# Tytuły artykułów o branży. To NIE są powody do odrzucenia firmy — cyrekdigital.com
# czy grupa-icea.pl to realne agencje, artykułowy jest tylko tytuł, który zwróciła
# wyszukiwarka. Trafienie zamienia nazwę na domenę, żeby na liście nie stało
# „Agencja e-commerce — czym się zajmuje i jak ją wybrać?" zamiast nazwy firmy.
#
# Wszystkie sześć przypadków „ARTYKUŁ" to realne wyniki z przebiegu 24.09.2026,
# które przeszły przez listę dosłownych fraz: zaimek rozbijał „jak wybrać",
# kropka rozbijała „ vs ", a „czym się zajmuje" nie było na liście wcale.
TYTULY_ARTYKULOW = [
    ("Agencja e-commerce - czym się zajmuje i jak ją wybrać?", True,  "zaimek w środku frazy"),
    ("Dobra agencja e-commerce. Jak ją znaleźć?",              True,  "zaimek + pytajnik"),
    ("Agencja SEM - czym się zajmuje? | iCEA Group",           True,  "pytajnik NIE na końcu"),
    ("Agencja SEM - jak wpływa na rozwój firmy?",              True,  "pytanie o wpływ"),
    ("Agencja PrestaShop czy to najlepszy wybór?",             True,  'fraza: czy to'),
    ("Agencja PrestaShop vs. samodzielne wdrożenie – co wybrać?", True, 'vs z kropka'),

    ("Convertis | Agencja eCommerce",                          False, "nazwa firmy"),
    ("Waynet lider wdrożeń PrestaShop",                        False, "nazwa firmy"),
    ("Grupa 3 Agencja Reklamowa",                              False, "PUŁAPKA: liczba w nazwie"),
    ("Studio 102 - agencja kreatywna",                         False, "PUŁAPKA: liczba + myślnik"),
    ("Tebim - tworzenie sklepów internetowych",                False, "nazwa + opis usługi"),
    ("Verseo - Agencja SEO & SEM",                             False, "nazwa firmy"),
    ("Sellision - wdrożenia PrestaShop i platformy B2B",       False, "nazwa + opis usługi"),
]


def sprawdz_tytuly_artykulow() -> int:
    """Czy rozpoznajemy tytuł artykułu, nie myląc go z nazwą firmy."""
    bledy = 0
    for tytul, ma_trafic, opis in TYTULY_ARTYKULOW:
        trafil = bool(app.TYTUL_ARTYKULU.search(tytul))
        ok = trafil == ma_trafic
        bledy += not ok
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {'artykuł' if trafil else 'nazwa firmy':11} "
              f"| {opis:28} | {tytul[:40]}")
    return bledy


def sprawdz_wykluczanie_domen() -> int:
    """Czy „Szukaj dalej" mówi wyszukiwarce, czego NIE pokazywać.

    Wcześniej kolejna runda dostawała od Tavily w dużej części te same domeny co
    poprzednia, my kasowaliśmy je lokalnie i z piętnastu wyników zostawały trzy —
    zapłacone za piętnaście, pokazane trzy. Stąd „kolejne rundy nic nie dają".

    Test offline: podmieniamy klienta Tavily i sprawdzamy, CO byśmy wysłali.
    """
    import app as _a

    bledy = 0
    wyslane = {}

    class AtrapaKlienta:
        def __init__(self, api_key=None): pass
        def search(self, zapytanie, **kw):
            wyslane.update(kw)
            wyslane["query"] = zapytanie
            return {"results": []}

    prawdziwy = _a.TavilyClient
    _a.TavilyClient = AtrapaKlienta
    try:
        _a.tavily_search("agencja e-commerce", 15, ["verseo.pl", "icea.pl"])
        wykluczone = wyslane.get("exclude_domains") or []
        if "verseo.pl" in wykluczone and "icea.pl" in wykluczone:
            print(f"  OK   | pokazane domeny lecą do Tavily jako wykluczenie ({len(wykluczone)})")
        else:
            print(f"  BŁĄD | wykluczenie nie dociera do Tavily: {wykluczone}")
            bledy += 1

        # Bez historii NIE wysyłamy pustej listy — niektóre API traktują ją inaczej
        # niż brak parametru, a tu chodzi o zwykłe pierwsze wyszukiwanie.
        wyslane.clear()
        _a.tavily_search("agencja e-commerce", 15, [])
        if wyslane.get("exclude_domains") is None:
            print("  OK   | pierwsza runda idzie bez wykluczeń")
        else:
            print(f"  BŁĄD | pusta historia wysyła: {wyslane.get('exclude_domains')!r}")
            bledy += 1

        # Tavily ma limit na długość listy — przy długiej historii bierzemy najnowsze.
        wyslane.clear()
        _a.tavily_search("x", 15, [f"firma{i}.pl" for i in range(90)])
        ile = len(wyslane.get("exclude_domains") or [])
        if ile <= 40:
            print(f"  OK   | długa historia przycięta do {ile} domen")
        else:
            print(f"  BŁĄD | wysyłamy {ile} domen, Tavily tego nie przyjmie")
            bledy += 1
    finally:
        _a.TavilyClient = prawdziwy
    return bledy


def sprawdz_presety() -> int:
    """Czy presety wyszukiwania są dobrze zbudowane — i czy zgadzają się z tagami.

    DWA ZESTAWY, BO DWA RÓŻNE SPOSOBY SZUKANIA. Wyszukiwarka i Google przeszukują
    TREŚĆ stron, więc znoszą frazy wąskie („wdrożenia Consent Mode"). Mapy dopasowują
    do NAZWY firmy i kategorii wizytówki, więc ta sama fraza zwraca tam zero — żadna
    wizytówka się tak nie nazywa. Stąd osobna, krótsza i ogólniejsza lista dla Map.

    CO SIĘ ZMIENIŁO 24.09.2026 — I DLACZEGO WRACAMY DO JEDNEJ LISTY. Przez jeden
    dzień były dwie: 29 kategorii do SZUKANIA (PRESETY) i 10 szufladek, do których
    firma trafiała PO researchu (KATEGORIE_PARTNEROW). Brzmiało to sensownie, ale
    w interfejsie wyszło tak: szukasz w „Sklepy internetowe", a znaleziona firma
    dostaje tag „Budowa stron i sklepów" — nazwę, której nie ma na żadnej liście
    wyboru. Filtr w „Szukaj podobnych" i na liście Firm pokazywał wtedy szufladki
    tak szerokie, że osiem firm z dziewiętnastu siedziało pod jednym chipem.

    Teraz obie role pełni jedna lista i ten test tego pilnuje: nazwy kategorii
    w PRESETY.partner muszą być IDENTYCZNE z KATEGORIE_PARTNEROW, znak w znak.
    """
    import re
    from pathlib import Path
    from collections import Counter

    plik = Path(__file__).resolve().parent.parent / "frontend" / "app.js"
    if not plik.exists():
        print("  POMINIĘTE — nie znaleziono frontend/app.js")
        return 0

    tresc = plik.read_text(encoding="utf-8")
    granice = [("partner", "partner: [", "mapy: ["),
               ("mapy", "mapy: [", "klient: [")]

    bledy = 0
    for etykieta, od, do in granice:
        blok = tresc[tresc.index(od):tresc.index(do)]
        # Komentarze WYCINAMY PRZED parsowaniem. Bez tego wyrażenie łapie tekst
        # w cudzysłowach ze środka komentarza i zgłasza duplikaty, których nie ma —
        # nabrałem się na to przy pierwszej analizie tej listy.
        blok = re.sub(r"//[^\n]*", "", blok)
        grupy = re.findall(r'\["([^"]+)",\s*"([^"]*)",\s*\[(.*?)\](?:\s*,[^\]]*)?\s*\]', blok, re.S)

        ile_fraz = 0
        for nazwa, glowna, surowe in grupy:
            pod = [x for x in re.findall(r'"([^"]+)"', surowe) if x.strip()]
            ile_fraz += 1 + len(pod)
            if not glowna.strip():
                print(f"  BŁĄD | [{etykieta}] kategoria bez frazy głównej: {nazwa!r}")
                bledy += 1
            if not pod:
                print(f"  BŁĄD | [{etykieta}] kategoria bez podkategorii: {nazwa!r}")
                bledy += 1
            # Powtórzenie W OBRĘBIE kategorii to błąd. MIĘDZY kategoriami — nie:
            # w Mapach „firma informatyczna" trafnie opisuje i wdrożeniowca CRM,
            # i ERP, bo wizytówki są ogólne.
            powt = [k for k, v in Counter(pod).items() if v > 1]
            if powt:
                print(f"  BŁĄD | [{etykieta}] {nazwa!r} powtarza hasło: {powt}")
                bledy += len(powt)

        if not grupy:
            print(f"  BŁĄD | [{etykieta}] nie sparsowałem ani jednej kategorii")
            bledy += 1
        else:
            print(f"  OK   | [{etykieta}] {len(grupy)} kategorii, {ile_fraz} fraz")

    # ── Zgodność presetów z tagami. To jest właściwy powód istnienia tego testu:
    #    rozjazd nie wywala niczego, tylko po cichu produkuje tagi spoza filtrów.
    blok = re.sub(r"//[^\n]*", "", tresc[tresc.index("partner: ["):tresc.index("mapy: [")])
    nazwy = [m.group(1) for m in re.finditer(r'\n\s*\["([^"]+)",', blok)]

    brak_w_tagach = [n for n in nazwy if n not in app.KATEGORIE_PARTNEROW]
    brak_w_presetach = [k for k in app.KATEGORIE_PARTNEROW if k not in nazwy]
    for n in brak_w_tagach:
        print(f"  BŁĄD | preset {n!r} nie ma odpowiednika w KATEGORIE_PARTNEROW")
        bledy += 1
    for k in brak_w_presetach:
        print(f"  BŁĄD | kategoria {k!r} nie ma presetu — nikt jej nie wyszuka")
        bledy += 1
    if not brak_w_tagach and not brak_w_presetach:
        print(f"  OK   | {len(app.KATEGORIE_PARTNEROW)} kategorii: preset i tag to ta sama nazwa")

    # Sekcje muszą się sumować do całości — inaczej prompt wymieniłby modelowi
    # mniej kategorii, niż front pokazuje na filtrach.
    ok = app.KATEGORIE_USLUGOWE + app.KATEGORIE_SAAS == app.KATEGORIE_PARTNEROW
    print(f"  {'OK  ' if ok else 'BŁĄD'} | sekcje (usługi {len(app.KATEGORIE_USLUGOWE)} "
          f"+ SaaS {len(app.KATEGORIE_SAAS)}) składają się na pełną listę")
    bledy += not ok

    # Prompt ekstrakcji dostaje listy z tych samych stałych — sprawdzamy WYNIK,
    # bo to on trafia do modelu. Ręczna kopia w prompcie była tu wcześniej.
    braki = [k for k in app.KATEGORIE_PARTNEROW if k not in app.EKSTRAKCJA_PROMPT]
    if braki:
        print(f"  BŁĄD | prompt nie wymienia kategorii: {braki}")
        bledy += len(braki)
    else:
        print("  OK   | prompt ekstrakcji wymienia wszystkie kategorie")

    # Stare szufladki muszą mieć wpis w mapie migracji — bez tego rekord
    # z kopii zapasowej wróciłby jako „Bez kategorii" i nikt by nie zauważył.
    ok = all(v is None or v in app.KATEGORIE_PARTNEROW
             for v in app.STARE_KATEGORIE.values())
    print(f"  {'OK  ' if ok else 'BŁĄD'} | mapa starych nazw wskazuje na istniejące kategorie")
    bledy += not ok
    return bledy


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

    # Regula "menu uslug wygrywa z landingiem ze stopki". Kosztowala nas bledna
    # ocene Tebimu: strona /pozycjonowanie opisuje pelny proces (audyt, link
    # building, comiesieczne raporty), ale wisi tylko w stopce i nie ma jej w menu
    # USLUGI — to landing pod fraze "Pozycjonowanie Kalisz", nie pozycja w ofercie.
    if "landing pod lokalne wyszukiwanie" in app.EKSTRAKCJA_PROMPT:
        print("  OK   | ekstrakcja: menu uslug wygrywa z landingiem ze stopki")
    else:
        print("  BŁĄD | brak reguly o landingach — wroci blad z Tebimem")
        bledy += 1

    # Gotowe ujecia synergii dla branz. Bez nich model buduje narracje od zera przy
    # kazdym partnerze — raz mocno, raz jak ulotka. Z nimi ta sama mysl brzmi tak samo
    # dobrze przy kazdej firmie z danej branzy.
    # Naglowek zmienil sie 24.09.2026 przy scaleniu dwoch plikow w jeden — szczegoly
    # sprawdza sprawdz_synergie(), tu pilnujemy samego faktu podpiecia.
    if all("CZĘŚĆ 2 — GOTOWE UJĘCIA" in x for x in (app.CZAT_SYNERGIE, app.MAIL_SYNERGIE)):
        print("  OK   | gotowe ujecia branzowe podpiete do czatu i maili")
    else:
        print("  BŁĄD | brak ujec branzowych — model wymysla narracje od zera")
        bledy += 1

    # Kotwica na glownym profilu. Bez niej dluga lista uslug potrafi przykryc to,
    # czym firma JEST: z agencji PrestaShop robi sie "software house", a synergia
    # buduje sie na czyms, czym partner sie nie czuje.
    if all("ZACZNIJ OD GŁÓWNEGO PROFILU" in x
           for x in (app.CZAT_SYNERGIE, app.MAIL_SYNERGIE)):
        print("  OK   | synergia zakotwiczona na branzy i kategorii, nie na liscie uslug")
    else:
        print("  BŁĄD | brak kotwicy profilu — lista uslug przykryje glowny profil")
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


def sprawdz_mapy() -> int:
    """Czy miasto idzie do Map jako OBSZAR, a nie jako tekst w zapytaniu.

    To kosztowało nas 95% wyników. Places dopasowuje textQuery dosłownie, więc
    „doradztwo e-commerce poznań" szukało wizytówek z Poznaniem w nazwie i zwracało
    JEDNĄ firmę; ta sama fraza z obszarem Poznania zwraca 22. Objaw był niewidoczny:
    wyniki przychodziły, tylko było ich absurdalnie mało, a nikt nie wiedział czemu.

    Test jest offline — podmieniamy wywołanie sieciowe i sprawdzamy, CO byśmy wysłali.
    """
    import mapy

    bledy = 0
    wyslane = []
    prawdziwe_zapytaj, prawdziwy_obszar = mapy._zapytaj, mapy.obszar
    mapy._zapytaj = lambda tresc, pola=None: (wyslane.append(tresc) or {"places": []})
    mapy.obszar = lambda nazwa: {
        "nazwa": "Poznań", "km_ns": 24, "km_we": 23,
        "prostokat": {"low": {"latitude": 52.2, "longitude": 16.7},
                      "high": {"latitude": 52.5, "longitude": 17.1}}}
    try:
        mapy.szukaj("doradztwo e-commerce", "poznań")
        t = wyslane[0]
        if "poznań" in t["textQuery"].lower():
            print(f"  BŁĄD | miasto wróciło do treści zapytania: {t['textQuery']!r}")
            bledy += 1
        else:
            print(f"  OK   | fraza bez miasta: {t['textQuery']!r}")
        if "locationBias" in t:
            print("  OK   | miasto poszło jako obszar (locationBias)")
        else:
            print("  BŁĄD | brak locationBias — szukamy po całej Polsce")
            bledy += 1

        # Gdy obszaru nie da się rozpoznać, wracamy do starego sposobu — ale wtedy
        # front MUSI o tym powiedzieć, inaczej user widzi jeden wynik bez wyjaśnienia.
        wyslane.clear()
        mapy.obszar = lambda nazwa: None
        r = mapy.szukaj("doradztwo e-commerce", "Kostrzyca Dolna")
        if r.get("obszar_nierozpoznany") and "kostrzyca" in wyslane[0]["textQuery"].lower():
            print("  OK   | nierozpoznany obszar: stary sposób + flaga dla użytkownika")
        else:
            print("  BŁĄD | nierozpoznany obszar nie jest zgłaszany")
            bledy += 1
    finally:
        mapy._zapytaj, mapy.obszar = prawdziwe_zapytaj, prawdziwy_obszar
    return bledy


def sprawdz_zrodlo_google() -> int:
    """Czy źródło „Google" poprawnie czyta SERP-a — na zapisanej odpowiedzi, bez kosztu.

    Zaczynaliśmy to na Custom Search API i moduł był gotowy, zanim ktokolwiek sprawdził,
    czy to API nadal robi to, co pamiętamy. Nie robiło: Google wygasza przeszukiwanie
    całej sieci (nowe wyszukiwarki od 20.01.2026, całe API 01.01.2027). Kod działał
    poprawnie i był bezużyteczny. Stąd ten test — na prawdziwej próbce odpowiedzi.
    """
    import szukaj_google, dfs

    bledy = 0
    prawdziwe = szukaj_google.dfs.wywolaj
    szukaj_google.dfs.wywolaj = lambda *a, **k: dfs.wczytaj(
        "audyt_luka_elektromaniacy.pl_serp_gps dla dziecka")
    try:
        r = szukaj_google.szukaj("gps dla dziecka")
        w = r["wyniki"]
        if w:
            print(f"  OK   | SERP sparsowany: {len(w)} wyników organicznych, koszt ${r['koszt']}")
        else:
            print("  BŁĄD | parser nie wyciągnął żadnego wyniku z SERP-a")
            bledy += 1
        # Filtr dostaje url+title+content; brak któregokolwiek i firma przepada
        # albo trafia na listę jako goła domena bez opisu.
        braki = [k for k in ("url", "title", "content")
                 if any(not x.get(k) for x in w)]
        if braki:
            print(f"  BŁĄD | wyniki bez pól: {braki}")
            bledy += 1
        else:
            print("  OK   | każdy wynik ma url, tytuł i opis — kształt zgodny z Tavily")
        # SERP zawiera też people_also_ask, video, popular_products — to nie są firmy.
        if all("type" not in x for x in w):
            print("  OK   | wzięte tylko pozycje organiczne")
    finally:
        szukaj_google.dfs.wywolaj = prawdziwe
    return bledy


def sprawdz_audyt_bez_dataforseo() -> int:
    """Czy da się zrobić audyt GEO bez DataForSEO — i czy powtórzenia liczą się dobrze.

    Sekcja „pytania klientów" jest jedyną, która przeżywa awarię albo puste saldo
    dostawcy SEO. Do tego potrzebuje silników na NASZYCH kluczach — i muszą być
    co najmniej dwa, bo przy jednym nie da się odróżnić cechy modelu od stanu rynku.
    Zmierzone na Tebimie: ChatGPT wymienił firmę, Claude nie i podał 7 konkurentów.
    """
    import audyt

    bledy = 0
    wlasne = {k: v for k, v in audyt.SILNIKI.items() if v.get("wlasny_klucz")}
    if len(wlasne) >= 2:
        print(f"  OK   | {len(wlasne)} silniki na własnych kluczach: {', '.join(wlasne)}")
    else:
        print(f"  BŁĄD | tylko {len(wlasne)} silnik bez DataForSEO — audyt zależny od dostawcy")
        bledy += 1

    # Scalanie prób. 1 z 3 to widoczność przypadkowa i musi być odróżnialna
    # od 3 z 3 — inaczej powtarzanie pytań nie wnosi niczego poza kosztem.
    proby = [
        {"wspomniana": False, "cytowana": False, "zrodla": ["a.pl"], "marki": ["X"], "odpowiedz": "nie"},
        {"wspomniana": False, "cytowana": False, "zrodla": ["b.pl"], "marki": ["Y"], "odpowiedz": "nie"},
        {"wspomniana": True,  "cytowana": True,  "zrodla": ["a.pl", "c.pl"], "marki": ["X", "Z"], "odpowiedz": "TAK"},
    ]
    s = audyt.scal_powtorzenia(proby)
    sprawdzenia = [
        (s.get("trafien") == 1 and s.get("prob") == 3, "liczy 1 z 3 trafień"),
        (s.get("wspomniana") is True, "jedno trafienie wystarcza do „wymieniona”"),
        (len(s.get("zrodla") or []) == 3, "źródła scalone sumą, bez duplikatów"),
        (len(s.get("marki") or []) == 3, "konkurenci scaleni sumą"),
        (s.get("odpowiedz") == "TAK", "do raportu idzie próba Z trafieniem — to ona jest dowodem"),
    ]
    for ok, opis in sprawdzenia:
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
        bledy += not ok
    return bledy


def sprawdz_boty_ai() -> int:
    """Czy audyt odróżnia bota TRENINGOWEGO od UŻYTKOWEGO — i czy czyta Content-Signal.

    SKĄD TEN TEST. Sprawdzone na sortlist.pl 24.09.2026: blokują GPTBota (zbiera
    materiał do uczenia modelu), ale wpuszczają ChatGPT-User (pobiera stronę, gdy
    ktoś pyta asystenta o firmę). Nasz raport nazywał to blokadą i pisał „ChatGPT
    nie pobiera treści strony". To była nieprawda, a klient dostałby polecenie
    naprawy konfiguracji ustawionej wzorowo — w dokumencie, który ma nas
    uwiarygadniać. Bez tego testu pomyłka wróci przy pierwszej zmianie w geo.BOTY.
    """
    import geo

    bledy = 0

    # ── Lista botów. Sama obecność nazw w geo.BOTY jest warunkiem, żeby audyt
    #    w ogóle zauważył, że asystent ma wstęp na stronę.
    braki = [b for b in ("ChatGPT-User", "Claude-User", "Claude-SearchBot",
                         "Perplexity-User", "DuckAssistBot", "MistralAI-User",
                         "meta-externalfetcher") if b not in geo.BOTY]
    if braki:
        print(f"  BŁĄD | brakuje botów użytkowych w geo.BOTY: {', '.join(braki)}")
        bledy += 1
    else:
        print(f"  OK   | {len(geo.NAZWY_UZYTKOWE)} botów użytkowych obok "
              f"{len(geo.BOTY) - len(geo.NAZWY_UZYTKOWE)} treningowych")

    # Rozłączność ról. Gdyby GPTBot wpadł do zbioru użytkowych, jego blokada
    # znów podnosiłaby alarm — czyli dokładnie ten błąd, który naprawiamy.
    for t in ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended"):
        if t in geo.NAZWY_UZYTKOWE:
            print(f"  BŁĄD | {t} to bot treningowy, a leży wśród użytkowych")
            bledy += 1

    # ── Parsowanie robots.txt bez sieci. Udajemy odpowiedź serwera, bo test ma
    #    sprawdzać NASZ kod, a nie to, co dziś stoi na cudzym serwerze.
    class Odp:
        status_code = 200
        text = ("User-agent: GPTBot\nDisallow: /\n\n"
                "User-agent: ChatGPT-User\nAllow: /\n\n"
                "User-agent: *\nAllow: /\n"
                "Content-Signal: search=yes,ai-input=yes,ai-train=no\n")

    oryginal = geo._pobierz
    geo._pobierz = lambda *a, **k: Odp()
    try:
        r = geo.sprawdz_robots("https://przyklad.pl")
    finally:
        geo._pobierz = oryginal

    role = {z["bot"]: z["rola"] for z in r["zablokowane"]}
    sprawdzenia = [
        (role.get("GPTBot") == "treningowy", "GPTBot rozpoznany jako treningowy"),
        ("ChatGPT-User" not in role, "ChatGPT-User z Allow nie trafia na listę blokad"),
        (r["content_signal"] == {"search": "yes", "ai-input": "yes", "ai-train": "no"},
         "Content-Signal rozłożony na pary"),
    ]
    for ok, opis in sprawdzenia:
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
        bledy += not ok

    # ── Język raportu. To jest sedno poprawki: ta sama konfiguracja co wyżej
    #    NIE MOŻE dać ani jednej pozycji o wadze „blokada".
    pusto = {"jest": True, "adres": "", "tytul": "", "opis": "", "schema": [],
             "same_as": [], "naglowki": [], "znakow": 0}
    u = geo.zbuduj_ustalenia({"dostepna": True}, r, pusto, {"nazwa": "Przykład"})
    blokady = [x for x in u if x["waga"] == "blokada"]
    ok = not blokady
    print(f"  {'OK  ' if ok else 'BŁĄD'} | blokada treningowego to nie „blokada”"
          + ("" if ok else f" — zgłoszono: {blokady[0]['tytul']}"))
    bledy += not ok

    # ...a zamknięcie bota UŻYTKOWEGO musi ją dać, bo to realna utrata widoczności.
    r2 = dict(r, zablokowane=[{"bot": "ChatGPT-User", "silnik": "ChatGPT",
                               "udzial": 86.4, "skutek": "nie wejdzie na stronę",
                               "rola": "uzytkowy"}])
    u2 = geo.zbuduj_ustalenia({"dostepna": True}, r2, pusto, {"nazwa": "Przykład"})
    ok = any(x["waga"] == "blokada" for x in u2)
    print(f"  {'OK  ' if ok else 'BŁĄD'} | zamknięcie ChatGPT-User to nadal blokada")
    bledy += not ok
    return bledy


def sprawdz_kolejke() -> int:
    """Czy kolejka umie przechować kategorię, pod którą firmę znaleziono.

    DLACZEGO TO OSOBNY TEST. Kolumnę dokładaliśmy do TABELI, KTÓRA JUŻ ISTNIEJE,
    a `CREATE TABLE IF NOT EXISTS` w takim wypadku nie robi nic — schemat w kodzie
    wyglądałby poprawnie, a baza u kogoś, kto używał narzędzia wcześniej, zostałaby
    stara. Każde dodanie do kolejki kończyłoby się wtedy błędem 500. Sprawdzamy
    więc FAKTYCZNY schemat bazy, nie treść pliku.
    """
    import baza

    bledy = 0
    kolumny = {r["name"] for r in baza._polacz().execute("PRAGMA table_info(kolejka)")}
    for pole in ("kategoria", "zapytanie", "zrodlo"):
        ok = pole in kolumny
        print(f"  {'OK  ' if ok else 'BŁĄD'} | kolejka ma kolumnę {pole}")
        bledy += not ok

    # Kategoria z wiersza musi wygrywać z kategorią partii — inaczej import
    # z katalogu wrzuciłby 180 firm z różnych branż pod jedną etykietę.
    import inspect
    sygn = inspect.signature(baza.dodaj_do_kolejki).parameters
    ok = "kategoria" in sygn
    print(f"  {'OK  ' if ok else 'BŁĄD'} | dodaj_do_kolejki przyjmuje kategorię")
    bledy += not ok
    return bledy


def sprawdz_synergie() -> int:
    """Czy plik synergii jest podpięty tam, gdzie ma być — i czy nic z niego nie wypadło.

    JEDEN PLIK OD 24.09.2026. Wcześniej były dwa: `synergie.md` (jak pisać)
    i `synergie_branze.md` (co pisać dla branży), sklejane w app.py. Adam dostarczył
    jeden spójny dokument; ten test pilnuje, żeby rozjazd nie wrócił bokiem.

    TESTUJEMY PROMPT, NIE ODPOWIEDŹ MODELU. Odpowiedzi nie da się przypiąć do asercji,
    ale można sprawdzić, czy instrukcja w ogóle do modelu dociera — a to właśnie jest
    tryb awarii: ktoś podmienia plik albo zmienia sklejanie i połowa materiału cicho
    wypada z promptu. Nikt tego nie zauważy, bo model i tak coś odpowie.
    """
    bledy = 0

    tresc = profil.synergie()
    ok = len(tresc) > 20000
    print(f"  {'OK  ' if ok else 'BŁĄD'} | plik synergii wczytany ({len(tresc)} znaków)")
    bledy += not ok

    # Trzy części pliku pełnią trzy różne role. Brak którejkolwiek to inny produkt:
    # bez części 2 model wymyśla narrację od zera, bez części 3 dobiera sekcję na oko.
    for czesc in ("CZĘŚĆ 1 — INSTRUKCJA", "CZĘŚĆ 2 — GOTOWE UJĘCIA",
                  "CZĘŚĆ 3 — DOBÓR SEKCJI"):
        ok = czesc in tresc
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {czesc}")
        bledy += not ok

    for nazwa, tekst in (("czat", app.CZAT_SYNERGIE), ("mail", app.MAIL_SYNERGIE)):
        ok = tresc in tekst
        print(f"  {'OK  ' if ok else 'BŁĄD'} | [{nazwa}] dostaje CAŁY plik, nie wycinek")
        bledy += not ok

    # Zakazy z części „O czym NIE piszesz" — to jest polecenie Adama z 24.09.2026
    # i najłatwiejsza rzecz do zgubienia przy podmianie pliku.
    for fragment, opis in (("Żadnego modelu współpracy", "zakaz nazywania modelu współpracy"),
                           ("Żadnych pieniędzy", "zakaz rabatu, prowizji i marży")):
        ok = fragment in tresc
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
        bledy += not ok

    # Styl ekspercki był drugą drogą, którą „white label" wchodziło do maila,
    # z pominięciem instrukcji synergii.
    ekspercki = next((t for n, t in app.STYLE_MAILI if n == "ekspercki"), "")
    zakazane = [w for w in ("white-label", "white label", "referral", "15%") if w in ekspercki]
    ok = not zakazane
    print(f"  {'OK  ' if ok else 'BŁĄD'} | styl ekspercki nie nazywa modelu współpracy"
          + (f" — znalazłem: {zakazane}" if zakazane else ""))
    bledy += not ok

    # Tabela doboru sekcji musi mówić TYMI SAMYMI nazwami kategorii, którymi
    # narzędzie taguje firmy. Rozjazd nie wywala niczego — po prostu model
    # przestaje trafiać w gotowe ujęcie i pisze własne.
    brak = [k for k in app.KATEGORIE_PARTNEROW if k not in tresc]
    ok = not brak
    print(f"  {'OK  ' if ok else 'BŁĄD'} | tabela doboru zna wszystkie kategorie narzędzia"
          + (f" — brakuje: {brak}" if brak else ""))
    bledy += not ok

    # Stary plik nie może wrócić niezauważony: wczytywałby się obok nowego
    # i model dostawałby dwa opisy tego samego formatu.
    from pathlib import Path
    stary = Path(__file__).resolve().parent / "synergie_branze.md"
    ok = not stary.exists()
    print(f"  {'OK  ' if ok else 'BŁĄD'} | nie ma już osobnego synergie_branze.md")
    bledy += not ok
    return bledy


def sprawdz_maile() -> int:
    """Czy wzorce maili są podpięte i czy prompt im nie przeczy.

    SKĄD TEN TEST. Wzorce od zespołu mówią: forma „Państwo". Stary styl „partnerski"
    kazał pisać nieformalnie, na „Cześć". Dwa sprzeczne polecenia w jednym prompcie
    nie dają błędu — dają lo­terię: raz wychodzi tak, raz inaczej, i nikt nie wie
    dlaczego. Takie sprzeczności trzeba łapać w kodzie, bo w wyniku są niewidoczne.
    """
    bledy = 0

    baza = app.baza_maili()
    ok = len(baza) > 3000
    print(f"  {'OK  ' if ok else 'BŁĄD'} | wzorce maili wczytane ({len(baza)} znaków)")
    bledy += not ok

    # Pięć wzorców. Każdy styl odwołuje się do konkretnego numeru, więc brak
    # któregokolwiek znaczy, że model dostaje polecenie bez pokrycia.
    for wzorzec in ("Mail 1 — uniwersalny", "Mail 2 — web dev", "Mail 3 — marketing",
                    "Mail 4 — usługi eksperckie", "Mail 5 — follow-up"):
        ok = wzorzec in baza
        print(f"  {'OK  ' if ok else 'BŁĄD'} | jest wzorzec: {wzorzec}")
        bledy += not ok

    for zasada, opis in (("Forma „Państwo”", "forma „Państwo”"),
                         ("Bez modelu współpracy", "bez modelu współpracy i pieniędzy"),
                         ("150 słów", "limit długości")):
        ok = zasada in baza
        print(f"  {'OK  ' if ok else 'BŁĄD'} | zasada w bazie: {opis}")
        bledy += not ok

    # Trzy wersje mają robić trzy różne rzeczy, a nie trzy tony tego samego maila.
    nazwy = [n for n, _ in app.STYLE_MAILI]
    ok = nazwy == ["dopasowany", "uniwersalny", "follow-up"]
    print(f"  {'OK  ' if ok else 'BŁĄD'} | trzy wersje maila: {', '.join(nazwy)}")
    bledy += not ok

    # SPRZECZNOŚĆ, KTÓRA BYŁA. Żaden styl nie może kazać pisać na „ty", skoro wzorce
    # są na „Państwo" — ani wracać do nazywania modelu współpracy.
    caly = " ".join(o for _, o in app.STYLE_MAILI) + " " + app.MAIL_SYSTEM
    ok = "Cześć" not in caly and "na 'ty'" not in caly
    print(f"  {'OK  ' if ok else 'BŁĄD'} | żaden styl nie każe pisać nieformalnie")
    bledy += not ok

    # Prompt musi przenosić zasady z pliku — sam plik w kontekście nie wystarcza,
    # bo model traktuje go jako materiał, a nie jako polecenie.
    for fragment, opis in (("forma „Państwo", "forma „Państwo” w instrukcji"),
                           ("150 słów", "limit długości w instrukcji"),
                           ("GOTOWEGO WZORCA", "polecenie pisania z wzorca")):
        ok = fragment in app.MAIL_SYSTEM
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
        bledy += not ok

    # Stary plik nie może wrócić — czytałby się obok nowego tylko wtedy, gdyby ktoś
    # przywrócił też starą ścieżkę, ale jego obecność w repo myli przy edycji.
    from pathlib import Path
    stary = Path(__file__).resolve().parent.parent / "docs" / "email-examples.md"
    ok = not stary.exists()
    print(f"  {'OK  ' if ok else 'BŁĄD'} | nie ma już docs/email-examples.md")
    bledy += not ok
    return bledy


def sprawdz_czat() -> int:
    """Czy czat dostaje pełną kartę i czy nie pobiera dwa razy tej samej podstrony.

    SKĄD TEN TEST. Zmierzone 24.09.2026 na tribe47: czat dostawał dziewięć pól
    z dwudziestu pięciu, więc na pytanie „do kogo napisać" odpowiadał, że nie wie —
    choć research ustalił „Ewa Wysocka, CEO" i zapisał to w bazie. Do tego każde
    pytanie pobierało podstronę od nowa, bo `pobierz()` nie ma pamięci, a treści
    stron nie trzymamy nigdzie.
    """
    import time

    bledy = 0

    # ── Pamięć pobrań. Liczymy REALNE żądania, podstawiając własny `pobierz`.
    wywolania = []

    def udawany_pobierz(url, timeout=15):
        wywolania.append(url)
        return "<html><body><p>Oferta firmy</p></body></html>"

    oryginal_pobierz, oryginalna_domena = app.pobierz, app._czat_domena
    stan_pamieci = dict(app._POBRANE)
    app.pobierz = udawany_pobierz
    app._czat_domena = "przyklad.pl"
    app._POBRANE.clear()
    try:
        a = app.otworz_podstrone("https://przyklad.pl/oferta")
        b = app.otworz_podstrone("https://przyklad.pl/oferta")
        c = app.otworz_podstrone("https://przyklad.pl/kontakt")

        sprawdzenia = [
            (len(wywolania) == 2, f"dwa adresy = dwa pobrania (było {len(wywolania)})"),
            (a == b, "drugie pytanie o tę samą stronę dostaje tę samą treść"),
            ("[TREŚĆ https://przyklad.pl/oferta]" in b,
             "treść z pamięci zachowuje znacznik — inaczej znika lista źródeł"),
            ("kontakt" in c or "Odmowa" not in c, "inna podstrona pobiera się normalnie"),
        ]
        for ok, opis in sprawdzenia:
            print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
            bledy += not ok

        # Przeterminowanie. Bez tego pamięć zamienia się w cichą kopię serwisu:
        # strona się zmienia, a czat miesiącami opowiada stan sprzed zmiany.
        app._POBRANE["https://przyklad.pl/oferta"] = (
            time.time() - app.WAZNOSC_POBRANIA - 1, "stare")
        app.otworz_podstrone("https://przyklad.pl/oferta")
        ok = len(wywolania) == 3
        print(f"  {'OK  ' if ok else 'BŁĄD'} | po wygaśnięciu pobiera na nowo")
        bledy += not ok

        # Ograniczenie do domeny firmy musi przeżyć dołożenie pamięci — inaczej
        # narzędzie staje się otwartym proxy z naszego IP.
        obca = app.otworz_podstrone("https://inna-domena.pl/cokolwiek")
        ok = obca.startswith("Odmowa")
        print(f"  {'OK  ' if ok else 'BŁĄD'} | adres spoza domeny firmy dalej odrzucany")
        bledy += not ok
    finally:
        app.pobierz, app._czat_domena = oryginal_pobierz, oryginalna_domena
        app._POBRANE.clear()
        app._POBRANE.update(stan_pamieci)

    # ── Karta firmy. Sprawdzamy, czego NIE wolno pominąć.
    zrodlo = inspect.getsource(app.api_czat)
    ok = '"zrodlo_danych", "tryb", "w_koszyku", "zbadana", "url"' in zrodlo
    print(f"  {'OK  ' if ok else 'BŁĄD'} | karta idzie w całości, poza polami technicznymi")
    bledy += not ok

    ok = "PODSTRONY JUŻ PRZECZYTANE" in zrodlo
    print(f"  {'OK  ' if ok else 'BŁĄD'} | model wie, co research już przeczytał")
    bledy += not ok
    return bledy


def sprawdz_dokument() -> int:
    """Czy dokument dla klienta partnera składa się poprawnie i nie rusza wzoru.

    CO TU MOŻE PÓJŚĆ NIE TAK. Ten plik idzie do klienta partnera pod marką ICEA,
    więc dwie rzeczy muszą być pewne: że podmieniamy DOKŁADNIE trzy sekcje i że
    reszta — case study Botland, nagroda, zdjęcia, stopka — zostaje bajt w bajt.
    Regex, który złapałby o jeden znacznik za dużo, zabrałby pół dokumentu i nikt
    by tego nie zauważył, bo plik dalej otwierałby się w przeglądarce.
    """
    import dokument

    bledy = 0

    ok = dokument.SZABLON.exists()
    print(f"  {'OK  ' if ok else 'BŁĄD'} | szablon jest na miejscu")
    bledy += not ok
    if not ok:
        return bledy

    tresc = {
        "wstep_tytul": "Sklep masz zbudowany.", "wstep_tresc": "Partner zrobił swoje.",
        "audyt_wstep": "Zadaliśmy trzy pytania.", "audyt_wniosek": "Nie padłaś w żadnej.",
        "dostep_tytul": "Roboty mają wstęp", "dostep_tresc": "Od tej strony jest dobrze.",
        "role_tytul": "Kto co robi", "role_wstep": "Partner robi swoje.",
        "braki": [{"tytul": f"Brak {i}", "opis": "Opis"} for i in range(3)],
        "rola_partner_tytul": "Zostaje u partnera",
        "rola_partner": ["sklep", "utrzymanie"], "rola_my": ["widoczność", "pomiar"],
        "role_puenta": "Nikt nikogo nie zastępuje.",
    }
    badanie = {"pytania": ["gdzie kupić sukienkę"], "data": "25.09.2026",
               "dowod": {"pytanie": "gdzie kupić sukienkę", "odpowiedz": "Polecam sklepy A i B."}}

    wzor = dokument.SZABLON.read_text(encoding="utf-8")
    html = dokument.zbuduj(tresc, badanie, "Tebim")

    # Wzór ma ~384 tys. znaków (zdjęcia w base64). Gdyby regex zjadł za dużo,
    # dokument skurczyłby się o dziesiątki tysięcy znaków — stąd próg.
    ok = abs(len(html) - len(wzor)) < 5000
    print(f"  {'OK  ' if ok else 'BŁĄD'} | dokument nie stracił treści "
          f"(wzór {len(wzor)}, wynik {len(html)})")
    bledy += not ok

    # Elementy, których nie wolno ruszyć: dowód, nagroda i identyfikacja.
    for fragment, opis in (("Zrobiliśmy to dla Botland", "case study Botland"),
                           ("European Search Awards 2025", "nominacja"),
                           ("192 588", "liczba wejść z AI"),
                           ("Tomasz Czechowski", "podpis i zdjęcie"),
                           ("Agencja Search od 2007 roku", "stopka ICEA")):
        ok = fragment in html
        print(f"  {'OK  ' if ok else 'BŁĄD'} | zostaje nietknięte: {opis}")
        bledy += not ok

    # Trzy sekcje muszą być PODMIENIONE, a nie dołożone obok.
    for fragment, opis in (("Sklep masz zbudowany.", "wstępniak z modelu"),
                           ("Zadaliśmy trzy pytania.", "mikroaudyt z pomiaru"),
                           ("Nikt nikogo nie zastępuje.", "podział ról")):
        ok = fragment in html
        print(f"  {'OK  ' if ok else 'BŁĄD'} | wstawione: {opis}")
        bledy += not ok

    for fragment, opis in (("Opinie masz zebrane i potwierdzone", "stary wstępniak"),
                           ("Sprawdź to sam, zanim nam uwierzysz", "przykładowy audyt"),
                           ("Opinie są dowodem", "stara sekcja o opiniach")):
        ok = fragment not in html
        print(f"  {'OK  ' if ok else 'BŁĄD'} | usunięte ze wzoru: {opis}")
        bledy += not ok

    # Materiał dostaje klient partnera, więc nie może mówić o firmie od opinii.
    ok = "firma, która prowadzi Twoje opinie" not in html and "Tebim" in html
    print(f"  {'OK  ' if ok else 'BŁĄD'} | nagłówek i stopka mówią o tym partnerze")
    bledy += not ok

    # Cudzysłowy w danych z modelu nie mogą rozwalić znaczników.
    tresc_z_cudzyslowem = dict(tresc, wstep_tytul='Sklep "gotowy" <b>działa</b>')
    html2 = dokument.zbuduj(tresc_z_cudzyslowem, badanie, "Tebim")
    ok = "<b>działa</b>" not in html2 and "&lt;b&gt;" in html2
    print(f"  {'OK  ' if ok else 'BŁĄD'} | tekst z modelu jest escapowany")
    bledy += not ok

    # ── Przewijana ramka z odpowiedziami ─────────────────────────────
    # Trzy pytania i trzy odpowiedzi. Wcześniej ramka pokazywała jedną wybraną,
    # a pozostałe dwie ginęły — klient widział listę pytań i dowód na jedno z nich.
    badanie3 = {
        "pytania": ["gdzie kupić sukienkę", "jaki sklep ma sukienki", "gdzie boutique"],
        "data": "25.09.2026",
        "odpowiedzi": [
            {"pytanie": f"pytanie {i}",
             "odpowiedz": "Polecam **Zalando** ([zalando.pl](https://zalando.pl?utm_source=openai)) i **COS**."}
            for i in (1, 2, 3)],
    }
    html3 = dokument.zbuduj(tresc, badanie3, "Tebim")

    sprawdzenia = [
        (html3.count('class="slajd"') == 3, "trzy slajdy, po jednym na pytanie"),
        (html3.count('class="kropka') == 3, "trzy kropki nawigacji"),
        ('id="ekran-odpowiedzi"' in html3 and "<script>" in html3, "ramka ma obsługę klikania"),
        (html3.count('class="pytanie-link"') == 3, "pytania po lewej są klikalne"),
    ]
    for ok, opis in sprawdzenia:
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
        bledy += not ok

    # Markdown z ChatGPT nie może trafić do dokumentu surowy — we wzorze widać
    # było `**Zalando**` z gwiazdkami, jak wklejony log.
    sekcja = html3.split("s-zmiana")[1][:4000]
    ok = "**" not in sekcja and "<strong>Zalando</strong>" in html3
    print(f"  {'OK  ' if ok else 'BŁĄD'} | pogrubienie z markdownu zamienione na <strong>")
    bledy += not ok

    ok = "utm_source=openai" not in html3
    print(f"  {'OK  ' if ok else 'BŁĄD'} | przypisy z linkami wycięte z odpowiedzi")
    bledy += not ok

    # ── Odpowiedzi w całości ─────────────────────────────────────────
    # Wcześniej ucinaliśmy na 850 znakach: model wymieniał dziesięć firm, klient
    # widział trzy i wielokropek. Dowód, który urywa się w połowie, jest gorszy
    # niż brak dowodu — czytający nie wie, czy dalej padła jego marka.
    nl = chr(10)
    dluga = ("Polecam kilka sklepów:" + nl * 2
             + nl.join(f"{i}. **Firma {i}** z opisem, który zajmuje trochę miejsca"
                       for i in range(1, 21))
             + nl * 2 + "Na koniec warto sprawdzic ZAKONCZENIE-ODPOWIEDZI.")
    html_d = dokument.zbuduj(tresc, dict(badanie3, odpowiedzi=[
        {"pytanie": "gdzie kupić", "odpowiedz": dluga}], pytania=["gdzie kupić"]), "Tebim")

    ok = "ZAKONCZENIE-ODPOWIEDZI" in html_d and "Firma 20" in html_d
    print(f"  {'OK  ' if ok else 'BŁĄD'} | odpowiedź modelu idzie do dokumentu w całości")
    bledy += not ok

    ok = "…</p>" not in html_d and "…</li>" not in html_d
    print(f"  {'OK  ' if ok else 'BŁĄD'} | nic nie jest ucięte wielokropkiem")
    bledy += not ok

    # Zwijanie zamiast ucinania: ramka nie rozpycha sekcji, ale treść zostaje.
    ok = 'class="odp zwiniete"' in html_d and 'class="rozwin"' in html_d
    print(f"  {'OK  ' if ok else 'BŁĄD'} | długa odpowiedź zwija się i rozwija")
    bledy += not ok

    # Markdown modelu to listy, nie myślniki na początku linii.
    ok = html_d.count("<li value=") == 20
    print(f"  {'OK  ' if ok else 'BŁĄD'} | numerowana lista z odpowiedzi ma 20 pozycji "
          f"({html_d.count('<li value=')})")
    bledy += not ok

    # Kartki nie da się kliknąć, więc w druku wszystkie odpowiedzi są pod sobą.
    ok = ".ekran .slajd[hidden]{display:block !important;}" in dokument.STYLE_SLAJDOW
    print(f"  {'OK  ' if ok else 'BŁĄD'} | w wydruku widać wszystkie trzy odpowiedzi")
    bledy += not ok

    # Jedna odpowiedź to nie slajder — nawigacja nie ma wtedy czego przewijać.
    html1 = dokument.zbuduj(tresc, dict(badanie3, odpowiedzi=badanie3["odpowiedzi"][:1],
                                        pytania=badanie3["pytania"][:1]), "Tebim")
    # Szukamy ZNACZNIKA, nie nazwy klasy: nazwa jest też w arkuszu stylów, który
    # dokładamy zawsze. Pierwsza wersja tego testu wywalała się właśnie na tym.
    ok = '<div class="slajd-nawigacja">' not in html1
    print(f"  {'OK  ' if ok else 'BŁĄD'} | przy jednej odpowiedzi nawigacja się nie pojawia")
    bledy += not ok

    # Nazwa pliku trafia do przeglądarki — bez polskich znaków i spacji.
    nazwa = dokument.nazwa_pliku("Ella Boutique Łódź")
    ok = nazwa.startswith("ai-search-ella-boutique-lodz-") and nazwa.endswith(".html")
    print(f"  {'OK  ' if ok else 'BŁĄD'} | nazwa pliku: {nazwa}")
    bledy += not ok

    # Pytania idą do dokumentu słowo w słowo — obcy alfabet nie może przejść.
    ok = app._po_polsku("Gdzie kupić sukienkę na wesele?") and not app._po_polsku(
        "Gdzie kupić eleganck\u044e sukienkę?")
    print(f"  {'OK  ' if ok else 'BŁĄD'} | pytanie z cyrylicą odrzucone")
    bledy += not ok
    return bledy


def sprawdz_raport_geo() -> int:
    """Czy audyt GEO wychodzi jako dokument i czy nie gubi po drodze sekcji.

    CZEGO TU PILNUJEMY. Audyt zwraca pięć rzeczy, których nie ma w materiale dla
    klienta: rozbicie na silniki, konkurentów, źródła, obecność marki na
    cytowanych stronach i ustalenia techniczne. Każda z nich ma własną sekcję
    i własny wykres — a że składamy je stringami, jedna literówka w nazwie klucza
    dałaby pustą sekcję zamiast błędu. Stąd test na każdą z osobna.
    """
    import raport_geo

    bledy = 0
    raport = {
        "firma": {"nazwa": "Tebim", "domena": "tebim.pro", "url": "https://tebim.pro"},
        "podsumowanie": {
            "promptow": 10, "wspomniana": 2, "cytowana": 3, "udzial_wspomnien": 20,
            "per_silnik": [
                {"nazwa": "ChatGPT", "udzial": 86, "pytan": 5, "wspomniana": 1, "cytowana": 2},
                {"nazwa": "Claude", "udzial": 4, "pytan": 5, "wspomniana": 1, "cytowana": 1}],
            "konkurenci": [{"marka": "Waynet", "wystapien": 3},
                           {"marka": "ARTGRUPA", "wystapien": 2}],
        },
        # Dziesięć wierszy, ale PIĘĆ pytań — każde poszło do dwóch modeli.
        "prompty": [{"prompt": f"pytanie {i % 5}", "odpowiedz": f"odpowiedź {i}",
                     "wspomniana": False, "cytowana": False, "marki": [], "zrodla": []}
                    for i in range(10)],
        "powtorzenia": 2,
        "zrodlo_promptow": {"google": 0, "model": 5},
        "zrodla": {"zrodel_lacznie": 132, "domen_unikalnych": 74, "nasze_cytowania": 3,
                   "nasze_miejsce": 6, "remisujacych": 3,
                   "top_zrodla": [{"domena": "experts.prestashop.com", "cytowan": 13},
                                  {"domena": "sellision.pl", "cytowan": 11}]},
        "obecnosc_w_zrodlach": [
            {"domena": "experts.prestashop.com", "cytowan": 13, "stan": "brak",
             "typ": "strona firmy", "tytul": "Waynet \u00e2\x80\x94 Certified agency"},
            {"domena": "webixa.pl", "cytowan": 4, "stan": "jest",
             "typ": "ranking", "tytul": "Agencje PrestaShop 2026"}],
        "techniczne": {"blokady": 1, "braki": 2, "ok": 3, "ustalenia": [
            {"waga": "ok", "tytul": "Roboty mają dostęp", "fakt": "f", "co_zrobic": ""},
            {"waga": "brak", "tytul": "Brak FAQ", "fakt": "f", "co_zrobic": "dodać"},
            {"waga": "blokada", "tytul": "Serwer odmawia", "fakt": "f", "co_zrobic": "zdjąć"}]},
    }
    tresc = {
        "wstep_tytul": "A", "wstep_tresc": "B", "audyt_wstep": "C", "audyt_wniosek": "D",
        "dostep_tytul": "E", "dostep_tresc": "F", "role_tytul": "G", "role_wstep": "H",
        "braki": [{"tytul": "x", "opis": "y"}] * 3, "rola_partner_tytul": "Z",
        "rola_partner": ["a"], "rola_my": ["b"], "role_puenta": "P",
        "pomiar_tytul": "Co zmierzyliśmy", "pomiar_wstep": "PW", "pomiar_wniosek": "PWN",
        "konkurenci_tytul": "Kto zamiast Was", "konkurenci_wstep": "KW",
        "konkurenci_wniosek": "KWN", "zrodla_tytul": "Skąd model bierze",
        "zrodla_wstep": "ZW", "zrodla_wniosek": "ZWN",
        "techniczne_tytul": "Co blokuje", "techniczne_wstep": "TW",
    }

    badanie = raport_geo.badanie_z_raportu(raport)
    badanie["data"] = "25.09.2026"
    html = raport_geo.zbuduj(raport, tresc, badanie, "Tebim")

    # Pięć pytań, nie dziesięć wierszy — ramka pokazuje pytania, nie powtórzenia.
    ok = len(badanie["pytania"]) == 5
    print(f"  {'OK  ' if ok else 'BŁĄD'} | ramka bierze pytania, nie wiersze "
          f"({len(badanie['pytania'])} z 10 wierszy)")
    bledy += not ok

    for klasa, opis in (("s-pomiar", "pomiar z rozbiciem na silniki"),
                        ("s-konkurenci", "konkurenci wymieniani zamiast marki"),
                        ("s-zrodla", "skąd model bierze odpowiedzi"),
                        ("s-techniczne", "ustalenia techniczne")):
        ok = f'class="{klasa}"' in html
        print(f"  {'OK  ' if ok else 'BŁĄD'} | sekcja audytu: {opis}")
        bledy += not ok

    # Sekcje audytu wchodzą PRZED case study, nie za stopką.
    ok = 0 < html.index('class="s-pomiar"') < html.index('class="s-case"')
    print(f"  {'OK  ' if ok else 'BŁĄD'} | sekcje audytu stoją przed case study")
    bledy += not ok

    for fragment, opis in (("Zrobiliśmy to dla Botland", "case study Botland"),
                           ("European Search Awards 2025", "nominacja"),
                           ("Agencja Search od 2007 roku", "stopka ICEA")):
        ok = fragment in html
        print(f"  {'OK  ' if ok else 'BŁĄD'} | zostaje nietknięte: {opis}")
        bledy += not ok

    # Kafel liczy PYTANIA. Wcześniej brał liczbę wierszy i przy dwóch modelach
    # pokazywał dwa razy za dużo.
    ok = "<strong>5</strong>" in html and "20 zapytań łącznie" in html
    print(f"  {'OK  ' if ok else 'BŁĄD'} | kafel pokazuje 5 pytań i 20 zapytań")
    bledy += not ok

    # Słupki: dwa silniki + dwóch konkurentów + źródła (w tym nasza domena).
    ok = html.count('class="slupek') >= 7 and 'class="wypelnienie"' in html
    print(f"  {'OK  ' if ok else 'BŁĄD'} | wykresy słupkowe są wypełnione "
          f"({html.count('class=\"slupek')} słupków)")
    bledy += not ok

    # Procent musi być widać jako procent: skala silników idzie od zera do stu,
    # nie do najwyższego wyniku. Inaczej dwa razy „1 z 5" rysowało dwa pełne paski.
    ok = "width:20.0%" in html
    print(f"  {'OK  ' if ok else 'BŁĄD'} | wykres silników ma skalę 0–100%, nie względną")
    bledy += not ok

    # Nasza domena wyróżniona na tle cytowanych źródeł.
    ok = 'class="slupek nasz"' in html
    print(f"  {'OK  ' if ok else 'BŁĄD'} | strona badanej firmy wyróżniona w źródłach")
    bledy += not ok

    ok = 'class="tabelka"' in html and "marka jest" in html and "brak marki" in html
    print(f"  {'OK  ' if ok else 'BŁĄD'} | tabela obecności marki na cytowanych stronach")
    bledy += not ok

    # Blokady na górze: to jedyne ustalenia, przez które reszta pracy nie liczy się.
    ok = html.index('class="ustalenie blokada"') < html.index('class="ustalenie ok"')
    print(f"  {'OK  ' if ok else 'BŁĄD'} | blokady wypisane przed resztą ustaleń")
    bledy += not ok

    # Tytuł wrócił ze scrapera w złym kodowaniu — w dokumencie ma być czysty.
    ok = "â" not in html.split("s-zrodla")[1].split("</section>")[0]
    print(f"  {'OK  ' if ok else 'BŁĄD'} | tytuły ze scrapera odkodowane")
    bledy += not ok

    # Raport wysyła ICEA, nie audytowana firma.
    ok = ("materiał przygotowany dla: Tebim" in html
          and "rozmowę umówi i poprowadzi razem z nami Tebim" not in html)
    print(f"  {'OK  ' if ok else 'BŁĄD'} | nadawcą jest ICEA, nie badana firma")
    bledy += not ok

    ok = raport_geo.nazwa_pliku("Tebim").startswith("audyt-ai-tebim-")
    print(f"  {'OK  ' if ok else 'BŁĄD'} | nazwa pliku: {raport_geo.nazwa_pliku('Tebim')}")
    bledy += not ok

    # Audyt GEO nie mierzy Google — sekcja SEO nie może pojawić się z zerami.
    ok = 'class="s-seo"' not in html
    print(f"  {'OK  ' if ok else 'BŁĄD'} | audyt GEO bez danych Google nie ma sekcji SEO")
    bledy += not ok

    # ── AUDYT KLIENTA PARTNERA ──────────────────────────────────────
    # Raport dla Trafiki wysyła Tebim, jak materiał z zakładki Materiały: zdanie
    # „otrzymujesz ten materiał od firmy, z którą pracujesz" zostaje z wzoru, bo
    # jest prawdziwe. Podmiana na „przygotowany dla" przedstawiałaby klienta
    # jako adresata własnego audytu od ICEA, a partnera wymazywała z obrazka.
    klient = {**raport,
              "firma": {"nazwa": "Trafika", "domena": "trafika.pl", "url": "https://trafika.pl"},
              "partner": {"nazwa": "Tebim", "url": "https://tebim.pro"},
              "seo": {"dane_wiarygodne": True, "etykieta_czolo": "fraz w TOP 3",
                      "top3": 12, "top10": 40, "fraz_lacznie": 1250, "ruch": 3604,
                      "frazy": [{"fraza": "tytoń, gilzy", "pozycja": 3, "wolumen": 9900, "ruch": 320}],
                      "konkurenci": [{"domena": "dopalenia.pl", "wspolne_frazy": 881}]}}
    html_k = raport_geo.zbuduj(klient, {**tresc, "seo_tytul": "Jak radzi sobie w Google",
                                        "seo_wstep": "SW", "seo_wniosek": "SWN"},
                               badanie, "Tebim", od_partnera=True)
    ok = ("otrzymujesz ten materiał od firmy, z którą pracujesz: Tebim" in html_k
          and "materiał przygotowany dla" not in html_k
          and "rozmowę umówi i poprowadzi razem z nami Tebim" in html_k)
    print(f"  {'OK  ' if ok else 'BŁĄD'} | audyt klienta: nadawcą jest partner, jak w Materiałach")
    bledy += not ok

    ok = ('class="s-seo"' in html_k and "tytoń, gilzy" in html_k
          and "9 900" in html_k and "1 250" in html_k)
    print(f"  {'OK  ' if ok else 'BŁĄD'} | mikroaudyt: sekcja Google z frazami i liczbami")
    bledy += not ok

    ok = html_k.index('class="s-pomiar"') < html_k.index('class="s-seo"') < html_k.index('class="s-case"')
    print(f"  {'OK  ' if ok else 'BŁĄD'} | sekcja Google stoi między pomiarem AI a case study")
    bledy += not ok
    return bledy


def sprawdz_marke() -> int:
    """Czy narzędzie mówi jedną marką — ICEA — wszędzie tam, gdzie widzi to człowiek.

    PO CO TEN TEST. Zmiana marki to nie jedna podmiana w jednym pliku: nazwa siedzi
    w profilu, w trzech promptach, w pliku synergii, we wzorcach maili, w tytule
    strony i w stopce eksportu. Wystarczy, że jedno miejsce zostanie po staremu,
    i partner dostaje maila podpisanego nazwą, która już nie istnieje. Test patrzy
    na WSZYSTKIE te miejsca naraz, bo pojedynczo każde wygląda na dopilnowane.
    """
    from pathlib import Path

    import audyt
    import profil

    bledy = 0
    STARA = "Last Agency"
    korzen = Path(__file__).resolve().parent.parent

    # Profil to źródło wiedzy o nas dla każdego promptu — jego brak jest awarią.
    ok = profil.PLIK.exists() and profil.PLIK.name == "profil_icea.md"
    print(f"  {'OK  ' if ok else 'BŁĄD'} | profil agencji: {profil.PLIK.name}")
    bledy += not ok

    tresc = profil.pelny()
    ok = "ICEA" in tresc and STARA not in tresc
    print(f"  {'OK  ' if ok else 'BŁĄD'} | profil mówi ICEA ({tresc.count('ICEA')} wzmianek)")
    bledy += not ok

    # Fakty z materiału wysyłanego klientom muszą być też w profilu — inaczej czat
    # i maile nie wiedzą o dowodzie, którym podpisany jest dokument.
    for fragment, opis in (("2007", "rok założenia"),
                           ("Botland", "case study"),
                           ("European Search Awards", "nominacja"),
                           ("grupa-icea.pl", "adres agencji")):
        ok = fragment in tresc
        print(f"  {'OK  ' if ok else 'BŁĄD'} | profil zna {opis}")
        bledy += not ok

    ok = STARA not in profil.synergie()
    print(f"  {'OK  ' if ok else 'BŁĄD'} | plik synergii bez starej marki")
    bledy += not ok

    # Prompty: stała część idzie do cache i powtarza się w każdym wywołaniu.
    for nazwa, zadanie in (("dokument dla klienta", app.zadanie_dokument),
                           ("raport z audytu", app.zadanie_raport_geo)):
        ok = STARA not in (zadanie.staly or "")
        print(f"  {'OK  ' if ok else 'BŁĄD'} | prompt „{nazwa}” bez starej marki")
        bledy += not ok

    for nazwa, tekst in (("maile", app.MAIL_SYSTEM),
                         ("ekstrakcja researchu", app.EKSTRAKCJA_PROMPT)):
        ok = STARA not in tekst
        print(f"  {'OK  ' if ok else 'BŁĄD'} | instrukcja „{nazwa}” bez starej marki")
        bledy += not ok

    ok = STARA not in (korzen / "docs/maile-do-partnerow.md").read_text(encoding="utf-8")
    print(f"  {'OK  ' if ok else 'BŁĄD'} | wzorce maili podpisane nową marką")
    bledy += not ok

    # To, co widzi człowiek w przeglądarce.
    for plik, opis in (("frontend/index.html", "tytuł strony i sidebar"),
                       ("frontend/app.js", "stopki eksportu i okładki"),
                       ("frontend/style.css", "arkusz stylów")):
        tekst = (korzen / plik).read_text(encoding="utf-8")
        ok = STARA not in tekst and "lastagency" not in tekst.lower()
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {opis}")
        bledy += not ok

    # Case study wraca: pod marką ICEA Botland jest projektem własnym, a nie cudzym.
    case = audyt.TRESC_STALA.get("case") or {}
    ok = case.get("pokaz") and "Botland" in (case.get("naglowek") or "")
    print(f"  {'OK  ' if ok else 'BŁĄD'} | raport z audytu pokazuje case study Botland")
    bledy += not ok

    ok = "192 588" in (case.get("tekst") or "") and "353,7%" in (case.get("tekst") or "")
    print(f"  {'OK  ' if ok else 'BŁĄD'} | liczby w case study zgodne z materiałem")
    bledy += not ok
    return bledy


def sprawdz_nazwy() -> int:
    """Czy w kolejce i wynikach stoi nazwa FIRMY, a nie tytuł strony.

    Przypadki wzięte z prawdziwej kolejki z 25.09.2026, gdzie nazwą partnera
    bywał nagłówek artykułu („Tworzenie dynamicznych reklam w Google Ads"),
    a firma z Map dostawała sam adres („mkgrow.pl").
    """
    import nazwy

    PRZYPADKI = [
        # (tytuł strony, adres, oczekiwana nazwa, dlaczego)
        ("Dlaczego Adlife? Agencja marketingu online | offline", "https://adlife.pl",
         "Adlife", "nazwa z tytułu zgodna z domeną"),
        ("oferta - AdsOn - Agencja Digital Marketingu", "https://adson.net.pl",
         "AdsOn", "myślnik w tytule nie dokleja się do nazwy"),
        ("Future Mind — Digital Advisory", "https://futuremind.com",
         "Future Mind", "dwa słowa sklejone w domenie"),
        ("4 REAL - agencja", "https://4real.pl",
         "4 REAL", "cyfra i wersaliki"),
        ("Jak agencja marketingu internetowego buduje sprzedaż, a ...", "https://silesion.pl",
         "Silesion", "tytuł artykułu → nazwa z domeny"),
        ("Tworzenie dynamicznych reklam w Google Ads", "https://kingasroka.pl",
         "Kingasroka", "tytuł artykułu → nazwa z domeny"),
        ("mkgrow.pl", "https://mkgrow.pl",
         "Mkgrow", "wynik z Map: adres podany jak nazwa"),
        ("Oferta marketingu internetowego SEM", "https://agencjamedio.pl",
         "Agencja Medio", "sklejona domena rozbita na znanym słowie"),
        ("non.agency", "https://non.agency",
         "non.agency", "krótki rdzeń zostaje pełną domeną"),
    ]
    bledy = 0
    for tytul, url, oczekiwana, dlaczego in PRZYPADKI:
        wynik = nazwy.nazwa_firmy(tytul, url)
        ok = wynik == oczekiwana
        print(f"  {'OK  ' if ok else 'BŁĄD'} | {oczekiwana:16} ← {dlaczego}"
              + ("" if ok else f"   [dostałem: {wynik!r}]"))
        bledy += not ok

    # Idempotencja: kolejka przelicza nazwy przy odczycie, więc poprawna nazwa
    # przepuszczona drugi raz musi wyjść bez zmian.
    for tytul, url, oczekiwana, _ in PRZYPADKI:
        if nazwy.nazwa_firmy(oczekiwana, url) != oczekiwana:
            print(f"  BŁĄD | przeliczenie zmienia gotową nazwę: {oczekiwana!r}")
            bledy += 1
            break
    else:
        print("  OK   | przeliczenie gotowej nazwy niczego nie zmienia")

    # Audyt klienta: dwa systemy, wspólne pola. Klient dostaje materiał od partnera,
    # audyt samej firmy — od ICEA. Gdyby wariant klienta odziedziczył „ZMIANA
    # ODBIORCY", model pisałby do Trafiki, że nie ma żadnego partnera.
    ok = ("ODBIORCA I NADAWCA" in app.RAPORT_KLIENTA_SYSTEM
          and "ZMIANA ODBIORCY" not in app.RAPORT_KLIENTA_SYSTEM
          and "ZMIANA ODBIORCY" in app.RAPORT_GEO_SYSTEM
          and "seo_tytul" in app.RAPORT_KLIENTA_SYSTEM)
    print(f"  {'OK  ' if ok else 'BŁĄD'} | raport klienta pisany od partnera, raport firmy od ICEA")
    bledy += not ok

    ok = "agencję" in app.PYTANIA_KLIENTA and "KLIENT KOŃCOWY" in app.PYTANIA_KLIENTA
    print(f"  {'OK  ' if ok else 'BŁĄD'} | pytania audytu klienta nie dotyczą agencji")
    bledy += not ok

    # Wyniki wyszukiwania dostają nazwę z tej samej funkcji.
    firmy = app.filtruj_firmy([{"url": "https://kingasroka.pl",
                                "title": "Tworzenie dynamicznych reklam w Google Ads",
                                "content": "reklamy"}], "")
    ok = bool(firmy) and firmy[0]["nazwa"] == "Kingasroka"
    print(f"  {'OK  ' if ok else 'BŁĄD'} | wyniki wyszukiwania nie niosą tytułu artykułu"
          + ("" if ok else f"   [{firmy}]"))
    bledy += not ok
    return bledy


def sprawdz_regresje() -> int:
    """Zwraca liczbę błędów. 0 = wszystko zgodne z oczekiwaniem."""
    bledy = 0

    print("=" * 74)
    print("ŹRÓDŁO GOOGLE — czytanie SERP-a z DataForSEO")
    print("=" * 74)
    bledy += sprawdz_zrodlo_google()
    print()

    print("=" * 74)
    print("MAPY — miasto jako obszar, nie jako tekst")
    print("=" * 74)
    bledy += sprawdz_mapy()
    print()

    print("=" * 74)
    print("MODELE — praca na Claude, pomiar GEO na OpenAI")
    print("=" * 74)
    bledy += sprawdz_modele()
    print()

    print("=" * 74)
    print("AUDYT BEZ DATAFORSEO — silniki na własnych kluczach i powtórzenia")
    print("=" * 74)
    bledy += sprawdz_audyt_bez_dataforseo()
    print()

    print("=" * 74)
    print("BOTY AI — czy odróżniamy trenowanie modelu od odpowiadania klientowi")
    print("=" * 74)
    bledy += sprawdz_boty_ai()
    print()

    print("=" * 74)
    print("SYNERGIE — czy jeden plik trafia do czatu i do maili")
    print("=" * 74)
    bledy += sprawdz_synergie()
    print()

    print("=" * 74)
    print("CZAT — pełna karta firmy i pamięć pobranych podstron")
    print("=" * 74)
    bledy += sprawdz_czat()
    print()

    print("=" * 74)
    print("DOKUMENT DLA KLIENTA — trzy sekcje podmienione, reszta wzoru nietknięta")
    print("=" * 74)
    bledy += sprawdz_dokument()
    print()

    print("=" * 74)
    print("NAZWY FIRM — nazwa partnera zamiast tytułu strony")
    print("=" * 74)
    bledy += sprawdz_nazwy()
    print()

    print("=" * 74)
    print("MARKA — czy całe narzędzie mówi ICEA, od profilu po stopkę w przeglądarce")
    print("=" * 74)
    bledy += sprawdz_marke()
    print()

    print("=" * 74)
    print("RAPORT Z AUDYTU GEO — wykresy, źródła, ustalenia na wzorze dokumentu")
    print("=" * 74)
    bledy += sprawdz_raport_geo()
    print()

    print("=" * 74)
    print("MAILE — czy wzorce od zespołu są podpięte i czy prompt im nie przeczy")
    print("=" * 74)
    bledy += sprawdz_maile()
    print()

    print("=" * 74)
    print("KOLEJKA — czy uniesie kategorię, pod którą firmę znaleziono")
    print("=" * 74)
    bledy += sprawdz_kolejke()
    print()

    print("=" * 74)
    print("SZUKAJ DALEJ — czy wykluczamy pokazane domeny po stronie Tavily")
    print("=" * 74)
    bledy += sprawdz_wykluczanie_domen()
    print()

    print("=" * 74)
    print("TYTUŁY ARTYKUŁÓW — czy nie mylimy ich z nazwami firm")
    print("=" * 74)
    bledy += sprawdz_tytuly_artykulow()
    print()

    print("=" * 74)
    print("PRESETY WYSZUKIWANIA — kształt danych i powtórzenia fraz")
    print("=" * 74)
    bledy += sprawdz_presety()
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

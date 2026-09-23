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


def sprawdz_presety() -> int:
    """Czy presety wyszukiwania są dobrze zbudowane — osobno dla każdego źródła.

    DWA ZESTAWY, BO DWA RÓŻNE SPOSOBY SZUKANIA. Wyszukiwarka i Google przeszukują
    TREŚĆ stron, więc znoszą frazy wąskie („wdrożenia Consent Mode"). Mapy dopasowują
    do NAZWY firmy i kategorii wizytówki, więc ta sama fraza zwraca tam zero — żadna
    wizytówka się tak nie nazywa. Stąd osobna, krótsza i ogólniejsza lista dla Map.

    CO SIĘ ZMIENIŁO 23.09.2026. Ten test wcześniej sprawdzał, czy nazwy grup są
    identyczne z KATEGORIE_PARTNEROW. Było to słuszne, dopóki jedna lista pełniła
    obie role — ale to właśnie był problem: dodanie frazy do szukania wymagało
    dodania szufladki, do której trafiają zbadane firmy. Teraz to dwie różne rzeczy:

      * PRESETY (frontend)        — kategorie fraz, po których SZUKASZ firm;
      * KATEGORIE_PARTNEROW (app) — szufladki, do których firma trafia PO researchu.

    Front grupuje zbadane firmy po wartości `firma.kategoria` nadanej przez backend,
    a nie po nazwach presetów, więc rozdzielenie niczego nie rozspójnia.
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

    print(f"  OK   | {len(app.KATEGORIE_PARTNEROW)} szufladek dla zbadanych firm "
          f"(osobna lista, celowo inna niż presety)")
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
    if all("GOTOWE UJĘCIA SYNERGII" in x for x in (app.CZAT_SYNERGIE, app.MAIL_SYNERGIE)):
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

"""
Raport z audytu GEO jako dokument do wysłania — ten sam wzór co materiał dla
klienta partnera, ta sama identyfikacja ICEA, te same dowody.

CZYM TO SIĘ RÓŻNI OD ZAKŁADKI. `raportHTML()` w froncie to widok w narzędziu:
tabele, wszystko naraz, dla kogoś, kto wie, na co patrzy. To jest ARTEFAKT —
plik, który idzie mailem do audytowanej firmy. Ta sama treść, inna kolejność
i inny język: najpierw co zmierzyliśmy, potem czym to zmierzyliśmy, na końcu
co z tego wynika.

CO WCHODZI Z AUDYTU. Zakładka pokazuje pięć rzeczy, których nie było w materiale
dla klienta i których nie wolno zgubić przy przenoszeniu na wzór:
  1. rozbicie wzmianek na silniki — „2 z 10" nic nie mówi, „ChatGPT 0/5,
     Claude 2/5" mówi wszystko,
  2. konkurentów wymienianych zamiast marki,
  3. analizę źródeł — skąd model bierze wiedzę w tej branży,
  4. obecność marki na stronach, które model cytuje (najmocniejszy wniosek),
  5. ustalenia techniczne — co blokuje roboty i czego brakuje na stronie.
Każda z nich dostała własną sekcję z wykresem albo zestawieniem.

WYKRESY SĄ INLINE. Zero bibliotek: słupki to divy z szerokością w procentach,
liczby to tekst. Dokument bywa otwierany bez internetu i drukowany do PDF.
"""

from __future__ import annotations

from html import escape

import dokument

# Style sekcji audytu żyją w arkuszu wzoru (wzor_trustmate/styl.css) — raport
# i materiał to jeden dokument, więc mają jeden arkusz. Sekcje audytu wchodzą
# jako osobne strony A4 po stronie z pomiarem, a przed podziałem ról: najpierw
# co zmierzyliśmy, potem kto co z tym robi, na końcu dowód, że umiemy to zmienić.


# ══════════════════════════════════════════════════════════════════════
#  Kawałki wspólne
# ══════════════════════════════════════════════════════════════════════
def _czysty_tytul(tekst: str) -> str:
    """Naprawia tytuły, które wróciły ze scrapera w złym kodowaniu.

    Zmierzone: „Waynet â Certified PrestaShop agency" — myślnik z UTF-8
    odczytany jako latin-1. W zakładce to literówka, w dokumencie wysyłanym
    firmie — dowód, że nikt tego nie przeczytał. Próbujemy odwrócić pomyłkę
    i zostawiamy oryginał, gdy się nie udaje.
    """
    t = tekst or ""
    if not any(z in t for z in ("â", "Â", "Ã")):
        return t
    for kodowanie in ("latin-1", "cp1252"):
        try:
            naprawiony = t.encode(kodowanie).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if naprawiony.isprintable():
            return naprawiony
    return t


def _slupki(pozycje: list[tuple[str, float, str]], maks: float | None = None) -> str:
    """Poziome słupki: etykieta, tor, liczba. `pozycje` to (etykieta, wartość, opis).

    Poziomo, a nie pionowo, bo etykietami są nazwy firm i domeny — pod pionowym
    słupkiem musiałyby się łamać albo obracać. Skala zawsze od zera do najwyższej
    wartości; bez tego dwa podobne słupki wyglądałyby na przepaść.
    """
    if not pozycje:
        return ""
    gorny = maks or max((w for _, w, _ in pozycje), default=0) or 1
    wiersze = "".join(
        f'<div class="slupek{" nasz" if "◀" in opis else ""}">'
        f'<span class="etykieta">{escape(etykieta)}</span>'
        f'<span class="tor"><span class="wypelnienie" style="width:{100 * wartosc / gorny:.1f}%"></span></span>'
        f'<span class="licz">{escape(opis.replace("◀", "").strip())}</span></div>'
        for etykieta, wartosc, opis in pozycje)
    return f'<div class="slupki">{wiersze}</div>'


def _kafle_wynikow(pozycje: list[tuple[str, str, str]]) -> str:
    """Ciemne kafle z liczbami — te same, którymi wzór podsumowuje case study."""
    return '<div class="wyniki">' + "".join(
        f'<div class="wynik"><strong>{escape(liczba)}</strong><span>{escape(opis)}</span>'
        + (f'<em>{escape(drobne)}</em>' if drobne else "")
        + '</div>' for liczba, opis, drobne in pozycje) + '</div>'


# ══════════════════════════════════════════════════════════════════════
#  Sekcje audytu
# ══════════════════════════════════════════════════════════════════════
def _sekcja_pomiar(raport: dict, t: dict) -> str:
    """Ile razy marka padła — w rozbiciu na silniki.

    ROZBICIE JEST TU CAŁĄ TREŚCIĄ. Jedna liczba zbiorcza („2 z 10") zaciera to,
    co partner naprawdę chce wiedzieć: czy brak wzmianki jest cechą jednego
    modelu, czy prawidłowością. Zmierzone: na tym samym pytaniu ChatGPT wymieniał
    badaną firmę, a Claude nie i podawał siedmiu konkurentów.
    """
    p = raport.get("podsumowanie") or {}
    silniki = p.get("per_silnik") or []
    # PYTAŃ, NIE WIERSZY. `promptow` liczy wiersze raportu, a każde pytanie ma
    # osobny wiersz dla każdego modelu — przy pięciu pytaniach i dwóch modelach
    # wychodziło „10 pytań zadanych modelom", czyli dwa razy za dużo.
    pytan = len({w.get("prompt") for w in (raport.get("prompty") or [])}) or 0
    odpowiedzi = p.get("promptow") or 0
    powtorzenia = raport.get("powtorzenia") or 1

    wsp, nikt = p.get("wspomniana", 0) or 0, p.get("bez_polecen")
    konk = len(p.get("konkurenci") or [])
    # Wiersz to pytanie zadane jednemu modelowi, scalone z powtórzeń. Przy jednym
    # modelu to po prostu pytanie — i tak trzeba to nazwać, bo „1 odpowiedź z nazwą"
    # przy 14 zapytaniach czyta się jak 1 z 14, a to było 1 z 7 pytań.
    jeden = len(silniki) <= 1
    # Zapytania FAKTYCZNIE wykonane, nie pytania × powtórzenia: gdy jedna próba
    # nie przejdzie, było ich 13, a kafel pisał 14.
    # Stare audyty nie mają `prob` — wtedy każde pytanie poszło `powtorzenia` razy.
    lacznie = sum(w.get("prob") or powtorzenia for w in (raport.get("prompty") or [])) \
        or odpowiedzi * powtorzenia
    co = ("pytanie", "pytania", "pytań") if jeden else ("odpowiedź", "odpowiedzi", "odpowiedzi")
    trafien = sum(w.get("trafien") or 0 for w in (raport.get("prompty") or []))
    kafle = _kafle_wynikow([
        (str(pytan), _odmiana(pytan, "pytanie zadane modelom", "pytania zadane modelom",
                              "pytań zadanych modelom"),
         f'{lacznie} {_odmiana(lacznie, "zapytanie", "zapytania", "zapytań")} łącznie'
         if powtorzenia > 1 else ""),
        (f"{wsp} z {odpowiedzi}", f"{co[2]} z nazwą firmy",
         f"w {trafien} z {lacznie} zapytań" if powtorzenia > 1
         else f'{p.get("udzial_wspomnien", 0)}% wszystkich'),
        # Odpowiedzi, w których AI nie poleciło nikogo, to nie przegrana z
        # konkurencją — liczone osobno. Stare audyty tego pola nie mają.
        *([(f"{nikt} z {odpowiedzi}", f"{co[2]} bez wskazania, u kogo kupić",
            "AI nikogo nie poleciło")] if nikt is not None else []),
        (str(konk), _odmiana(konk, "inna firma wymieniona", "inne firmy wymienione",
                             "innych firm wymienionych"), ""),
    ])

    # SKALA OD ZERA DO STU, nie do najwyższego wyniku. Przy dwóch silnikach po
    # 1 z 5 skala względna rysowała dwa pełne paski — wykres mówił „komplet",
    # a pomiar mówił „20%". Tu procent musi być widać jako procent.
    slupki = _slupki([
        (s.get("nazwa") or "—",
         100 * (s.get("wspomniana") or 0) / (s.get("pytan") or 1),
         f'{s.get("wspomniana", 0)} z {s.get("pytan", 0)}')
        for s in silniki], maks=100)

    zrodlo = raport.get("zrodlo_promptow") or {}
    modele = (f"modelowi {silniki[0].get('nazwa')}" if len(silniki) == 1
              else f"każdemu z {len(silniki)} modeli")
    metoda = (f'Metoda: {pytan} {_odmiana(pytan, "pytanie", "pytania", "pytań")}, '
              f'każde zadane {powtorzenia}× {modele} — {lacznie} '
              f'{_odmiana(lacznie, "zapytanie", "zapytania", "zapytań")} łącznie. '
              f'Pytania pochodzą z podpowiedzi Google ({zrodlo.get("google", 0)}) '
              f'i z modelu ({zrodlo.get("model", 0)}). '
              + ('Modele są niedeterministyczne: to samo pytanie zadane ponownie '
                 'potrafi dać inną odpowiedź, dlatego każde powtarzamy.' if powtorzenia > 1
                 else 'Każde pytanie zadaliśmy raz, więc pojedynczy wynik może być '
                      'przypadkowy.'))

    return f'''<div class="blok s-pomiar">
<p class="brew">Wyniki pomiaru</p>
<h2>{escape(t["pomiar_tytul"])}</h2>
<p class="lead">{escape(t["pomiar_wstep"])}</p>
{kafle}
<div class="os">
<h3>Jak wypada marka w poszczególnych modelach</h3>
<p class="pod">Udział odpowiedzi, w których model wymienił markę z nazwy.</p>
{slupki}
</div>
<p class="skala">{escape(t["pomiar_wniosek"])}</p>
<p class="metoda">{escape(metoda)}</p>
</div>'''


def _sekcja_konkurenci(raport: dict, t: dict) -> str:
    """Kogo model wymienia zamiast marki.

    Lista nazwisk, nie procentów: partner rozpoznaje konkurentów po nazwie i to
    ona robi wrażenie. Marki rozpoznaje model, nie regex — wyciąganie po
    pogrubieniu zwracało „Certyfikacja PrestaShop" jako firmę.
    """
    konkurenci = (raport.get("podsumowanie") or {}).get("konkurenci") or []
    if not konkurenci:
        return ""
    slupki = _slupki([(k["marka"], k["wystapien"],
                       f'{k["wystapien"]}×') for k in konkurenci[:10]])
    # Marki produktów nie są konkurencją — klient może je mieć na półce. Zdanie
    # składa kod, żeby model nie dopisał ich do listy „zamiast Ciebie".
    produkty = (raport.get("podsumowanie") or {}).get("marki_produktow") or []
    przypis = (f'<p class="metoda">AI wymieniało też marki produktów: '
               f'{escape(", ".join(produkty[:8]))}. To nie konkurenci — '
               f'te produkty możesz mieć w swojej ofercie.</p>' if produkty else "")
    return f'''<div class="blok s-konkurenci">
<p class="brew">Konkurencja w odpowiedziach</p>
<h2>{escape(t["konkurenci_tytul"])}</h2>
<p class="lead">{escape(t["konkurenci_wstep"])}</p>
{slupki}
<p class="skala">{escape(t["konkurenci_wniosek"])}</p>
{przypis}
</div>'''


def _sekcja_zrodla(raport: dict, t: dict) -> str:
    """Skąd model bierze odpowiedzi — i czy marka tam jest.

    DWIE RZECZY, KTÓRE TRZEBA POKAZAĆ RAZEM. Sama lista cytowanych domen mówi
    tylko „model czyta ranking X". Dopiero sprawdzenie, czy marka na tym rankingu
    figuruje, zamienia ją w zdanie: „model składa odpowiedź z listy, na której
    Was nie ma". Dlatego tabela obecności stoi tuż pod wykresem źródeł.
    """
    z = raport.get("zrodla") or {}
    obecnosc = obecnosc_do_dokumentu(raport)
    if not z and not obecnosc:
        return ""

    kafle = _kafle_wynikow([
        (str(z.get("zrodel_lacznie", 0)), "linków w odpowiedziach", ""),
        (str(z.get("domen_unikalnych", 0)), "różnych serwisów", ""),
        (str(z.get("nasze_cytowania", 0)), _odmiana(z.get("nasze_cytowania", 0) or 0,
                                                    "cytowanie Waszej strony",
                                                    "cytowania Waszej strony",
                                                    "cytowań Waszej strony"), ""),
        (f'{z.get("nasze_miejsce") or "—"}', "miejsce wśród źródeł",
         f'remis z {z["remisujacych"]}' if z.get("remisujacych") else ""),
    ]) if z else ""

    nasza = z.get("nasze_cytowania") or 0
    pozycje = [(x["domena"], x["cytowan"], f'{x["cytowan"]}×')
               for x in (z.get("top_zrodla") or [])[:6]]
    if nasza:
        pozycje.append((raport.get("firma", {}).get("domena") or "Wasza strona",
                        nasza, f'{nasza}× ◀'))
        pozycje.sort(key=lambda x: -x[1])
    slupki = _slupki(pozycje)

    tabela = ""
    if obecnosc:
        wiersze = "".join(
            f'<tr><td>{escape(_czysty_tytul(x.get("tytul") or "") or x["domena"])}<br>'
            f'<span class="szara" style="font-size:7.6pt">{escape(x["domena"])}</span></td>'
            f'<td class="szara">{escape(x.get("typ") or "—")}</td>'
            f'<td class="szara">{x.get("cytowan", 0)}×</td>'
            f'<td><span class="znacznik {"jest" if x.get("stan") == "jest" else "brak" if x.get("stan") == "brak" else ""}">'
            f'{"marka jest" if x.get("stan") == "jest" else "brak marki" if x.get("stan") == "brak" else "nie sprawdzono"}'
            f'</span></td></tr>' for x in obecnosc[:4])
        tabela = f'''<h3 class="podtytul">Czy marka jest na stronach, które model cytuje</h3>
<table class="tabelka"><thead><tr><th>Strona</th><th>Rodzaj</th><th>Cytowań</th><th>Marka</th></tr></thead>
<tbody>{wiersze}</tbody></table>'''

    return f'''<div class="blok s-zrodla">
<p class="brew">Źródła odpowiedzi</p>
<h2>{escape(t["zrodla_tytul"])}</h2>
<p class="lead">{escape(t["zrodla_wstep"])}</p>
{kafle}
{slupki}
{tabela}
<p class="skala">{escape(t["zrodla_wniosek"])}</p>
</div>'''


def _sekcja_techniczne(raport: dict, t: dict) -> str:
    """Co blokuje roboty i czego brakuje na stronie.

    Kolejność jest posortowana wagą, nie tym, jak wypadły testy: blokady na górze,
    bo to jedyne ustalenia, przez które reszta pracy nie ma znaczenia. Rzeczy
    działające zostają na dole i też są wypisane — brak problemu to informacja,
    nie pustka.
    """
    ustalenia = ustalenia_do_dokumentu(raport.get("techniczne"))
    if not ustalenia:
        return ""

    porzadek = {"blokada": 0, "brak": 1, "ok": 2}
    posortowane = sorted(ustalenia, key=lambda u: porzadek.get(u.get("waga"), 3))

    ile = {w: sum(1 for u in ustalenia if u.get("waga") == w) for w in ("blokada", "brak", "ok")}
    kafle = _kafle_wynikow([x for x in (
        (str(ile["blokada"]), _odmiana(ile["blokada"], "blokada widoczności",
                                       "blokady widoczności", "blokad widoczności"), "")
        if ile["blokada"] else None,
        (str(ile["brak"]), _odmiana(ile["brak"], "brak do uzupełnienia",
                                    "braki do uzupełnienia", "braków do uzupełnienia"), ""),
        (str(ile["ok"]), _odmiana(ile["ok"], "rzecz zrobiona dobrze",
                                  "rzeczy zrobione dobrze", "rzeczy zrobionych dobrze"), ""),
    ) if x])

    pozycje = "".join(
        f'<div class="ustalenie {escape(u.get("waga") or "")}">'
        f'<h3>{escape(u.get("tytul") or "")}</h3>'
        f'<p>{escape(u.get("fakt") or "")}</p>'
        + (f'<p class="robimy"><b>Co z tym robimy:</b> {escape(u["co_zrobic"])}</p>'
           if u.get("co_zrobic") else "")
        + '</div>' for u in posortowane)

    return f'''<div class="blok s-techniczne">
<p class="brew">Co strona mówi maszynie</p>
<h2>{escape(t["techniczne_tytul"])}</h2>
<p class="lead">{escape(t["techniczne_wstep"])}</p>
{kafle}
<div class="ustalenia">{pozycje}</div>
</div>'''


def _odmiana(n: int, jedna: str, kilka: str, wiele: str) -> str:
    """1 pytanie, 4 pytania, 5 pytań, 22 pytania, 12 pytań — dokument idzie do
    klienta, a „4 pytań" czyta się jak tekst, którego nikt nie przeczytał."""
    if n == 1:
        return jedna
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return kilka
    return wiele


def _liczba(n) -> str:
    """12 211 zamiast 12211 — twarda spacja, żeby liczba nie łamała się w kaflu."""
    return f"{int(n or 0):,}".replace(",", " ")


def _sekcja_seo(raport: dict, t: dict) -> str:
    """Widoczność w zwykłym Google — część „SEO" mikroaudytu.

    Pojawia się tylko w dokumencie z mikroaudytu, bo tylko on ją mierzy (dane
    DataForSEO). Audyt GEO na własnych kluczach Google nie dotyka, więc ta sekcja
    po prostu znika, zamiast pokazywać zera, które wyglądałyby jak wynik.

    TABELA FRAZ, NIE SUMA. „457 fraz w TOP 3" robi wrażenie, ale nic nie mówi
    klientowi sklepu. „gps do samochodu — pozycja 3, 9 900 wyszukań" mówi od razu,
    o jakie pieniądze chodzi.
    """
    seo = raport.get("seo") or {}
    if not seo.get("dane_wiarygodne") and not seo.get("fraz_lacznie"):
        return ""

    aio = raport.get("ai_overview") or {}
    kafle = _kafle_wynikow([
        (_liczba(seo.get("top3")),
         seo.get("etykieta_czolo") or "fraz w TOP 3", ""),
        (_liczba(seo.get("top10")), "fraz w TOP 10", ""),
        (_liczba(seo.get("fraz_lacznie")),
         "fraz, na które strona się wyświetla", ""),
        (_liczba(seo.get("ruch")),
         "szacowanych wejść z Google miesięcznie", ""),
    ] + ([(str(aio.get("liczba_wzmianek") or 0),
           "zapytań, przy których cytuje ją AI Overviews", "")]
         if aio else []))

    frazy = (seo.get("frazy") or [])[:10]
    tabela = ""
    if frazy:
        wiersze = "".join(
            f'<tr><td>{escape(f.get("fraza") or "")}</td>'
            f'<td class="szara">{f.get("pozycja") or "—"}</td>'
            f'<td class="szara">{_liczba(f.get("wolumen"))}</td>'
            f'<td class="szara">{_liczba(f.get("ruch"))}</td></tr>'
            for f in frazy)
        tabela = f'''<h3 class="podtytul">Frazy, na które strona już się wyświetla</h3>
<table class="tabelka"><thead><tr><th>Fraza</th><th>Pozycja</th><th>Wyszukań / mies.</th><th>Wejść / mies.</th></tr></thead>
<tbody>{wiersze}</tbody></table>'''

    konk = (seo.get("konkurenci") or [])[:8]
    slupki = ""
    if konk:
        slupki = ("<h3 class=\"podtytul\">Kto konkuruje o te same frazy w Google</h3>"
                  + _slupki([(k["domena"], k.get("wspolne_frazy") or 0,
                              f'{k.get("wspolne_frazy") or 0} wspólnych fraz') for k in konk]))

    return f'''<div class="blok s-seo">
<p class="brew">Widoczność w Google</p>
<h2>{escape(t.get("seo_tytul") or "Jak strona radzi sobie w Google")}</h2>
<p class="lead">{escape(t.get("seo_wstep") or "")}</p>
{kafle}
{tabela}
{slupki}
<p class="skala">{escape(t.get("seo_wniosek") or "")}</p>
<p class="metoda">Źródło: {escape(seo.get("zrodlo") or "baza Google PL")}.</p>
</div>'''


# ══════════════════════════════════════════════════════════════════════
#  Składanie
# ══════════════════════════════════════════════════════════════════════
# Ustalenia o dostępie robotów nie idą do dokumentu (02.10.2026). Strona za
# Cloudflare wpuszcza nasze żądanie podszyte pod GPTBota, a ten sam robot z innym
# nagłówkiem dostaje 403 — z zewnątrz nie da się rzetelnie powiedzieć, czy prawdziwy
# robot przechodzi. Dane rejestrowe (NIP, telefon) wypadły z audytu w ogóle.
# Nowe audyty niosą znacznik `temat`; stare rozpoznajemy po tytułach.
_TYTULY_POMIJANE = {
    "Serwer odmawia dostępu robotom AI",
    "Strona jest zamknięta dla robotów, które odpowiadają klientom",
    "Zamknięte dla asystentów o znikomym udziale w Polsce",
    "Roboty trenujące modele zablokowane, odpowiadające — wpuszczone",
    "Roboty trenujące modele są zablokowane",
    "Strona deklaruje wprost, na co pozwala modelom AI",
    "Roboty AI mają dostęp do strony",
    "Niepełne dane identyfikujące firmę",
}


def ustalenia_do_dokumentu(tech: dict | None) -> list[dict]:
    return [u for u in ((tech or {}).get("ustalenia") or [])
            if u.get("temat") != "dostep" and u.get("tytul") not in _TYTULY_POMIJANE]


def obecnosc_do_dokumentu(raport: dict) -> list[dict]:
    """Tabela „czy marka tu jest" bez urzędów, WHO, encyklopedii i sklepów z
    aplikacjami — tam firma nie wejdzie. Nowe audyty odsiewają je już przy
    pomiarze; tu filtr dla starych."""
    from audyt_geo import instytucja, typ_strony
    wynik = []
    for x in raport.get("obecnosc_w_zrodlach") or []:
        if instytucja(x.get("domena") or ""):
            continue
        # Typ liczony na nowo z tytułu — stare audyty mają zapisany typ z czasów,
        # gdy „najlepsza" w tytule sklepu robiło z niego ranking.
        if x.get("tytul"):
            x = dict(x, typ=typ_strony(x.get("domena") or "", x["tytul"]))
        wynik.append(x)
    return wynik


def badanie_z_raportu(raport: dict) -> dict:
    """Przepisuje wiersze audytu na kształt, którego oczekuje ramka z dokumentu.

    Do ramki idą odpowiedzi z RÓŻNYCH pytań, nie powtórzenia tego samego: przy
    dwóch silnikach i ośmiu pytaniach wierszy jest szesnaście, a przewijanie
    szesnastu slajdów to nie dowód, tylko log. Bierzemy pierwsze wystąpienie
    każdego pytania i ograniczamy do sześciu.
    """
    widziane, wybrane = set(), []
    for w in raport.get("prompty") or []:
        pytanie = w.get("prompt") or ""
        if pytanie in widziane or not (w.get("odpowiedz") or "").strip():
            continue
        widziane.add(pytanie)
        wybrane.append({"pytanie": pytanie, "odpowiedz": w["odpowiedz"],
                        "wspomniana": w.get("wspomniana")})
        if len(wybrane) == 6:
            break
    p = raport.get("podsumowanie") or {}
    return {"pytania": [o["pytanie"] for o in wybrane], "odpowiedzi": wybrane,
            "liczba_pytan": len({w.get("prompt") for w in (raport.get("prompty") or [])}),
            "liczba_odpowiedzi": p.get("promptow") or 0,
            "modeli": len(raport.get("silniki") or []) or 1,
            "powtorzenia": raport.get("powtorzenia") or 1,
            "wspomniana": p.get("wspomniana") or 0,
            "bez_polecen": p.get("bez_polecen"),
            "marka": raport.get("marka")}


def zbuduj(raport: dict, tresc: dict, badanie: dict, nadawca: str,
           od_partnera: bool = False) -> str:
    """Raport z audytu na wzorze ICEA: strony wzoru + strony z pomiarem.

    `od_partnera` — audyt KLIENTA partnera. Wtedy `nadawca` to partner (Tebim)
    i materiał wygląda dokładnie jak z zakładki Materiały: „Tebim × ICEA",
    „Materiał ICEA dla klientów Tebim". Bez partnera raport wysyła sama ICEA
    firmie, którą zmierzyła — wtedy w nagłówku jest tylko logo ICEA.
    """
    import dokument

    strony = [x for x in (
        _sekcja_pomiar(raport, tresc),
        _sekcja_seo(raport, tresc),
        _sekcja_konkurenci(raport, tresc),
        _sekcja_zrodla(raport, tresc),
        _sekcja_techniczne(raport, tresc),
    ) if x]
    odbiorca = (raport.get("firma") or {}).get("nazwa") or nadawca
    return dokument.zbuduj(tresc, badanie, nadawca if od_partnera else None,
                           strony_audytu=strony, odbiorca=odbiorca)


def nazwa_pliku(firma: str) -> str:
    return dokument.nazwa_pliku(firma).replace("ai-search-", "audyt-ai-", 1)

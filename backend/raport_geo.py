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

# Sekcje audytu wchodzą przed case study Botland: najpierw pomiar tej firmy,
# potem dowód, że umiemy to zmienić. Odwrotna kolejność czytałaby się jak
# oferta, do której doklejono cudze dane.
KOTWICA = '<section class="s-case">'

STYLE_RAPORTU = """
.slupki{display:flex;flex-direction:column;gap:9px;margin:0 0 6px;}
.slupek{display:grid;grid-template-columns:minmax(120px,26%) 1fr auto;gap:12px;align-items:center;}
.slupek .etykieta{font-size:14.5px;color:#000623;overflow-wrap:anywhere;}
.slupek .tor{background:#eef0f5;border-radius:4px;height:14px;overflow:hidden;}
.slupek .wypelnienie{background:#5768ff;height:100%;border-radius:4px;min-width:2px;}
.slupek.nasz .wypelnienie{background:#000623;}
.slupek.nasz .etykieta{font-weight:600;}
.slupek .licz{font-size:13.5px;color:#5b6070;font-variant-numeric:tabular-nums;}
.tabelka{width:100%;border-collapse:collapse;font-size:14.5px;background:#fff;
border:1px solid #e3e5ec;border-radius:12px;overflow:hidden;}
.tabelka th{text-align:left;font-size:12px;letter-spacing:.09em;text-transform:uppercase;
color:#5b6070;font-weight:600;padding:12px 16px;border-bottom:1px solid #e3e5ec;}
.tabelka td{padding:11px 16px;border-top:1px solid #eef0f5;color:#000623;}
.tabelka td.szara{color:#5b6070;}
.znacznik{display:inline-block;font-size:12px;padding:2px 9px;border-radius:20px;
border:1px solid #e3e5ec;color:#5b6070;}
.znacznik.brak{border-color:#e0b4b4;color:#a4423a;}
.znacznik.jest{border-color:#b6ceb6;color:#3d6b3d;}
.ustalenia{display:flex;flex-direction:column;gap:12px;}
.ustalenie{background:#fff;border:1px solid #e3e5ec;border-radius:12px;
padding:18px 20px;border-left:3px solid #b9bece;}
.ustalenie.blokada{border-left-color:#a4423a;}
.ustalenie.brak{border-left-color:#d8a838;}
.ustalenie.ok{border-left-color:#3d6b3d;}
.ustalenie h3{font-size:16.5px;margin:0 0 6px;}
.ustalenie p{margin:0;font-size:14.5px;color:#5b6070;}
.ustalenie .robimy{margin-top:8px;font-size:14.5px;color:#000623;}
.metoda{font-size:12.5px;color:#6B7186;margin:14px 0 0;max-width:760px;}
@media print{
.ustalenie,.slupek,.tabelka tr{break-inside:avoid;}
}
"""


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

    kafle = _kafle_wynikow([
        (str(pytan), "pytań zadanych modelom",
         f'{odpowiedzi * powtorzenia} zapytań łącznie' if powtorzenia > 1 else ""),
        (f'{p.get("wspomniana", 0)}', "odpowiedzi z nazwą firmy",
         f'{p.get("udzial_wspomnien", 0)}% wszystkich'),
        (f'{p.get("cytowana", 0)}', "odpowiedzi z linkiem do strony", ""),
        (str(len(p.get("konkurenci") or [])), "innych firm wymienionych", ""),
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
    metoda = (f'Metoda: {pytan} pytań, każde zadane {powtorzenia}× każdemu '
              f'z {len(silniki)} modeli — {odpowiedzi * powtorzenia} zapytań łącznie. '
              f'Pytania pochodzą z podpowiedzi Google ({zrodlo.get("google", 0)}) '
              f'i z modelu ({zrodlo.get("model", 0)}). '
              'Modele są niedeterministyczne: to samo pytanie zadane ponownie '
              'potrafi dać inną odpowiedź, dlatego każde powtarzamy.')

    return f'''<section class="s-pomiar">
<h2>{escape(t["pomiar_tytul"])}</h2>
<p class="pod">{escape(t["pomiar_wstep"])}</p>
{kafle}
<div class="os">
<h3>Jak wypada marka w poszczególnych modelach</h3>
<p class="pod">Udział odpowiedzi, w których model wymienił markę z nazwy.</p>
{slupki}
</div>
<p class="skala">{escape(t["pomiar_wniosek"])}</p>
<p class="metoda">{escape(metoda)}</p>
</section>'''


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
    return f'''<section class="s-konkurenci">
<h2>{escape(t["konkurenci_tytul"])}</h2>
<p class="pod">{escape(t["konkurenci_wstep"])}</p>
{slupki}
<p class="skala">{escape(t["konkurenci_wniosek"])}</p>
</section>'''


def _sekcja_zrodla(raport: dict, t: dict) -> str:
    """Skąd model bierze odpowiedzi — i czy marka tam jest.

    DWIE RZECZY, KTÓRE TRZEBA POKAZAĆ RAZEM. Sama lista cytowanych domen mówi
    tylko „model czyta ranking X". Dopiero sprawdzenie, czy marka na tym rankingu
    figuruje, zamienia ją w zdanie: „model składa odpowiedź z listy, na której
    Was nie ma". Dlatego tabela obecności stoi tuż pod wykresem źródeł.
    """
    z = raport.get("zrodla") or {}
    obecnosc = raport.get("obecnosc_w_zrodlach") or []
    if not z and not obecnosc:
        return ""

    kafle = _kafle_wynikow([
        (str(z.get("zrodel_lacznie", 0)), "linków w odpowiedziach", ""),
        (str(z.get("domen_unikalnych", 0)), "różnych serwisów", ""),
        (str(z.get("nasze_cytowania", 0)), "cytowań Waszej strony", ""),
        (f'{z.get("nasze_miejsce") or "—"}', "miejsce wśród źródeł",
         f'remis z {z["remisujacych"]}' if z.get("remisujacych") else ""),
    ]) if z else ""

    nasza = z.get("nasze_cytowania") or 0
    pozycje = [(x["domena"], x["cytowan"], f'{x["cytowan"]}×')
               for x in (z.get("top_zrodla") or [])[:10]]
    if nasza:
        pozycje.append((raport.get("firma", {}).get("domena") or "Wasza strona",
                        nasza, f'{nasza}× ◀'))
        pozycje.sort(key=lambda x: -x[1])
    slupki = _slupki(pozycje)

    tabela = ""
    if obecnosc:
        wiersze = "".join(
            f'<tr><td>{escape(_czysty_tytul(x.get("tytul") or "") or x["domena"])}<br>'
            f'<span class="szara" style="font-size:12.5px">{escape(x["domena"])}</span></td>'
            f'<td class="szara">{escape(x.get("typ") or "—")}</td>'
            f'<td class="szara">{x.get("cytowan", 0)}×</td>'
            f'<td><span class="znacznik {"jest" if x.get("stan") == "jest" else "brak" if x.get("stan") == "brak" else ""}">'
            f'{"marka jest" if x.get("stan") == "jest" else "brak marki" if x.get("stan") == "brak" else "nie sprawdzono"}'
            f'</span></td></tr>' for x in obecnosc)
        tabela = f'''<h3 style="margin:26px 0 10px">Czy marka jest na stronach, które model cytuje</h3>
<table class="tabelka"><thead><tr><th>Strona</th><th>Rodzaj</th><th>Cytowań</th><th>Marka</th></tr></thead>
<tbody>{wiersze}</tbody></table>'''

    return f'''<section class="s-zrodla">
<h2>{escape(t["zrodla_tytul"])}</h2>
<p class="pod">{escape(t["zrodla_wstep"])}</p>
{kafle}
{slupki}
{tabela}
<p class="skala">{escape(t["zrodla_wniosek"])}</p>
</section>'''


def _sekcja_techniczne(raport: dict, t: dict) -> str:
    """Co blokuje roboty i czego brakuje na stronie.

    Kolejność jest posortowana wagą, nie tym, jak wypadły testy: blokady na górze,
    bo to jedyne ustalenia, przez które reszta pracy nie ma znaczenia. Rzeczy
    działające zostają na dole i też są wypisane — brak problemu to informacja,
    nie pustka.
    """
    tech = raport.get("techniczne") or {}
    ustalenia = tech.get("ustalenia") or []
    if not ustalenia:
        return ""

    porzadek = {"blokada": 0, "brak": 1, "ok": 2}
    posortowane = sorted(ustalenia, key=lambda u: porzadek.get(u.get("waga"), 3))

    kafle = _kafle_wynikow([
        (str(tech.get("blokady", 0)), "blokad dostępu dla robotów AI", ""),
        (str(tech.get("braki", 0)), "braków do uzupełnienia", ""),
        (str(tech.get("ok", 0)), "rzeczy zrobionych dobrze", ""),
    ])

    pozycje = "".join(
        f'<div class="ustalenie {escape(u.get("waga") or "")}">'
        f'<h3>{escape(u.get("tytul") or "")}</h3>'
        f'<p>{escape(u.get("fakt") or "")}</p>'
        + (f'<p class="robimy"><b>Co z tym robimy:</b> {escape(u["co_zrobic"])}</p>'
           if u.get("co_zrobic") else "")
        + '</div>' for u in posortowane)

    return f'''<section class="s-techniczne">
<h2>{escape(t["techniczne_tytul"])}</h2>
<p class="pod">{escape(t["techniczne_wstep"])}</p>
{kafle}
<div class="ustalenia">{pozycje}</div>
</section>'''


# ══════════════════════════════════════════════════════════════════════
#  Składanie
# ══════════════════════════════════════════════════════════════════════
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
    return {"pytania": [o["pytanie"] for o in wybrane], "odpowiedzi": wybrane}


# Wzór zakłada, że materiał wysyła partner swojemu klientowi. Tu wysyła go ICEA
# firmie, którą zmierzyła, więc dwa zdania o partnerze trzeba postawić na nogi —
# inaczej raport przedstawiałby audytowaną firmę jako własnego nadawcę.
PODMIANY_NADAWCY = [
    ("otrzymujesz ten materiał od firmy, z którą pracujesz: {firma}",
     "materiał przygotowany dla: {firma}"),
    ("Jeśli wolisz, rozmowę umówi i poprowadzi razem z nami {firma}.",
     "Wszystkie liczby w tym materiale pochodzą z pomiaru wykonanego "
     "{data} — możemy przejść przez nie razem, pytanie po pytaniu."),
]


def zbuduj(raport: dict, tresc: dict, badanie: dict, nadawca: str) -> str:
    """Wzór ICEA z sekcjami audytu. Case study, nagroda i stopka zostają."""
    html = dokument.zbuduj(tresc, badanie, nadawca)
    for stare, nowe in PODMIANY_NADAWCY:
        html = html.replace(stare.format(firma=nadawca),
                            nowe.format(firma=nadawca, data=badanie.get("data", "")))

    sekcje = "\n\n".join(x for x in (
        _sekcja_pomiar(raport, tresc),
        _sekcja_konkurenci(raport, tresc),
        _sekcja_zrodla(raport, tresc),
        _sekcja_techniczne(raport, tresc),
    ) if x)

    if KOTWICA not in html:
        raise ValueError("Nie znalazłem w szablonie miejsca na sekcje audytu.")
    html = html.replace(KOTWICA, sekcje + "\n\n" + KOTWICA, 1)
    return html.replace("</style>", STYLE_RAPORTU + "</style>", 1)


def nazwa_pliku(firma: str) -> str:
    return dokument.nazwa_pliku(firma).replace("ai-search-", "audyt-ai-", 1)

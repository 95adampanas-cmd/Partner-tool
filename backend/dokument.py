"""
Dokument dla KLIENTA PARTNERA — ten sam materiał co wzór ICEA, z trzema sekcjami
napisanymi pod konkretną parę: partner i jego klient.

KIM JEST ODBIORCA. Nie partnerem. Dokument dostaje firma, która już z partnerem
pracuje — ma od niego sklep, stronę, kampanie albo opinie. Dlatego całość mówi
„Twoja firma" do klienta, a o partnerze mówi w trzeciej osobie, z szacunkiem dla
tego, co już zrobił. To jest materiał, który partner może wysłać dalej pod swoją
ręką, a nie oferta wysłana obok niego.

DLACZEGO SZABLON, A NIE GENEROWANIE CAŁEJ STRONY. Wzór (`szablon_dokumentu.html`)
jest dopracowany: układ, typografia, case study Botland, nagroda, zdjęcia, stopka.
Model, który dostałby to do napisania od zera, za każdym razem zwróciłby inny
dokument i prędzej czy później zepsułby markup. Tu zmieniają się TRZY miejsca —
reszta jest nietykalna, bo to identyfikacja ICEA i dowód, który już działa.

CO SIĘ ZMIENIA:
  1. Wstępniak w nagłówku — co klient JUŻ ma od partnera i gdzie zaczyna się nasza
     część. Miękko, bez sprzedaży.
  2. Sekcja „Co się zmienia dla Twojej firmy" — mikroaudyt GEO: trzy pytania zadane
     ChatGPT o kategorię klienta plus sprawdzenie, czy roboty AI mają wstęp na jego
     stronę. Prawdziwy pomiar, nie przykład.
  3. Sekcja o podziale ról — jak partner i Last Agency się uzupełniają, na podstawie
     tego, co partner realnie robi, i gotowych ujęć z `synergie.md`.

MODEL ZWRACA TEKST, NIE HTML. Składanie znaczników zostaje po stronie Pythona.
Gdyby model generował markup, jeden nieznany mu `<div>` rozjechałby layout całego
dokumentu — a to jest plik, który idzie do klienta partnera.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re

SZABLON = Path(__file__).resolve().parent / "szablon_dokumentu.html"

# Regiony podmieniane w szablonie. Każdy domyka się przed pierwszym znacznikiem
# zamykającym tego samego typu i żaden nie zawiera zagnieżdżonego <section>,
# więc leniwe dopasowanie wystarczy. Sprawdzone na wzorze ICEA.
WZORY = {
    "wstepniak": re.compile(r'<div class="wstepniak">.*?</div>', re.S),
    "zmiana": re.compile(r'<section class="s-zmiana">.*?</section>', re.S),
    "branza": re.compile(r'<section class="s-branza">.*?</section>', re.S),
}

# Zdania ze wzoru, które mówią o partnerze od opinii. Dokument ma działać dla
# każdego partnera, więc podmieniamy je na jego nazwę. To jedyne miejsca poza
# trzema sekcjami, których dotykamy — i tylko dlatego, że inaczej klient dostałby
# materiał mówiący o firmie, z którą nie pracuje.
PODMIANY_PARTNERA = [
    ("otrzymujesz ten materiał od firmy, która zbiera i publikuje Twoje opinie",
     "otrzymujesz ten materiał od firmy, z którą pracujesz: {partner}"),
    ("Jeśli wolisz, rozmowę umówi i poprowadzi razem z nami firma, która prowadzi Twoje opinie.",
     "Jeśli wolisz, rozmowę umówi i poprowadzi razem z nami {partner}."),
]


def klienci(firma: dict) -> list[str]:
    """Klienci partnera z researchu — z nich wybiera się adresata dokumentu.

    Bierzemy `case_studies`, bo to jedyne miejsce, gdzie research zapisuje nazwy
    firm, dla których partner pracował. Lista bywa pusta i to normalne: nie każdy
    partner pokazuje realizacje. Wtedy nazwę klienta wpisuje człowiek.
    """
    BRAK = "nie do ustalenia"
    return [c for c in (firma.get("case_studies") or [])
            if c and c.strip() and c.strip().lower() != BRAK]


# ══════════════════════════════════════════════════════════════════════
#  Składanie sekcji
# ══════════════════════════════════════════════════════════════════════
def _wstepniak(t: dict) -> str:
    return (f'<div class="wstepniak">\n'
            f'<strong>{escape(t["wstep_tytul"])}</strong>\n'
            f'<p>{escape(t["wstep_tresc"])}</p>\n'
            f'</div>')


def _zmiana(t: dict, badanie: dict) -> str:
    """Sekcja z mikroaudytem. Lewa kolumna to wnioski, prawa — dowód.

    DOWODEM JEST ODPOWIEDŹ, NIE NASZE ZDANIE O NIEJ. Wzór ICEA pokazywał w tej
    ramce prawdziwy fragment odpowiedzi Google z datą. Tu jest to samo, tylko
    o kliencie: pytanie, które zadaliśmy, i to, co ChatGPT naprawdę odpowiedział.
    Bez tego cała sekcja byłaby opinią agencji o kliencie.
    """
    pytania = ''.join(f'<li>„{escape(p)}”</li>' for p in badanie['pytania'])
    dowod = badanie.get("dowod") or {}
    odpowiedz = escape((dowod.get("odpowiedz") or "")[:700])
    if len(dowod.get("odpowiedz") or "") > 700:
        odpowiedz += "…"

    dostep = ""
    if t.get("dostep_tytul"):
        dostep = (f'<p class="drobne"><b>{escape(t["dostep_tytul"])}</b> '
                  f'{escape(t["dostep_tresc"])}</p>')

    return f'''<section class="s-zmiana">
<h2>Co się zmienia dla Twojej firmy</h2>
<p class="pod">Lista dziesięciu wyników dawała szansę każdemu, kto się na nią załapał.
Odpowiedź asystenta wymienia kilka firm i nie pokazuje reszty.
Nie ma spadku pozycji, który dałoby się zauważyć. Jest cisza.</p>
<div class="test">
<div class="test-tresc">
<h3>Sprawdziliśmy to za Ciebie</h3>
<p>{escape(t["audyt_wstep"])}</p>
<ul>{pytania}</ul>
<p class="drobne">{escape(t["audyt_wniosek"])}</p>
{dostep}
</div>
<div class="ekran">
<div class="belka"><span></span><span></span><span></span></div>
<p class="pyt">{escape(dowod.get("pytanie") or "")}</p>
<p class="odp">„{odpowiedz}”</p>
<p class="stopa">Fragment prawdziwej odpowiedzi ChatGPT na to zapytanie, {badanie["data"]}.</p>
</div></div>
</section>'''


def _branza(t: dict) -> str:
    kafle = "".join(
        f'<div class="brak-kafel"><h3>{escape(k["tytul"])}</h3>'
        f'<p>{escape(k["opis"])}</p></div>' for k in t["braki"])
    rola_partner = "".join(f"<li>{escape(x)}</li>" for x in t["rola_partner"])
    rola_my = "".join(f"<li>{escape(x)}</li>" for x in t["rola_my"])
    return f'''<section class="s-branza">
<h2>{escape(t["role_tytul"])}</h2>
<p class="pod">{escape(t["role_wstep"])}</p>
<div class="braki">{kafle}</div>
<div class="role"><div class="rola-kol"><h3>{escape(t["rola_partner_tytul"])}</h3>
<ul>{rola_partner}</ul></div>
<div class="rola-kol"><h3>Bierzemy na siebie</h3>
<ul>{rola_my}</ul></div></div>
<p class="rola-puenta">{escape(t["role_puenta"])}</p>
</section>'''


def zbuduj(tresc: dict, badanie: dict, partner: str) -> str:
    """Wstawia trzy sekcje w szablon. Reszta pliku zostaje bajt w bajt."""
    html = SZABLON.read_text(encoding="utf-8")
    for stare, nowe in PODMIANY_PARTNERA:
        html = html.replace(stare, nowe.format(partner=partner))

    for klucz, budowa in (("wstepniak", lambda: _wstepniak(tresc)),
                          ("zmiana", lambda: _zmiana(tresc, badanie)),
                          ("branza", lambda: _branza(tresc))):
        nowy = budowa()
        html, ile = WZORY[klucz].subn(lambda _m: nowy, html, count=1)
        if ile != 1:
            raise ValueError(f"Nie znalazłem w szablonie sekcji: {klucz}")
    return html


def nazwa_pliku(klient: str) -> str:
    """Nazwa pliku do pobrania — bez polskich znaków i spacji, z datą."""
    zamiana = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    czysta = (klient or "klient").translate(zamiana)
    czysta = re.sub(r"[^A-Za-z0-9]+", "-", czysta).strip("-").lower() or "klient"
    return f"ai-search-{czysta}-{datetime.now():%Y%m%d}.html"

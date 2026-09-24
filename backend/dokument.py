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


def _odpowiedz_html(tekst: str, limit: int = 850) -> str:
    """Odpowiedź modelu w HTML — bez surowego markdownu.

    ChatGPT odpowiada markdownem i we wzorze widać było `**Zalando**` z gwiazdkami.
    W dokumencie dla klienta to wygląda jak wklejony log. Zamieniamy pogrubienie na
    <strong> (tak samo, jak zrobił to człowiek w oryginale ICEA) i usuwamy przypisy
    z linkami, bo w wydruku i tak są nieklikalne, a rozbijają zdanie.
    """
    t = escape((tekst or "").strip())
    t = re.sub(r"\(\[[^\]]+\]\([^)]*\)\)", "", t)      # ([domena](url)) — przypis
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)     # [tekst](url) — link
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t, flags=re.S)
    t = re.sub(r"[ \t]{2,}", " ", t)
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "…"
        # Ucięcie mogło rozciąć znacznik w połowie — wtedy domykamy go sami.
        if t.count("<strong>") > t.count("</strong>"):
            t += "</strong>"
    return t


def _zmiana(t: dict, badanie: dict) -> str:
    """Sekcja z mikroaudytem. Lewa kolumna to wnioski, prawa — dowód.

    DOWODEM JEST ODPOWIEDŹ, NIE NASZE ZDANIE O NIEJ. Wzór ICEA pokazywał w tej
    ramce prawdziwy fragment odpowiedzi Google z datą. Tu jest to samo, tylko
    o kliencie: pytania, które zadaliśmy, i to, co ChatGPT naprawdę odpowiedział.
    Bez tego cała sekcja byłaby opinią agencji o kliencie.

    TRZY ODPOWIEDZI, NIE JEDNA. Wcześniej ramka pokazywała jedną wybraną odpowiedź,
    a pozostałe dwie ginęły — klient widział listę trzech pytań i dowód tylko na
    jedno z nich. Teraz ramka przewija się jak slajdy, a w wydruku wszystkie trzy
    drukują się pod sobą, bo kartki nie da się kliknąć.
    """
    odpowiedzi = badanie.get("odpowiedzi") or []
    if not odpowiedzi and badanie.get("dowod"):
        odpowiedzi = [badanie["dowod"]]

    slajdy = "".join(
        f'<div class="slajd" data-slajd="{i}"{"" if i == 0 else " hidden"}>'
        f'<p class="pyt">{escape(o.get("pytanie") or "")}</p>'
        f'<p class="odp">„{_odpowiedz_html(o.get("odpowiedz") or "")}”</p>'
        f'</div>'
        for i, o in enumerate(odpowiedzi))

    kropki = "".join(
        f'<button class="kropka{" jest" if i == 0 else ""}" data-idx="{i}" type="button"'
        f' aria-label="Pytanie {i + 1}"></button>' for i in range(len(odpowiedzi)))

    nawigacja = "" if len(odpowiedzi) < 2 else f'''
<div class="slajd-nawigacja">
<button class="slajd-strzalka" data-krok="-1" type="button" aria-label="Poprzednie pytanie">‹</button>
<div class="kropki">{kropki}</div>
<button class="slajd-strzalka" data-krok="1" type="button" aria-label="Następne pytanie">›</button>
<span class="slajd-licznik"><b>1</b> z {len(odpowiedzi)}</span>
</div>'''

    pytania = ''.join(
        f'<li><button class="pytanie-link" data-idx="{i}" type="button">„{escape(p)}”</button></li>'
        for i, p in enumerate(badanie["pytania"]))

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
<ul class="pytania-lista">{pytania}</ul>
<p class="drobne">{escape(t["audyt_wniosek"])}</p>
{dostep}
</div>
<div class="ekran" id="ekran-odpowiedzi">
<div class="belka"><span></span><span></span><span></span></div>
{slajdy}
{nawigacja}
<p class="stopa">Prawdziwe odpowiedzi ChatGPT na te zapytania, {badanie["data"]}.</p>
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


# Style i skrypt przewijanej ramki. Dokładane do dokumentu przy składaniu, a nie
# wpisane do szablonu — szablon ma zostać tym, czym jest: wzorem od Adama. Dzięki
# temu podmiana wzoru na nowszą wersję nie wymaga przenoszenia tych reguł.
#
# WSZYSTKO JEST W PLIKU. Dokument idzie mailem i bywa otwierany bez internetu,
# więc żadnych zewnętrznych bibliotek: pięćdziesiąt linii CSS i dwadzieścia JS.
STYLE_SLAJDOW = """
.pytania-lista{list-style:none;padding-left:0;}
.pytania-lista li{margin-bottom:7px;}
.pytanie-link{background:none;border:0;padding:0;font:inherit;color:#000623;
text-align:left;cursor:pointer;border-bottom:1px dashed #b9bece;}
.pytanie-link:hover,.pytanie-link.jest{color:#4653EA;border-bottom-color:#4653EA;}
.ekran .slajd{animation:pokaz .18s ease;}
@keyframes pokaz{from{opacity:0;}to{opacity:1;}}
.slajd-nawigacja{display:flex;align-items:center;gap:10px;margin:14px 0 10px;}
.slajd-strzalka{width:28px;height:28px;border:1px solid #e3e5ec;background:#fff;
border-radius:8px;font-size:17px;line-height:1;color:#000623;cursor:pointer;}
.slajd-strzalka:hover{border-color:#5768ff;color:#4653EA;}
.kropki{display:flex;gap:6px;}
.kropka{width:8px;height:8px;padding:0;border:0;border-radius:50%;background:#e3e5ec;cursor:pointer;}
.kropka.jest{background:#5768ff;}
.slajd-licznik{margin-left:auto;font-size:12px;color:#6B7186;}
@media print{
.ekran .slajd[hidden]{display:block !important;}
.ekran .slajd+.slajd{margin-top:14px;padding-top:14px;border-top:1px solid #eef0f5;}
.slajd-nawigacja{display:none;}
.pytanie-link{border-bottom:0;}
}
"""

SKRYPT_SLAJDOW = """
<script>
(function(){
  var ekran=document.getElementById("ekran-odpowiedzi");
  if(!ekran)return;
  var slajdy=ekran.querySelectorAll(".slajd"),
      kropki=ekran.querySelectorAll(".kropka"),
      licznik=ekran.querySelector(".slajd-licznik b"),
      pytania=document.querySelectorAll(".pytanie-link"),
      teraz=0;
  function pokaz(i){
    teraz=(i+slajdy.length)%slajdy.length;
    slajdy.forEach(function(s,n){s.hidden=n!==teraz;});
    kropki.forEach(function(k,n){k.classList.toggle("jest",n===teraz);});
    pytania.forEach(function(p,n){p.classList.toggle("jest",n===teraz);});
    if(licznik)licznik.textContent=teraz+1;
  }
  ekran.addEventListener("click",function(e){
    var strzalka=e.target.closest(".slajd-strzalka");
    if(strzalka)return pokaz(teraz+ +strzalka.dataset.krok);
    var kropka=e.target.closest(".kropka");
    if(kropka)return pokaz(+kropka.dataset.idx);
  });
  // Klikniecie pytania po lewej pokazuje jego odpowiedz — lista pytan i ramka
  // to jedna rzecz, a nie dwie obok siebie.
  pytania.forEach(function(p){
    p.addEventListener("click",function(){pokaz(+p.dataset.idx);});
  });
  pokaz(0);
})();
</script>
"""


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

    # Style idą na KONIEC arkusza, żeby wygrywały przy równej specyficzności,
    # a skrypt przed </body>, gdy ramka jest już w drzewie.
    html = html.replace("</style>", STYLE_SLAJDOW + "</style>", 1)
    html = html.replace("</body>", SKRYPT_SLAJDOW + "</body>", 1)
    return html


def nazwa_pliku(klient: str) -> str:
    """Nazwa pliku do pobrania — bez polskich znaków i spacji, z datą."""
    zamiana = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    czysta = (klient or "klient").translate(zamiana)
    czysta = re.sub(r"[^A-Za-z0-9]+", "-", czysta).strip("-").lower() or "klient"
    return f"ai-search-{czysta}-{datetime.now():%Y%m%d}.html"

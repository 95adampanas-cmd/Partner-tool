"""
Dokument dla KLIENTA PARTNERA — wzór „TrustMate × ICEA", osiem stron A4.

KIM JEST ODBIORCA. Nie partnerem. Dokument dostaje firma, która już z partnerem
pracuje — ma od niego sklep, stronę, kampanie albo opinie. Dlatego całość mówi
„Twoja firma" do klienta, a o partnerze mówi w trzeciej osobie, z szacunkiem dla
tego, co już zrobił. To jest materiał, który partner może wysłać dalej pod swoją
ręką, a nie oferta wysłana obok niego.

WZÓR JEST Z PDF-a OD ADAMA (październik 2026). Wcześniej dokument powstawał przez
podmianę trzech sekcji w gotowym pliku HTML wyrażeniami regularnymi. Nowy wzór to
osiem stron A4 z główką i stopką na każdej i numeracją „02 / 08" — a przy raporcie
z audytu stron jest więcej, bo dochodzą sekcje pomiaru. Numeracji nie da się
wpisać na sztywno w plik, więc strony składa Python.

CO PISZE MODEL, A CO JEST STAŁE. Model pisze tekst do kilku miejsc: wstęp na
okładce, wniosek z pomiaru, podział ról, trzy kroki mechanizmu, cel na ostatniej
stronie. Reszta — epoki, skala zmiany, Botland, Tryb AI, „Jak zaczynamy",
kontakt — jest ze wzoru, bo to dowód i identyfikacja ICEA, które już działają.

MODEL ZWRACA TEKST, NIE HTML. Składanie znaczników zostaje po stronie Pythona,
a każdy tekst z modelu przechodzi przez escape(). Gdyby model generował markup,
jeden nieznany mu `<div>` rozjechałby stronę A4 — a to jest plik, który idzie do
klienta partnera.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re


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
#  Odpowiedzi modeli
# ══════════════════════════════════════════════════════════════════════
def _odpowiedz_html(tekst: str) -> str:
    """Odpowiedź modelu w HTML — CAŁA, z zachowaną strukturą.

    Wcześniej ucinaliśmy po 850 znakach i w dokumencie zostawał ogryzek: model
    wymieniał dziesięć firm, a klient widział trzy i wielokropek. Dowód, który
    urywa się w połowie, jest gorszy niż brak dowodu — czytający nie wie, czy
    dalej padła jego marka. Teraz idzie całość; za mieszczenie się na ekranie
    odpowiada ramka (zwija się i rozwija), nie nożyczki w Pythonie.

    ChatGPT odpowiada markdownem, więc zamieniamy go na znaczniki: pogrubienie na
    <strong>, listy na <ul>/<ol>, akapity na <p>. Bez tego w dokumencie lądował
    surowy zapis — `**Zalando**` z gwiazdkami i myślniki na początkach linii,
    czyli coś, co wygląda jak wklejony log.
    """
    t = escape((tekst or "").strip())
    t = re.sub(r"\(\[[^\]]+\]\([^)]*\)\)", "", t)      # ([domena](url)) — przypis
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)     # [tekst](url) — link
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t, flags=re.S)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)        # nagłówki — zwykły akapit

    czesci, lista, rodzaj = [], [], None

    def domknij():
        nonlocal lista, rodzaj
        if lista:
            czesci.append(f"<{rodzaj}>" + "".join(f"<li{a}>{x}</li>" for a, x in lista)
                          + f"</{rodzaj}>")
            lista, rodzaj = [], None

    for linia in t.split("\n"):
        linia = linia.strip()
        if not linia:
            domknij()
            continue
        punkt = re.match(r"^[-*•]\s+(.*)$", linia)
        numer = re.match(r"^\d+[.)]\s+(.*)$", linia)
        if punkt or numer:
            nowy_rodzaj = "ul" if punkt else "ol"
            if rodzaj and rodzaj != nowy_rodzaj:
                domknij()
            rodzaj = nowy_rodzaj
            # Numer z odpowiedzi trafia do `value`, bo listy bywają przerywane
            # podpunktami i bez tego druga część zaczynałaby liczyć od jedynki.
            if numer:
                lista.append((f' value="{linia.split(chr(46))[0].split(chr(41))[0]}"',
                              numer.group(1)))
            else:
                lista.append(("", punkt.group(1)))
        else:
            domknij()
            czesci.append(f"<p>{linia}</p>")
    domknij()
    return "".join(czesci) or "<p></p>"


# Style i skrypt przewijanej ramki na stronie 3. Oddzielnie od wzoru, bo to
# zachowanie, nie wygląd: wzór pokazuje jedną odpowiedź, my mamy trzy (a w raporcie
# do sześciu) i każdą w całości.
STYLE_SLAJDOW = """
.pytanie-link{background:none;border:0;padding:0;font:inherit;color:inherit;text-align:left;cursor:pointer;}
.pytanie-link:hover,.pytanie-link.jest{color:#4e5ee6;}
.ekran .slajd{animation:pokaz .18s ease;}
.ekran .odp p{margin:0 0 7pt;}
.ekran .odp ul,.ekran .odp ol{margin:0 0 7pt;padding-left:14pt;}
.ekran .odp li{margin-bottom:3pt;}
/* Odpowiedzi modeli bywają na pół strony. Zwijamy je, żeby ramka mieściła się
   na stronie A4 jak we wzorze, ale NIE ucinamy treści — pełna odpowiedź jest
   w pliku i rozwija się jednym kliknięciem. */
.ekran .odp.zwiniete{max-height:190pt;overflow:hidden;position:relative;}
.ekran .odp.zwiniete::after{content:"";position:absolute;left:0;right:0;bottom:0;height:40pt;
background:linear-gradient(to bottom,rgba(255,255,255,0),#fff);}
.rozwin{background:none;border:0;padding:5pt 0 0;font:inherit;font-size:8.4pt;font-weight:600;
color:#4e5ee6;cursor:pointer;}
.rozwin:hover{text-decoration:underline;}
@keyframes pokaz{from{opacity:0;}to{opacity:1;}}
.slajd-nawigacja{display:flex;align-items:center;gap:8pt;margin:10pt 0 2pt;}
.slajd-strzalka{width:20pt;height:20pt;padding:0;border:.75pt solid #e3e5ee;background:#fff;
font-size:12pt;line-height:1;color:#0b1026;cursor:pointer;}
.slajd-strzalka:hover{border-color:#5768ff;color:#4e5ee6;}
.kropki{display:flex;gap:5pt;}
.kropka{width:6pt;height:6pt;padding:0;border:0;border-radius:50%;background:#dfe2ec;cursor:pointer;}
.kropka.jest{background:#5768ff;}
.slajd-licznik{margin-left:auto;font-size:7.6pt;color:#565b70;}
/* W druku jedna odpowiedź w ramce, zwinięta — dokładnie jak we wzorze. Rozwinięcie
   wszystkich trzech wypychało ramkę poza stronę A4 i dokument miał dziewięć stron
   zamiast ośmiu. Pełne odpowiedzi są w pliku HTML, w wersji do klikania. */
@media print{
.rozwin,.slajd-nawigacja{display:none;}
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
    slajdy.forEach(function(s){
      var o=s.querySelector(".odp"),b=s.querySelector(".rozwin");
      if(o&&b&&!o.classList.contains("zwiniete")){
        o.classList.add("zwiniete");b.textContent="Pokaż całą odpowiedź";
      }
    });
  }
  ekran.addEventListener("click",function(e){
    var rozwin=e.target.closest(".rozwin");
    if(rozwin){
      var odp=rozwin.previousElementSibling,zwiniete=odp.classList.toggle("zwiniete");
      rozwin.textContent=zwiniete?"Pokaż całą odpowiedź":"Zwiń odpowiedź";
      return;
    }
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


STYL_WZORU = ""  # wczytywany niżej, po zdefiniowaniu ścieżki wzoru

# ══════════════════════════════════════════════════════════════════════
#  WZÓR „TRUSTMATE × ICEA" — osiem stron A4
# ══════════════════════════════════════════════════════════════════════
# Odwzorowany 1:1 z PDF-a od Adama (październik 2026): wymiary, stopnie pisma
# i kolory są przepisane z pliku, a nie zgadywane — dlatego CSS jest w punktach.
# 1 pt w CSS to 1 pt w PDF-ie, więc „23pt" tutaj to dokładnie ten nagłówek,
# który jest we wzorze, i wydruk do PDF wychodzi w tej samej skali.
#
# ZMIENIA SIĘ TREŚĆ, NIE UKŁAD. Model pisze tekst do kilku miejsc (wstęp na
# okładce, wniosek z pomiaru, podział ról, cel na ostatniej stronie). Cała
# reszta — epoki, skala zmiany, Botland, Tryb AI, „Jak zaczynamy", kontakt —
# jest stała, bo to dowód i identyfikacja, które już zostały zatwierdzone.

WZOR = Path(__file__).resolve().parent / "wzor_trustmate"

KONTAKT = {
    "osoba": "Paweł Borowik",
    "rola": "Head of Sales, ICEA",
    "mail": "p.borowik@grupa-icea.pl",
    "tel": "+48 731 279 205",
    "tel_href": "+48731279205",
}

MIESIACE = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec",
            "sierpień", "wrzesień", "październik", "listopad", "grudzień"]


def _obraz(nazwa: str) -> str:
    """Zdjęcie jako data URI — plik idzie mailem i ma działać bez internetu."""
    import base64
    plik = WZOR / nazwa
    typ = "image/png" if plik.suffix == ".png" else "image/jpeg"
    return f"data:{typ};base64," + base64.b64encode(plik.read_bytes()).decode()


def _logo_icea(kolor: str, wysokosc: float) -> str:
    sciezka = (WZOR / "logo_icea_path.txt").read_text(encoding="utf-8").strip()
    szer = wysokosc * 186 / 40
    return (f'<svg class="logo-icea" viewBox="0 0 186 40" style="height:{wysokosc}pt;'
            f'width:{szer:.1f}pt" role="img" aria-label="ICEA">'
            f'<path fill-rule="evenodd" clip-rule="evenodd" d="{sciezka}" fill="{kolor}"/></svg>')


def _logotypy(partner: str | None, ciemne: bool, wysokosc: float) -> str:
    """„Partner × ICEA". Logo partnera to jego nazwa złożona krojem wzoru —
    plików logo partnerów nie mamy, a podmieniony obrazek z ich strony bywa
    rozmazany albo w złym kolorze. Bez partnera zostaje samo ICEA."""
    kolor = "#ffffff" if ciemne else "#000523"
    icea = _logo_icea(kolor, wysokosc)
    if not partner:
        return f'<div class="logotypy">{icea}</div>'
    return (f'<div class="logotypy"><span class="znak-partnera">{escape(partner)}</span>'
            f'<span class="razy">×</span>{icea}</div>')


def _mailto(partner: str | None) -> str:
    temat = "Diagnoza widoczności w AI" + (f" · {partner}" if partner else "")
    from urllib.parse import quote
    return f"mailto:{KONTAKT['mail']}?subject={quote(temat)}"


# Ikony liniowe w kolorze akcentu. Rysunek prosty, bo we wzorze też jest prosty:
# kreska 1,6 i zaokrąglone końce — wszystko ponad to zaczynałoby udawać ilustrację.
_IKONY = {
    "ksiazka": '<path d="M5 7h7a3 3 0 0 1 3 3v14a2.5 2.5 0 0 0-2.5-2.5H5z"/><path d="M25 7h-7a3 3 0 0 0-3 3v14a2.5 2.5 0 0 1 2.5-2.5H25z"/><path d="M8 12h4M8 16h4M18 12h4M18 16h4" opacity=".5"/>',
    "strona": '<rect x="4" y="6" width="22" height="18" rx="2.5"/><path d="M8 12h9M8 16h12M8 20h7" opacity=".5"/><circle cx="21.5" cy="11" r="1.8"/>',
    "czat": '<path d="M6 21V11a5 5 0 0 1 5-5h8a5 5 0 0 1 5 5v3a5 5 0 0 1-5 5h-9z"/><path d="M11 12h8M11 15.5h5"/>',
    "wiadomosc": '<path d="M6 6h18v13H13l-5 4v-4H6z"/><path d="M10 11h10M10 14.5h7" opacity=".6"/>',
    "lupa": '<circle cx="13" cy="13" r="7"/><path d="M18.2 18.2 25 25M13 10v6M10 13h6"/>',
    "wykres": '<path d="M5 5v20h20"/><path d="M10 21v-6M15 21v-10M20 21V8"/>',
    "gwiazdka": '<rect x="5" y="5" width="20" height="20" rx="1.5"/><path d="m15 9 1.8 3.7 4 .6-2.9 2.8.7 4L15 18.2l-3.6 1.9.7-4-2.9-2.8 4-.6z"/>',
    "dymek": '<path d="M5 7h20v13H13l-5 4v-4H5z"/><path d="M9 12h12M9 15.5h8" opacity=".6"/>',
    "ptaszek": '<rect x="5" y="5" width="20" height="20" rx="1.5"/><path d="m10 15.5 3.5 3.5L21 11"/>',
}


def _ikona(nazwa: str, rozmiar: float = 30) -> str:
    return (f'<svg class="ikona" viewBox="0 0 30 30" style="width:{rozmiar}pt;height:{rozmiar}pt"'
            f' fill="none" stroke="#5768ff" stroke-width="1.6" stroke-linecap="round"'
            f' stroke-linejoin="round" aria-hidden="true">{_IKONY[nazwa]}</svg>')


# Cudzysłów ze wzoru: dwa znaki z zaokrąglonym narożnikiem, nie ukośne kreski.
_CUDZYSLOW = ('<svg class="cudzyslow" viewBox="0 0 20 14" aria-hidden="true" fill="#5767ff">'
              '<path d="M0 14V7.5A7.5 7.5 0 0 1 7.5 0H8.6v4.4H7.6A3.2 3.2 0 0 0 4.4 7.6V14z"/>'
              '<path d="M11.2 14V7.5A7.5 7.5 0 0 1 18.7 0h1.1v4.4h-1A3.2 3.2 0 0 0 15.6 7.6V14z"/></svg>')


def _strona(tresc: str, nr: int, razem: int, partner: str | None, naglowek: str,
            klasa: str = "") -> str:
    """Biała strona z główką i stopką — tak wyglądają strony 2–7 wzoru."""
    return f'''<section class="strona {klasa}">
<header class="glowka">{_logotypy(partner, False, 11)}<span>{escape(naglowek)}</span></header>
<div class="tresc">{tresc}</div>
<footer class="stopka"><span><a href="{_mailto(partner)}">{KONTAKT["mail"]}</a><span class="sep">·</span><a href="tel:{KONTAKT["tel_href"]}">{KONTAKT["tel"]}</a></span><span><b>{nr:02d}</b> / {razem:02d}</span></footer>
</section>'''


def _okladka(t: dict, partner: str | None, odbiorca: str, data: str) -> str:
    brew = (f"Materiał ICEA dla klientów {partner}" if partner
            else f"Materiał ICEA dla {odbiorca}")
    return f'''<section class="strona ciemna okladka">
<header class="glowka">{_logotypy(partner, True, 15.3)}</header>
<div class="okladka-srodek">
<p class="brew brew-okladka">{escape(brew)}</p>
<h1>Klient już nie szuka.<br>Pyta AI, którą firmę wybrać.<br><em>Czy wskaże Twoją?</em></h1>
<p class="lead-okladka">Twoi klienci coraz częściej nie przeglądają wyników. Pytają
sztuczną inteligencję i dostają gotową odpowiedź z nazwami kilku firm. Wybierają
spośród tych kilku, bo reszty nie widzą.</p>
</div>
<div class="okladka-cytat">
<div class="cytat-tresc">{_CUDZYSLOW}
<p class="cytat-tytul">{escape(t["wstep_tytul"])}</p>
<p class="cytat-akapit">{escape(t["wstep_tresc"])}</p>
</div>
<figure class="cytat-osoba"><img src="{_obraz("haremza.png")}" alt="Wojciech Haremza">
<figcaption><b>Wojciech Haremza</b><span>CEO, ICEA</span></figcaption></figure>
</div>
<footer class="stopka"><span>Czy AI wymienia Twoją firmę?</span><span>{escape(data)}</span></footer>
</section>'''


def _epoki() -> str:
    karty = [("Kiedyś", "ksiazka", "Książka telefoniczna.",
              "Klient szukał firmy w grubej książce telefonicznej. Wygrywał ten, kto w niej był i ten, kto miał większe ogłoszenie.", ""),
             ("Potem", "strona", "Pierwsza strona Google.",
              "Wyszukiwarka dała listę kilkudziesięciu firm, ale wygrywał ten, kto był na pierwszej stronie.", ""),
             ("Dziś", "czat", "Jedna rekomendacja.",
              "AI odpowiada zdaniem, nie długą listą. Wymienia kilka propozycji, wygrywa ten, kogo wymieni.", "ciemna")]
    kafle = "".join(f'<article class="karta {k}"><span class="etykieta">{e}</span>{_ikona(i)}'
                    f'<h3>{h}</h3><p>{p}</p></article>' for e, i, h, p, k in karty)
    siatka = "".join(f'<i class="{"pelny" if n < 10 else ""}"></i>' for n in range(30))
    return f'''<div class="blok">
<p class="brew">Jak szukają klienci</p>
<h2>Trzy sposoby, w jakie klient Cię znajdował.</h2>
<p class="lead">Za każdym razem zmieniało się jedno: ile firm klient w ogóle widział, zanim wybrał.</p>
<div class="trzy">{kafle}</div>
</div>
<div class="blok">
<p class="brew">Skala zmiany</p>
<h2>To nie jest zapowiedź, to już się dzieje.</h2>
<div class="skala-zmiany">
<div class="skala-liczba"><strong>10</strong><span>milionów Polaków</span></div>
<div class="skala-opis"><div class="siatka">{siatka}</div>
<p>korzysta z ChatGPT w ciągu miesiąca. To jedna trzecia wszystkich internautów w Polsce.</p>
<small>Źródło: Mediapanel Gemius/PBI, październik 2025.</small></div>
</div>
</div>'''


def _zmiana(t: dict, badanie: dict) -> str:
    """Strona 3: pytania po lewej, rozmowa z AI po prawej.

    DOWODEM JEST ODPOWIEDŹ, NIE NASZE ZDANIE O NIEJ. We wzorze ramka pokazuje
    prawdziwy fragment odpowiedzi AI z datą. Tu jest to samo, tylko o kliencie:
    pytania, które zadaliśmy, i to, co ChatGPT naprawdę odpowiedział — wszystkie,
    przewijane jak slajdy, a w wydruku pod sobą, bo kartki nie da się kliknąć.
    """
    # Na stronie mieszczą się cztery pytania z odpowiedziami — przy sześciu ramka
    # i wniosek zjeżdżały na drugą kartkę. Liczby w linii pomiaru są z całości.
    odpowiedzi = (badanie.get("odpowiedzi") or [])[:4]
    if not odpowiedzi and badanie.get("dowod"):
        odpowiedzi = [badanie["dowod"]]

    slajdy = "".join(
        f'<div class="slajd" data-slajd="{i}"{"" if i == 0 else " hidden"}>'
        f'<div class="pytanie-klienta"><span>Pytanie klienta</span>'
        f'<p class="pyt">{escape(o.get("pytanie") or "")}</p></div>'
        f'<p class="odpowiedz-ai">✳ Odpowiedź AI</p>'
        f'<div class="odp zwiniete">{_odpowiedz_html(o.get("odpowiedz") or "")}</div>'
        f'<button class="rozwin" type="button">Pokaż całą odpowiedź</button>'
        f'</div>'
        for i, o in enumerate(odpowiedzi))

    kropki = "".join(
        f'<button class="kropka{" jest" if i == 0 else ""}" data-idx="{i}" type="button"'
        f' aria-label="Pytanie {i + 1}"></button>' for i in range(len(odpowiedzi)))
    nawigacja = "" if len(odpowiedzi) < 2 else f'''<div class="slajd-nawigacja">
<button class="slajd-strzalka" data-krok="-1" type="button" aria-label="Poprzednie pytanie">‹</button>
<div class="kropki">{kropki}</div>
<button class="slajd-strzalka" data-krok="1" type="button" aria-label="Następne pytanie">›</button>
<span class="slajd-licznik"><b>1</b> z {len(odpowiedzi)}</span>
</div>'''

    pytania = "".join(
        f'<li><span class="nr">{i + 1:02d}</span>'
        f'<button class="pytanie-link" data-idx="{i}" type="button">„{escape(p)}”</button></li>'
        for i, p in enumerate((badanie.get("pytania") or [])[:4]))

    # Model lubi zaczynać wstęp od nagłówka, który stoi tuż nad nim — w raporcie
    # Trafiki „Sprawdź to sam, zanim nam uwierzysz." stało dwa razy pod sobą.
    wstep = (t.get("audyt_wstep") or "").strip()
    if wstep.lower().startswith("sprawdź to sam"):
        wstep = wstep.split(".", 1)[-1].strip() or "Zapytaj AI tak, jak zapytałby Twój klient:"

    return f'''<div class="blok s-zmiana">
<p class="brew">Sprawdź swoją markę</p>
<h2>Co się zmienia dla Twojej firmy.</h2>
<p class="lead">Lista dziesięciu wyników dawała szansę każdemu, kto się na nią załapał. Odpowiedź AI
wymienia kilka firm i nie pokazuje reszty.</p>
<div class="test">
<div class="test-tresc">
<h3>Sprawdź to sam,<br>zanim nam uwierzysz.</h3>
<p class="pod-h3">{escape(wstep)}</p>
<ul class="pytania-lista">{pytania}</ul>
{_linia_pomiaru(badanie)}
</div>
<div class="ramka"><div class="ekran" id="ekran-odpowiedzi">
<div class="belka"><span></span><span></span><span></span>Przykład rozmowy z AI</div>
<div class="ekran-srodek">{slajdy}{nawigacja}</div>
<p class="stopa">Prawdziwa odpowiedź ChatGPT na to zapytanie, {escape(badanie.get("data") or "")}.</p>
</div></div>
</div>
<p class="wyroznienie">{escape(t["audyt_wniosek"])}</p>
</div>'''


def _odmiana(n: int, jedna: str, kilka: str, wiele: str) -> str:
    if n == 1:
        return jedna
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return kilka
    return wiele


def _linia_pomiaru(badanie: dict) -> str:
    """Pomiar w trzech liczbach, policzony przez kod, nie napisany przez model.

    Osobno liczymy odpowiedzi, w których AI nie poleciło NIKOGO. Na Trafice trzy
    z czterech pytań o tytoń skończyły się odmową z powodu prawa — liczone razem
    z resztą wyglądały jak „konkurencja zajęła Twoje miejsce", a nikt go nie zajął.
    """
    pytan = badanie.get("liczba_pytan") or 0
    if not pytan:
        return ""
    odp = badanie.get("liczba_odpowiedzi") or pytan
    modeli = badanie.get("modeli") or 1
    powt = badanie.get("powtorzenia") or 1
    padla = badanie.get("wspomniana") or 0
    zdania = [f'Zadaliśmy {pytan} {_odmiana(pytan, "pytanie", "pytania", "pytań")}'
              + (f", każde {powt} razy" if powt > 1 else "")
              + (f", każdemu z {modeli} modeli" if modeli > 1 else "") + ".",
              (f'Marka padła przy {padla} z {odp} {"pytania" if odp == 1 else "pytań"}.'
               if modeli == 1 else f"Marka padła w {padla} z {odp} odpowiedzi modeli.")]
    nikt = badanie.get("bez_polecen")
    if nikt:
        zdania.append(f'Przy {nikt} z {odp} AI nie wskazało nikogo, u kogo kupić.')
    return f'<p class="linia-pomiaru">{escape(" ".join(zdania))}</p>'


def _marka(t: dict, badanie: dict) -> str:
    """Co AI mówi o samej marce, zapytane wprost o adres strony.

    Pomiar kategorii mówi, czy AI poleca markę. To pytanie mówi, czy w ogóle ją
    zna i czy opisuje ją zgodnie z prawdą. Odpowiedź stoi w całości, a ocenę
    model pisze wyłącznie przez porównanie z tekstem ze strony klienta.
    """
    m = badanie.get("marka") or {}
    if not (m.get("odpowiedz") or "").strip():
        return ""
    pokaz = m.get("odpowiedz_pokaz") or m["odpowiedz"]
    wyciete = pokaz != m["odpowiedz"]
    return f'''<div class="blok s-marka">
<p class="brew">Twoja marka w AI</p>
<h2>{escape(t.get("marka_tytul") or "Co AI wie o Twojej firmie.")}</h2>
<p class="lead">Zapytaliśmy ChatGPT wprost o adres Twojej strony. Tak odpowiedział{
", słowo w słowo — pominęliśmy tylko dane rejestrowe i kontaktowe" if wyciete else ", słowo w słowo"}.</p>
<div class="ramka"><div class="ekran">
<div class="belka"><span></span><span></span><span></span>Rozmowa z AI</div>
<div class="ekran-srodek">
<div class="pytanie-klienta"><span>Pytanie</span><p class="pyt">{escape(m.get("pytanie") or "")}</p></div>
<p class="odpowiedz-ai">✳ Odpowiedź AI</p>
<div class="odp">{_odpowiedz_html(pokaz)}</div>
</div>
<p class="stopa">Prawdziwa odpowiedź ChatGPT na to zapytanie, {escape(badanie.get("data") or "")}.</p>
</div></div>
{f'<p class="wyroznienie">{escape(t["marka_wniosek"])}</p>' if t.get("marka_wniosek") else ""}
</div>'''


PRZEPLYW_DOMYSLNY = [
    {"tytul": "Pytanie do AI", "opis": "Klient pyta o Twoją kategorię"},
    {"tytul": "Odpowiedź", "opis": "AI wymienia kilka firm z nazwy"},
    {"tytul": "Twoja nazwa", "opis": "gdy AI wie, czym się zajmujesz"},
]


def _branza(t: dict, partner: str | None) -> str:
    """Strona 4: czego praca partnera nie obejmuje i kto co robi."""
    ikony = ("wiadomosc", "lupa", "wykres")
    kafle = "".join(
        f'<article class="karta">{_ikona(ikony[i % 3])}<h3>{escape(k["tytul"])}</h3>'
        f'<p>{escape(k["opis"])}</p></article>' for i, k in enumerate(t["braki"][:3]))

    przeplyw = [k for k in (t.get("przeplyw") or []) if k.get("tytul")][:3] or PRZEPLYW_DOMYSLNY
    ikony_p = ("gwiazdka", "dymek", "ptaszek")
    kroki = '<span class="strzalka">→</span>'.join(
        f'<div class="krok-p">{_ikona(ikony_p[i], 22)}<div><b>{escape(k["tytul"])}</b>'
        f'<span>{escape(k.get("opis") or "")}</span></div></div>'
        for i, k in enumerate(przeplyw))

    lista = lambda xs: "".join(f"<li>{escape(x)}</li>" for x in xs)
    tytul_partnera = t.get("rola_partner_tytul") or (f"Zostaje w {partner}." if partner else "Zostaje u Ciebie.")
    return f'''<div class="blok s-branza">
<p class="brew">Wspólne działania</p>
<h2 class="h2-mniejszy">{escape(t["role_tytul"])}</h2>
<p class="lead">{escape(t["role_wstep"])}</p>
<div class="trzy trzy-wyzsze">{kafle}</div>
<div class="przeplyw">{kroki}</div>
<p class="puenta">{escape(t.get("role_puenta") or "Im lepiej AI rozumie, czym zajmuje się Twoja firma, tym częściej ją wymienia.")}</p>
<div class="role">
<div class="rola-kol"><h3>{escape(tytul_partnera)}</h3><ul>{lista(t["rola_partner"][:4])}</ul></div>
<div class="rola-kol ciemna"><h3>Bierze na siebie ICEA.</h3><ul>{lista(t["rola_my"][:4])}</ul></div>
</div>
</div>'''


BOTLAND_SLUPKI = [("2 495", 2495, "maj 2025", "punkt wyjścia"),
                  ("7 783", 7783, "sierpień", "pierwsze efekty prac"),
                  ("10 119", 10119, "listopad", "przekroczenie progu 10 tysięcy"),
                  ("12 211", 12211, "luty 2026", "najwyższy poziom")]


def _botland() -> str:
    kafle = "".join(f'<div class="wynik"><strong>{a}</strong><span>{b}</span>'
                    + (f'<em>{c}</em>' if c else "") + '</div>' for a, b, c in (
        ("5 830", "wejść z AI rocznie przed projektem", ""),
        ("192 588", "wejść z AI po dwunastu miesiącach", ""),
        ("+389,4%", "wzrost liczby zapytań, w których AI sięga po treści firmy", ""),
        ("770 352 zł", "tyle kosztowałoby kupienie tego ruchu w reklamie",
         "przy stawce 4 zł za kliknięcie")))
    najw = max(v for _, v, _, _ in BOTLAND_SLUPKI)
    slupki = "".join(
        f'<div class="kolumna"><span class="wartosc">{a}</span>'
        f'<span class="slup" style="height:{103.1 * v / najw:.1f}pt"></span>'
        f'<span class="miesiac">{m}</span><span class="opis">{o}</span></div>'
        for a, v, m, o in BOTLAND_SLUPKI)
    return f'''<div class="blok s-case">
<p class="brew">Przykład projektu</p>
<h2>Zrobiliśmy to dla Botland.</h2>
<p class="lead">Nie opowiadamy o możliwościach. Pokazujemy jeden z naszych projektów: Botland
(botland.com.pl), sklep z elektroniką i robotyką, który przez dwanaście miesięcy budował
widoczność w odpowiedziach AI. Mówimy, co dokładnie się w nim wydarzyło.</p>
<div class="wyniki">{kafle}</div>
<div class="wykres-botland"><h3>Jak to rosło przez dwanaście miesięcy.</h3>
<p>Liczba zapytań, w których odpowiedź AI sięgała po treści tej firmy.</p>
<div class="kolumny">{slupki}</div></div>
<div class="cytat-czechowski"><img src="{_obraz("czechowski.jpg")}" alt="Tomasz Czechowski">
<div><p>„Wynik nie pojawił się jednorazowo. Najpierw uporządkowaliśmy fundamenty,
potem przyszło przyspieszenie, a na końcu stabilizacja widoczności.”</p>
<span><b>Tomasz Czechowski</b> Head of SEO, ICEA</span></div></div>
</div>'''


def _dowod() -> str:
    return f'''<div class="blok s-dowod">
<p class="brew">Przykład projektu</p>
<h2>Nie musisz wierzyć nam na słowo. Zapytaj o nas AI.</h2>
<p class="lead">Tak Google odpowiada dziś w Trybie AI na pytanie „botland i icea”. Mechanizm opisany
w tym materiale działa więc również w drugą stronę: to, co robimy, jest dla AI widoczne,
zrozumiałe i cytowalne.</p>
<div class="fragment-ai"><span>Fragment odpowiedzi AI</span>
<p>„Wdrożenie strategii AI Search przez ICEA pozwoliło zwiększyć liczbę wejść z AI
z około 5,8 tys. do ponad 192,5 tys. rocznie”.</p></div>
<figure class="zrzut"><div class="zrzut-ramka"><img src="{_obraz("tryb_ai.jpg")}"
alt="Odpowiedź Google w Trybie AI na pytanie botland i icea"></div>
<figcaption>Google, Tryb AI, zapytanie „botland i icea”, 19.09.2026.</figcaption></figure>
<p class="nagroda">Projekt dla Botland był nominowany do European Search Awards 2025 w kategorii
Best Use of Search. O tej nominacji AI też mówi sama z siebie.</p>
</div>'''


def _strata_i_kroki() -> str:
    karty = [("01", "Klient pyta.", "Klient szuka produktu i chce kupić tam, gdzie inni są zadowoleni. Coraz częściej pyta o to AI: gdzie kupić i komu zaufać.", ""),
             ("02", "AI odpowiada.", "Odpowiedź wymienia kilka firm z nazwy i krótko mówi, dlaczego właśnie te. Twojej firmy w niej nie ma.", ""),
             ("03", "Ty nic nie widzisz.", "Nie przychodzi zapytanie, o którym mógłbyś wiedzieć. Zamówienie trafia do firmy z odpowiedzi, a Ty nie wiesz nawet, że była rozmowa.", "ciemna")]
    kafle = "".join(f'<article class="karta {k}"><span class="nr">{n}</span><h3>{h}</h3><p>{p}</p></article>'
                    for n, h, p, k in karty)
    kroki = [("01", "Krótka rozmowa.", "15 do 30 minut", "Ustalamy, czym się zajmujesz, kto u Ciebie kupuje i o co pyta, zanim wybierze firmę."),
             ("02", "Analiza wyników.", "przed spotkaniem", "Sprawdzamy, w jakich odpowiedziach AI pada dziś Twoja marka, a w jakich konkurencja. To analiza przygotowana pod Twoją firmę, nie gotowy raport dla wszystkich."),
             ("03", "Sesja z ekspertem.", "60 do 90 minut", "Tyle trwa rzetelne omówienie wyników. Pokazujemy, jak AI widzi Twoją markę na tle konkurencji i odpowiadamy na każde pytanie."),
             ("04", "Wnioski na piśmie.", "bezpłatnie", "Od trzech do pięciu priorytetów i czarno na białym odpowiedź, czy AI w ogóle wie, że istniejesz. Bez zobowiązań: decyzję, co dalej, podejmujesz sam.")]
    etapy = "".join(f'<div class="etap"><span class="nr">{n}</span><h3>{h}</h3><em>{c}</em><p>{p}</p></div>'
                    for n, h, c, p in kroki)
    return f'''<div class="blok">
<p class="brew">Perspektywa klienta</p>
<h2>Strata, której nie zobaczysz w żadnym raporcie.</h2>
<p class="lead">Botland to duży sklep, ale ten mechanizm działa w każdej branży i przy każdej skali.
Najbardziej boli firmę, na którą klienci już zapracowali zaufaniem: klient zapytał AI, gdzie kupić,
a odpowiedź wskazała konkurenta, zanim w ogóle dotarł do Ciebie. Ty zapracowałeś na zaufanie,
a korzyść odniósł ktoś inny.</p>
<div class="trzy trzy-nizsze">{kafle}</div>
<p class="wyroznienie-pomarancz">W zwykłej wyszukiwarce spadek z trzeciego na dziesiąte miejsce widać w raporcie.
Tutaj nie ma czego zobaczyć i dlatego tę stratę tak łatwo przeoczyć.</p>
</div>
<div class="blok">
<p class="brew">Pierwszy krok</p>
<h2>Jak zaczynamy.</h2>
<p class="lead">Od rzetelnego sprawdzenia, jak jest dzisiaj, nie od oferty. Pierwsza analiza jest bezpłatna
i do niczego nie zobowiązuje: chcemy pokazać Ci twarde fakty, zanim podejmiesz jakąkolwiek decyzję.</p>
<div class="etapy">{etapy}</div>
</div>'''


def _zamkniecie(t: dict, partner: str | None, naglowek: str, nr: int, razem: int) -> str:
    cel = t.get("wspolny_cel") or "Wspólny cel: kiedy ktoś pyta AI, u kogo kupić, ma usłyszeć Twoją nazwę."
    kolumna_partnera = ""
    if partner:
        kolumna_partnera = (f'<div><b>{escape(partner)}</b>'
                            f'<p>{escape(t.get("partner_opis") or "")}</p></div>')
    return f'''<section class="strona ciemna zamkniecie">
<div class="cta">
<img class="cta-zdjecie" src="{_obraz("borowik.jpg")}" alt="{KONTAKT["osoba"]}">
<div class="cta-tresc">
<h2>Sprawdźmy, czy AI o Tobie wie.</h2>
<p>Po rozmowie masz na piśmie trzy rzeczy: gdzie Twoja marka pojawia się dziś w odpowiedziach AI,
jak wypada na tle konkurencji i od czego zacząć. Umawiasz się bezpośrednio z osobą, która robi to badanie.</p>
<p class="cta-osoba"><b>{KONTAKT["osoba"]}</b><span>{KONTAKT["rola"]}</span></p>
<p>Sprawdza, w jakich pytaniach do AI pada nazwa marki, a w jakich jej brakuje. Pierwszą rozmowę
prowadzi jak diagnozę: co widać dziś i co ma sens w pierwszej kolejności.</p>
<a class="cta-przycisk" href="{_mailto(partner)}">Umów rozmowę <span>↗</span></a>
<p class="cta-kontakt"><a href="{_mailto(partner)}">{KONTAKT["mail"]}</a><a href="tel:{KONTAKT["tel_href"]}">{KONTAKT["tel"]}</a></p>
</div>
</div>
<div class="cel">
{_logotypy(partner, True, 13.6)}
<p class="cel-tytul">{escape(cel)}</p>
<div class="cel-kolumny">{kolumna_partnera}
<div><b>ICEA</b><p>Agencja Search od 2007 roku. Sprawdza, czy AI wymienia Twoją firmę, i dokłada
wiedzę, po którą AI sięga, zanim kogoś poleci.</p></div></div>
</div>
<footer class="stopka"><span>{escape(naglowek)}</span><span><b>{nr:02d}</b> / {razem:02d}</span></footer>
</section>'''


def zbuduj(tresc: dict, badanie: dict, partner: str | None,
           strony_audytu: list[str] | None = None, odbiorca: str = "") -> str:
    """Składa dokument ze stron wzoru.

    `partner` — kto wysyła materiał (Tebim). Gdy None, nadawcą jest sama ICEA,
    a `odbiorca` to firma, której dotyczy materiał (audyt wysyłany bezpośrednio).
    `strony_audytu` — gotowe treści stron z raportu (raport_geo), wstawiane po
    stronie z pomiarem, a przed podziałem ról: najpierw co zmierzyliśmy, potem
    kto co z tym robi, a na końcu dowód, że umiemy to zmienić.
    """
    strony_audytu = strony_audytu or []
    naglowek = (f"Materiał ICEA dla klientów {partner}" if partner
                else f"Materiał ICEA dla {odbiorca or 'Twojej firmy'}")
    teraz = datetime.now()
    data = f"{MIESIACE[teraz.month - 1]} {teraz.year}"

    marka = _marka(tresc, badanie)
    srodek = [_epoki(), _zmiana(tresc, badanie), *([marka] if marka else []), *strony_audytu,
              _branza(tresc, partner), _botland(), _dowod(), _strata_i_kroki()]
    razem = len(srodek) + 2
    strony = [_okladka(tresc, partner, odbiorca, data)]
    for i, tresc_strony in enumerate(srodek, start=2):
        strony.append(_strona(tresc_strony, i, razem, partner, naglowek))
    strony.append(_zamkniecie(tresc, partner, naglowek, razem, razem))

    tytul = f"Czy AI wymienia Twoją firmę? — {naglowek}"
    return f'''<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(tytul)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap">
<style>{STYL_WZORU}{STYLE_SLAJDOW}</style>
</head><body>
{"".join(strony)}
{SKRYPT_SLAJDOW}
</body></html>'''


STYL_WZORU = (WZOR / "styl.css").read_text(encoding="utf-8")


def nazwa_pliku(klient: str) -> str:
    """Nazwa pliku do pobrania — bez polskich znaków i spacji, z datą."""
    zamiana = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    czysta = (klient or "klient").translate(zamiana)
    czysta = re.sub(r"[^A-Za-z0-9]+", "-", czysta).strip("-").lower() or "klient"
    return f"ai-search-{czysta}-{datetime.now():%Y%m%d}.html"

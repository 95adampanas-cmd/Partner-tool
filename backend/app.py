"""
Partner Tool — backend.

Zasada z PRD: deterministyczne zadania = zwykłe funkcje Pythona (scraper, filtr, CSV).
LLM tylko tam, gdzie trzeba rozumieć język: ekstrakcja danych, zapytanie do wyszukiwarki, mail.

API:
  POST /api/research  {url}              -> dane firmy (Funkcja 1)
  POST /api/similar   {firma}            -> lista podobnych firm (Funkcja 2)
  POST /api/email     {firma}            -> 3 drafty maila (Funkcja 3)
  POST /api/export    {firmy: [...]}     -> plik CSV do pobrania (Funkcja 4)
  GET  /                                 -> frontend

Uruchomienie (z folderu backend/):
    uvicorn app:app --reload
"""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin
import asyncio
import csv
import io
import os
import re

from dotenv import load_dotenv
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
import requests
from bs4 import BeautifulSoup
from tavily import TavilyClient
from agents import Agent, Runner, WebSearchTool

import audyt
import baza
import claude
import mapy
import krs as krs_api
import dfs
import geo
import profil

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

DOCS = Path(__file__).resolve().parent.parent / "docs"

# ── Modele ────────────────────────────────────────────────────────────
# Cała praca językowa idzie na Claude. Podział wg ryzyka, nie wg ceny: gdzie wynik
# czyta człowiek albo trafia do maila do partnera, stoi Sonnet; klasyfikacja
# i tagowanie idą na Haiku.
MOCNY = claude.MOCNY
TANI = claude.TANI

# JEDYNY wyjątek — audyt GEO. `agent_pytajacy` nie używa modelu do pracy, tylko
# go MIERZY: pyta „kogo polecasz" i sprawdza, czy padnie nazwa badanej firmy.
# Klienci partnera pytają ChatGPT, więc pomiar musi chodzić na modelu OpenAI
# z wyszukiwarką OpenAI. Podmiana na Claude nie zmieniłaby dostawcy, tylko
# PRZEDMIOT POMIARU — raport przestałby mówić „jesteś widoczny w ChatGPT".
MODEL_POMIARU_GEO = "gpt-5.4-mini"

BRAK = "nie do ustalenia"    # PRD: uczciwy brak zamiast halucynacji

_NOWA_LINIA = chr(10)   # zamiast sekwencji ucieczki — jest odporna na przenoszenie kodu

# Kategorie partnerskie — JEDNO ŹRÓDŁO PRAWDY. Model przypisuje tu firmę przy
# researchu, front grupuje po tym listy, a /api/kategorie je udostępnia.
#
# Te same nazwy są nagłówkami grup w PRESETY (frontend/app.js). Nazwy MUSZĄ się
# zgadzać, inaczej firma wyląduje w kategorii, której nie ma na liście wyboru.
# Pilnuje tego test regresji — poprzednim razem kopia reguł w teście rozjechała
# się po cichu i nikt tego nie zauważył przez trzy commity.
KATEGORIE_PARTNEROW = [
    "Budowa stron i sklepów",
    "Utrzymanie i administracja",
    "Strategia i doradztwo",
    "Branding i kreacja",
    "Marketing poza SEO",
    "Sprzedaż i marketplace",
    "Technologia, integracje i resellerzy",
    "AI i automatyzacja",
    "Wiedza i usługi prawne",
    "Sieci i społeczności biznesowe",
]


# ══════════════════════════════════════════════════════════════════════
#  MODEL DANYCH  (patrz docs/DATA-MODEL.md)
# ══════════════════════════════════════════════════════════════════════
class Firma(BaseModel):
    nazwa: str
    branza: str
    uslugi: list[str]
    wielkosc_zespolu: str        # liczba lub "nie do ustalenia"
    liczba_projektow: str        # liczba lub "nie do ustalenia"
    case_studies: list[str]      # nazwy klientów / realizacji
    telefon: str                 # ogólny kontakt firmowy
    email: str                   # ogólny kontakt firmowy
    nazwa_prawna: str            # pełna nazwa spółki (np. "Grupa X sp. z o.o.")
    nip: str
    krs: str                     # numer KRS ze stron prawnych; otwiera oficjalny rejestr
    regon: str
    adres: str                   # ulica + kod pocztowy
    miasto: str
    persona_imie: str            # osoba decyzyjna: imię i nazwisko
    persona_stanowisko: str      # jej rola (CEO, właściciel, dyrektor...)
    persona_email: str           # jej bezpośredni mail, jeśli podany przy osobie
    persona_telefon: str         # jej bezpośredni telefon, jeśli podany przy osobie
    # FAKT, nie osąd: czy firma sprzedaje SEO/SEM/pozycjonowanie. Wcześniej było tu
    # `konkurent: bool` — czyli narzędzie orzekało, kto jest konkurentem. To decyzja
    # zespołu, nie modelu: agencja z SEO w ofercie bywa i konkurentem, i najlepszym
    # partnerem, zależnie od tego, po co do niej piszemy.
    ma_seo: bool
    seo_zakres: str              # co dokładnie oferuje i jak duża część oferty
    opis: str                    # 2-3 zdania, czym firma się zajmuje
    kategoria: str               # jedna z KATEGORIE_PARTNEROW — po niej grupujemy listy


# ══════════════════════════════════════════════════════════════════════
#  SCRAPER — zwykła funkcja, wielostronicowy
#  Homepage nie wystarcza: zespół, realizacje i kontakt są na podstronach.
# ══════════════════════════════════════════════════════════════════════
# Kolejność MA ZNACZENIE — bierzemy po jednej podstronie z każdej grupy, od najważniejszej.
# Wcześniej braliśmy pierwsze 4 pasujące linki i na stronach z rozbudowanym menu
# wszystkie 4 sloty zjadała /oferta/*, przez co /kontakt nigdy nie był odwiedzany.
GRUPY_PODSTRON = (
    ("kontakt", "contact"),                                    # kontakt, adres, NIP
    ("o-nas", "o_nas", "about", "zespol", "zespół", "team"),    # zespół, osoba decyzyjna
    ("realizacje", "portfolio", "case", "projekty", "wdrozenia", "wdrożenia"),  # case studies
    ("oferta", "uslugi", "usługi", "services"),                 # usługi
)

# Wpisy blogowe i newsy zjadają limit znaków, a rzadko mają dane o firmie.
# UWAGA: regulaminu i polityki prywatności NIE pomijamy, choć kiedyś były na tej
# liście. To był błąd kosztujący realne dane — polskie prawo wymaga podania tam
# pełnej nazwy, NIP-u, KRS-u i adresu rejestrowego, więc to często JEDYNE miejsce
# w serwisie, gdzie te dane w ogóle są. Zmierzone: NIP brakował w 6 z 10 firm,
# a u Devisu i widoczni leżał właśnie w polityce prywatności.
POMIJAJ = ("/blog", "/aktualnosci", "/news", "/aktualnosc", "/wpis")

# Strony z danymi rejestrowymi. Traktujemy je INACZEJ niż zwykłe podstrony:
# nie wrzucamy całej treści do LLM, bo to kilkanaście tysięcy znaków prawniczej
# formuły, która zjadłaby limit. Wyciągamy z nich sam blok rejestrowy regexem.
SCIEZKI_PRAWNE = ("polityka", "regulamin", "privacy", "prywatnosc", "prywatność",
                  "terms", "legal", "rodo", "impressum")

# NIP bywa zapisany z myślnikami i spacjami; KRS zawsze ma 10 cyfr.
RE_NIP = re.compile(r"\bNIP[:\s]*((?:PL)?[\s-]?[0-9](?:[\s-]?[0-9]){9})", re.I)
RE_KRS = re.compile(r"\bKRS[:\s]*([0-9]{10})\b", re.I)
RE_REGON = re.compile(r"\bREGON[:\s]*([0-9]{9}(?:[0-9]{5})?)\b", re.I)

MAX_PODSTRON = 4
LIMIT_ZNAKOW = 12000


def pobierz(url: str, timeout: int = 15) -> str:
    """Pobiera HTML jednej strony. Zwraca '' gdy się nie udało."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (PartnerTool)"})
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


# Pozycje menu, ktore nigdy nie sa usluga. Porownujemy CALA nazwe, nie fragment —
# pierwsza wersja szukala podciagu i slowo "sklep" (mialo odsiewac koszyk) wycinalo
# "Sklep B2B PrestaShop" oraz "Utrzymanie sklepu PrestaShop", czyli polowe oferty.
# Reszte zostawiamy modelowi: to on ma rozstrzygnac, co jest oferta, a my mamy mu
# tylko DOSTARCZYC dane.
MENU_NIE_USLUGA = frozenset((
    "kontakt", "o nas", "about", "about us", "blog", "kariera", "career", "praca",
    "realizacje", "portfolio", "baza wiedzy", "case studies", "aktualnosci",
    "aktualności", "newsletter", "polityka prywatności", "regulamin", "cookies",
    "rodo", "home", "strona główna", "koszyk", "zaloguj", "logowanie", "sklep",
    "en", "pl", "de", "menu", "szukaj", "faq", "pomoc", "cennik", "wiedza",
))


def menu_nawigacji(soup) -> list[str]:
    """Pozycje z menu górnego — najbardziej wiarygodna lista tego, co firma sprzedaje.

    DLACZEGO TO ISTNIEJE. `tekst_ze_strony` wycina <nav>, żeby nawigacja nie zaśmiecała
    treści — i razem z nią wyrzucało MENU USŁUG, czyli najlepsze źródło informacji
    o ofercie. Skutek był mylący: model dostawał tylko sekcję „Nasze Usługi" ze strony
    głównej, która bywa skróconą zajawką. U Tebimu ta zajawka ma 6 pozycji o nazwach
    ogólnych („Integracje E-commerce"), a prawdziwe menu — 10 pozycji z nazwami
    konkretnymi („Integracje PrestaShop", „Wdrożenie PIM"). Wyciągaliśmy więc gorszą
    z dwóch dostępnych list i wychodziła z tego generyczna agencja zamiast
    wyspecjalizowanej.
    """
    pozycje = []
    for nav in soup.find_all("nav"):
        for a in nav.find_all("a"):
            nazwa = " ".join(a.get_text(separator=" ").split())
            if not (3 < len(nazwa) < 70):
                continue
            plaska = nazwa.lower().strip(" -–—|")
            if plaska in MENU_NIE_USLUGA:
                continue
            # numery telefonu i adresy trafiaja do nawigacji rownie czesto co uslugi
            if sum(c.isdigit() for c in nazwa) > len(nazwa) / 3:
                continue
            if nazwa not in pozycje:
                pozycje.append(nazwa)
    return pozycje[:30]


def tekst_ze_strony(html: str) -> str:
    # UWAGA: NIE wycinamy <footer> — to tam zwykle są dane firmowe: adres, NIP, telefon, mail.
    soup = BeautifulSoup(html, "html.parser")
    # Menu ratujemy PRZED usunięciem <nav> i doklejamy osobnym, opisanym blokiem.
    # Osobnym, bo model ma wiedzieć, że to oferta, a nie zdanie z treści strony.
    menu = menu_nawigacji(soup)
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    tresc = " ".join(soup.get_text(separator=" ").split())
    if menu:
        tresc = "[MENU GŁÓWNE SERWISU] " + " | ".join(menu) + " " + _NOWA_LINIA + tresc
    return tresc


def znajdz_podstrony(html: str, base_url: str) -> list[str]:
    """Wybiera po JEDNEJ podstronie z każdej grupy (kontakt → o nas → realizacje → oferta),
    żeby jeden typ podstron nie zjadł wszystkich slotów."""
    soup = BeautifulSoup(html, "html.parser")
    # Porównanie hostów MUSI ignorować wielkość liter. Część stron ma linki absolutne
    # zapisane jako "https://WWW.Firma.pl/kontakt" — przy porównaniu wrażliwym na
    # wielkość liter taka podstrona wypadała jako „obca domena" i nigdy jej nie
    # odwiedzaliśmy. Traciliśmy przez to NIP, adres i osobę decyzyjną, bez śladu w logach.
    # Dodatkowo ucinamy "www." — strony potrafią mieszać linki z www i bez niego
    # w obrębie tej samej witryny. Przy dosłownym porównaniu połowa podstron wypadała
    # jako „obca domena". Prawdziwe subdomeny (blog., sklep.) nadal są odrzucane.
    def host(u: str) -> str:
        return urlparse(u).netloc.lower().removeprefix("www.")

    domena = host(base_url)

    linki, widziane = [], set()
    for a in soup.find_all("a", href=True):
        pelny = urljoin(base_url, a["href"]).split("#")[0].split("?")[0].rstrip("/")
        if host(pelny) != domena or pelny in widziane:
            continue
        if any(p in pelny.lower() for p in POMIJAJ):
            continue
        widziane.add(pelny)
        linki.append(pelny)

    wybrane = []
    for grupa in GRUPY_PODSTRON:
        trafienie = next((l for l in linki
                          if any(s in l.lower() for s in grupa) and l not in wybrane), None)
        if trafienie:
            wybrane.append(trafienie)
    return wybrane[:MAX_PODSTRON]


def dane_rejestrowe(html: str, base_url: str) -> tuple[str, list[str]]:
    """Wyciąga NIP, KRS i REGON ze stron prawnych. Zwraca (blok tekstu, odwiedzone).

    Osobna funkcja, a nie kolejna podstrona w scrape_firme, bo te strony traktujemy
    INACZEJ. Regulamin potrafi mieć kilkanaście tysięcy znaków prawniczej formuły —
    wrzucony w całości zjadłby limit, który ma iść na opis usług. Bierzemy z nich
    wyłącznie linijkę z numerami.

    Po co w ogóle: polskie prawo wymaga podania na tych stronach pełnej nazwy, NIP-u
    i adresu rejestrowego, więc bywa to JEDYNE miejsce w serwisie, gdzie te dane są.
    Zmierzone na 10 partnerach: NIP brakował w 6, a u Devisu i widoczni leżał
    właśnie w polityce prywatności — której scraper wcześniej celowo NIE odwiedzał.
    """
    soup = BeautifulSoup(html, "html.parser")
    wlasna = urlparse(base_url).netloc.lower().removeprefix("www.")

    kandydaci = []
    for a in soup.find_all("a", href=True):
        pelny = urljoin(base_url, a["href"]).split("#")[0].split("?")[0]
        if urlparse(pelny).netloc.lower().removeprefix("www.") != wlasna:
            continue
        sciezka = urlparse(pelny).path.lower()
        if any(w in sciezka for w in SCIEZKI_PRAWNE) and pelny not in kandydaci:
            kandydaci.append(pelny)

    znalezione, odwiedzone = {}, []
    for adres in kandydaci[:3]:          # trzy strony wystarczą, dalej są powtórki
        h = pobierz(adres)
        if not h:
            continue
        tekst = tekst_ze_strony(h)
        odwiedzone.append(adres)
        for nazwa, wzor in (("NIP", RE_NIP), ("KRS", RE_KRS), ("REGON", RE_REGON)):
            if nazwa not in znalezione:
                m = wzor.search(tekst)
                if m:
                    znalezione[nazwa] = " ".join(m.group(1).split())
        if len(znalezione) == 3:         # komplet — nie ma po co czytać dalej
            break

    if not znalezione:
        return "", odwiedzone
    linie = ", ".join(f"{k}: {v}" for k, v in znalezione.items())
    return f"[DANE REJESTROWE ZE STRON PRAWNYCH]\n{linie}", odwiedzone


def scrape_firme(url: str) -> tuple[str, list[str]]:
    """Zwraca (tekst ze strony głównej + podstron, lista odwiedzonych URL-i)."""
    html = pobierz(url)
    if not html:
        return "", []
    czesci = [f"[STRONA GŁÓWNA: {url}]\n{tekst_ze_strony(html)}"]
    odwiedzone = [url]
    for pod in znajdz_podstrony(html, url):
        h = pobierz(pod)
        if h:
            czesci.append(f"[PODSTRONA: {pod}]\n{tekst_ze_strony(h)}")
            odwiedzone.append(pod)

    # Numery rejestrowe dokładamy NA KOŃCU i po obcięciu limitu, żeby długa oferta
    # nigdy ich nie wypchnęła. To kilkadziesiąt znaków, a decyduje o tym, czy
    # rekord w Pipedrive ma NIP.
    tresc = "\n\n".join(czesci)[:LIMIT_ZNAKOW]
    blok, prawne = dane_rejestrowe(html, url)
    if blok:
        tresc += "\n\n" + blok
        odwiedzone += prawne
    return tresc, odwiedzone


# ══════════════════════════════════════════════════════════════════════
#  TAVILY + FILTR — zwykłe funkcje (deterministyczne, powtarzalne)
# ══════════════════════════════════════════════════════════════════════
# Pliki i obce domeny — nigdy nie są stroną polskiej firmy partnerskiej.
ROZSZERZENIA = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip")
OBCE_TLD = (
    ".es", ".de", ".fr", ".it", ".ru", ".ua", ".cz", ".sk", ".hu", ".nl", ".se",
    ".ie", ".uk", ".dk", ".no", ".fi", ".pt", ".gr", ".ro", ".bg", ".at", ".ch",
    ".be", ".lt", ".lv", ".ee",
)

# Domeny wystawione na sprzedaż i strony w budowie. Tavily zwraca ich STARE tytuły
# z czasów, gdy firma istniała — poznać je można tylko po treści strony.
MARKERY_MARTWEJ = (
    "buy this domain", "domain for sale", "expired domain", "this domain is for sale",
    "domena na sprzedaz", "domena na sprzedaż", "domena jest na sprzedaż",
    "under construction", "strona w budowie", "coming soon", "site not found",
    "afternic", "sedo.com", "parked domain", "buy-it-now",
)


def sprawdz_zywotnosc(url: str) -> str:
    """'zywa' | 'martwa' | 'niepewna'.

    PRD: firmę niedostępną OZNACZAMY, nie pomijamy. Blokada bota (Cloudflare) czy timeout
    to NIE dowód, że firma nie istnieje — takie zostawiamy z adnotacją.
    Odrzucamy tylko potwierdzone trupy: parking domeny, "under construction", pustka.
    """
    html = pobierz(url, timeout=6)
    if not html:
        return "niepewna"
    tekst = tekst_ze_strony(html)[:2500].lower()
    if any(m in tekst for m in MARKERY_MARTWEJ):
        return "martwa"
    # Mało tekstu to NIE dowód śmierci: bywa bramka językowa (cyrekdigital.com)
    # albo strona renderowana JS-em (SPA) — HTML jest wtedy prawie pusty.
    if len(tekst) < 200:
        return "niepewna"
    return "zywa"


# Domeny, które NIE są firmami — katalogi, portale, social, media. Odrzucamy w całości.
DOMENY_ODPADAJACE = (
    "clutch.co", "sortlist", "themanifest", "goodfirms", "designrush", "techbehemoths",
    "topcssgallery", "infoisinfo", "biznesfinder", "panoramafirm", "pkt.pl", "aleo.com",
    "firmy.net", "zumi.pl", "targeo", "oferteo", "ceneo", "opineo", "useme",
    "rocketreach", "emailformats", "signalhire", "lusha", "apollo.io", "zleca.pl",
    "prospeo", "hunter.io", "snov.io", "clearbit", "zoominfo", "crunchbase", "dnb.com",
    # portale ogłoszeniowe / z ofertami pracy — to nie są firmy partnerskie
    "pracuj.pl", "bulldogjob", "nofluffjobs", "justjoin", "indeed", "olx.", "gowork",
    "jooble", "jobs.pl", "startup-house.com", "f6s.com",
    "trustpilot", "marketingibiznes", "egospodarka", "wikipedia", "facebook", "linkedin",
    "instagram", "youtube", "wordpress.org", "domenomania",
    # media/blogi/fora — po ucięciu do domeny i tak nie byłyby firmą
    "blog", "news", "portal", "magazyn", "forum",

    # ── Rejestry i wywiadownie gospodarcze ──
    # Wchodziły jako firmy, bo wpis w rejestrze NAZYWA SIĘ jak firma: wynik
    # "STUDIO ECOMMERCE SP. Z O.O. | KRS: 0001146410" wygląda w liście identycznie
    # jak prawdziwy kandydat. Po ucięciu do domeny zostaje jednak bizraport.pl.
    "rejestr.io", "bizraport", "krs-online", "krs-pobierz", "imsig", "mojepanstwo",
    "infoveriti", "ems.ms.gov.pl", "rejestr.firmy", "wywiadownia", "bazafirm",
    "katalogfirm", "firmy-w-polsce", "ncrejestr", "kalkulatory.gofin",

    # ── Katalogi startupów i platformy społecznościowe ──
    "skool.com", "startupblink", "dealroom", "producthunt", "angel.co", "wellfound",
    "startup.info", "eu-startups",

    # ── Izby i organizacje branżowe (publikują mapy i listy członków) ──
    # mapa.iab.org.pl to katalog agencji, nie agencja.
    "iab.org.pl", "eizba.pl", "piit.org.pl", "kigeit", "zpp.net.pl", "lewiatan.org",

    # ── Media branżowe, wydarzenia, biura prasowe ──
    "wiadomoscihandlowe", "e-biznes.pl", "poradnikprzedsiebiorcy", "dlaprasy",
    "eventyb2b", "prnews", "wirtualnemedia", "money.pl", "bankier.pl", "interia.pl",
    "onet.pl", "wp.pl", "gazeta.pl",

    # ── Słowniki, porównywarki oprogramowania, fora, dokumentacja producentów ──
    # Wsypały się przy branży "software house": termin jest angielski, więc
    # wyszukiwarka podawała definicję ze słownika i dokumentację Visual Studio.
    "dictionary", "cambridge.org", "merriam-webster", "reddit.com", "quora.com",
    "stackoverflow", "github.com", "capterra", "g2.com", "getapp", "softwareadvice",
    "microsoft.com", "google.com", "apple.com", "amazon.", "atlassian.com",
    "yelp.com", "yell.com", "mapy.cz", "booksy",
)

# Domeny publiczne i uczelniane — nigdy nie są firmą-kandydatem. Wchodziły przez
# rejestry usług rozwojowych (uslugirozwojowe.parp.gov.pl) i strony studiów
# podyplomowych, które przy branży "e-commerce" trafiały w wyniki jako "firmy".
KONCOWKI_PUBLICZNE = (".gov.pl", ".gov", ".gouv.fr", ".edu.pl", ".edu", ".ac.uk", ".mil")

# Poddomeny, które nigdy nie są stroną firmy-kandydata, tylko jej dokumentacją,
# pomocą technczną albo bazą wiedzy. Reguła strukturalna zamiast wyliczania domen:
# "docs.johnsoncontrols.com" nie da się przewidzieć, ale prefiks już tak.
PODDOMENY_ODPADAJACE = (
    "docs.", "doc.", "support.", "help.", "helpdesk.", "developer.", "developers.",
    "learn.", "wiki.", "kb.", "status.", "api.", "community.",
)


def domena_z_url(url: str) -> str:
    """Domena bez przedrostka www.

    `netloc.replace("www.", "")` wycinało "www." TAKŻE ZE ŚRODKA nazwy: realna
    firma seo-www.pl zamieniała się w nieistniejące "seo-pl" i pod takim adresem
    trafiała na listę. Usuwamy wyłącznie przedrostek.
    """
    d = urlparse(url.lower()).netloc
    return d[4:] if d.startswith("www.") else d


def powod_odrzucenia(url: str) -> str | None:
    """Dlaczego adres nie jest stroną firmy-kandydata. None = przechodzi.

    Jedno miejsce prawdy dla reguł odrzucania. normalizuj_url() podejmuje decyzję
    na podstawie tej funkcji, a test_filtr.py czyta z niej POWÓD — wcześniej test
    trzymał własną kopię tych warunków i po zmianach w app.py sprawdzał wersję,
    która już nie istniała (wołał usuniętą czy_konkurent_w_wyniku i nie znał reguł
    poddomen ani końcówek publicznych).
    """
    u = url.lower()
    domena = domena_z_url(url)
    if not domena:
        return "brak domeny"
    if any(d in domena for d in DOMENY_ODPADAJACE):
        return "katalog/rejestr/portal"
    if domena.startswith(PODDOMENY_ODPADAJACE):
        return "dokumentacja/pomoc"
    # porównanie i na równość, bo sama "gov.pl" nie kończy się na ".gov.pl"
    if any(domena == k.lstrip(".") or domena.endswith(k) for k in KONCOWKI_PUBLICZNE):
        return "domena publiczna (gov/edu)"
    if domena.endswith(OBCE_TLD):
        return "obca domena"
    if u.split("?")[0].endswith(ROZSZERZENIA):
        return "plik (jpg/pdf)"
    return None


def normalizuj_url(url: str) -> str | None:
    """Zwraca adres STRONY GŁÓWNEJ firmy albo None, jeśli to nie firma.

    Tavily często zwraca głęboki link (artykuł, /tag/, /baza-wiedzy/) na domenie realnej firmy.
    Kiedyś takie wyniki odrzucaliśmy — traciliśmy prawdziwych kandydatów (np. Convertis).
    Teraz ucinamy do strony głównej; scraper i tak sam znajdzie podstrony przy researchu.
    """
    if powod_odrzucenia(url):
        return None
    return f"https://{domena_z_url(url)}"

# Tytuły artykułów, poradników i wydarzeń — to nie są firmy, tylko treści o branży.
FRAZY_NIE_FIRMA = (
    "jak zbudowa", "jak wybra", "jak zrobi", "jak dziala", "jak działa", "poradnik",
    "co to jest", "czym jest", "blog", "konferencja", "webinar", "targi", "szkolenie online",
    "przewodnik", " vs ", "porównanie", "porownanie", "definicja", "słownik", "slownik",
    "najlepsze w kategorii", "najwieksze agencje", "największe agencje", "warto zna",
)

# Zestawienia: "50 agencji digital", "Top 5 Najlepszych...".
#
# Wcześniej wzorzec był zakotwiczony na POCZĄTKU tytułu, żeby nie łapać firm z liczbą
# w nazwie ("Grupa 3 Agencja Reklamowa"). Kotwica działała, ale przepuszczała
# zestawienia z liczbą w środku — "Strony internetowe Warszawa: 20 firm i agencji,
# które warto znać" wchodziło na listę jako firma.
#
# Kotwicę zdejmujemy, a przed fałszywym trafieniem chroni LICZBA MNOGA: zestawienie
# mówi "20 firm" i "15 agencji", nazwa firmy — "3 Agencja". Dlatego wymagamy końcówek
# mnogich z granicą słowa; "Agencja" w liczbie pojedynczej nie pasuje.
# Do dwóch słów przerwy między liczbą a rzeczownikiem, bo zestawienia wtrącają
# przymiotnik: "71 Top E-commerce Companies". Rzeczownik w liczbie mnogiej nadal
# jest wymagany, więc "Grupa 3 Agencja Reklamowa" się nie łapie.
# Drugi wariant — samo "Top 50 czegokolwiek". Rzeczownik bywa dowolny ("Top 50
# E-Commerce Photo Studio Professionals"), więc lista końcówek go nie obejmie,
# ale "top" przed liczbą jest jednoznaczne: to ranking, nie nazwa firmy.
LISTICLE = re.compile(
    r"\btop\s+\d{1,3}\b"
    r"|\b\d{1,3}\s+([\w-]+\s+){0,2}"
    r"(firm\b|firmy\b|agencji\b|agencje\b|companies\b|software\s+houses\b|najlepsz\w*\s+(agencj|firm))",
    re.IGNORECASE,
)

# Tytuły, po których ODRZUCAMY wynik nawet po ucięciu do strony głównej — bo cała domena
# okazuje się rankingiem, katalogiem albo portalem z ogłoszeniami, a nie firmą.
TYTULY_ODRZUCAJACE = (
    "ranking", "top 10", "top10", "directory", "katalog firm", "zestawienie",
    "najlepszych agencji", "najlepsze agencje", "oferty pracy", "praca ", " praca",
    # wpisy w rejestrach gospodarczych — wyglądają jak firma, są wyciągiem z KRS
    "krs:", "nip:", "regon:", "| krs", "sprawozdanie finansowe",
)


def tavily_search(zapytanie: str, max_results: int = 15) -> list:
    """Wyszukiwanie ograniczone do Polski.

    Bez `country` całe klasy zapytań wracały z zagranicy, bo terminy branżowe są
    angielskie i globalne strony wygrywają autorytetem. Zmierzone na tej samej
    frazie „autoryzowany partner CRM": bez parametru 0/8 domen polskich (Salesforce,
    Gartner, agilecrm), z parametrem 7/8 (erpline.pl, intebuco.pl, tillio.pl).
    Podobnie „logistyka e-commerce" 4/8 -> 6/8.

    Wcześniej łatano to nazwami presetów — „fulfillment e-commerce" na „logistyka
    e-commerce". To leczyło objaw: polskie warianty zapytań i tak zwracały
    angielskie wyniki, bo problem był w braku ograniczenia geograficznego.

    `topic="general"` jest podane wprost, bo `country` działa tylko w tym trybie.
    """
    key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TVLY_API_KEY")
    if not key:
        return []
    return TavilyClient(api_key=key).search(
        zapytanie, max_results=max_results, country="poland", topic="general",
    ).get("results", [])


# Odsiewamy TYLKO firmy, dla których SEO jest rdzeniem i właściwie całą ofertą.
# Agencja e-commerce czy software house z "optymalizacją SEO" wśród kilkunastu usług
# to partner komplementarny, nie konkurent — i ma zostać na liście.
#
# Wcześniej filtr porównywał tytuł z listą ośmiu fraz. Na ośmiu realnych polskich
# agencjach SEO przepuszczał siedem, w tym Grupę iCEA i Delante: wystarczyło, że
# agencja nie wpisała frazy "agencja SEO" do znacznika title. Liczba odsianych była
# prawdziwa, ale znaczyła "tyle firm miało tę frazę w tytule", a nie "tylu było
# konkurentów".
#
# Teraz dwa etapy. Najpierw ten sygnał — tani, deterministyczny, tylko zawęża pole:
# odpowiada na pytanie "czy w ogóle jest o czym rozmawiać". W realnym wyszukiwaniu
# przechodzi przez niego 6 z 29 wyników, więc model ocenia garstkę, nie wszystko.
#
# Granice słów są tu istotne, nie kosmetyczne. Dopasowanie podciągiem łapało "sem"
# w środku innych wyrazów i podawało do oceny firmę wdrożeniową oraz software house.
SYGNAL_SEO = re.compile(r"\b(seo|sxo|pozycjonowani\w*|pozycjonowa\w*)\b", re.IGNORECASE)

# Kampanie płatne to NIE jest SEO i same z siebie nie dają tagu — wcześniej wzorzec
# łapał "google ads", "sem" i "ppc", więc agencja prowadząca wyłącznie reklamy
# dostawała znaczek SEO.
ANTY_SEO = re.compile(
    r"\b(audyt\w*|audit\w*|optymalizacj\w*|optimi[sz]\w*|copywriting|szkoleni\w*)"
    r"\s+(\w+\s+){0,2}?seo"
    r"|seo\s+(audyt\w*|audit\w*|copywriting|optymalizacj\w*|optimi[sz]\w*)"
    r"|zoptymalizowan\w*\s+pod\s+seo",
    re.IGNORECASE,
)


def ma_sygnal_seo(tytul: str, opis: str) -> bool:
    """Czy w opisie widać, że firma prowadzi KAMPANIE SEO. Sam znacznik, nie werdykt.

    Uczciwe ograniczenie: opis z wyszukiwarki ma kilkaset znaków i często nie da się
    z niego odróżnić kampanii od audytu. Odsiewamy więc to, co widać wprost — audyt,
    optymalizację, SEO copywriting — a resztę tagujemy. Pełne rozstrzygnięcie robi
    dopiero research całej strony (pole ma_seo w modelu Firma).

    Tag NIGDY nie usuwa firmy z listy ani jej nie ukrywa. Służy wyłącznie do tego,
    żeby człowiek widział, z kim ma do czynienia.
    """
    tekst = f"{tytul or ''} {opis or ''}"
    if not SYGNAL_SEO.search(tekst):
        return False
    # jedyna wzmianka o SEO to audyt/optymalizacja -> to nie są kampanie
    bez_okolo = ANTY_SEO.sub(" ", tekst)
    return bool(SYGNAL_SEO.search(bez_okolo))

# Usługi, których NIE wolno wpuścić do zapytania — inaczej szukamy własnych konkurentów.
USLUGI_KONKURENCYJNE = ("seo", "sem", "pozycjonowanie", "google ads", "meta ads", "adwords", "ppc")


# ── Lokalizacja w zapytaniu ───────────────────────────────────────────
# Doklejanie miasta było wcześniej regułą w promptcie agenta i model łamał ją
# w 4 na 6 przebiegów: przy pustym polu "miasto" dopisywał Warszawę albo Kraków,
# raz tak, raz inaczej przy tym samym wejściu. Skutek był cichy — wyszukiwanie
# ogólnopolskie zawężało się do losowego miasta, a wyniki wyglądały normalnie.
#
# To nie jest zadanie dla modelu: nie ma tu nic do zrozumienia, jest sklejenie
# dwóch stringów. Model odpowiada wyłącznie za frazy branżowe, miejsce dokleja
# ta funkcja — więc "miasto z powietrza" przestaje być możliwe.
MIASTA = (
    "warszawa", "kraków", "krakow", "łódź", "lodz", "wrocław", "wroclaw",
    "poznań", "poznan", "gdańsk", "gdansk", "szczecin", "bydgoszcz", "lublin",
    "białystok", "bialystok", "katowice", "gdynia", "częstochowa", "czestochowa",
    "radom", "sosnowiec", "toruń", "torun", "kielce", "rzeszów", "rzeszow",
    "gliwice", "zabrze", "olsztyn", "bielsko-biała", "bielsko-biala", "opole",
    "polska", "polsce", "poland",
)


def bez_lokalizacji(fraza: str) -> str:
    """Zdejmuje z frazy nazwę miasta lub kraju.

    Pas bezpieczeństwa, nie główny mechanizm: prompt już zabrania lokalizacji,
    ale prompt to prośba, a nie gwarancja. Gdyby model jednak dopisał miasto,
    bez tego powstałoby "agencja e-commerce Kraków Poznań".
    """
    slowa = [s for s in fraza.split() if s.strip(",.-").lower() not in MIASTA]
    return " ".join(slowa)


def zapytanie_z_miejscem(fraza: str, miasto: str = "", limit_slow: int = 5) -> str:
    """Fraza branżowa + miasto, ale TYLKO takie, jakie wskazał user.

    Bez miasta nie doklejamy nic — w szczególności nie "Polska". Sprawdzone na
    tej samej frazie: z dopiskiem "Polska" wyszukiwarka zwracała YouTube, Trustpilot,
    Clutch i artykuły o "e-Commerce Polska awards", bo słowo trafia w nazwy nagród
    i izb branżowych, a nie w kraj. Bez dopisku — realne agencje. Polskojęzyczna
    fraza sama załatwia geografię.

    Kolejność ma znaczenie: najpierw przycinamy FRAZĘ, dopiero potem doklejamy miasto.
    Odwrotnie — jak było w pierwszej wersji — długa fraza wypychała lokalizację poza
    limit słów i zapytanie traciło dokładnie to, co ta funkcja miała zagwarantować.
    """
    slowa = bez_lokalizacji(fraza).replace("|", " ").split()[:limit_slow]
    if not slowa:
        return ""
    return " ".join(slowa) + (f" {miasto.strip()}" if miasto.strip() else "")


def filtruj_firmy(wyniki: list, wlasna_domena: str, limit: int = 10,
                  pomin: set | None = None) -> list:
    """Zostawia realne firmy. Odrzuca katalogi/rankingi, badaną firmę i duplikaty domen.

    ŻADNA firma nie wypada z powodu SEO. Wcześniej model rozstrzygał, czy agencja
    jest konkurentem, i taką usuwał — czyli narzędzie podejmowało decyzję, którą
    ma podjąć zespół, a odrzuconych nikt nawet nie widział. Zostaje sam TAG:
    czy w opisie firmy pada SEO/SEM/pozycjonowanie. Fakt, nie wniosek.

    Opis z Tavily przychodzi w tej samej odpowiedzi i nic nie kosztuje, a to
    jedyne miejsce, po którym da się poznać, czym firma się zajmuje, bez
    wchodzenia na stronę.
    """
    firmy, widziane = [], set()
    for r in wyniki:
        strona = normalizuj_url(r.get("url", ""))
        if not strona:
            continue
        dom = urlparse(strona).netloc
        if dom in widziane or (wlasna_domena and wlasna_domena in dom):
            continue
        # Firmy pokazane w poprzednich rundach "Szukaj dalej" — bez tego kolejne
        # klikniecie zwracaloby w kolku te sama pierwsza dziesiatke.
        if pomin and domena_z_url(strona) in pomin:
            continue
        widziane.add(dom)

        tytul = (r.get("title") or "").strip()
        if any(f in tytul.lower() for f in TYTULY_ODRZUCAJACE):
            continue
        opis = " ".join((r.get("content") or "").split())[:600]
        # tytuł artykułu/zestawienia nie opisuje firmy — lepiej pokazać domenę
        if not tytul or any(f in tytul.lower() for f in FRAZY_NIE_FIRMA) or LISTICLE.search(tytul):
            tytul = dom
        firmy.append({"nazwa": tytul[:60], "url": strona, "opis": opis,
                      "ma_seo": ma_sygnal_seo(tytul, opis)})
    return firmy[:limit]


# ══════════════════════════════════════════════════════════════════════
#  CSV — zwykła funkcja. Plik leci do POBRANIA w przeglądarce,
#  NIE zapisujemy na serwerze (dysk Render jest efemeryczny).
# ══════════════════════════════════════════════════════════════════════
# ⚠️ Nazwy kolumn do potwierdzenia z importem Pipedrive (otwarte pytanie w DECISIONS).
KOLUMNY = [
    ("Organization", "nazwa"),
    ("Website", "url"),
    ("Nazwa prawna", "nazwa_prawna"),
    ("NIP", "nip"),
    ("KRS", "krs"),
    ("REGON", "regon"),
    ("PKD", "pkd"),
    ("Address", "adres"),
    ("City", "miasto"),
    ("Branza", "branza"),
    ("Uslugi", "uslugi"),
    ("Wielkosc zespolu", "wielkosc_zespolu"),
    ("Liczba projektow", "liczba_projektow"),
    ("Case studies", "case_studies"),
    ("Phone", "telefon"),
    ("Email", "email"),
    ("Person name", "persona_imie"),
    ("Person position", "persona_stanowisko"),
    ("Person email", "persona_email"),
    ("Person phone", "persona_telefon"),
    ("Ma SEO w ofercie", "ma_seo"),
    ("Zakres SEO", "seo_zakres"),
]


def zbuduj_csv(firmy: list[dict]) -> str:
    bufor = io.StringIO()
    writer = csv.writer(bufor, delimiter=";")
    writer.writerow([naglowek for naglowek, _ in KOLUMNY])
    for f in firmy:
        wiersz = []
        for _, klucz in KOLUMNY:
            v = f.get(klucz, BRAK)
            if isinstance(v, list):
                v = ", ".join(v) if v else BRAK
            elif isinstance(v, bool):
                v = "TAK" if v else "NIE"
            wiersz.append(v)
        writer.writerow(wiersz)
    return bufor.getvalue()


def baza_maili() -> str:
    """Baza wiedzy mailingu — plik .md czytany na bieżąco (edycja = lepsze maile bez zmian w kodzie)."""
    plik = DOCS / "email-examples.md"
    return plik.read_text(encoding="utf-8") if plik.exists() else ""


# ══════════════════════════════════════════════════════════════════════
#  AGENCI LLM
# ══════════════════════════════════════════════════════════════════════
EKSTRAKCJA_PROMPT = f"""Jesteś analitykiem researchu partnerskiego Last Agency (SEO/SEM/GEO/AI Search).
Dostajesz TEKST ze strony firmy (strona główna + podstrony). Wyciągnij z niego dane o firmie.

ŻELAZNA ZASADA — NIE ZMYŚLAJ:
Jeśli czegoś NIE MA w tekście, wpisz dokładnie "{BRAK}". Nigdy nie zgaduj telefonu, maila,
liczby osób ani realizacji. Uczciwy brak jest lepszy niż wymyślona wartość.

CO WYCIĄGNĄĆ:
- nazwa: nazwa firmy
- branza: czym się zajmuje (np. "agencja e-commerce", "software house", "branding")
- uslugi: nazwy usług PRZEPISANE DOSŁOWNIE z menu usług / sekcji oferty.
  Nie streszczaj ich, nie uogólniaj i nie tłumacz na własne słowa. Jeśli w menu
  stoi "Integracje PrestaShop", masz napisać "Integracje PrestaShop" — a NIE
  "Integracje E-commerce". Nazwa usługi niesie informację o tym, na czym firma
  pracuje; usunięcie z niej platformy albo technologii zamienia wyspecjalizowaną
  agencję w generyczną i psuje cały dalszy obraz firmy.
  Bierz TYLKO pozycje z menu usług / oferty. Linki obecne wyłącznie w stopce
  (patrz reguła o landingach niżej) NIE są usługami z oferty.
- wielkosc_zespolu: liczba osób, jeśli podana (np. "20+ specjalistów")
- liczba_projektow: liczba wdrożeń/projektów/klientów, jeśli podana
- case_studies: nazwy klientów lub realizacji wymienione na stronie
- telefon / email: OGÓLNY kontakt firmowy, TYLKO jeśli faktycznie jest w tekście
- opis: 2-3 zdania, czym firma się zajmuje

DANE SPÓŁKI (zwykle w stopce lub na podstronie "kontakt"):
- nazwa_prawna: pełna nazwa prawna, np. "Grupa Maciaszczyk spółka jawna", "X sp. z o.o."
- nip: numer NIP (same cyfry, mogą być ze spacjami/myślnikami jak na stronie)
- adres: ulica + kod pocztowy, np. "ul. Łazienna 4, 61-857"
- miasto

OSOBA DECYZYJNA (persona_*) — to ma być KONKRETNY CZŁOWIEK do kontaktu, nie opis profilu firmy:
- persona_imie: imię i nazwisko osoby decyzyjnej wymienionej na stronie
- persona_stanowisko: jej rola, np. CEO, właściciel, founder, prezes, dyrektor zarządzający
- persona_email / persona_telefon: JEJ bezpośredni kontakt, jeśli podany obok nazwiska
  (jeśli na stronie jest tylko ogólny kontakt firmowy, wpisz tu "{BRAK}")
Kogo wybrać: osobę NAJWYŻEJ w hierarchii (właściciel/CEO/founder przed managerem).
Szukaj w sekcjach "o nas", "zespół", "kontakt". Jeśli nikt nie jest wymieniony z nazwiska
— wszystkie pola persona_* to "{BRAK}". NIE zgaduj i NIE wymyślaj nazwisk.

NUMERY REJESTROWE. Blok „[DANE REJESTROWE ZE STRON PRAWNYCH]" na końcu tekstu
pochodzi z regulaminu albo polityki prywatności firmy. Jeśli tam są NIP, KRS lub REGON,
przepisz je do odpowiednich pól — to źródło pewniejsze niż stopka strony.
KRS to dokładnie 10 cyfr. Gdy któregoś numeru nie ma, wpisz "{BRAK}".

SEO W OFERCIE — ustalasz FAKT, nie wydajesz osądu.

ma_seo = true TYLKO wtedy, gdy firma PROWADZI KLIENTOM KAMPANIE SEO — czyli sprzedaje
pozycjonowanie jako ciągłą usługę, w której odpowiada za wzrost widoczności w czasie.

ma_seo = false we WSZYSTKICH pozostałych przypadkach, a zwłaszcza gdy firma robi
jednorazowe albo techniczne rzeczy wokół SEO:
- audyt SEO,
- "optymalizacja SEO" strony lub sklepu,
- techniczne SEO przy wdrożeniu,
- SEO copywriting, teksty pod SEO,
- "strona zoptymalizowana pod SEO" jako cecha tego, co sprzedają,
- wpis na blogu o SEO albo słowo "SEO" w stopce czy w tagach.

To NIE są kampanie SEO. Firma robiąca audyt albo optymalizację przy wdrożeniu ma
ma_seo = false, choćby słowo "SEO" padało na stronie kilkanaście razy.

Google Ads, Meta Ads i inne kampanie płatne to NIE jest SEO — same z siebie nigdy
nie dają ma_seo = true.

GDZIE USŁUGA JEST OPISANA, MA ZNACZENIE — to rozstrzyga najczęstszą pomyłkę.
Oferta firmy to jej MENU USŁUG. Osobna strona pod frazę ("Pozycjonowanie Kalisz",
"SEO Wrocław"), linkowana tylko ze stopki albo z sitemapy i NIEOBECNA w menu usług,
to landing pod lokalne wyszukiwanie, a nie pozycja w ofercie. Taka strona potrafi
opisywać pełen proces — audyt, link building, comiesięczne raporty — i mimo to
nie znaczyć, że firma tę usługę sprzedaje.

Gdy zachodzi taka rozbieżność: menu usług wygrywa, ma_seo = false, a w seo_zakres
napisz WPROST, że strona pozycjonowania istnieje, ale nie ma jej w menu usług.
Człowiek ma zobaczyć rozbieżność, a nie sam werdykt.

W seo_zakres napisz KRÓTKO, co dokładnie firma robi w obszarze SEO i skąd to wiadomo
— po to, żeby człowiek mógł sprawdzić Twój wniosek. Gdy ma_seo = false, ale coś
około-SEO w ofercie jest (audyt, optymalizacja), napisz co, zamiast "{BRAK}".

KATEGORIA — przypisz firmę do DOKŁADNIE JEDNEJ z poniższych. Przepisz nazwę
znak w znak, bez zmieniania wielkości liter i bez własnych wariantów:
- Budowa stron i sklepów
- Utrzymanie i administracja
- Strategia i doradztwo
- Branding i kreacja
- Marketing poza SEO
- Sprzedaż i marketplace
- Technologia, integracje i resellerzy
- AI i automatyzacja
- Wiedza i usługi prawne
- Sieci i społeczności biznesowe

Wybierz po tym, co jest RDZENIEM oferty, a nie po tym, co firma robi przy okazji.
Agencja budująca sklepy, która ma też branding wśród usług, idzie do "Budowa stron
i sklepów". Agencja brandingowa robiąca strony klientom idzie do "Branding i kreacja".

Gdy firma naprawdę nie pasuje do żadnej — wpisz "{BRAK}". Nie naciągaj.

NIE orzekaj, czy firma jest konkurentem ani czy jest dobrym partnerem. Ta sama agencja
z SEO w ofercie bywa jednym i drugim, zależnie od tego, po co do niej piszemy.
Dostarczasz fakty — decyduje człowiek."""

# Ekstrakcja stoi na Sonnecie, mimo że formalnie jest „wyciąganiem pól". Powód:
# te 22 pola są fundamentem wszystkiego dalej — karty, maila, kategorii, kolejki.
# Błąd tutaj nie zostaje tutaj, tylko rozchodzi się po całym narzędziu.
# Przy okazji: sam prompt ma ~1570 tokenów, więc mieści się w progu cache Sonneta
# (1024). Na Haiku próg wynosi 2048 i cache by się nie włączył.
zadanie_ekstrakcja = claude.Zadanie(
    nazwa="ekstrakcja",
    staly=EKSTRAKCJA_PROMPT,     # blok stały — to on idzie do cache
    instrukcje="",
    schemat=Firma,
    model=MOCNY,
)

zadanie_zapytanie = claude.Zadanie(
    nazwa="zapytanie",
    model=TANI,
    max_tokenow=200,
    instrukcje="""Dostajesz branżę i kilka usług firmy. Napisz JEDNO zapytanie do wyszukiwarki,
które znajdzie inne firmy TEGO SAMEGO typu w Polsce.

ZASADY (twarde):
- MAKSYMALNIE 5 słów. Krótkie zapytanie = trafne wyniki. Długie = śmieci.
- Opisz TYP FIRMY, nie listę jej usług. Dobrze: "agencja brandingowa Polska".
  Źle: "agencja kreatywna branding design naming logo identyfikacja wizualna strony".
- NIGDY nie dodawaj miasta ani regionu, jeśli nie dostałeś go wprost w danych.
- Nie DODAWAJ od siebie słów: SEO, SEM, pozycjonowanie, Google Ads, marketing —
  szukamy partnerów, nie agencji marketingowych. WYJĄTEK: jeśli użytkownik wskazał
  taką usługę wprost, uszanuj jego wybór i zbuduj zapytanie wokół niej.
- NIGDY fraz typu "ranking", "top 10", "najlepsze firmy".
- Jeśli dostajesz USŁUGI WSKAZANE PRZEZ UŻYTKOWNIKA — to one mają być rdzeniem zapytania.
  Możesz je przeformułować na naturalną frazę wyszukiwarki, ale nie zmieniaj tematu.

Zwróć TYLKO samo zapytanie, bez cudzysłowów i komentarza.""",
)


class WariantyZapytan(BaseModel):
    zapytania: list[str]


zadanie_warianty = claude.Zadanie(
    nazwa="warianty",
    model=TANI,
    schemat=WariantyZapytan,
    max_tokenow=400,
    instrukcje="""Dostajesz typ firmy. Wygeneruj 4 RÓŻNE frazy branżowe, po których
da się znaleźć takie firmy.

CEL: dotrzeć do firm, które NIE są w TOP10 na najbardziej oczywistą frazę. Jedno zapytanie
zwraca wciąż tych samych liderów rynku; cztery różne wyciągają mniejsze, słabiej
wypozycjonowane firmy — a to one są najciekawsze jako partnerzy.

ZASADY:
- Każda fraza MAKSYMALNIE 4 słowa.
- Warianty muszą się REALNIE różnić. Użyj kolejno:
  (1) nazwy branży, (2) synonimu / innej nazwy tej samej branży,
  (3) KONKRETNEJ USŁUGI, którą taka firma świadczy, (4) innej konkretnej usługi.
- ŻADNEJ lokalizacji: bez miasta, województwa, kraju, "Polska", "w Polsce".
  Miejsce dokleja program po Twojej stronie — Twoim zadaniem jest wyłącznie branża.
- NIGDY fraz typu "ranking", "top 10", "najlepsze", "opinie", "cennik".
- Nie dodawaj od siebie SEO/SEM/marketing, chyba że to wprost wskazana branża.

Zwróć DOKŁADNIE 4 osobne pozycje na liście. Każda to jedna fraza — nie sklejaj
kilku w jeden ciąg, nie używaj znaku "|" ani przecinków między wariantami.

Przykład dla "agencja brandingowa" — cztery odrębne pozycje:
  1. agencja brandingowa
  2. studio brandingowe
  3. projektowanie identyfikacji wizualnej
  4. tworzenie logo marki""",
)


class Prompty(BaseModel):
    pytania: list[str]


# ChatGPT pytany BEZPOŚREDNIO, naszym kluczem OpenAI — bez DataForSEO po drodze.
# Powód nie jest kosztowy, tylko taki: sekcja z pytaniami klientów to nasza jedyna
# przewaga nad audytami konkurencji, a szła przez dostawcę, który potrafi zawiesić
# konto albo wyczerpać saldo i zabrać ją razem z resztą raportu. Od czasu, gdy
# DataForSEO został jedynym dostawcą danych SEO, ma to jeszcze większe znaczenie:
# to JEDYNA sekcja audytu, która przeżyje jego awarię albo puste saldo.
# ⚠ TEN JEDEN AGENT ZOSTAJE NA OPENAI. Nie przenoś go na Claude „dla spójności".
#
# Wszystkie pozostałe agenty WYKONUJĄ pracę — model jest dla nich narzędziem
# i wymiana narzędzia zmienia jakość wyniku. Ten jeden jest BADANYM OBIEKTEM:
# udaje asystenta, któremu klient partnera zadaje pytanie, a my sprawdzamy, czy
# w odpowiedzi padnie nazwa badanej firmy. Cała sekcja GEO audytu mierzy właśnie to.
#
# Klienci pytają ChatGPT. Gdyby tu stanął Claude, raport nadal pokazywałby liczby
# i nadal wyglądałby poprawnie — tyle że mówiłby „nie widać Cię w Claude" zamiast
# „nie widać Cię w ChatGPT". Ten sam kształt, inne znaczenie; dokładnie ta klasa
# błędu, którą w tym projekcie łapiemy najczęściej.
agent_pytajacy = Agent(
    name="pytajacy",
    instructions=(
        "Odpowiadasz jak asystent wyszukiwarki na pytanie polskiego klienta. "
        "Szukaj w sieci i podaj konkretne firmy z nazwy, jeśli pytanie ich dotyczy. "
        "Pisz po polsku, rzeczowo, bez wstępów."
    ),
    tools=[WebSearchTool(search_context_size="medium")],
    model=MODEL_POMIARU_GEO,
)


async def zapytaj_chatgpt_wprost(pytanie: str) -> dict:
    """Zwraca kształt zgodny z audyt.analizuj_odpowiedz — treść i cytowane URL-e."""
    wynik = await Runner.run(agent_pytajacy, pytanie)
    zrodla = []
    for item in wynik.new_items:
        surowy = getattr(item, "raw_item", None)
        for tresc in (getattr(surowy, "content", None) or []):
            for ad in (getattr(tresc, "annotations", None) or []):
                url = getattr(ad, "url", None)
                if url:
                    zrodla.append(url)
    return {"tekst": str(wynik.final_output or ""), "zrodla": zrodla}


class MarkiWOdpowiedziach(BaseModel):
    marki_per_odpowiedz: list[list[str]]


# Wyciąganie marek po **pogrubieniu** nie działa: model pogrubia też zwykłe frazy
# („Certyfikacja PrestaShop", „Doświadczenie"), a prawdziwe nazwy firm bywają
# w zwykłym tekście. Rozpoznanie nazwy własnej wymaga rozumienia języka — czyli LLM.
zadanie_marki = claude.Zadanie(
    nazwa="marki",
    model=TANI,                  # rozpoznawanie nazw własnych — klasyfikacja, nie generowanie
    schemat=MarkiWOdpowiedziach,
    instrukcje="""Dostajesz ponumerowane odpowiedzi AI. Dla KAŻDEJ wypisz nazwy FIRM,
które w niej wystąpiły jako polecani/wymieniani dostawcy usług.

ZASADY:
- TYLKO nazwy własne firm (np. „Waynet", „Convertis", „Astrabit").
- NIE wypisuj: nazw usług, certyfikatów, platform (PrestaShop, Shopify, WordPress),
  miast, ogólnych fraz („Doświadczenie", „Certyfikacja", „Expert").
- Jeśli w odpowiedzi nie ma żadnej firmy — pusta lista dla tej pozycji.
- Zachowaj kolejność: lista wyników musi mieć tyle pozycji, ile dostałeś odpowiedzi.""",
)


zadanie_prompty = claude.Zadanie(
    nazwa="prompty-audyt",
    model=TANI,
    schemat=Prompty,
    max_tokenow=800,
    instrukcje=audyt.PROMPT_GENERATORA.format(ile="{ile}").replace("{ile}", "5"),
)


MAIL_SYSTEM = """Jesteś partnership managerem w Last Agency — agencji SEO/GEO/SEM.
Piszesz krótkiego, spersonalizowanego maila z propozycją współpracy partnerskiej.

KONTEKST:
- Klienci Last Agency pytają o usługi, których MY NIE świadczymy — takie, jakie ma odbiorca.
- Chcemy kierować takich klientów do zaufanych partnerów.
- Jednocześnie klienci odbiorcy mogą potrzebować SEO/GEO/SEM, które pokrywa Last Agency.
- Cel maila: umówić krótką rozmowę o potencjale partnerskim.
- To propozycja partnerstwa MIĘDZY RÓWNYMI STRONAMI, nie oferta sprzedażowa.

Mail oprzyj na danych firmy z researchu — nawiąż KONKRETNIE do tego, czym się zajmuje
(nazwij ich usługi), żeby mail nie był generyczny. Nie zmyślaj: jeśli czegoś nie ma
w danych, nie wspominaj o tym.

Trzymaj się struktury, zasad i przykładów z bazy wiedzy mailingu, którą dostajesz.
Szczególnie sekcji „Czego NIE robić".

Zwróć SAM MAIL (temat w pierwszej linii + treść), bez komentarzy i wyjaśnień."""

# Style muszą się REALNIE różnić — inaczej dostajemy 3 warianty tego samego maila.
# Dlatego każdy ma narzuconą inną długość, inne otwarcie i inne CTA.
STYLE_MAILI = [
    ("rzeczowy",
     "Rzeczowo i konkretnie, jak zabiegany decydent. MAKSYMALNIE 4 zdania w całym mailu. "
     "Zero ozdobników. Otwarcie: od razu po co piszesz. CTA: konkretna propozycja terminu "
     "(np. 'wtorek albo środa, 15 minut?'). Zwracaj się per 'Dzień dobry'."),
    ("partnerski",
     "Ciepło i partnersko, ton nieformalny, na 'Cześć'. Otwarcie: od wspólnego mianownika — "
     "obsługujemy podobnych klientów, tylko z dwóch różnych stron. Możesz użyć jednego pytania "
     "retorycznego. CTA: luźne zaproszenie do rozmowy, bez narzucania terminu."),
    ("ekspercki",
     "Ekspercko — pokazujesz, że rozumiesz ICH model biznesowy. Otwarcie: konkretny insight "
     "branżowy (np. co dzieje się z ich klientem PO zakończeniu ich projektu i czego wtedy "
     "potrzebuje). Nazwij mechanizm współpracy (referral / white-label). CTA: propozycja "
     "rozmowy o modelu współpracy."),
]

# Poprawianie gotowego maila. Osobny agent, bo zadanie jest inne niz pisanie od zera:
# dostaje TEKST, który ma zachować, i jedno polecenie. Agent od pisania dostałby tu
# dane firmy i zaczął od nowa — a user chce poprawki, nie nowego maila.
# ══════════════════════════════════════════════════════════════════════
#  CZAT DO POGŁĘBIENIA RESEARCHU
# ══════════════════════════════════════════════════════════════════════
# Research jest jednorazowy: odwiedza 4-5 podstron i tnie do 12 tys. znaków.
# Pytanie „czy oni robią B2B?" zwykle NIE MA odpowiedzi w tym, co zebraliśmy —
# czat nad samą kartą firmy odpowiadałby „nie wiem" na większość sensownych pytań.
#
# Dlatego agent dostaje narzędzie do dociągania podstron W TRAKCIE rozmowy.
# Odpowiedź pochodzi wtedy ze strony firmy, a nie z tego, co model pamięta
# o branży — i da się pokazać, skąd.

# Domena badanej firmy. Ustawiana przed każdą rozmową, czytana przez narzędzie.
# Prosta zmienna wystarcza: serwer obsługuje jednego użytkownika, a rozmowa jest
# jednym żądaniem — nie ma dwóch czatów naraz.
_czat_domena = ""


def otworz_podstrone(adres: str) -> str:
    """Pobiera treść podstrony z serwisu badanej firmy."""
    if not _czat_domena:
        return "Brak kontekstu firmy."
    pelny = adres if adres.lower().startswith("http") else urljoin("https://" + _czat_domena, adres)
    # TWARDE ograniczenie do domeny firmy. Bez tego narzędzie staje się otwartym
    # proxy: model mógłby na życzenie pobrać dowolny adres w internecie, a żądanie
    # wyszłoby z naszego serwera i z naszego IP.
    if domena_z_url(pelny) != _czat_domena:
        return f"Odmowa: {pelny} jest poza domeną {_czat_domena}."
    html = pobierz(pelny)
    if not html:
        return f"Nie udało się pobrać {pelny} (blokada bota albo strona nie istnieje)."
    return f"[TREŚĆ {pelny}]" + _NOWA_LINIA + tekst_ze_strony(html)[:6000]


# ── Instrukcja synergii, w dwóch różnych zakresach ────────────────────
# synergie.md to szablon FORMATU WYJŚCIA, nie wiedza o firmie. Wklejony bez
# zastrzeżenia zamienia każdą odpowiedź w rozpisaną listę — także odpowiedź na
# „czy obsługują B2B?". Dlatego oba miejsca dostają go z własnym ograniczeniem.

# Kotwica na głównym profilu — wspólna dla obu zastosowań.
#
# Research zwraca listę usług, która przy każdej agencji jest długa: wdrożenia, UX,
# integracje, audyty, hosting, szkolenia. Model, który czyta ją jak równą listę,
# potrafi z agencji PrestaShop zrobić „software house" albo „firmę od audytów" —
# i cała synergia buduje się wtedy na czymś, czym partner się nie czuje. Na spotkaniu
# to widać natychmiast: rozmówca prostuje pierwsze zdanie i reszta traci wagę.
#
# Dlatego rozstrzyga branża i kategoria z researchu, a nie najdłuższa lista usług.
KOTWICA_PROFILU = (
    "ZACZNIJ OD GŁÓWNEGO PROFILU FIRMY." + _NOWA_LINIA +
    "Rozstrzyga pole `branza` i `kategoria` z researchu — to jest to, czym firma JEST "
    "i za co bierze pieniądze. Lista usług opisuje, co przy tym jeszcze robi, i nie "
    "może przykryć głównego profilu." + _NOWA_LINIA +
    "Przykład: agencja PrestaShop, która ma w usługach integracje i audyty, dalej jest "
    "agencją PrestaShop — NIE software housem i NIE firmą audytową. Synergia ma się "
    "opierać na tym, czym są, nie na najdłuższej pozycji z listy usług." + _NOWA_LINIA +
    "Gdy usługa poboczna jest naprawdę istotna dla współpracy, nazwij ją jako poboczną, "
    "zamiast przesuwać na nią cały opis partnera.")


# Czat: pełny format, ale WYŁĄCZNIE na żądanie. Rozmowa ma zostać rozmową.
CZAT_SYNERGIE = (
    "PONIŻSZA INSTRUKCJA OBOWIĄZUJE TYLKO WTEDY, gdy user prosi o synergie, "
    "powody do współpracy albo materiał na spotkanie. Przy każdym innym pytaniu "
    "ZIGNORUJ ten format i odpowiadaj normalnie, zwięźle." + _NOWA_LINIA * 2
    + KOTWICA_PROFILU + _NOWA_LINIA * 2 + profil.synergie())

# Mail: bierzemy SPOSÓB MYŚLENIA, nie format. Mail ma mieć kilka zdań i jeden
# konkret — rozpisana tabelka synergii w pierwszym kontakcie to ulotka, nie list.
MAIL_SYNERGIE = (
    "JAK SZUKAĆ POWODU DO WSPÓŁPRACY — instrukcja analityczna. Zastosuj sposób "
    "myślenia opisany niżej: rozpoznaj kanał (white-label czy referral), szukaj "
    "komplementarności zamiast dublowania, nazwij korzyść dla KLIENTA partnera." + _NOWA_LINIA +
    "ALE NIE PRZENOŚ TEGO FORMATU DO MAILA. Nie wypisuj listy synergii, nagłówków "
    "ani punktów „Wpływ na wyniki”. Z całej analizy wybierz JEDEN najmocniejszy "
    "powód i napisz go zwykłym zdaniem." + _NOWA_LINIA * 2
    + KOTWICA_PROFILU + _NOWA_LINIA * 2 + profil.synergie())


# Opis narzędzia dla modelu. Schemat piszemy wprost, zamiast wyprowadzać go
# z sygnatury funkcji — dzięki temu widać w jednym miejscu dokładnie to, co dostaje
# model, i nie trzeba zgadywać, jak dekorator przetłumaczył docstring.
NARZEDZIE_PODSTRONA = {
    "name": "otworz_podstrone",
    "description": ("Pobiera treść podstrony z serwisu badanej firmy. "
                    "Działa WYŁĄCZNIE w obrębie jej domeny."),
    "input_schema": {
        "type": "object",
        "properties": {
            "adres": {
                "type": "string",
                "description": 'Ścieżka albo pełny URL, np. "/oferta".',
            }
        },
        "required": ["adres"],
    },
    "wykonaj": otworz_podstrone,
}


# Czat dostaje profil Last Agency jako blok stały — ten sam, którego używają maile.
#
# Bez niego agent nie wiedział, dla kogo pracuje: na pytanie o synergię odpowiadał
# „nie mam dostępu do lastagency.pl, podaj czym się zajmujecie". Formalnie uczciwe,
# praktycznie bezużyteczne — user musiał przepisywać własną ofertę do okienka,
# żeby dostać odpowiedź o własnej firmie.
#
# Rozdział źródeł jest twardy: o BADANEJ firmie agent wie tylko to, co przeczyta na
# jej stronie; o NAS — tylko z profilu. Narzędzie i tak nie wpuści go poza domenę
# badanej firmy, więc naszej strony nie odwiedzi nawet gdyby chciał.
zadanie_czat = claude.Zadanie(
    nazwa="czat-research",
    model=MOCNY,
    narzedzia=[NARZEDZIE_PODSTRONA],
    staly=profil.pelny() + _NOWA_LINIA * 2 + CZAT_SYNERGIE,
    instrukcje=(
        "Odpowiadasz na pytania o KONKRETNĄ firmę, na podstawie jej strony." + _NOWA_LINIA +
        "Masz dane z researchu oraz narzędzie otworz_podstrone do dociągania podstron."
        + _NOWA_LINIA + _NOWA_LINIA +
        "DWA ŹRÓDŁA, NIE MIESZAJ ICH:" + _NOWA_LINIA +
        "- O BADANEJ firmie wiesz tylko to, co przeczytasz na jej stronie." + _NOWA_LINIA +
        "- O LAST AGENCY (czyli o nas) wiesz z profilu powyżej — i to jest pełna "
        "wiedza, jaką masz. Pytania o synergię, sens współpracy czy dopasowanie "
        "partnera odpowiadasz zestawiając profil z tym, co wiesz o badanej firmie. "
        "Nie proś użytkownika, żeby opisał Ci własną agencję." + _NOWA_LINIA +
        "- Rozpisany format synergii stosujesz TYLKO wtedy, gdy user o nie poprosi. "
        "Na zwykłe pytanie o firmę odpowiadasz zwyczajnie, dwoma zdaniami." + _NOWA_LINIA +
        _NOWA_LINIA +
        "ZASADY:" + _NOWA_LINIA +
        "- Gdy odpowiedzi nie ma w danych z researchu, SPRÓBUJ otworzyć podstronę, "
        "która może ją mieć (/oferta, /uslugi, /b2b, /cennik, /realizacje, /kontakt)." + _NOWA_LINIA +
        "- Odpowiadaj TYLKO na podstawie tego, co przeczytałeś. Nie uzupełniaj "
        "wiedzą o branży ani domysłami o tym, jak zwykle bywa." + _NOWA_LINIA +
        "- Gdy po sprawdzeniu nadal nie wiesz, napisz wprost: czego szukałeś, gdzie, "
        "i że tego nie ma. To jest pełnoprawna odpowiedź, nie porażka." + _NOWA_LINIA +
        "- Podaj, z której podstrony pochodzi odpowiedź." + _NOWA_LINIA +
        "- Pisz zwiezle i po polsku. Bez wstepow w rodzaju: oczywiscie, sprawdze."
    ),
)


zadanie_poprawka = claude.Zadanie(
    nazwa="poprawka-maila",
    model=MOCNY,                 # poprawiany tekst idzie do partnera — bez oszczędzania
    instrukcje=(
        "Poprawiasz GOTOWY mail sprzedażowy według polecenia użytkownika." + _NOWA_LINIA +
        "ZASADY:" + _NOWA_LINIA +
        "- Zmieniaj TYLKO to, o co prosi user. Reszta zostaje słowo w słowo." + _NOWA_LINIA +
        "- Nie dopisuj faktów o firmie, których nie ma w tekście. Gdy polecenie "
        "wymaga informacji, której nie masz, napisz mail bez niej zamiast zmyślać." + _NOWA_LINIA +
        "- Zachowaj język i formę zwracania się, chyba że polecenie mówi inaczej." + _NOWA_LINIA +
        "- Zwróć SAM mail: bez komentarza, bez wstępu, bez wyjaśnień co zmieniłeś."
    ),
)


# Blok stały maili: profil Last Agency + zasady pisania. IDENTYCZNY dla wszystkich
# trzech stylów — i to jest warunek, żeby cache miał sens. Styl jest zmienny, więc
# trafia do `instrukcje`, czyli ZA blok cache'owany. Gdyby styl wszedł do prefiksu,
# każdy z trzech maili unieważniałby cache poprzedniego.
MAIL_STALY = (profil.pelny() + _NOWA_LINIA * 2 + MAIL_SYNERGIE
              + _NOWA_LINIA * 2 + MAIL_SYSTEM)
if not profil.istnieje():
    # Bez profilu narzędzie ma działać dalej, tylko bez wiedzy o nas — ale model musi
    # o tym WIEDZIEĆ. Inaczej uzupełni lukę tym, co brzmi wiarygodnie, a wymyślona
    # prowizja albo zmyślony zakres usług w pierwszym mailu do partnera to nie
    # literówka, tylko wpadka przy pierwszym kontakcie.
    MAIL_STALY += (_NOWA_LINIA * 2 +
                   "UWAGA: brakuje profilu Last Agency. NIE opisuj naszej oferty, "
                   "warunków współpracy ani prowizji — nie znasz ich. Napisz mail "
                   "oparty wyłącznie na tym, co wiesz o odbiorcy.")

zadania_mail = [
    claude.Zadanie(nazwa=f"mail-{nazwa}", model=MOCNY,
                   staly=MAIL_STALY, instrukcje=f"STYL: {opis}")
    for nazwa, opis in STYLE_MAILI
]


def stan_cache() -> list[dict]:
    """Czy bloki stałe naprawdę przekraczają próg cache — prawdziwym pomiarem,
    nie szacunkiem. Odpalaj po każdej zmianie profilu:

        python -c "import app; print(app.stan_cache())"

    Cache poniżej progu nie zgłasza błędu, tylko po cichu nie działa, więc jedynym
    sposobem, żeby się o tym dowiedzieć, jest sprawdzić."""
    return claude.sprawdz_cache([zadanie_ekstrakcja, zadanie_czat] + zadania_mail)


# ══════════════════════════════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════════════════════════════
def pusty_research(f: dict) -> bool:
    """Czy research praktycznie nic nie przyniósł — strona zablokowała bota albo padła.

    To NIE jest ocena jakości firmy. Firma może być mała i mieć jedną usługę;
    tu chodzi o zbieg trzech rzeczy naraz: nieustalona branża, najwyżej jedna
    usługa i najwyżej jedna odwiedzona podstrona. Tak wygląda pobranie, które
    zwróciło samą stronę powitalną albo komunikat blokady.
    """
    return ((f.get("branza") or BRAK) == BRAK
            and len(f.get("uslugi") or []) <= 1
            and len(f.get("zrodlo_danych") or []) <= 1)


async def api_research(request):
    """Funkcja 1 — research firmy po URL."""
    try:
        body = await request.json()
        url = (body.get("url") or "").strip()
        if not url:
            return JSONResponse({"ok": False, "error": "Brak URL"})
        # .lower() w warunku jest konieczne: adres wklejony jako "HTTPS://..." nie zaczyna
        # się od "http" i dostawał drugi przedrostek ("https://HTTPS://...").
        if not url.lower().startswith("http"):
            url = "https://" + url
        # Nazwa hosta na małe litery. Adres wpisany ręcznie zachowywał wielkość liter
        # (autouzupełnianie przeglądarki lubi zaczynać od wielkiej), a adresy z wyszukiwarki
        # przechodzą przez normalizuj_url() i są małymi — ta sama firma potrafiła więc trafić
        # do aplikacji dwa razy, a DataForSEO zwracał dla niej 0 wyników (dopasowuje domenę
        # wrażliwie na wielkość liter). Ścieżki NIE ruszamy — bywa wrażliwa na wielkość liter.
        _u = urlparse(url)
        url = _u._replace(scheme=_u.scheme.lower(), netloc=_u.netloc.lower()).geturl()

        # Adres sprowadzony do postaci KANONICZNEJ: https://domena, bez www i bez
        # ścieżki. To ten sam kształt, jaki produkuje normalizuj_url dla wyników
        # wyszukiwania — bez tego "tebim.pro" i "www.tebim.pro/" to dla bazy dwie
        # różne firmy, bo url jest kluczem głównym. Tak właśnie powstał duplikat
        # Tebima 07.09. Scraper i tak sam znajduje podstrony, więc nic nie tracimy.
        _kanon = domena_z_url(url)
        if _kanon:
            url = "https://" + _kanon

        tekst, odwiedzone = scrape_firme(url)
        if not tekst:
            return JSONResponse({
                "ok": False,
                "error": "Nie udało się pobrać strony (blokada bota lub strona nieosiągalna).",
            })

        wynik = await claude.uruchom(zadanie_ekstrakcja, f"URL: {url}\n\nTEKST ZE STRONY:\n{tekst}")
        firma = wynik.final_output.model_dump()
        firma["url"] = url
        firma["zrodlo_danych"] = odwiedzone
        # ścieżka, w której firma została zbadana — „Praca" rozdziela po niej listy
        # Oficjalny odpis z KRS, jeśli udało się wyłuskać numer ze stron prawnych.
        # UZUPEŁNIAMY tylko braki — danych, które scraper zdobył, nie nadpisujemy
        # po cichu. Rejestr bywa wprawdzie dokładniejszy, ale ciche podmienianie
        # tego, co user widział na karcie, to dokładnie ta klasa błędu, na której
        # przejechaliśmy się już przy ma_seo.
        firma["zrodlo_krs"] = ""
        numer = krs_api.poprawny_numer(firma.get("krs") or "")
        if numer:
            try:
                o = await asyncio.to_thread(krs_api.odpis, numer)
            except krs_api.BladKRS as e:
                o = None
                print(f"[krs] {numer}: {e}")
            if o:
                uzupelnione = []
                for pole in ("nazwa_prawna", "nip", "regon", "adres", "miasto"):
                    obecne = (firma.get(pole) or BRAK).strip()
                    if obecne in ("", BRAK) and o.get(pole):
                        firma[pole] = o[pole]
                        uzupelnione.append(pole)
                firma["krs"] = o["krs"]
                if o.get("pkd"):
                    firma["pkd"] = o["pkd"]
                firma["zrodlo_krs"] = (
                    f"KRS {o['krs']}, wpis {o['data_rejestracji']}"
                    + (f" — uzupełniono: {', '.join(uzupelnione)}" if uzupelnione
                       else " — dane ze strony były kompletne"))

        firma["tryb"] = (body.get("tryb") or "partner").lower()

        # Nieudany research NIE MOŻE nadpisać dobrego rekordu. Brantt.pl miał
        # 83 usługi i pełną kartę; przy ponownym badaniu strona nas zablokowała
        # i wróciło „nie do ustalenia" z jedną usługą — co skasowało wszystko,
        # bez żadnego błędu. Odkryte dopiero przy oglądaniu wyników.
        stara = next((x for x in baza.firmy() if x.get("url") == url), None)
        if stara and pusty_research(firma) and not pusty_research(stara):
            return JSONResponse({
                "ok": False,
                "error": ("Strona nie oddała treści (prawdopodobnie blokuje bota). "
                          "Zachowałem poprzednie dane tej firmy — spróbuj ponownie później."),
            })

        baza.zapisz_firme(firma, firma["tryb"])
        # Zbadana firma znika z kolejki — kolejka pokazuje robotę DO zrobienia.
        baza.usun_z_kolejki(url)
        return JSONResponse({"ok": True, "firma": firma})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def znajdz_firmy(zapytanie: str, wlasna_domena: str = "",
                       pomin: set | None = None, ile: int = 15) -> dict:
    """Jedno zapytanie -> Tavily -> filtr -> kontrola żywotności.

    Ze SKRACANIEM AWARYJNYM. Zmierzone: „agencja PrestaShop e-commerce" zwraca
    z Tavily ZERO wyników, a „agencja PrestaShop" — piętnaście. Jedno słowo za
    dużo i wyszukiwarka milknie. Model układa frazę za każdym razem inaczej, więc
    funkcja działała losowo: raz jedenaście firm, raz pusto, przy tej samej firmie
    wzorcowej.

    Zamiast próbować wymusić na modelu krótsze frazy — co i tak byłoby prośbą,
    nie gwarancją — obcinamy ostatnie słowo i pytamy ponownie. Zwracamy frazę,
    która NAPRAWDĘ zadziałała, bo pokazanie userowi zapytania bez wyników byłoby
    wprowadzaniem w błąd.
    """
    slowa = zapytanie.split()
    uzyte, wynik = zapytanie, None
    # Sprawdzamy wynik KOŃCOWY, nie surowy. Tavily potrafi oddać dziesięć pozycji,
    # z których wszystkie wypadną jako katalogi, duplikaty albo martwe strony —
    # dla usera to tak samo pusty ekran, więc tak samo trzeba spróbować krócej.
    for dlugosc in range(len(slowa), 1, -1):
        uzyte = " ".join(slowa[:dlugosc])
        surowe = await asyncio.to_thread(tavily_search, uzyte, ile)
        wynik = await znajdz_firmy_z_wynikow(surowe, wlasna_domena, pomin)
        if wynik["firmy"]:
            break

    return {"zapytanie": uzyte, "skrocone": uzyte != zapytanie,
            **(wynik or {"firmy": [], "z_seo": 0, "juz_zbadane": 0, "odsiane_martwe": 0})}


async def znajdz_firmy_z_wynikow(wyniki: list, wlasna_domena: str = "",
                                 pomin: set | None = None) -> dict:
    """Filtr + deduplikacja + kontrola żywotności.
    Osobno od pobierania, bo Tryb B scala wyniki z kilku zapytań naraz."""
    # Limit dobrany do tego, ile realnie potrafi przyjść: Mapy oddają do 60 firm
    # na zapytanie (3 strony po 20), z czego część bez strony WWW odpada wcześniej.
    #
    # Wcześniej stały tu DWA ścięcia jedno po drugim — limit=18, a potem [:12] przy
    # zwracaniu. Z 40 firm z Map do użytkownika docierało 12, a UI pisało
    # „ZNALEZIONE FIRMY (12)", jakby tyle właśnie było. Płaciliśmy Google za wyniki,
    # które sami wyrzucaliśmy do kosza, i to bez śladu.
    firmy = filtruj_firmy(wyniki, wlasna_domena, limit=60, pomin=pomin)

    def sprawdz_wszystkie():
        with ThreadPoolExecutor(max_workers=12) as pool:
            return list(pool.map(lambda f: sprawdz_zywotnosc(f["url"]), firmy))

    # do_thread, bo pula wątków blokowałaby pętlę zdarzeń na czas kilkunastu żądań HTTP
    stany = await asyncio.to_thread(sprawdz_wszystkie)

    # Firmy, które już badaliśmy. NIE usuwamy ich z wyników — mogą być trafne
    # i user ma prawo je zobaczyć — ale oznaczamy, żeby nie płacić po raz drugi
    # za te same 30 sekund researchu. Przy dwóch źródłach i 78 kategoriach ta
    # sama firma wraca regularnie.
    znane = {}
    for z in await asyncio.to_thread(baza.firmy):
        d = domena_z_url(z.get("url") or "")
        if d:
            znane[d] = z.get("tryb") or "partner"

    zostaja = []
    for f, stan in zip(firmy, stany):
        if stan == "martwa":
            continue
        if stan == "niepewna":
            f["niepewna"] = True  # front pokaże adnotację, user decyduje
        gdzie = znane.get(domena_z_url(f["url"]))
        if gdzie:
            f["zbadana"] = True
            f["zbadana_tryb"] = gdzie   # bywa, że w DRUGIEJ ścieżce — to też trzeba wiedzieć
        zostaja.append(f)

    # Zwracamy WSZYSTKO, co przeżyło. Liczniki też liczymy z całości — inaczej
    # „3 już masz" znaczyłoby „3 wśród pierwszych dwunastu", czyli co innego niż
    # sugeruje etykieta.
    return {
        "firmy": zostaja,
        "z_seo": sum(1 for f in zostaja if f.get("ma_seo")),
        "juz_zbadane": sum(1 for f in zostaja if f.get("zbadana")),
        "odsiane_martwe": stany.count("martwa"),
    }


async def api_szukaj(request):
    """TRYB B — szukanie po kryteriach (branża + miasto), bez firmy wejściowej.

    Podział pracy: LLM robi to, w czym jest dobry — wymyśla synonimy branży i konkretne
    usługi. Lokalizację dokleja Python, bo to sklejenie stringów, a nie zrozumienie
    tekstu. Wcześniej jedno i drugie robił model i mylił się w 4 na 6 przebiegów.
    """
    try:
        body = await request.json()
        branza = (body.get("branza") or "").strip()
        miasto = (body.get("miasto") or "").strip()
        zrodlo = (body.get("zrodlo") or "wyszukiwarka").lower()
        if not branza:
            return JSONResponse({"ok": False, "error": "Podaj branżę lub typ firmy."})

        # ── ŹRÓDŁO: MAPY GOOGLE ─────────────────────────────────────────────
        # Wyszukiwarka pokazuje to, co wypozycjonowane. Firma bez SEO tam nie
        # wychodzi — a przy ścieżce KLIENTÓW to właśnie ona jest najlepszym
        # tropem. Na Mapach jest każdy, kto ma wizytówkę.
        # Z Map bierzemy WYŁĄCZNIE adres strony; dane zbiera potem nasz scraper
        # z serwisu firmy. Powód regulaminowy — patrz mapy.py.
        if zrodlo == "mapy":
            if not mapy.dostepne():
                return JSONResponse({"ok": False, "error":
                    "Brak GOOGLE_MAPS_API_KEY w .env — wyszukiwanie po Mapach wyłączone."})
            try:
                # Trzy strony, bo tyle wynosi sufit API: Google przestaje oddawać
                # nextPageToken po 60 firmach, niezależnie od wielkości rynku.
                # Zmierzone: Warszawa 60, Leszno 60, Wielkopolska 60. Braliśmy dwie,
                # czyli dwie trzecie tego, co i tak jesteśmy w stanie dostać.
                z_map = await asyncio.to_thread(mapy.szukaj, branza, miasto, 3)
            except mapy.BladMap as e:
                return JSONResponse({"ok": False, "error": str(e)})

            # Mapy nie dają opisu firmy, więc filtr dostaje sam adres. Tytuł
            # spadnie do domeny, a tag SEO będzie pusty — do czasu researchu
            # naprawdę nie wiemy, czym firma się zajmuje. To uczciwy stan,
            # nie brak funkcji.
            wyniki = [{"url": u, "title": "", "content": ""} for u in z_map["adresy"]]
            wynik = await znajdz_firmy_z_wynikow(wyniki)
            # Obszar pokazujemy użytkownikowi: rozpoznanie nazwy bywa nietrafione
            # („powiat leszczyński" Google rozumie jako miasto Leszno), a bez tego
            # wyniki cicho zmieniają znaczenie i nie ma jak tego zauważyć.
            return JSONResponse({"ok": True, "zapytanie": z_map["zapytanie"],
                                 "zrodlo": "mapy", "bez_strony": z_map["bez_strony"],
                                 "zapytan_do_map": z_map["zapytan"],
                                 "obszar": z_map.get("obszar"),
                                 "obszar_nierozpoznany": z_map.get("obszar_nierozpoznany"),
                                 **wynik})

        if not (os.environ.get("TAVILY_API_KEY") or os.environ.get("TVLY_API_KEY")):
            return JSONResponse({"ok": False, "error": "Brak klucza Tavily w środowisku."})

        # LLM rozpisuje branżę na kilka RÓŻNYCH fraz — jedno zapytanie zwraca tylko TOP10
        # najlepiej wypozycjonowanych, a szukamy tych mniej widocznych (główny ból z PRD).
        # Agent dostaje SAMĄ branżę — o mieście nie ma prawa wiedzieć, więc nie ma go
        # skąd zmyślić. Miejsce doklejamy niżej, już poza modelem.
        r = await claude.uruchom(zadanie_warianty, f"Typ firmy: {branza}.")
        warianty = [q for q in (zapytanie_z_miejscem(z, miasto)
                                for z in (r.final_output.zapytania or [])) if q][:4]
        if not warianty:
            # Ostatnia deska: sama branża od usera. Jego słów nie filtrujemy — gdyby
            # wpisał w to pole miasto, to jego decyzja, a pusty string do Tavily nie idzie.
            warianty = [zapytanie_z_miejscem(branza, miasto)
                        or f"{branza} {miasto}".strip()]

        # Wszystkie warianty równolegle, potem scalamy w jedną pulę wyników.
        with ThreadPoolExecutor(max_workers=4) as pool:
            partie = list(pool.map(lambda q: tavily_search(q, max_results=10), warianty))
        wszystkie = [w for partia in partie for w in partia]

        wynik = await znajdz_firmy_z_wynikow(wszystkie)
        return JSONResponse({"ok": True, "zapytanie": " | ".join(warianty), **wynik})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_similar(request):
    """Funkcja 2 — szukaj podobnych firm (LLM tylko generuje zapytanie, filtr jest deterministyczny)."""
    try:
        if not (os.environ.get("TAVILY_API_KEY") or os.environ.get("TVLY_API_KEY")):
            return JSONResponse({
                "ok": False,
                "error": "Brak klucza Tavily. Dodaj TAVILY_API_KEY do .env (lokalnie) "
                         "i do zmiennych środowiskowych na Render.",
            })
        body = await request.json()
        firma = body.get("firma") or {}
        tagi = body.get("tagi") or []
        # Domeny pokazane w poprzednich rundach — przychodzą z frontu przy "Szukaj dalej".
        pomin = {d for d in (body.get("pomin") or []) if d}
        runda = int(body.get("runda") or 1)
        zrodlo = (body.get("zrodlo") or "wyszukiwarka").lower()
        # Miasto TYLKO gdy user je poda. Wcześniej braliśmy miasto firmy wzorcowej
        # i wyszło głupio: Tebim siedzi w Kaliszu, więc „podobne agencje PrestaShop"
        # szukały się w Kaliszu i zwracały zero. Podobna firma nie musi być
        # w tym samym mieście — a jak ma być, user to napisze.
        miasto = (body.get("miasto") or "").strip()
        if miasto == BRAK:
            miasto = ""

        branza = (firma.get("branza") or "").strip()

        # Zapytanie zawsze układa LLM — user daje mu tylko wskazówki.
        if tagi:
            opis = ("Branża: " + branza + "." + _NOWA_LINIA +
                    "USŁUGI WSKAZANE PRZEZ UŻYTKOWNIKA (zbuduj zapytanie WOKÓŁ NICH, "
                    "uszanuj ten wybór): " + ", ".join(tagi) + ".")
        else:
            # Bez tagów szukamy po BRANŻY — po tym, jak sami sklasyfikowaliśmy tę firmę
            # przy researchu. Wcześniej dokładaliśmy do tego pięć usług, przez co
            # zapytanie stawało się wąskie — a kto nie zaznaczył żadnego tagu,
            # ten właśnie NIE chciał zawężać.
            opis = ("Branża: " + branza + "." if branza else
                    "Firma: " + (firma.get("nazwa") or "") + ". Opis: " + (firma.get("opis") or "")[:200])

        # Kolejna runda ma dać INNE firmy. Samo odsianie już pokazanych dawałoby
        # coraz krótsze listy z tego samego zapytania, więc prosimy o inne ujęcie.
        if runda > 1:
            opis += (_NOWA_LINIA + _NOWA_LINIA + "To już " + str(runda) + ". podejście do tej samej firmy. "
                     "Poprzednie zapytania zwróciły firmy, których user nie chce oglądać "
                     "ponownie. Zaproponuj INNE UJĘCIE tej samej branży — synonim, węższą "
                     "specjalizację albo pokrewny typ firmy. Nie powtarzaj poprzedniej frazy.")

        r = await claude.uruchom(zadanie_zapytanie, opis)
        # bez_lokalizacji, bo model mimo zakazu dopisuje "Polska" — a zmierzyliśmy,
        # że to słowo trafia w nazwy nagród i izb, nie w kraj. Tavily i tak jest
        # ograniczone do Polski parametrem country.
        zapytanie = " ".join(bez_lokalizacji(
            (r.final_output or "").strip().strip('"')).split()[:8])

        # Kolejne rundy odsiewają wszystko, co już pokazaliśmy, więc muszą mieć
        # z czego wybierać — inaczej po pierwszej rundzie lista jest pusta.
        ile = 15 if runda == 1 else 20

        wlasna = domena_z_url(firma.get("url", ""))

        # ── ŹRÓDŁO: MAPY ────────────────────────────────────────────────
        # Ta sekcja chodziła wyłącznie po wyszukiwarce, mimo że przy „Szukaj po
        # branży" zmierzyliśmy, że Mapy dają 10 z 12 firm, których wyszukiwarka
        # nie znajduje. Zapytanie budujemy TAK SAMO — model nie wie, dokąd
        # pójdzie — różni się tylko to, kto na nie odpowiada.
        if zrodlo == "mapy":
            if not mapy.dostepne():
                return JSONResponse({"ok": False, "error":
                    "Brak GOOGLE_MAPS_API_KEY w .env — wyszukiwanie po Mapach wyłączone."})
            try:
                z_map = await asyncio.to_thread(mapy.szukaj, zapytanie, miasto)
            except mapy.BladMap as e:
                return JSONResponse({"ok": False, "error": str(e)})
            wyniki = [{"url": u, "title": "", "content": ""} for u in z_map["adresy"]]
            wynik = await znajdz_firmy_z_wynikow(wyniki, wlasna, pomin)
            return JSONResponse({"ok": True, "runda": runda, "zrodlo": "mapy",
                                 "zapytanie": z_map["zapytanie"],
                                 "bez_strony": z_map["bez_strony"], **wynik})

        return JSONResponse({"ok": True, "runda": runda, "zrodlo": "wyszukiwarka",
                             **await znajdz_firmy(zapytanie, wlasna, pomin, ile)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_email(request):
    """Funkcja 3 — 3 drafty maila na bazie docs/email-examples.md."""
    try:
        body = await request.json()
        firma = body.get("firma") or {}
        kontekst = (
            f"DANE FIRMY Z RESEARCHU:\n{firma}\n\n"
            f"BAZA WIEDZY MAILINGU (struktura, zasady, przykłady):\n{baza_maili()}"
        )
        # 3 style równolegle — czas jak przy jednym mailu
        wyniki = await asyncio.gather(*[claude.uruchom(z, kontekst) for z in zadania_mail])
        # Draft zapisujemy OD RAZU. Wcześniej żył tylko w przeglądarce — zamknięcie
        # karty kasowało go bezpowrotnie, mimo że napisanie kosztowało tokeny i czas.
        url = (firma.get("url") or "").strip()
        tryb = (body.get("tryb") or firma.get("tryb") or "partner").lower()
        maile = []
        for (nazwa, _), w in zip(STYLE_MAILI, wyniki):
            tresc = str(w.final_output or "")
            mid = await asyncio.to_thread(baza.zapisz_mail, url, nazwa, tresc, tryb) if url else None
            maile.append({"id": mid, "styl": nazwa, "tresc": tresc})
        return JSONResponse({"ok": True, "maile": maile})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_audyt(request):
    """Funkcja 5 — mikroaudyt SEO/GEO. PŁATNE (DataForSEO), więc liczymy koszt i zwracamy go."""
    try:
        if not (os.environ.get("DATAFORSEO_LOGIN") and os.environ.get("DATAFORSEO_PASSWORD")):
            return JSONResponse({"ok": False, "error":
                                 "Brak danych DataForSEO w .env (DATAFORSEO_LOGIN / _PASSWORD)."})
        body = await request.json()
        firma = body.get("firma") or {}
        ile = int(body.get("ile_promptow") or 5)
        z_aio = bool(body.get("ai_overview", True))
        # Jedyny dostawca danych SEO. Pole zostaje w raporcie i w bazie, bo stare
        # audyty maja zapisane "seranking" i musza dalej dac sie odczytac.
        dostawca = "dataforseo"
        # Można wybrać kilka modeli naraz — wtedy każde pytanie idzie do każdego z nich.
        wybrane = body.get("silniki") or [body.get("silnik") or "chatgpt_wprost"]
        silniki = [audyt.SILNIKI[k] for k in wybrane if k in audyt.SILNIKI]
        if not silniki:
            silniki = [audyt.SILNIKI["chatgpt_wprost"]]

        nazwa = firma.get("nazwa") or ""
        # .lower() JEST KONIECZNE. DataForSEO dopasowuje domenę wrażliwie na wielkość liter:
        # zapytanie o "Elektromaniacy.pl" zwróciło status 20000 Ok, policzyło $0.10
        # i oddało total_count=0 — cicha, płatna porażka. Domena musi być znormalizowana.
        domena = domena_z_url(firma.get("url", "")).strip()

        # 1) Prompty generuje NASZ model (tanio, mamy kontrolę) — nie DataForSEO
        opis = (f"Firma: {nazwa}\nBranża: {firma.get('branza','')}\n"
                f"Usługi: {', '.join(firma.get('uslugi', [])[:10])}\n"
                f"Miasto: {firma.get('miasto','')}\nOpis: {firma.get('opis','')}")
        r = await claude.uruchom(zadanie_prompty, f"Wygeneruj {ile} pytań.\n\n{opis}")
        pytania = (r.final_output.pytania or [])[:ile]

        # 2) Każde pytanie do KAŻDEGO wybranego modelu. Przy kilku modelach widać,
        # czy brak wzmianki to cecha jednego silnika, czy prawidłowość — a to zupełnie
        # inna rozmowa z partnerem.
        koszt = 0.0
        wiersze = []
        # Sekcja pytań idzie zawsze przez DataForSEO i jest pierwsza w kolejności.
        # Bez tego przełącznika brak środków u JEDNEGO dostawcy blokował cały audyt,
        # łącznie z sekcjami, które miał wypełnić drugi. Teraz da się ją pominąć.
        if not bool(body.get("pytania", True)):
            silniki = []
        for opis in silniki:
            for i, pytanie in enumerate(pytania, 1):
                if opis.get("wlasny_klucz"):
                    # własny klucz OpenAI — bez pośrednika, więc i bez jego awarii
                    surowy = await zapytaj_chatgpt_wprost(pytanie)
                    w = audyt.z_wlasnego_zapytania(
                        surowy["tekst"], surowy["zrodla"], nazwa, domena, pytanie)
                    koszt += opis["koszt"]
                else:
                    nazwa_f = f"audyt_{domena}_{opis['silnik'][0]}_{i}"
                    odp = await asyncio.to_thread(
                        audyt.zapytaj_llm, pytanie, opis["silnik"], nazwa_f
                    )
                    koszt += odp.get("cost", 0)
                    w = audyt.analizuj_odpowiedz(odp, nazwa, domena, pytanie)
                w["silnik_nazwa"] = opis["nazwa"]
                w["silnik_udzial"] = opis["udzial"]
                wiersze.append(w)

        # 2b) Marki konkurencyjne — jedno wywołanie na wszystkie odpowiedzi naraz (tanio)
        if wiersze:
            zlepek = "\n\n".join(
                f"[ODPOWIEDŹ {i}]\n{w['odpowiedz'][:1500]}" for i, w in enumerate(wiersze, 1)
            )
            try:
                rm = await claude.uruchom(zadanie_marki, f"Firma badana: {nazwa}\n\n{zlepek}")
                war = audyt.warianty_marki(nazwa, domena)
                for w, marki in zip(wiersze, rm.final_output.marki_per_odpowiedz):
                    # ten sam filtr co w analizuj_odpowiedz — badana firma nie moze
                    # trafic na wlasna liste konkurentow (nazwa bywa zapisana z domena)
                    w["marki"] = [m for m in marki
                                  if not any(x in m.lower() for x in war)]
            except Exception:
                pass  # zostaje wersja z parsera — lepsze to niż brak

        # 2c) Skąd model czerpie wiedzę — z zapisanych źródeł, bez dodatkowego kosztu
        zrodla = audyt.analiza_zrodel(wiersze, domena)

        # 2d) Techniczny audyt GEO — czy roboty AI w ogóle mogą przeczytać stronę.
        # Same żądania HTTP do strony klienta, zero kosztu API.
        try:
            techniczne = await asyncio.to_thread(geo.audyt_geo, firma.get("url", ""), firma)
        except Exception:
            techniczne = None

        # 3) AI Overview (opcjonalnie — najdroższy pojedynczy element raportu)
        aio = None
        if z_aio:
            # Można wziąć kilka platform naraz i pokazać różnicę. To dokładnie ten
            # wniosek, którego nie widać przy jednym silniku: firma bywa pierwsza
            # w jednym asystencie i nieobecna w drugim, a obie liczby są prawdziwe.
            wybrane_pl = body.get("platformy") or ["google"]
            wybrane_pl = [x for x in wybrane_pl if x in audyt.PLATFORMY_WZMIANEK] or ["google"]
            zebrane = []
            for pl in wybrane_pl:
                odp_aio = await asyncio.to_thread(
                    audyt.wzmianki_ai_overview, domena, 10,
                    f"audyt_aio_{domena}_{pl}", pl
                )
                koszt += odp_aio.get("cost", 0)
                w = audyt.analizuj_ai_overview(odp_aio, domena, nazwa)
                w["silnik_nazwa"] = audyt.PLATFORMY_WZMIANEK[pl]
                zebrane.append(w)
            aio = zebrane[0]
            if len(zebrane) > 1:
                aio["platformy"] = [
                    {"nazwa": z["silnik_nazwa"], "liczba": z["liczba_wzmianek"],
                     "srednia": z["srednia_pozycja"]} for z in zebrane]

        # 4) Klasyczne SEO — „Raport Zero"
        # Pole `etykieta_czolo` zostaje mimo jednego dostawcy: raport ma podpisywać
        # liczbę nazwą metryki, która ją opisuje ("fraz w TOP 3"), zamiast zakładać,
        # że czytelnik wie, co dokładnie zliczono. Stare audyty niosą tu inną wartość.
        seo = None
        if bool(body.get("seo", True)):
            rank, konk, strony, frazy, ruch_konk, k = await asyncio.to_thread(
                audyt.dane_seo, domena, f"audyt_seo_{domena}"
            )
            koszt += k
            seo = audyt.analizuj_seo(rank, konk, strony, domena, frazy, ruch_konk)

            # 4b) Luka GEO — zestawienie pozycji w Google z obecnoscia w AI Overview.
            # Wymaga danych z AIO (kto nas cytuje), wiec tylko gdy wlaczone.
            if seo.get("frazy") and aio:
                cytowane = {w["prompt"].lower() for w in (aio.get("wzmianki") or [])}
                luka = await asyncio.to_thread(
                    audyt.analiza_luki, audyt.pula_fraz(frazy), domena, cytowane, 8,
                    f"audyt_luka_{domena}", not aio.get("probka_niepelna", False)
                )
                koszt += sum(w.get("koszt", 0) for w in luka)
                seo["luka"] = luka

        raport = audyt.zbuduj_raport({**firma, "domena": domena}, wiersze, aio, koszt, seo)
        raport["dostawca"] = dostawca
        raport["silniki"] = [{"nazwa": s["nazwa"], "udzial": s["udzial"]} for s in silniki]
        raport["zrodla"] = zrodla
        raport["techniczne"] = techniczne

        # Gotowy raport zapisujemy na dysk. Odpowiedzi DataForSEO trafiają do fixtures/
        # automatycznie, ale wynik NASZEGO modelu (marki konkurencyjne) i cała złożona
        # treść — nie. Bez tego nie da się później zweryfikować, co dokładnie zobaczył
        # użytkownik, inaczej niż powtarzając płatny audyt.
        try:
            import json as _json
            from datetime import datetime as _dt
            (Path(__file__).resolve().parent / "fixtures").mkdir(exist_ok=True)
            plik = (Path(__file__).resolve().parent / "fixtures" /
                    f"raport_{domena}_{_dt.now():%Y%m%d_%H%M}.json")
            plik.write_text(_json.dumps(raport, ensure_ascii=False, indent=1), encoding="utf-8")
            baza.zapisz_audyt(firma.get("url", ""), raport,
                              (firma.get("tryb") or "partner"), dostawca)
            print(f"  raport zapisany: {plik.name}")
        except Exception as e:
            print(f"  (nie udalo sie zapisac raportu: {e})")
        raport["saldo_po"] = dfs.saldo()
        return JSONResponse({"ok": True, "raport": raport})
    except dfs.BladAPI as e:
        # Awaria po stronie DataForSEO. Świadomie NIE budujemy raportu: dokument
        # z pustych danych wygląda jak wynik i powiedziałby partnerowi, że ma zerową
        # widoczność — a to nieprawda. Lepiej pokazać błąd niż fałszywe zero.
        return JSONResponse({"ok": False, "error": str(e), "typ": "api"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_firmy(request):
    """Lista zbadanych firm z bazy — front wczytuje ją przy starcie, żeby praca
    nie ginęła po odświeżeniu strony."""
    tryb = request.query_params.get("tryb")
    return JSONResponse({"ok": True, "firmy": baza.firmy(tryb)})


async def api_firma_usun(request):
    try:
        body = await request.json()
        baza.usun_firme((body.get("url") or "").strip())
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_koszyk(request):
    try:
        body = await request.json()
        baza.ustaw_koszyk((body.get("url") or "").strip(), bool(body.get("w_koszyku")))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_audyty(request):
    """Historia audytów. Ten sam URL badany dwa razy to dwa pomiary — porównanie
    ich pokazuje, czy działania partnera przyniosły efekt."""
    url = request.query_params.get("url")
    id_ = request.query_params.get("id")
    if id_:
        r = baza.audyt(int(id_))
        return JSONResponse({"ok": bool(r), "raport": r})
    return JSONResponse({"ok": True, "audyty": baza.audyty(url)})


async def api_czat(request):
    """Pytanie o zbadaną firmę. Agent może dociągnąć podstrony jej serwisu.

    Historia rozmowy przychodzi z frontu i NIE jest zapisywana w bazie: to
    narzędzie pracy nad jedną firmą, nie komunikator. Gdyby okazało się, że
    wnioski z rozmów są warte zachowania, dołożymy tabelę — ale nie zakładamy
    tego z góry.
    """
    global _czat_domena
    try:
        body = await request.json()
        firma = body.get("firma") or {}
        pytanie = (body.get("pytanie") or "").strip()
        historia = body.get("historia") or []
        if not pytanie:
            return JSONResponse({"ok": False, "error": "Zadaj pytanie."})

        _czat_domena = domena_z_url(firma.get("url") or "")
        if not _czat_domena:
            return JSONResponse({"ok": False, "error": "Firma bez adresu strony."})

        # Karta firmy jako punkt wyjścia — bez niej agent zaczynałby od zera
        # i dociągał podstrony, które już mamy.
        karta = {k: v for k, v in firma.items()
                 if k in ("nazwa", "branza", "opis", "uslugi", "case_studies",
                          "wielkosc_zespolu", "miasto", "ma_seo", "seo_zakres")}
        wejscie = ("FIRMA: " + (firma.get("url") or "") + _NOWA_LINIA
                   + "DANE Z RESEARCHU: " + str(karta) + _NOWA_LINIA + _NOWA_LINIA)
        for w in historia[-6:]:          # sześć ostatnich wystarczy na sensowny wątek
            rola = "PYTANIE" if w.get("rola") == "user" else "ODPOWIEDZ"
            wejscie += rola + ": " + str(w.get("tresc") or "")[:1500] + _NOWA_LINIA
        wejscie += "PYTANIE: " + pytanie

        w = await claude.uruchom(zadanie_czat, wejscie)

        # Które podstrony agent naprawdę otworzył — user ma widzieć źródło,
        # a nie ufać, że model gdzieś zajrzał.
        #
        # Wcześniej trzeba było to odtwarzać z obiektów zwracanych przez SDK i raz
        # się to już wyłożyło: wynik narzędzia przychodził jako słownik, odczyt szedł
        # przez getattr, lista źródeł wychodziła pusta mimo czterech otwartych
        # podstron. Teraz źródła notuje ten, kto wywołuje narzędzie — czyli my.
        return JSONResponse({"ok": True, "odpowiedz": str(w.final_output or ""),
                             "zrodla": w.odwiedzone})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})



async def api_maile(request):
    """Biblioteka maili. GET lista, DELETE usuwa jedną wersję, PATCH oznacza wysłany.

    „Wysłany" to jedyny ślad, że mail poszedł — narzędzie nie ma dostępu do skrzynki
    i nie będzie udawać, że wie więcej niż user mu powie.
    """
    if request.method == "GET":
        url = request.query_params.get("url")
        tryb = request.query_params.get("tryb")
        return JSONResponse({"ok": True,
                             "maile": await asyncio.to_thread(baza.maile, url, tryb)})

    body = await request.json()
    if request.method == "DELETE":
        await asyncio.to_thread(baza.usun_mail, int(body.get("id") or 0))
        return JSONResponse({"ok": True})

    await asyncio.to_thread(baza.oznacz_wyslany,
                            int(body.get("id") or 0), bool(body.get("wyslany", True)))
    return JSONResponse({"ok": True})


async def api_email_popraw(request):
    """Poprawia gotowy mail według polecenia. Zapisuje jako NOWĄ wersję.

    Nowa wersja, a nie nadpisanie: poprawka bywa gorsza od oryginału, a bez historii
    nie da się do niego wrócić. To ta sama zasada, co przy historii audytów.
    """
    try:
        body = await request.json()
        zrodlo = int(body.get("id") or 0)
        polecenie = (body.get("polecenie") or "").strip()
        if not polecenie:
            return JSONResponse({"ok": False, "error": "Napisz, co poprawić."})

        stary = await asyncio.to_thread(baza.mail, zrodlo)
        if not stary:
            return JSONResponse({"ok": False, "error": "Nie znalazłem tego maila w bibliotece."})

        wejscie = ("MAIL DO POPRAWY:" + _NOWA_LINIA + stary["tresc"]
                   + _NOWA_LINIA + _NOWA_LINIA + "POLECENIE UŻYTKOWNIKA:" + _NOWA_LINIA + polecenie)
        w = await claude.uruchom(zadanie_poprawka, wejscie)
        tresc = str(w.final_output or "").strip()
        if not tresc:
            return JSONResponse({"ok": False, "error": "Model nie zwrócił treści — spróbuj inaczej sformułować."})

        nowy_id = await asyncio.to_thread(
            baza.zapisz_mail, stary["url"], "poprawiony", tresc,
            stary.get("tryb") or "partner", polecenie)
        return JSONResponse({"ok": True, "mail": {
            "id": nowy_id, "styl": "poprawiony", "tresc": tresc, "polecenie": polecenie}})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_kolejka(request):
    """Kolejka kandydatów — firmy znalezione, jeszcze niezbadane.

    GET  zwraca listę, POST dopisuje, DELETE usuwa pojedynczy adres.
    Firmy już zbadane nie trafiają do kolejki (pilnuje tego baza) — kolejka ma
    pokazywać robotę do zrobienia, a nie mieszać jej ze zrobioną.
    """
    if request.method == "GET":
        tryb = request.query_params.get("tryb")
        return JSONResponse({"ok": True, "kolejka": await asyncio.to_thread(baza.kolejka, tryb)})

    body = await request.json()
    if request.method == "DELETE":
        await asyncio.to_thread(baza.usun_z_kolejki, (body.get("url") or "").strip())
        return JSONResponse({"ok": True})

    doszlo = await asyncio.to_thread(
        baza.dodaj_do_kolejki, body.get("firmy") or [],
        (body.get("tryb") or "partner").lower(),
        body.get("zrodlo") or "", body.get("zapytanie") or "")
    return JSONResponse({"ok": True, "doszlo": doszlo})


async def api_zrodla(request):
    """Które źródła firm są podłączone. Front pyta, zanim pokaże przełącznik —
    opcja, która na pewno zwróci błąd, nie powinna być klikalna."""
    return JSONResponse({"ok": True, "zrodla": {
        "wyszukiwarka": bool(os.environ.get("TAVILY_API_KEY") or os.environ.get("TVLY_API_KEY")),
        "mapy": mapy.dostepne(),
    }})


async def api_kategorie(request):
    """Kategorie partnerskie dla frontu. Backend jest tu źródłem prawdy — front
    ma je tylko wyświetlić, a nie trzymać własną kopię."""
    return JSONResponse({"ok": True, "kategorie": KATEGORIE_PARTNEROW})


async def api_columns(request):
    """Kolumny eksportu — front renderuje podgląd DOKŁADNIE tak, jak zapisze CSV."""
    return JSONResponse({"kolumny": [{"naglowek": n, "klucz": k} for n, k in KOLUMNY]})


async def api_export(request):
    """Funkcja 4 — CSV do POBRANIA (nie zapisujemy na serwerze)."""
    try:
        body = await request.json()
        firmy = body.get("firmy") or []
        if not firmy:
            return JSONResponse({"ok": False, "error": "Brak firm do eksportu"})
        csv_tekst = "﻿" + zbuduj_csv(firmy)  # BOM => polskie znaki OK w Excelu
        return Response(
            csv_tekst,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="partnerzy.csv"'},
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"

app = Starlette(routes=[
    Route("/api/research", api_research, methods=["POST"]),
    Route("/api/similar", api_similar, methods=["POST"]),
    Route("/api/szukaj", api_szukaj, methods=["POST"]),
    Route("/api/email", api_email, methods=["POST"]),
    Route("/api/columns", api_columns, methods=["GET"]),
    Route("/api/kategorie", api_kategorie, methods=["GET"]),
    Route("/api/zrodla", api_zrodla, methods=["GET"]),
    Route("/api/kolejka", api_kolejka, methods=["GET", "POST", "DELETE"]),
    Route("/api/maile", api_maile, methods=["GET", "DELETE", "PATCH"]),
    Route("/api/czat", api_czat, methods=["POST"]),
    Route("/api/email/popraw", api_email_popraw, methods=["POST"]),
    # pamięć — bez tego cała praca ginęła po odświeżeniu strony
    Route("/api/firmy", api_firmy, methods=["GET"]),
    Route("/api/firmy/usun", api_firma_usun, methods=["POST"]),
    Route("/api/koszyk", api_koszyk, methods=["POST"]),
    Route("/api/audyty", api_audyty, methods=["GET"]),
    Route("/api/audyt", api_audyt, methods=["POST"]),
    Route("/api/export", api_export, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=str(frontend_dir), html=True), name="frontend"),
])

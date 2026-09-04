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
import dfs
import geo
import seranking

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

DOCS = Path(__file__).resolve().parent.parent / "docs"

MODEL = "gpt-5.4-mini"       # ekstrakcja i mail — potrzebna rzetelność
MODEL_TANI = "gpt-5.4-nano"  # proste zadania (np. wygenerowanie zapytania)

BRAK = "nie do ustalenia"    # PRD: uczciwy brak zamiast halucynacji


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

# wpisy blogowe/newsy zjadają limit znaków, a rzadko mają dane o firmie
POMIJAJ = ("/blog", "/aktualnosci", "/news", "/polityka", "/regulamin")

MAX_PODSTRON = 4
LIMIT_ZNAKOW = 12000


def pobierz(url: str, timeout: int = 15) -> str:
    """Pobiera HTML jednej strony. Zwraca '' gdy się nie udało."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (PartnerTool)"})
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def tekst_ze_strony(html: str) -> str:
    # UWAGA: NIE wycinamy <footer> — to tam zwykle są dane firmowe: adres, NIP, telefon, mail.
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


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
    return "\n\n".join(czesci)[:LIMIT_ZNAKOW], odwiedzone


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
SYGNAL_SEO = re.compile(
    r"\b(seo|sem|ppc|sxo|adwords|google\s+ads|pozycjonowani\w*|pozycjonowa\w*)\b",
    re.IGNORECASE,
)


def ma_sygnal_seo(tytul: str, opis: str) -> bool:
    """Czy wynik w ogóle warto oddać modelowi do oceny. NIE jest werdyktem."""
    return bool(SYGNAL_SEO.search(f"{tytul or ''} {opis or ''}"))

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


def filtruj_firmy(wyniki: list, wlasna_domena: str, limit: int = 10) -> list:
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
- uslugi: lista konkretnych usług z oferty
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

SEO W OFERCIE — ustalasz FAKT, nie wydajesz osądu.

ma_seo = true, gdy firma SPRZEDAJE KLIENTOM pozycjonowanie / SEO / SEM / Google Ads
jako usługę — obojętne, czy to rdzeń oferty, czy jedna z kilkunastu pozycji.

ma_seo = false, gdy takiej usługi w ofercie NIE MA. Nie liczą się:
- "strona zoptymalizowana pod SEO" jako cecha produktu, który sprzedają,
- wpis na blogu o SEO,
- słowo "SEO" w stopce, w tagach albo w opisie technologii.
To są wzmianki, nie usługa na sprzedaż.

W seo_zakres napisz KRÓTKO dwie rzeczy: jakie dokładnie usługi SEO/SEM widać w ofercie
i jak dużą jej część stanowią — czy to rdzeń działalności, czy dodatek obok wdrożeń,
brandingu albo software'u. Gdy ma_seo = false, wpisz "{BRAK}".

NIE orzekaj, czy firma jest konkurentem ani czy jest dobrym partnerem. Ta sama agencja
z SEO w ofercie bywa jednym i drugim, zależnie od tego, po co do niej piszemy.
Dostarczasz fakty — decyduje człowiek."""

agent_ekstrakcja = Agent(
    name="ekstrakcja",
    instructions=EKSTRAKCJA_PROMPT,
    output_type=Firma,
    model=MODEL,
)

agent_zapytanie = Agent(
    name="zapytanie",
    instructions="""Dostajesz branżę i kilka usług firmy. Napisz JEDNO zapytanie do wyszukiwarki,
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
    model=MODEL_TANI,
)


class WariantyZapytan(BaseModel):
    zapytania: list[str]


agent_warianty = Agent(
    name="warianty",
    instructions="""Dostajesz typ firmy. Wygeneruj 4 RÓŻNE frazy branżowe, po których
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
    output_type=WariantyZapytan,
    model=MODEL_TANI,
)


class Prompty(BaseModel):
    pytania: list[str]


# ChatGPT pytany BEZPOŚREDNIO, naszym kluczem OpenAI — bez DataForSEO po drodze.
# Powód nie jest kosztowy, tylko taki: sekcja z pytaniami klientów to nasza jedyna
# przewaga nad audytami konkurencji, a szła przez dostawcę, który potrafi zawiesić
# konto albo wyczerpać saldo i zabrać ją razem z resztą raportu. SE Ranking nie ma
# odpowiednika tej funkcji (ich AI Search zwraca tylko prompty z własnej bazy),
# więc bez tego przy wyborze SE Ranking sekcja w ogóle by nie działała.
agent_pytajacy = Agent(
    name="pytajacy",
    instructions=(
        "Odpowiadasz jak asystent wyszukiwarki na pytanie polskiego klienta. "
        "Szukaj w sieci i podaj konkretne firmy z nazwy, jeśli pytanie ich dotyczy. "
        "Pisz po polsku, rzeczowo, bez wstępów."
    ),
    tools=[WebSearchTool(search_context_size="medium")],
    model=MODEL,
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
agent_marki = Agent(
    name="marki",
    instructions="""Dostajesz ponumerowane odpowiedzi AI. Dla KAŻDEJ wypisz nazwy FIRM,
które w niej wystąpiły jako polecani/wymieniani dostawcy usług.

ZASADY:
- TYLKO nazwy własne firm (np. „Waynet", „Convertis", „Astrabit").
- NIE wypisuj: nazw usług, certyfikatów, platform (PrestaShop, Shopify, WordPress),
  miast, ogólnych fraz („Doświadczenie", „Certyfikacja", „Expert").
- Jeśli w odpowiedzi nie ma żadnej firmy — pusta lista dla tej pozycji.
- Zachowaj kolejność: lista wyników musi mieć tyle pozycji, ile dostałeś odpowiedzi.""",
    output_type=MarkiWOdpowiedziach,
    model=MODEL,
)


agent_prompty = Agent(
    name="prompty-audyt",
    instructions=audyt.PROMPT_GENERATORA.format(ile="{ile}").replace("{ile}", "5"),
    output_type=Prompty,
    model=MODEL,
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

agenci_mail = [
    Agent(name=f"mail-{nazwa}", instructions=f"{MAIL_SYSTEM}\n\nSTYL: {opis}", model=MODEL)
    for nazwa, opis in STYLE_MAILI
]


# ══════════════════════════════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════════════════════════════
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

        tekst, odwiedzone = scrape_firme(url)
        if not tekst:
            return JSONResponse({
                "ok": False,
                "error": "Nie udało się pobrać strony (blokada bota lub strona nieosiągalna).",
            })

        wynik = await Runner.run(agent_ekstrakcja, f"URL: {url}\n\nTEKST ZE STRONY:\n{tekst}")
        firma = wynik.final_output.model_dump()
        firma["url"] = url
        firma["zrodlo_danych"] = odwiedzone
        # ścieżka, w której firma została zbadana — „Praca" rozdziela po niej listy
        firma["tryb"] = (body.get("tryb") or "partner").lower()
        baza.zapisz_firme(firma, firma["tryb"])
        return JSONResponse({"ok": True, "firma": firma})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def znajdz_firmy(zapytanie: str, wlasna_domena: str = "") -> dict:
    """Jedno zapytanie -> Tavily -> filtr -> kontrola żywotności."""
    wyniki = await asyncio.to_thread(tavily_search, zapytanie)
    return {"zapytanie": zapytanie,
            **await znajdz_firmy_z_wynikow(wyniki, wlasna_domena)}


async def znajdz_firmy_z_wynikow(wyniki: list, wlasna_domena: str = "") -> dict:
    """Filtr + deduplikacja + kontrola żywotności.
    Osobno od pobierania, bo Tryb B scala wyniki z kilku zapytań naraz."""
    firmy = filtruj_firmy(wyniki, wlasna_domena, limit=18)

    def sprawdz_wszystkie():
        with ThreadPoolExecutor(max_workers=12) as pool:
            return list(pool.map(lambda f: sprawdz_zywotnosc(f["url"]), firmy))

    # do_thread, bo pula wątków blokowałaby pętlę zdarzeń na czas kilkunastu żądań HTTP
    stany = await asyncio.to_thread(sprawdz_wszystkie)

    zostaja = []
    for f, stan in zip(firmy, stany):
        if stan == "martwa":
            continue
        if stan == "niepewna":
            f["niepewna"] = True  # front pokaże adnotację, user decyduje
        zostaja.append(f)

    return {
        "firmy": zostaja[:12],
        "z_seo": sum(1 for f in zostaja[:12] if f.get("ma_seo")),
        "odsiane_martwe": stany.count("martwa"),
    }


async def api_szukaj(request):
    """TRYB B — szukanie po kryteriach (branża + miasto), bez firmy wejściowej.

    Podział pracy: LLM robi to, w czym jest dobry — wymyśla synonimy branży i konkretne
    usługi. Lokalizację dokleja Python, bo to sklejenie stringów, a nie zrozumienie
    tekstu. Wcześniej jedno i drugie robił model i mylił się w 4 na 6 przebiegów.
    """
    try:
        if not (os.environ.get("TAVILY_API_KEY") or os.environ.get("TVLY_API_KEY")):
            return JSONResponse({"ok": False, "error": "Brak klucza Tavily w środowisku."})
        body = await request.json()
        branza = (body.get("branza") or "").strip()
        miasto = (body.get("miasto") or "").strip()
        if not branza:
            return JSONResponse({"ok": False, "error": "Podaj branżę lub typ firmy."})

        # LLM rozpisuje branżę na kilka RÓŻNYCH fraz — jedno zapytanie zwraca tylko TOP10
        # najlepiej wypozycjonowanych, a szukamy tych mniej widocznych (główny ból z PRD).
        # Agent dostaje SAMĄ branżę — o mieście nie ma prawa wiedzieć, więc nie ma go
        # skąd zmyślić. Miejsce doklejamy niżej, już poza modelem.
        r = await Runner.run(agent_warianty, f"Typ firmy: {branza}.")
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

        # Zapytanie zawsze układa LLM — user daje mu tylko wskazówki (zaznaczone usługi).
        if tagi:
            opis = (f"Branża: {firma.get('branza', '')}.\n"
                    f"USŁUGI WSKAZANE PRZEZ UŻYTKOWNIKA (zbuduj zapytanie WOKÓŁ NICH, "
                    f"uszanuj ten wybór): {', '.join(tagi)}.")
        else:
            # Bez wskazówek: wywalamy usługi konkurencyjne, inaczej sami prosimy o agencje SEO.
            uslugi = [u for u in firma.get("uslugi", [])
                      if not any(z in u.lower() for z in USLUGI_KONKURENCYJNE)][:5]
            opis = f"Branża: {firma.get('branza', '')}. Główne usługi: {', '.join(uslugi)}."

        r = await Runner.run(agent_zapytanie, opis)
        zapytanie = " ".join((r.final_output or "").strip().strip('"').split()[:8])

        wlasna = domena_z_url(firma.get("url", ""))
        return JSONResponse({"ok": True, **await znajdz_firmy(zapytanie, wlasna)})
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
        wyniki = await asyncio.gather(*[Runner.run(a, kontekst) for a in agenci_mail])
        maile = [
            {"styl": nazwa, "tresc": w.final_output}
            for (nazwa, _), w in zip(STYLE_MAILI, wyniki)
        ]
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
        # Jeden dostawca na audyt — nigdy dwaj naraz.
        dostawca = (body.get("dostawca") or "dataforseo").lower()
        # Można wybrać kilka modeli naraz — wtedy każde pytanie idzie do każdego z nich.
        wybrane = body.get("silniki") or [body.get("silnik") or "chatgpt_wprost"]
        silniki = [audyt.SILNIKI[k] for k in wybrane if k in audyt.SILNIKI]
        if dostawca == "seranking":
            # Twardy wymóg: wybór SE Ranking odcina DataForSEO CAŁKOWICIE.
            # Zostają wyłącznie silniki na własnym kluczu — inaczej audyt „na SE Ranking"
            # po cichu sięgałby po drugiego dostawcę i padał na jego saldzie.
            silniki = [s for s in silniki if s.get("wlasny_klucz")]
        if not silniki:
            silniki = [audyt.SILNIKI["chatgpt_wprost"]]
        koszt_kredytow = 0

        nazwa = firma.get("nazwa") or ""
        # .lower() JEST KONIECZNE. DataForSEO dopasowuje domenę wrażliwie na wielkość liter:
        # zapytanie o "Elektromaniacy.pl" zwróciło status 20000 Ok, policzyło $0.10
        # i oddało total_count=0 — cicha, płatna porażka. Domena musi być znormalizowana.
        domena = domena_z_url(firma.get("url", "")).strip()

        # 1) Prompty generuje NASZ model (tanio, mamy kontrolę) — nie DataForSEO
        opis = (f"Firma: {nazwa}\nBranża: {firma.get('branza','')}\n"
                f"Usługi: {', '.join(firma.get('uslugi', [])[:10])}\n"
                f"Miasto: {firma.get('miasto','')}\nOpis: {firma.get('opis','')}")
        r = await Runner.run(agent_prompty, f"Wygeneruj {ile} pytań.\n\n{opis}")
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
                rm = await Runner.run(agent_marki, f"Firma badana: {nazwa}\n\n{zlepek}")
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

        # 3) AI Overview — u SE Ranking to inny endpoint i inna jednostka rozliczeniowa.
        # UWAGA: inicjalizacja MUSI być tutaj, przed pierwszym przypisaniem. Wcześniej
        # `aio = None` stało niżej, między blokiem SE Ranking a blokiem DataForSEO,
        # i kasowało wynik SE Ranking zaraz po jego ustawieniu — sekcja znikała
        # z raportu mimo naliczonych kredytów.
        aio = None
        if z_aio and dostawca == "seranking":
            try:
                # Ich baza pokrywa pięć platform — można wziąć kilka naraz i pokazać
                # różnicę. To dokładnie ten wniosek, którego nie widać przy jednym
                # silniku: firma może być pierwsza w Google AI Mode i nieobecna
                # w ChatGPT, a obie liczby są prawdziwe.
                wybrane_sr = body.get("silniki_sr") or [body.get("silnik_sr") or "ai-overview"]
                wybrane_sr = [x for x in wybrane_sr if x in seranking.SILNIKI_AI] or ["ai-overview"]
                platformy = []
                for nazwa_pl in wybrane_sr:
                    sr, k = await asyncio.to_thread(
                        seranking.wzmianki_ai, domena, nazwa_pl, 10,
                        f"audyt_{domena}_{nazwa_pl}")
                    koszt_kredytow += k
                    w = seranking.analizuj_wzmianki(sr, domena, nazwa)
                    w["silnik_nazwa"] = seranking.SILNIKI_AI[nazwa_pl]
                    platformy.append(w)
                # pierwsza platforma zasila sekcję szczegółową, reszta idzie do
                # tabeli porównawczej — bez mieszania danych z różnych źródeł
                aio = platformy[0]
                if len(platformy) > 1:
                    aio["platformy"] = [
                        {"nazwa": p["silnik_nazwa"], "liczba": p["liczba_wzmianek"],
                         "srednia": p["srednia_pozycja"]} for p in platformy]
            except seranking.BladAPI:
                raise

        # 3b) AI Overview przez DataForSEO (opcjonalnie — najdroższy pojedynczy element)
        if z_aio and dostawca != "seranking":
            # Tak samo jak u SE Ranking: można wziąć kilka platform i pokazać różnicę.
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
        # Dostawcę wybiera użytkownik przed audytem i NIGDY nie mieszamy dwóch
        # w jednym dokumencie: jedna liczba, jedno podpisane źródło. Różnice znaczeń
        # (SE Ranking nie ma koszyka TOP 3, tylko TOP 5) niesie pole `etykieta_czolo`,
        # żeby raport nie podpisał liczby nazwą metryki, której nie dotyczy.
        seo = None
        if bool(body.get("seo", True)):
            if dostawca == "seranking":
                ov, fr, kk, st, k = await asyncio.to_thread(
                    seranking.dane_seo, domena, f"audyt_{domena}")
                koszt_kredytow += k
                # ruch konkurentów jest już w odpowiedzi domain/competitors
                seo = seranking.analizuj_seo(ov, fr, kk, st, domena, None, audyt.PORTALE)
                # Ta sama sekcja co przy DataForSEO, tylko z ich danych — bez
                # dodatkowego wywolania, bo block_type jest juz w odpowiedzi.
                seo["luka"] = seranking.luka_z_fraz(fr, domena)
                frazy = fr
            else:
                rank, konk, strony, frazy, ruch_konk, k = await asyncio.to_thread(
                    audyt.dane_seo, domena, f"audyt_seo_{domena}"
                )
                koszt += k
                seo = audyt.analizuj_seo(rank, konk, strony, domena, frazy, ruch_konk)

            # 4b) Luka GEO — zestawienie pozycji w Google z obecnoscia w AI Overview.
            # Wymaga danych z AIO (kto nas cytuje), wiec tylko gdy wlaczone.
            if dostawca != "seranking" and seo.get("frazy") and aio:
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
        raport["koszt_kredytow"] = koszt_kredytow
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
        # Saldo pytamy TYLKO tego dostawcy, którego faktycznie użyliśmy.
        # Wcześniej szło bezwarunkowo, więc audyt „na SE Ranking" i tak zaglądał
        # do DataForSEO — nieszkodliwie, ale wbrew zasadzie rozdzielenia.
        raport["saldo_po"] = dfs.saldo() if dostawca != "seranking" else None
        return JSONResponse({"ok": True, "raport": raport})
    except (dfs.BladAPI, seranking.BladAPI) as e:
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
    # pamięć — bez tego cała praca ginęła po odświeżeniu strony
    Route("/api/firmy", api_firmy, methods=["GET"]),
    Route("/api/firmy/usun", api_firma_usun, methods=["POST"]),
    Route("/api/koszyk", api_koszyk, methods=["POST"]),
    Route("/api/audyty", api_audyty, methods=["GET"]),
    Route("/api/audyt", api_audyt, methods=["POST"]),
    Route("/api/export", api_export, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=str(frontend_dir), html=True), name="frontend"),
])

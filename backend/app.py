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
    konkurent: bool              # czy GŁÓWNA oferta to SEO/SEM/GEO
    konkurent_uzasadnienie: str
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
)


def normalizuj_url(url: str) -> str | None:
    """Zwraca adres STRONY GŁÓWNEJ firmy albo None, jeśli to nie firma.

    Tavily często zwraca głęboki link (artykuł, /tag/, /baza-wiedzy/) na domenie realnej firmy.
    Kiedyś takie wyniki odrzucaliśmy — traciliśmy prawdziwych kandydatów (np. Convertis).
    Teraz ucinamy do strony głównej; scraper i tak sam znajdzie podstrony przy researchu.
    """
    u = url.lower()
    domena = urlparse(u).netloc.replace("www.", "")
    if not domena:
        return None
    if any(d in domena for d in DOMENY_ODPADAJACE):
        return None
    if domena.endswith(OBCE_TLD):
        return None
    if u.split("?")[0].endswith(ROZSZERZENIA):
        return None
    return f"https://{domena}"

# Tytuły artykułów, poradników i wydarzeń — to nie są firmy, tylko treści o branży.
FRAZY_NIE_FIRMA = (
    "jak zbudowa", "jak wybra", "jak zrobi", "jak dziala", "jak działa", "poradnik",
    "co to jest", "czym jest", "blog", "konferencja", "webinar", "targi", "szkolenie online",
    "przewodnik", " vs ", "porównanie", "porownanie", "definicja", "słownik", "slownik",
    "najlepsze w kategorii", "najwieksze agencje", "największe agencje", "warto zna",
)

# Zestawienia: "50 agencji digital", "Top 5 Najlepszych...". Kotwiczymy na POCZĄTKU tytułu,
# inaczej wpadały firmy typu "360agencja.pl" albo "Grupa 3 Agencja Reklamowa".
LISTICLE = re.compile(
    r"^\s*(top\s+)?\d{1,3}\s+(top\s+|best\s+)?(najlepsz|agencj|firm|software|companies)",
    re.IGNORECASE,
)

# Tytuły, po których ODRZUCAMY wynik nawet po ucięciu do strony głównej — bo cała domena
# okazuje się rankingiem, katalogiem albo portalem z ogłoszeniami, a nie firmą.
TYTULY_ODRZUCAJACE = (
    "ranking", "top 10", "top10", "directory", "katalog firm", "zestawienie",
    "najlepszych agencji", "najlepsze agencje", "oferty pracy", "praca ", " praca",
)


def tavily_search(zapytanie: str, max_results: int = 15) -> list:
    key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TVLY_API_KEY")
    if not key:
        return []
    return TavilyClient(api_key=key).search(zapytanie, max_results=max_results).get("results", [])


# Odsiewamy TYLKO jawne agencje SEO/pozycjonowania (SEO jako rdzeń oferty).
# Agencje SEM / Google Ads / marketingowe zostawiamy — to partnerzy komplementarni
# (oni płatne kampanie, my organiczne), nie konkurenci.
FRAZY_KONKURENTA = (
    "agencja seo", "agencji seo", "agencja pozycjonowania", "pozycjonowanie stron",
    "pozycjonowanie sklep", "seo agency", "specjalisci seo", "specjaliści seo",
)

# Usługi, których NIE wolno wpuścić do zapytania — inaczej szukamy własnych konkurentów.
USLUGI_KONKURENCYJNE = ("seo", "sem", "pozycjonowanie", "google ads", "meta ads", "adwords", "ppc")


def czy_konkurent_w_wyniku(tytul: str, url: str) -> bool:
    t = (tytul or "").lower()
    return any(f in t for f in FRAZY_KONKURENTA)


def filtruj_firmy(wyniki: list, wlasna_domena: str, limit: int = 10) -> tuple[list, int]:
    """Zostawia realne firmy. Odrzuca: katalogi/rankingi, badaną firmę, duplikaty domen
    oraz agencje SEO/SEM (konkurentów — nie są kandydatami na partnera).
    Zwraca (firmy, ile_odsianych_konkurentow)."""
    firmy, widziane, odsiani = [], set(), 0
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
        if czy_konkurent_w_wyniku(tytul, strona):
            odsiani += 1
            continue
        # tytuł artykułu/zestawienia nie opisuje firmy — lepiej pokazać domenę
        if not tytul or any(f in tytul.lower() for f in FRAZY_NIE_FIRMA) or LISTICLE.search(tytul):
            tytul = dom
        firmy.append({"nazwa": tytul[:60], "url": strona})
    return firmy[:limit], odsiani


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
    ("Konkurent", "konkurent"),
    ("Konkurent - uzasadnienie", "konkurent_uzasadnienie"),
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

KONKURENT (SEO/SEM/GEO) — to samo oznaczenie, NIE ocena wartości firmy.

TEST: czym firma NAZYWA SAMĄ SIEBIE? Patrz na pozycjonowanie marki (nagłówek, "kim jesteśmy",
jak się przedstawia), a NIE na to, czy słowo "SEO" pada gdziekolwiek na stronie.

konkurent = true TYLKO gdy firma przedstawia się jako agencja SEO / SEM / GEO / pozycjonowania,
czyli walczyłaby z nami o ten sam budżet klienta.

konkurent = false gdy firma przedstawia się jako coś innego (agencja e-commerce, software house,
branding, social media), NAWET JEŚLI:
- ma "optymalizację SEO" na liście usług obok kilkunastu innych,
- oferuje SEO jako dodatek do wdrożenia strony/sklepu,
- ma "Pozycjonowanie" w formularzu kontaktowym lub w menu,
- pisze "strona zoptymalizowana pod SEO".
To są wzmianki poboczne — NIE czynią firmy konkurentem.

PRZYKŁAD: firma opisująca się jako "agencja PrestaShop", z wdrożeniami sklepów jako rdzeniem
oferty, która ma też "optymalizację SEO" wśród kilkunastu usług => konkurent = FALSE
(rdzeniem są wdrożenia e-commerce, nie sprzedaż SEO).

W konkurent_uzasadnienie napisz, JAK firma sama się przedstawia i dlaczego to (nie) czyni jej konkurentem.

NIE oceniaj, czy firma jest dobrym partnerem. Dostarczasz dane — ocenia człowiek."""

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
    instructions="""Dostajesz typ firmy i (opcjonalnie) miasto. Wygeneruj 4 RÓŻNE zapytania
do wyszukiwarki, które znajdą takie firmy w Polsce.

CEL: dotrzeć do firm, które NIE są w TOP10 na najbardziej oczywistą frazę. Jedno zapytanie
zwraca wciąż tych samych liderów rynku; cztery różne wyciągają mniejsze, słabiej
wypozycjonowane firmy — a to one są najciekawsze jako partnerzy.

ZASADY:
- Każde zapytanie MAKSYMALNIE 5 słów.
- Warianty muszą się REALNIE różnić. Użyj kolejno:
  (1) nazwy branży, (2) synonimu / innej nazwy tej samej branży,
  (3) KONKRETNEJ USŁUGI, którą taka firma świadczy, (4) innej konkretnej usługi.
- Jeśli dostałeś miasto — dodaj je do KAŻDEGO wariantu. Jeśli nie — dodaj "Polska".
- NIGDY fraz typu "ranking", "top 10", "najlepsze", "opinie", "cennik".
- Nie dodawaj od siebie SEO/SEM/marketing, chyba że to wprost wskazana branża.

Przykład dla "agencja brandingowa" + "Kraków":
  agencja brandingowa Kraków | studio brandingowe Kraków |
  projektowanie identyfikacji wizualnej Kraków | tworzenie logo marki Kraków""",
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
        return JSONResponse({"ok": True, "firma": firma})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


def znajdz_firmy(zapytanie: str, wlasna_domena: str = "") -> dict:
    """Jedno zapytanie -> Tavily -> filtr -> kontrola żywotności."""
    return {"zapytanie": zapytanie,
            **znajdz_firmy_z_wynikow(tavily_search(zapytanie), wlasna_domena)}


def znajdz_firmy_z_wynikow(wyniki: list, wlasna_domena: str = "") -> dict:
    """Filtr + deduplikacja + kontrola żywotności na gotowej puli wyników.
    Osobno od pobierania, bo Tryb B scala wyniki z kilku zapytań naraz."""
    firmy, odsiani = filtruj_firmy(wyniki, wlasna_domena, limit=18)

    with ThreadPoolExecutor(max_workers=12) as pool:
        stany = list(pool.map(lambda f: sprawdz_zywotnosc(f["url"]), firmy))

    zostaja = []
    for f, stan in zip(firmy, stany):
        if stan == "martwa":
            continue
        if stan == "niepewna":
            f["niepewna"] = True  # front pokaże adnotację, user decyduje
        zostaja.append(f)

    return {
        "firmy": zostaja[:12],
        "odsiani_konkurenci": odsiani,
        "odsiane_martwe": stany.count("martwa"),
    }


async def api_szukaj(request):
    """TRYB B — szukanie po kryteriach (branża + miasto), bez firmy wejściowej.

    Zapytanie składamy DETERMINISTYCZNIE (zasada z PRD) — user sam podaje branżę i miasto,
    więc nie ma czego zgadywać przez LLM. Zero kosztu tokenów.
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
        polecenie = f"Typ firmy: {branza}." + (f" Miasto: {miasto}." if miasto else "")
        r = await Runner.run(agent_warianty, polecenie)
        warianty = [" ".join(z.split()[:6]) for z in (r.final_output.zapytania or [])][:4]
        if not warianty:
            warianty = [f"{branza} {miasto}".strip() or f"{branza} Polska"]

        # Wszystkie warianty równolegle, potem scalamy w jedną pulę wyników.
        with ThreadPoolExecutor(max_workers=4) as pool:
            partie = list(pool.map(lambda q: tavily_search(q, max_results=10), warianty))
        wszystkie = [w for partia in partie for w in partia]

        wynik = znajdz_firmy_z_wynikow(wszystkie)
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

        wlasna = urlparse(firma.get("url", "")).netloc.replace("www.", "").lower()
        return JSONResponse({"ok": True, **znajdz_firmy(zapytanie, wlasna)})
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
        domena = urlparse(firma.get("url", "")).netloc.replace("www.", "").strip().lower()

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
                silnik_sr = (body.get("silnik_sr") or "ai-overview")
                if silnik_sr not in seranking.SILNIKI_AI:
                    silnik_sr = "ai-overview"
                sr, k = await asyncio.to_thread(
                    seranking.wzmianki_ai, domena, silnik_sr, 10, f"audyt_{domena}")
                koszt_kredytow += k
                aio = seranking.analizuj_wzmianki(sr, domena)
                aio["silnik_nazwa"] = seranking.SILNIKI_AI[silnik_sr]
            except seranking.BladAPI:
                raise

        # 3b) AI Overview przez DataForSEO (opcjonalnie — najdroższy pojedynczy element)
        if z_aio and dostawca != "seranking":
            odp_aio = await asyncio.to_thread(
                audyt.wzmianki_ai_overview, domena, 10, f"audyt_aio_{domena}"
            )
            koszt += odp_aio.get("cost", 0)
            aio = audyt.analizuj_ai_overview(odp_aio, domena)

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
    Route("/api/audyt", api_audyt, methods=["POST"]),
    Route("/api/export", api_export, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=str(frontend_dir), html=True), name="frontend"),
])

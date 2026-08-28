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
from agents import Agent, Runner

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
    telefon: str
    email: str
    persona: str                 # ⚠️ do potwierdzenia: osoba decyzyjna (imię + stanowisko)
    konkurent: bool              # czy GŁÓWNA oferta to SEO/SEM/GEO
    konkurent_uzasadnienie: str
    opis: str                    # 2-3 zdania, czym firma się zajmuje


# ══════════════════════════════════════════════════════════════════════
#  SCRAPER — zwykła funkcja, wielostronicowy
#  Homepage nie wystarcza: zespół, realizacje i kontakt są na podstronach.
# ══════════════════════════════════════════════════════════════════════
SLOWA_PODSTRON = (
    "o-nas", "o_nas", "about", "zespol", "zespół", "team",
    "realizacje", "portfolio", "case", "projekty", "wdrozenia", "wdrożenia",
    "kontakt", "contact",
    "oferta", "uslugi", "usługi", "services",
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
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def znajdz_podstrony(html: str, base_url: str) -> list[str]:
    """Z menu/linków wybiera podstrony, gdzie realnie są dane (o nas, realizacje, kontakt)."""
    soup = BeautifulSoup(html, "html.parser")
    domena = urlparse(base_url).netloc
    znalezione, widziane = [], set()
    for a in soup.find_all("a", href=True):
        pelny = urljoin(base_url, a["href"]).split("#")[0].split("?")[0].rstrip("/")
        if urlparse(pelny).netloc != domena or pelny in widziane:
            continue
        if any(p in pelny.lower() for p in POMIJAJ):
            continue
        if any(s in pelny.lower() for s in SLOWA_PODSTRON):
            widziane.add(pelny)
            znalezione.append(pelny)
    return znalezione[:MAX_PODSTRON]


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
KATALOGI = (
    # katalogi firm i agregatory
    "clutch.co", "sortlist", "themanifest", "goodfirms", "designrush", "techbehemoths",
    "topcssgallery", "infoisinfo", "biznesfinder", "panoramafirm", "pkt.pl", "aleo.com",
    "firmy.net", "zumi.pl", "targeo", "oferteo", "ceneo", "opineo", "useme",
    "rocketreach", "emailformats", "signalhire", "lusha", "apollo.io",
    # portale, social, fora
    "wikipedia", "facebook", "linkedin", "instagram", "youtube", "egospodarka",
    "wordpress.org", "domenomania", "forum.", "/forum",
    "trustpilot", "zleca.pl", "/wykonawcy/", "/categories/", "marketingibiznes",
    # strony przeglądowe, nie firmy
    "/tag/", "/tematy/", "/karta/", "/kategoria/", "/category/", "/szukaj", "/search",
    "/newsy", "/aktualnosci",
    "/ranking", "najlepsze-", "top-10", "top10", "firm-i-agencji", "/blog/", "/artykul",
)

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
LISTICLE = re.compile(r"^\s*(top\s*)?\d{1,3}\s+(najlepsz|agencj|firm|software)", re.IGNORECASE)


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
    ("Branza", "branza"),
    ("Uslugi", "uslugi"),
    ("Wielkosc zespolu", "wielkosc_zespolu"),
    ("Liczba projektow", "liczba_projektow"),
    ("Case studies", "case_studies"),
    ("Phone", "telefon"),
    ("Email", "email"),
    ("Persona", "persona"),
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
- telefon / email: TYLKO jeśli faktycznie są w tekście
- persona: osoba decyzyjna wymieniona na stronie (imię + stanowisko), np. "Jan Kowalski, CEO"
- opis: 2-3 zdania, czym firma się zajmuje

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
- NIGDY nie używaj słów: SEO, SEM, pozycjonowanie, Google Ads, marketing.
  Szukamy PARTNERÓW, nie agencji marketingowych.
- NIGDY fraz typu "ranking", "top 10", "najlepsze firmy".

Zwróć TYLKO samo zapytanie, bez cudzysłowów i komentarza.""",
    model=MODEL_TANI,
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
        if not url.startswith("http"):
            url = "https://" + url

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

        # Deterministycznie: wywalamy usługi konkurencyjne (inaczej szukamy agencji SEO)
        # i ograniczamy listę — długie zapytanie = śmieciowe wyniki.
        uslugi = [u for u in firma.get("uslugi", [])
                  if not any(z in u.lower() for z in USLUGI_KONKURENCYJNE)][:5]
        opis = f"Branża: {firma.get('branza', '')}. Główne usługi: {', '.join(uslugi)}."

        r = await Runner.run(agent_zapytanie, opis)
        zapytanie = " ".join((r.final_output or "").strip().strip('"').split()[:8])

        wlasna = urlparse(firma.get("url", "")).netloc.replace("www.", "").lower()
        firmy, odsiani = filtruj_firmy(tavily_search(zapytanie), wlasna, limit=14)

        # Kontrola żywotności — równolegle, żeby nie czekać po kolei na 14 stron.
        with ThreadPoolExecutor(max_workers=10) as pool:
            stany = list(pool.map(lambda f: sprawdz_zywotnosc(f["url"]), firmy))

        zostaja = []
        for f, stan in zip(firmy, stany):
            if stan == "martwa":
                continue
            if stan == "niepewna":
                f["niepewna"] = True  # front pokaże adnotację, user decyduje
            zostaja.append(f)

        return JSONResponse({
            "ok": True,
            "firmy": zostaja[:10],
            "zapytanie": zapytanie,
            "odsiani_konkurenci": odsiani,
            "odsiane_martwe": stany.count("martwa"),
        })
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
    Route("/api/email", api_email, methods=["POST"]),
    Route("/api/columns", api_columns, methods=["GET"]),
    Route("/api/export", api_export, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=str(frontend_dir), html=True), name="frontend"),
])

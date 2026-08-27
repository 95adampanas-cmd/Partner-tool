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
from urllib.parse import urlparse, urljoin
import csv
import io
import os

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
    "clutch.co", "sortlist", "themanifest", "goodfirms", "designrush", "techbehemoths",
    "topcssgallery", "wikipedia", "facebook", "linkedin", "instagram", "youtube",
    "oferteo", "ceneo", "opineo", "wordpress.org", "domenomania",
    "/ranking", "najlepsze-", "top-10", "top10", "firm-i-agencji", "/blog/",
)


def tavily_search(zapytanie: str, max_results: int = 15) -> list:
    key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TVLY_API_KEY")
    if not key:
        return []
    return TavilyClient(api_key=key).search(zapytanie, max_results=max_results).get("results", [])


def filtruj_firmy(wyniki: list, wlasna_domena: str, limit: int = 10) -> list:
    """Zostawia realne firmy: bez katalogów/rankingów, bez badanej firmy, bez duplikatów domen."""
    firmy, widziane = [], set()
    for r in wyniki:
        url = r.get("url", "")
        dom = urlparse(url).netloc.replace("www.", "").lower()
        if not dom or dom in widziane:
            continue
        if wlasna_domena and wlasna_domena in dom:
            continue
        if any(k in url.lower() for k in KATALOGI):
            continue
        widziane.add(dom)
        firmy.append({"nazwa": (r.get("title") or dom)[:60], "url": url})
    return firmy[:limit]


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
    instructions="""Dostajesz opis firmy (branża + usługi). Napisz JEDNO krótkie zapytanie
do wyszukiwarki (po polsku), które znajdzie REALNE firmy z tej samej branży w Polsce.
Używaj fraz USŁUGOWYCH (np. "agencja e-commerce PrestaShop", "tworzenie stron WordPress Poznań"),
NIGDY fraz typu "ranking / top 10 / najlepsze firmy". Zwróć TYLKO samo zapytanie, bez cudzysłowów.""",
    model=MODEL_TANI,
)


class DraftyMaili(BaseModel):
    maile: list[str]


agent_mail = Agent(
    name="mail",
    instructions="""Piszesz maile otwierające do potencjalnych partnerów Last Agency
(agencja SEO/SEM/GEO/AI Search) — model referral i white-label.

Dostajesz: (1) dane firmy z researchu, (2) bazę wiedzy mailingu z przykładami.
Napisz DOKŁADNIE 3 różne propozycje maila, dopasowane do branży i usług tej firmy.

ZASADY:
- trzymaj styl i ton z bazy wiedzy mailingu
- odwołuj się do KONKRETÓW z researchu (usługi, realizacje, branża) — nie ogólniki
- nie zmyślaj faktów o firmie; jeśli czegoś nie ma w danych, nie wspominaj o tym
- każdy mail krótki, gotowy do wysłania, z tematem w pierwszej linii
- 3 propozycje mają się realnie różnić podejściem (nie 3 warianty tego samego zdania)""",
    output_type=DraftyMaili,
    model=MODEL,
)


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
        opis = f"Branża: {firma.get('branza', '')}. Usługi: {', '.join(firma.get('uslugi', []))}."

        r = await Runner.run(agent_zapytanie, opis)
        zapytanie = (r.final_output or "").strip().strip('"')

        wlasna = urlparse(firma.get("url", "")).netloc.replace("www.", "").lower()
        firmy = filtruj_firmy(tavily_search(zapytanie), wlasna)
        return JSONResponse({"ok": True, "firmy": firmy, "zapytanie": zapytanie})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def api_email(request):
    """Funkcja 3 — 3 drafty maila na bazie docs/email-examples.md."""
    try:
        body = await request.json()
        firma = body.get("firma") or {}
        kontekst = (
            f"DANE FIRMY:\n{firma}\n\n"
            f"BAZA WIEDZY MAILINGU (styl i przykłady):\n{baza_maili()}"
        )
        r = await Runner.run(agent_mail, kontekst)
        return JSONResponse({"ok": True, "maile": r.final_output.maile})
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

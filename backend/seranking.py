"""
SE Ranking — drugi dostawca danych do mikroaudytu, obok DataForSEO.

Zasada: NIGDY nie mieszamy dostawców w jednym raporcie. Użytkownik wybiera jednego
przed audytem, a raport podpisuje się jego nazwą — tak jak audyty ICEA podpisują
każdy wykres („Dane z narzędzia Senuto"). Dzięki temu żadna liczba nie udaje, że
pochodzi skądinąd.

CZEGO SE RANKING NIE POTRAFI: przyjąć naszego własnego pytania. Ich AI Search API
zwraca wyłącznie prompty z własnej bazy, w których domena JUŻ się pojawia, i jest
odświeżane raz w miesiącu. Nie da się więc zadać pytania klienta, który firmy nie zna —
a to jest sedno sekcji „Jak AI odpowiada na pytania klientów". Ta sekcja działa
wyłącznie na DataForSEO.

RÓŻNICE ZNACZEŃ, których NIE WOLNO zatrzeć:
  - SE Ranking dzieli pozycje na 1-5 / 6-10 / 11-20 / 21-50 / 51-100.
    Nie ma koszyka TOP 3. Raport musi więc napisać „fraz w TOP 5", a nie „TOP 3" —
    stąd pole `etykieta_czolo` w zwracanym słowniku.
  - Ich endpoint konkurentów nie podaje ruchu konkurenta. Żeby go poznać, trzeba
    odpytać osobno o każdą domenę (100 kredytów za sztukę).

KOSZT (kredyty, wg dokumentacji API):
  overview 100 · keywords 100 · competitors 100 · pages 100 · discover-brand 100
  prompts-by-target 200 za prompt
  Pełny audyt ≈ 2 500 kredytów. Trial daje 100 000, czyli ok. 40 audytów.

UWAGA: kształty ZAPYTAŃ pochodzą z dokumentacji. Kształty ODPOWIEDZI trzeba
potwierdzić na żywym kluczu — parsery są napisane defensywnie (wszędzie .get),
ale dopóki nie zobaczymy prawdziwego JSON-a, traktujemy je jako niezweryfikowane.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
import json
import os
import threading
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

# Modul bywa uzywany samodzielnie (sonda diagnostyczna), nie tylko przez app.py,
# wiec wczytuje .env u siebie — tak samo jak dfs.py.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

BAZA = "https://api.seranking.com/v1"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
KRAJ_PL = "pl"

# ile kredytów kosztuje co — do pokazania użytkownikowi przed audytem
# Silniki, dla których SE Ranking ma dane o wzmiankach. To ICH baza — nie da się
# zadać własnego pytania, ale da się sprawdzić, gdzie domena jest cytowana w każdym
# z nich. Dzięki temu audyt na SE Ranking nie musi w ogóle dotykać DataForSEO.
SILNIKI_AI = {
    "ai-overview": "Google AI Overviews",
    "ai-mode":     "Google AI Mode",
    "chatgpt":     "ChatGPT",
    "perplexity":  "Perplexity",
    "gemini":      "Google Gemini",
}

KOSZTY = {
    "overview": 100, "keywords": 100, "competitors": 100,
    "pages": 100, "discover_brand": 100, "prompt": 200,
}


class BladAPI(RuntimeError):
    """Zapytanie odrzucone przez SE Ranking."""


# SE Ranking ma ostry limit zapytań — 429 „too many requests" wraca nawet przy
# wywołaniach sekwencyjnych z krótką przerwą. Pilnujemy więc minimalnego odstępu
# GLOBALNIE (nie w pojedynczej funkcji), bo audyt woła kilka miejsc naraz,
# i dodatkowo ponawiamy z rosnącym odczekaniem. Inaczej audyt przerywa się
# w połowie i zużyte kredyty przepadają bez raportu.
ODSTEP_MIN = 1.5
PROBY_429 = 4
_ostatnie = [0.0]
_zamek = threading.Lock()


def _przepustnica() -> None:
    with _zamek:
        czekaj = ODSTEP_MIN - (time.monotonic() - _ostatnie[0])
        if czekaj > 0:
            time.sleep(czekaj)
        _ostatnie[0] = time.monotonic()


def _klucz() -> str:
    k = os.environ.get("SERANKING_API_KEY", "")
    if not k:
        raise BladAPI("Brak SERANKING_API_KEY w .env — załóż konto i wklej klucz API.")
    return k


def _get(sciezka: str, params: dict, nazwa_fixture: str | None = None) -> dict:
    """GET do API. Zapisuje surową odpowiedź do fixtures/ — tak samo jak przy
    DataForSEO, żeby dało się później zweryfikować raport bez płacenia drugi raz."""
    url = f"{BAZA}/{sciezka.lstrip('/')}?{urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Token {_klucz()}",
        "Accept": "application/json",
    })
    odp = None
    for proba in range(PROBY_429):
        _przepustnica()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                odp = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            tresc = e.read().decode("utf-8", "ignore")[:300]
            if e.code == 429 and proba < PROBY_429 - 1:
                czekaj = 3.0 * (proba + 1)
                print(f"  [SE Ranking: limit zapytań, ponawiam za {czekaj:.0f}s]")
                time.sleep(czekaj)
                continue
            if e.code == 429:
                raise BladAPI(
                    f"[{sciezka}] SE Ranking odrzuca zapytania (limit przekroczony) "
                    f"mimo {PROBY_429} prób. Odczekaj minutę i spróbuj ponownie.")
            raise BladAPI(f"[{sciezka}] SE Ranking odrzuciło zapytanie (HTTP {e.code}). {tresc}")
        except Exception as e:
            raise BladAPI(f"[{sciezka}] Nie udało się połączyć z SE Ranking: {e}")

    if nazwa_fixture:
        FIXTURES.mkdir(exist_ok=True)
        (FIXTURES / f"{nazwa_fixture}.json").write_text(
            json.dumps(odp, ensure_ascii=False, indent=1), encoding="utf-8")
    # Błąd bywa w treści odpowiedzi mimo HTTP 200 — ta lekcja kosztowała nas
    # raport pełen zer przy DataForSEO, więc sprawdzamy od razu.
    if isinstance(odp, dict) and odp.get("error"):
        raise BladAPI(f"[{sciezka}] SE Ranking zwróciło błąd: {odp.get('error')}")
    print(f"[SE Ranking {sciezka}] ok")
    return odp


# ══════════════════════════════════════════════════════════════════
#  ZBIERANIE
# ══════════════════════════════════════════════════════════════════
def dane_seo(domena: str, nazwa_fixture: str = "") -> tuple[dict, dict, dict, dict, int]:
    """Cztery wywołania = odpowiednik sekcji „Widoczność w Google". ~400 kredytów."""
    f = lambda n: f"{nazwa_fixture}_{n}" if nazwa_fixture else None
    baza = {"source": KRAJ_PL, "domain": domena}

    def pobierz(co):
        if co == "overview":
            return _get("domain/overview/db", baza, f("sr_overview"))
        if co == "keywords":
            return _get("domain/keywords", {**baza, "limit": 100, "sort": "traffic",
                                            "sort_order": "desc"}, f("sr_frazy"))
        if co == "competitors":
            return _get("domain/competitors", {**baza, "limit": 20}, f("sr_konk"))
        return _get("domain/pages", {"source": KRAJ_PL, "target": domena,
                                     "scope": "domain", "limit": 10}, f("sr_strony"))

    # SEKWENCYJNIE, nie równolegle. Sonda pokazała, że przy czterech wywołaniach naraz
    # SE Ranking odsyła HTTP 429 „too many requests" — inaczej niż DataForSEO, które
    # znosi sześć wątków. Pół sekundy przerwy wystarcza.
    # Odstęp pilnuje _przepustnica() w _get, więc tu tylko kolejność.
    wyniki = [pobierz(co) for co in ("overview", "keywords", "competitors", "pages")]
    overview, frazy, konk, strony = wyniki
    return overview, frazy, konk, strony, sum(
        KOSZTY[k] for k in ("overview", "keywords", "competitors", "pages"))


# ruch_domen() usunięte: sonda pokazała, że domain/competitors zwraca `traffic_sum`
# dla każdego konkurenta od razu. Dopytywanie o każdą domenę osobno kosztowałoby
# 800 kredytów na audyt za dane, które i tak już mamy w odpowiedzi.


def wzmianki_ai(domena: str, silnik: str = "ai-overview", limit: int = 10,
                nazwa_fixture: str = "") -> tuple[dict, int]:
    """Prompty, w których domena jest cytowana w wynikach LLM.

    Silniki: ai-overview | chatgpt | perplexity | gemini | ai-mode.
    To NIE jest odpowiednik naszej sekcji z pytaniami klientów — tu dostajemy
    prompty z ich bazy, a nie odpowiedzi na pytania, które sami układamy.
    """
    # `source` i `scope` są wymagane — bez nich API odsyła 500 („source can't be empty",
    # potem „scope can't be empty"). Ustalone sondą, w dokumentacji tego nie było.
    odp = _get("ai-search/prompts-by-target",
               {"target": domena, "engine": silnik, "limit": limit,
                "source": KRAJ_PL, "scope": "domain"},
               f"{nazwa_fixture}_sr_ai" if nazwa_fixture else None)
    return odp, KOSZTY["prompt"] * limit


# ══════════════════════════════════════════════════════════════════
#  PARSERY → ten sam kształt, który raport już umie wyświetlić
# ══════════════════════════════════════════════════════════════════
PORTALE_IMPORT = None  # ustawiane przez app.py, żeby nie duplikować listy


def analizuj_seo(overview: dict, frazy: dict, konk: dict, strony: dict,
                 domena: str, ruch_konkurentow: dict | None = None,
                 portale: tuple = ()) -> dict:
    """Zwraca dokładnie taki słownik, jaki produkuje audyt.analizuj_seo dla DataForSEO —
    z jednym wyjątkiem: `etykieta_czolo` mówi, czy liczba dotyczy TOP 3 czy TOP 5.
    Bez tego raport wypisałby „fraz w TOP 3" pod liczbą, która obejmuje pozycje 1-5."""
    org = (overview.get("organic") or {}) if isinstance(overview, dict) else {}

    # Ich koszyk to 1-5. TOP 3 policzymy dokładnie z listy fraz, jeśli ją mamy.
    lista_fraz = frazy if isinstance(frazy, list) else (frazy or {}).get("keywords") or []
    poz = [k.get("position") for k in lista_fraz if isinstance(k.get("position"), int)]
    top3_dokladnie = sum(1 for p in poz if p <= 3) if poz else None

    # Domyślnie bierzemy ICH kompletną liczbę (TOP 1-5) i podpisujemy ją zgodnie
    # z prawdą. TOP 3 liczymy tylko wtedy, gdy mamy PEŁNĄ listę fraz — inaczej byłaby
    # to liczba z 2% zbioru (100 pobranych z 4322) podana jako metryka całej domeny,
    # czyli dokładnie ten sam błąd co „średnia z próbki" w sekcji AI Overviews.
    pelna_lista = bool(poz) and len(lista_fraz) >= (org.get("keywords_count") or 0)
    if pelna_lista:
        czolo, etykieta = top3_dokladnie, "fraz w TOP 3"
    else:
        czolo, etykieta = (org.get("top1_5") or 0), "fraz w TOP 5"

    lista_konk = konk if isinstance(konk, list) else (konk or {}).get("competitors") or []
    konkurenci = []
    for k in lista_konk:
        d = (k.get("domain") or "").lower()
        if not d or d == domena or any(p in d for p in portale):
            continue
        konkurenci.append({
            "domena": d,
            "wspolne_frazy": k.get("common_keywords") or 0,
            # traffic_sum przychodzi wprost z domain/competitors — potwierdzone sondą
            "ruch_calkowity": round(k.get("traffic_sum") or 0) or None,
            # SE Ranking nie podaje średniej pozycji konkurenta. `domain_relevance`
            # to ICH miara podobieństwa profilu fraz — wartości typu 0,5 czy 40,64
            # nie są pozycjami i wpisanie ich pod taką nazwą byłoby kłamstwem.
            "srednia_pozycja": None,
            "podobienstwo": k.get("domain_relevance"),
        })

    lista_stron = strony if isinstance(strony, list) else (strony or {}).get("pages") or []
    top_strony = [{"adres": s.get("url") or "",
                   "fraz": s.get("keywords_count") or 0,
                   "ruch": round(s.get("traffic_sum") or 0)}
                  for s in lista_stron[:8]]

    INFORMACYJNE = ("co to", "czym jest", "jak ", "znaczenie", "definicja",
                    "dlaczego", "kiedy ", "ile ", "czy ")
    # Deduplikacja — SE Ranking zwraca ranking per URL, więc „twoj startup" pojawia
    # się dwa razy z pozycjami #1 i #2. Zostawiamy najlepszą.
    najlepsze_fr = {}
    for k in lista_fraz:
        kl = (k.get("keyword") or "").lower()
        if not kl:
            continue
        p_ = najlepsze_fr.get(kl)
        if not p_ or (k.get("position") or 999) < (p_.get("position") or 999):
            najlepsze_fr[kl] = k

    frazy_out = []
    for k in sorted(najlepsze_fr.values(), key=lambda x: (x.get("position") or 999))[:12]:
        fraza = k.get("keyword") or ""
        frazy_out.append({
            "typ": "informacyjna" if any(i in f" {fraza.lower()} " for i in INFORMACYJNE)
                   else "handlowa",
            "fraza": fraza,
            "pozycja": k.get("position"),
            "wolumen": k.get("volume") or 0,
            "ruch": round(k.get("traffic") or 0),
        })

    fraz_lacznie = org.get("keywords_count") or 0
    return {
        "dane_wiarygodne": fraz_lacznie >= 30,
        "etykieta_czolo": etykieta,
        "top3": czolo,
        "top10": (org.get("top1_5") or 0) + (org.get("top6_10") or 0),
        "fraz_lacznie": fraz_lacznie,
        "ruch": round(org.get("traffic_sum") or 0),
        "ruch_nasz_calkowity": round(org.get("traffic_sum") or 0),
        # Sonda pokazała, że jednak podają — pod innymi nazwami niż DataForSEO.
        "wzrosty": org.get("keywords_up_count"),
        "spadki": org.get("keywords_down_count"),
        "nowe": org.get("keywords_new_count"),
        "utracone": org.get("keywords_lost_count"),
        "konkurenci": konkurenci[:8],
        "frazy": frazy_out,
        # NIE podajemy len(lista) jako liczby wszystkich podstron — to tylko tyle,
        # ile pobraliśmy. Bez danych o całości zwracamy None, a raport pomija zdanie.
        "podstron_widocznych": None,
        "top_podstrony": top_strony,
        "zrodlo": "SE Ranking · baza Google PL",
        "data_bazy": "",
    }


def luka_z_fraz(frazy, domena: str, limit: int = 8) -> list[dict]:
    """Sekcja „Luka między Google a AI" na danych SE Ranking.

    Oni nie mają SERP-a na żądanie (ich śledzenie jest projektowe), ale pole
    `block_type` w domain/keywords mówi, w jakim bloku wyniku strona się pojawia.
    Wartość „sge" = Search Generative Experience, czyli blok AI Overview.

    OGRANICZENIE, którego NIE zacieramy: wiemy tylko, gdzie strona JEST w bloku AI.
    Gdy jej tam nie ma, nie wiemy, czy AI Overview w ogóle się na tej frazie pojawia —
    a to dwie różne rzeczy. Takie wiersze dostają status „nie ustalono", nigdy
    „nie cytują Was". Ten sam wybór zrobiliśmy przy niepełnej próbce w DataForSEO.
    """
    lista = frazy if isinstance(frazy, list) else (frazy or {}).get("keywords") or []
    INFORMACYJNE = ("co to", "czym jest", "jak ", "znaczenie", "definicja",
                    "dlaczego", "kiedy ", "ile ", "czy ")
    # Deduplikacja po frazie: SE Ranking zwraca ranking per URL, więc ta sama fraza
    # potrafi wystąpić kilka razy dla różnych podstron. Zostawiamy najlepszą pozycję.
    najlepsze = {}
    for k in lista:
        f = (k.get("keyword") or "").lower()
        if not f:
            continue
        poprz = najlepsze.get(f)
        if not poprz or (k.get("position") or 999) < (poprz.get("position") or 999):
            najlepsze[f] = k

    wiersze = []
    for k in najlepsze.values():
        fraza = k.get("keyword") or ""
        w_sge = (k.get("block_type") or "").lower() == "sge"
        wiersze.append({
            "fraza": fraza,
            "wolumen": k.get("volume") or 0,
            "typ": "informacyjna" if any(i in f" {fraza.lower()} " for i in INFORMACYJNE)
                   else "handlowa",
            "pozycja": k.get("position"),
            # None, nie False: brak strony w bloku AI nie dowodzi, że bloku nie ma.
            # False oznaczałoby „sprawdziliśmy i AI Overview się nie pojawia".
            "ma_aio": True if w_sge else None,
            "cytowany_w_aio": w_sge,
            "nieustalone": not w_sge,
            "koszt": 0,
        })
    # Sortujemy CAŁĄ listę, dopiero potem tniemy — inaczej frazy z blokiem AI
    # wypadały poza limit i sekcja pokazywała same „nie ustalono".
    wiersze.sort(key=lambda w: (w["nieustalone"], w["pozycja"] or 999))
    return wiersze[:limit]


def analizuj_wzmianki(odp: dict, domena: str, marka: str = "") -> dict:
    """Sekcja AI Overviews z danych SE Ranking. Ich odpowiedź niesie też treść
    odpowiedzi modelu i cytowane linki — więcej, niż daje llm_mentions."""
    lista = odp if isinstance(odp, list) else (odp or {}).get("prompts") or []
    # patrz komentarz w audyt.analizuj_ai_overview — cytowanie jako źródło
    # to nie to samo co wymienienie marki w treści odpowiedzi
    from audyt import warianty_marki, bez_etykiet_zrodel
    warianty = warianty_marki(marka, domena) if (marka or domena) else []

    wzmianki = []
    for it in lista:
        odpowiedz = it.get("answer") or {}
        linki = odpowiedz.get("links") or []
        tekst_odp = odpowiedz.get("text") or ""
        bez_podpisow = bez_etykiet_zrodel(tekst_odp, warianty).lower()
        wzmianki.append({
            "wymieniona": any(w in bez_podpisow for w in warianty),
            "prompt": it.get("prompt") or "",
            "wolumen": it.get("volume") or 0,
            "zrodla": [str(l) for l in linki],
            "pozycja": next((i + 1 for i, l in enumerate(linki)
                             if domena.lower() in str(l).lower()), None),
            "tekst": odpowiedz.get("text") or "",
        })
    pozycje = [w["pozycja"] for w in wzmianki if w["pozycja"]]
    total = (odp or {}).get("total") if isinstance(odp, dict) else None
    return {
        "wymienionych": sum(1 for w in wzmianki if w["wymieniona"]),
        "liczba_wzmianek": total if total is not None else len(wzmianki),
        "pobrano": len(wzmianki),
        "srednia_pozycja": round(sum(pozycje) / len(pozycje), 2) if pozycje else None,
        "probka_niepelna": bool(total and len(wzmianki) < total),
        "wzmianki": sorted(wzmianki, key=lambda w: w["wolumen"], reverse=True),
    }

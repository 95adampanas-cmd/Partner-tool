"""
Mikroaudyt SEO/GEO — zbieranie danych i składanie raportu (Faza 2).

Struktura wg docs/audyt-struktura.md (wzorzec: audyt ICEA + uwagi specjalisty).

OSZCZĘDZANIE BUDŻETU: każda funkcja zbierająca ma tryb `offline` — czyta zapisaną
próbkę z fixtures/ zamiast wołać API. Cały rozwój parserów i szablonu robimy offline;
do API sięgamy dopiero przy realnym audycie.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import re

import dfs

# Silnik domyślny: Perplexity sonar. Test na tym samym prompcie dał 9 marek konkurencyjnych
# za $0.006, podczas gdy ChatGPT (gpt-5.6-sol) dał 3 marki za $0.109 — 18x drożej.
SILNIK_DOMYSLNY = ("perplexity", "sonar")
SILNIK_CHATGPT = ("chat_gpt", "gpt-5.6-sol")

# Który silnik pytamy — wybiera użytkownik. Udział w rynku PL jest tu istotny:
# raport pokazuje wykres, na którym ChatGPT ma 86,4%, więc badanie wyłącznie
# Perplexity (6,18%) tworzy niespójność między tym, co mówimy, a co mierzymy.
# Raport musi napisać wprost, którego modelu pytaliśmy i jaki ma udział.
# Modele potwierdzone darmowym endpointem .../llm_responses/models — wszystkie
# obsługują wyszukiwanie w sieci, więc odpowiadają na podstawie aktualnych stron,
# a nie samej pamięci modelu.
SILNIKI = {
    # ChatGPT pytany BEZPOŚREDNIO naszym kluczem OpenAI — jedyny silnik, który nie
    # zależy od DataForSEO ani SE Ranking. Dzięki niemu sekcja z pytaniami klientów
    # działa niezależnie od tego, który dostawca SEO jest wybrany i czy ma środki.
    "chatgpt_wprost": {"silnik": ("openai", "wprost"), "nazwa": "ChatGPT (bezpośrednio)",
                       "udzial": 86.4, "koszt": 0.012, "wlasny_klucz": True},
    # Claude pytany BEZPOŚREDNIO naszym kluczem Anthropic, z ich wyszukiwarką.
    # Drugi silnik niezależny od DataForSEO — dzięki temu sekcja pytań klientów ma
    # DWA modele, a nie jeden. Przy jednym nie dało się odróżnić cechy modelu od
    # prawidłowości rynku. Udział rynkowy niski, ale to nie o zasięg tu chodzi:
    # dwa niezależne pomiary tego samego są warte więcej niż jeden.
    "claude_wprost": {"silnik": ("anthropic", "wprost"), "nazwa": "Claude (bezpośrednio)",
                      "udzial": 0.71, "koszt": 0.035, "wlasny_klucz": True},
    "chatgpt":    {"silnik": ("chat_gpt", "o4-mini"), "nazwa": "ChatGPT",
                   "udzial": 86.4, "koszt": 0.109},
    "perplexity": {"silnik": ("perplexity", "sonar"), "nazwa": "Perplexity",
                   "udzial": 6.18, "koszt": 0.006},
    "gemini":     {"silnik": ("gemini", "gemini-3.6-flash"), "nazwa": "Google Gemini",
                   "udzial": 3.22, "koszt": 0.020},
    "claude":     {"silnik": ("claude", "claude-sonnet-5"), "nazwa": "Claude",
                   "udzial": 0.71, "koszt": 0.030},
    # Google AI Mode — tryb konwersacyjny wyszukiwarki. To NIE jest AI Overview
    # (tamto jest podsumowaniem do frazy i nie da się z nim rozmawiać). AI Mode
    # przyjmuje pytanie jak chatbot, więc pasuje do naszej metodyki.
    # Udziału rynkowego nie znamy — StatCounter mierzy chatboty, a AI Mode jest
    # częścią wyszukiwarki. Wpisanie tu liczby byłoby zmyśleniem, więc jest None.
    "ai_mode":    {"silnik": ("google", "ai_mode"), "nazwa": "Google AI Mode",
                   "udzial": None, "koszt": 0.006, "endpoint": "serp"},
}

LOKALIZACJA_PL = 2616
JEZYK_PL = "Polish"


# ══════════════════════════════════════════════════════════════════
#  TREŚĆ STAŁA — identyczna dla każdego klienta, zero kosztu API
#  (dane z materiałów ICEA + rekomendacji specjalisty)
# ══════════════════════════════════════════════════════════════════
TRESC_STALA = {
    "ai_overview": {
        "naglowek": "Czym są AI Overviews",
        "akapity": [
            "AI Overviews to podsumowania odpowiedzi generowane przez sztuczną inteligencję "
            "w Google, które pojawiają się nad wynikami wyszukiwania.",
            "W Polsce obejmują już **24,17% zapytań** — czyli prawie co czwarte wyszukiwanie "
            "kończy się gotową odpowiedzią AI zamiast kliknięciem w stronę. Tylko w dwa miesiące "
            "(maj–czerwiec 2025) polskie serwisy straciły **23,7 mln kliknięć organicznych**.",
            "Jednocześnie wysokie pozycje w Google wciąż są ważne — aż **65,9% treści cytowanych "
            "w AI Overviews pochodzi z TOP 3** wyników organicznych.",
        ],
    },
    "rynek_chatbotow": {
        "naglowek": "Rynek chatbotów w Polsce",
        "akapity": [
            "W pierwszej połowie 2025 roku liczba użytkowników ChatGPT w Polsce wzrosła "
            "z 3,6 mln do ponad **9,3 mln** — korzysta z niego już niemal co trzeci internauta.",
            "Rynek skonsolidował się wokół jednego gracza, który w największym stopniu "
            "przejmuje uwagę użytkowników.",
        ],
        "udzialy": [
            ("ChatGPT", 86.4), ("Perplexity", 6.18), ("Microsoft Copilot", 3.43),
            ("Google Gemini", 3.22), ("Claude", 0.71), ("DeepSeek", 0.07),
        ],
        "zrodlo": "StatCounter, mar 2025 – mar 2026",
    },
    # Miejsce na case study Last Agency — DO UZUPEŁNIENIA przez PM.
    # Wcześniej był tu przykład Botland, ale to nie jest klient Last Agency;
    # powoływanie się na cudzą firmę w raporcie dla partnera jest ryzykowne.
    # Ustaw "pokaz": True i wpisz własne dane, gdy będzie gotowy case.
    "case": {
        "pokaz": False,
        "naglowek": "",
        "tekst": "",
    },
}


# ══════════════════════════════════════════════════════════════════
#  PARSERY — działają na odpowiedziach API (offline na fixtures)
# ══════════════════════════════════════════════════════════════════
def _tekst_i_zrodla(wynik: dict) -> tuple[str, list[str]]:
    """Wyciąga treść odpowiedzi i cytowane URL-e.

    Obsługuje dwa kształty: llm_responses (items → sections) oraz Google AI Mode,
    który zwraca strukturę SERP-ową (items → ai_mode / typ z markdown i references).
    """
    # Google AI Mode — struktura SERP. Rozpoznajemy po obecności item_types.
    if wynik.get("item_types") or any(
            (i or {}).get("type") in ("ai_mode", "ai_overview")
            for i in (wynik.get("items") or [])):
        t, z = [], []
        for it in wynik.get("items") or []:
            if it.get("markdown"):
                t.append(it["markdown"])
            for sek in it.get("items") or []:
                if sek.get("text"):
                    t.append(sek["text"])
            for ref in (it.get("references") or []):
                if ref.get("url"):
                    z.append(ref["url"])
        return "\n\n".join(t), z

    tekst, zrodla = [], []
    for item in wynik.get("items") or []:
        for sekcja in item.get("sections") or []:
            if sekcja.get("type") == "summary_text":
                continue  # to „rozumowanie" modelu, nie odpowiedź dla klienta
            if sekcja.get("text"):
                tekst.append(sekcja["text"])
            for a in sekcja.get("annotations") or []:
                if a.get("url"):
                    zrodla.append(a["url"])
    return "\n\n".join(tekst), zrodla


def _marki_z_tekstu(tekst: str, pomijaj: str = "", pytanie: str = "") -> list[str]:
    """Nazwy marek z odpowiedzi. Zarówno ChatGPT, jak i Perplexity wyróżniają je **pogrubieniem**,
    więc wyciągamy je deterministycznie — bez kolejnego wywołania LLM."""
    # Pogrubienia bywają też zwykłym tekstem („Najprostszy wybór", „Nettigo lub Kamami"),
    # więc odsiewamy frazy zdaniowe po słowach-wskaźnikach i po małej literze na starcie.
    ZDANIOWE = (" lub ", " oraz ", " i ", " dla ", " w ", " z ", " / ", " – ", ":")
    znalezione, widziane = [], set()
    for m in re.findall(r"\*\*(.+?)\*\*", tekst):
        nazwa = m.strip(" .:,–—")
        klucz = nazwa.lower()
        if not nazwa or len(nazwa) > 30 or klucz in widziane:
            continue
        if not nazwa[0].isupper():
            continue
        if any(z in f" {klucz} " for z in ZDANIOWE):
            continue
        if pomijaj and pomijaj.lower() in klucz:
            continue
        # Model pogrubia też słowa z samego pytania (miasto, nazwa usługi) — to kontekst,
        # nie marka. Przykład: „**Wrocławiu**" w odpowiedzi na pytanie o Wrocław.
        if pytanie and klucz[:6] in pytanie.lower():
            continue
        widziane.add(klucz)
        znalezione.append(nazwa)
    return znalezione


def warianty_marki(nazwa: str, domena: str = "") -> list[str]:
    """Formy, w jakich marka może wystąpić w odpowiedzi modelu.

    Powód: ekstraktor często zapisuje nazwę razem z domeną („Elektromaniacy.pl",
    „Tebim sp. z o.o."), a model w odpowiedzi pisze samo „Elektromaniacy". Dopasowanie
    dosłowne dawało wtedy 0 wzmianek przy odpowiedziach, które markę wprost wymieniały —
    i dodatkowo wrzucało badaną firmę na jej własną listę konkurentów.

    Zwraca warianty od najdłuższego; człony krótsze niż 4 znaki pomijamy, żeby nie
    dopasowywać przypadkowych słów.
    """
    KONCOWKI = (".pl", ".com", ".pro", ".eu", ".net", ".org", ".com.pl", ".shop", ".store")
    PRAWNE = (" sp. z o.o.", " sp.z o.o.", " spółka z o.o.", " s.a.", " sp. j.",
              " sp. k.", " s.c.", " sp. z o. o.")
    kandydaci = set()
    for zrodlo in (nazwa or "", (domena or "").replace("www.", "")):
        b = zrodlo.strip().lower()
        if not b:
            continue
        kandydaci.add(b)
        for p in PRAWNE:
            if b.endswith(p):
                b = b[: -len(p)].strip()
        for k in KONCOWKI:
            if b.endswith(k):
                b = b[: -len(k)].strip()
        kandydaci.add(b)
    return sorted((k for k in kandydaci if len(k) >= 4), key=len, reverse=True)


def analizuj_odpowiedz(odp: dict, marka: str, domena: str, prompt: str) -> dict:
    """Jeden wiersz tabeli 'przykładowe prompty' — wzór: moduł Semrush ze screena."""
    wynik = (odp.get("tasks") or [{}])[0].get("result") or [{}]
    wynik = wynik[0] if wynik else {}
    tekst, zrodla = _tekst_i_zrodla(wynik)

    warianty = warianty_marki(marka, domena)
    t = tekst.lower()
    wspomniana = any(w in t for w in warianty)
    cytowana = any(domena.lower() in (u or "").lower() for u in zrodla)

    return {
        "prompt": prompt,
        "model": wynik.get("model_name", ""),
        "odpowiedz": tekst,
        "wspomniana": wspomniana,
        "cytowana": cytowana,
        "marki": [m for m in _marki_z_tekstu(tekst, pomijaj=marka, pytanie=prompt)
                  if not any(w in m.lower() for w in warianty)],
        "zrodla": zrodla,
        "koszt": wynik.get("money_spent", 0),
    }


def z_wlasnego_zapytania(tekst: str, zrodla: list[str], marka: str,
                         domena: str, prompt: str) -> dict:
    """Ten sam wiersz co analizuj_odpowiedz, ale z danych spoza DataForSEO.
    Używane, gdy pytamy model własnym kluczem — kształt musi być identyczny,
    bo raport i wszystkie dalsze analizy nie mogą wiedzieć, skąd przyszła odpowiedź."""
    warianty = warianty_marki(marka, domena)
    t = (tekst or "").lower()
    return {
        "prompt": prompt,
        "model": "",
        "odpowiedz": tekst or "",
        "wspomniana": any(w in t for w in warianty),
        "cytowana": any(domena.lower() in (u or "").lower() for u in zrodla),
        "marki": [m for m in _marki_z_tekstu(tekst or "", pomijaj=marka, pytanie=prompt)
                  if not any(x in m.lower() for x in warianty)],
        "zrodla": zrodla or [],
        "koszt": 0,
    }


# Wielkie portale dzielą frazy z każdą firmą, ale nie są jej konkurentami w biznesie.
# Bez tego filtra w tabeli konkurencji lądują YouTube, LinkedIn i portale z ogłoszeniami.
PORTALE = (
    "youtube.", "facebook.", "linkedin.", "instagram.", "tiktok.", "wikipedia.",
    "pracuj.pl", "olx.", "allegro.", "gowork.", "nofluffjobs", "justjoin", "bulldogjob",
    "google.", "twitter.", "x.com", "pinterest.", "booksy.", "oferteo", "panoramafirm",
    "aleo.com", "gratka.", "otodom.",
    # Marketplace'y, sieci handlowe i porownywarki cen dziela frazy z KAZDYM sklepem.
    # Weryfikacja na elektromaniacy.pl: mielismy mediaexpert, amazon i skapiec w TOP4
    # "konkurentow", podczas gdy audyt ICEA (Ahrefs) wskazywal same sklepy branzowe.
    "morele.", "ceneo.", "amazon.", "mediaexpert.", "skapiec.", "empik.", "x-kom.",
    "euro.com.pl", "mediamarkt.", "nokaut.", "okazje.info", "domodi.", "erli.",
    "temu.", "aliexpress.", "ebay.", "shopee.",
    "indeed.", "jooble.", "freelancer.", "useme.", "fiverr.", "upwork.", "glassdoor.",
    "wykop.", "reddit.", "medium.com", "quora.",
)

# Poniżej tylu fraz pokrywanie się słów kluczowych jest przypadkowe — lista „konkurentów"
# przestaje cokolwiek znaczyć. Wtedy uczciwiej napisać, że danych jest za mało.
PROG_WIARYGODNOSCI = 30


def analiza_zrodel(wiersze: list[dict], domena: str, limit: int = 12) -> dict:
    """Skąd model bierze wiedzę, odpowiadając na pytania klientów.

    Przy każdym pytaniu zapisujemy listę cytowanych URL-i. Zagregowane pokazują,
    które serwisy model traktuje jako źródło w tej branży — i czy strona klienta
    jest wśród nich. To pomiar, nie interpretacja: liczymy wystąpienia.

    Weryfikacja na tebim.pro: 5 pytań → 100 źródeł → 53 domeny, tebim.pro cytowany
    8 razy, dokładnie tyle samo co polecany przez model konkurent. Wniosek bywa więc
    odwrotny od oczekiwanego („jesteście widoczni, problem leży gdzie indziej") —
    i dlatego tę sekcję trzeba liczyć, a nie zakładać z góry.
    """
    from collections import Counter

    wszystkie = [u for w in wiersze for u in (w.get("zrodla") or [])]
    if not wszystkie:
        return {}

    licznik = Counter()
    for u in wszystkie:
        host = urlparse(u).netloc.replace("www.", "").lower()
        if host:
            licznik[host] += 1

    nasze = licznik.get(domena.replace("www.", "").lower(), 0)
    obce = [{"domena": d, "cytowan": n} for d, n in licznik.most_common()
            if d != domena.replace("www.", "").lower()][:limit]

    # Pozycja klienta na tle wszystkich cytowanych źródeł — liczba, nie ocena.
    # Remisy trzeba odnotować: przy 8 cytowaniach tebim.pro dzielił 1. miejsce z dwoma
    # innymi serwisami, a raport pisał po prostu „1. miejsce" — to zawyżenie.
    ranking = [n for _, n in licznik.most_common()]
    miejsce = (sum(1 for n in ranking if n > nasze) + 1) if nasze else None
    remisujacych = (sum(1 for d, n in licznik.items()
                        if n == nasze and d != domena.replace("www.", "").lower())
                    if nasze else 0)

    return {
        "zrodel_lacznie": len(wszystkie),
        "domen_unikalnych": len(licznik),
        "nasze_cytowania": nasze,
        "nasze_miejsce": miejsce,
        "remisujacych": remisujacych,
        "pytan": len(wiersze),
        "top_zrodla": obce,
    }


def data_bazy() -> str:
    """Data ostatniej aktualizacji bazy Google w DataForSEO Labs. Endpoint jest darmowy.
    Podpisujemy nią sekcję SEO — tak jak ICEA podpisuje wykresy „Dane z narzędzia Senuto".
    Różne narzędzia SEO podają różne liczby dla tej samej domeny; jawne źródło zdejmuje
    z raportu zarzut błędu i pokazuje, że wiemy, czym mierzymy."""
    try:
        s = dfs.pobierz("dataforseo_labs/status", "labs_status")
        r = ((s.get("tasks") or [{}])[0].get("result") or [{}])[0]
        return (r.get("google") or {}).get("date_update") or ""
    except Exception:
        return ""


def _frazy(odp: dict, limit: int = 12) -> list[dict]:
    """Konkretne frazy z pozycjami. „21 fraz" nic nie mówi — dopiero lista pokazuje,
    NA CO firma jest widoczna (i czy to zapytania handlowe, czy definicyjne)."""
    # Fraza definicyjna („co to jest SKU") przynosi ruch, ale nie klienta.
    # Rozróżnienie robimy deterministycznie — to jeden z mocniejszych wniosków raportu.
    INFORMACYJNE = ("co to", "czym jest", "jak ", "znaczenie", "definicja", "przyklad",
                    "przykład", "dlaczego", "kiedy ", "ile ", "czy ")
    lista = []
    for it in ((odp.get("tasks") or [{}])[0].get("result") or [{}])[0].get("items") or []:
        kd = it.get("keyword_data") or {}
        serp = (it.get("ranked_serp_element") or {}).get("serp_item") or {}
        fraza = kd.get("keyword", "")
        lista.append({
            "typ": "informacyjna" if any(i in f" {fraza.lower()} " for i in INFORMACYJNE)
                   else "handlowa",
            "fraza": fraza,
            "pozycja": serp.get("rank_absolute") or serp.get("rank_group"),
            "wolumen": (kd.get("keyword_info") or {}).get("search_volume") or 0,
            "ruch": round(serp.get("etv") or 0),
            "url": serp.get("relative_url") or serp.get("url") or "",
        })
        # Ta sama fraza potrafi wystąpić kilka razy — API zwraca ranking per URL.
    # Zostawiamy najlepszą pozycję, inaczej tabela pokazuje „twoj startup #1"
    # i „twoj startup #2" jako dwie różne frazy.
    najlepsze = {}
    for f in lista:
        k = f["fraza"].lower()
        if k not in najlepsze or (f["pozycja"] or 999) < (najlepsze[k]["pozycja"] or 999):
            najlepsze[k] = f
    lista = list(najlepsze.values())
    lista.sort(key=lambda f: (f["pozycja"] or 999, -f["wolumen"]))
    return lista[:limit]


def pula_fraz(odp: dict, limit: int = 40) -> list[dict]:
    """Szersza lista fraz na potrzeby analizy luki. W raporcie pokazujemy 12 najwyżej
    rankujących, ale do badania AI Overview potrzebny jest przekrój — wśród 12 czołowych
    fraz e-commerce bywa zero zapytań informacyjnych, a to właśnie one mają AIO."""
    return _frazy(odp, limit)


def analiza_luki(frazy: list[dict], domena: str, cytowane_aio: set[str],
                 limit: int = 8, nazwa_fixture: str = "",
                 lista_aio_pelna: bool = True) -> list[dict]:
    """Zestawia klasyczne SEO z AI Overview — najmocniejszy wniosek raportu.

    Dla każdej frazy sprawdzamy w żywym SERP-ie: czy Google pokazuje AI Overview
    i na której pozycji jest firma. Jeśli AIO jest, a firmy nie ma wśród cytowanych
    (dane z llm_mentions) — to LUKA: pozycja w Google jest, ale kliknięcie przejmuje AI.
    Koszt: $0.002 za frazę.
    """
    def sprawdz(f):
        try:
            odp = dfs.wywolaj(
                "serp/google/organic/live/advanced",
                [{"keyword": f["fraza"], "location_code": LOKALIZACJA_PL,
                  "language_name": JEZYK_PL, "device": "desktop"}],
                f"{nazwa_fixture}_serp_{f['fraza'][:20]}" if nazwa_fixture else None,
            )
            items = ((odp.get("tasks") or [{}])[0].get("result") or [{}])[0].get("items") or []
            ma_aio = any(i.get("type") == "ai_overview" for i in items)
            pozycja = next(
                (i.get("rank_group") for i in items
                 if i.get("type") == "organic" and domena in (i.get("domain") or "")),
                None,
            )
            cytowany = f["fraza"].lower() in cytowane_aio
            # Gdy lista fraz z AI Overview jest ucięta limitem zapytania, brak frazy
            # na tej liście NIE dowodzi, że strona nie jest w danym AIO cytowana.
            # Wtedy zamiast twierdzić „nie cytują Was" oznaczamy stan jako nieustalony.
            return {"fraza": f["fraza"], "wolumen": f["wolumen"], "typ": f["typ"],
                    "pozycja": pozycja, "ma_aio": ma_aio,
                    "cytowany_w_aio": cytowany,
                    "nieustalone": bool(ma_aio and not cytowany and not lista_aio_pelna),
                    "koszt": odp.get("cost", 0)}
        except Exception:
            return None

    # NIE zawężamy do fraz handlowych. Weryfikacja na elektromaniacy.pl pokazała, że to
    # zafałszowywało wynik: na zapytaniach zakupowych Google prawie nie pokazuje AI Overview
    # (wyświetla karuzele produktowe — popular_products, compare_sites), więc badając same
    # frazy handlowe znajdowaliśmy 0 luk. AI Overview dominuje na zapytaniach poradnikowych.
    # Bierzemy więc przekrój obu typów, proporcjonalnie do tego, co firma faktycznie ma.
    handlowe = [f for f in frazy if f["typ"] == "handlowa"]
    info = [f for f in frazy if f["typ"] == "informacyjna"]
    polowa = max(1, limit // 2)
    wybrane = (handlowe[:limit - min(len(info), polowa)] + info[:polowa])[:limit] or frazy[:limit]
    with ThreadPoolExecutor(max_workers=6) as pool:
        wyniki = [w for w in pool.map(sprawdz, wybrane) if w]
    # najpierw realne luki: AIO jest, nas nie ma, a mamy dobrą pozycję
    wyniki.sort(key=lambda w: (not (w["ma_aio"] and not w["cytowany_w_aio"]), w["pozycja"] or 999))
    return wyniki


def analizuj_seo(rank: dict, konkurenci: dict, strony: dict, domena: str,
                 frazy: dict | None = None, ruch_konk: dict | None = None) -> dict:
    """Sekcja 'Raport Zero' — widoczność w klasycznym Google (odpowiednik danych Senuto/Ahrefs)."""
    poz = (((rank.get("tasks") or [{}])[0].get("result") or [{}])[0]
           .get("items", [{}])[0].get("metrics", {}).get("organic", {}))

    top3 = (poz.get("pos_1") or 0) + (poz.get("pos_2_3") or 0)
    top10 = top3 + (poz.get("pos_4_10") or 0)

    lista = []
    for it in ((konkurenci.get("tasks") or [{}])[0].get("result") or [{}])[0].get("items") or []:
        dom = (it.get("domain") or "").lower()
        if not dom or domena.lower() in dom:          # to nie konkurent, to my
            continue
        if any(p in dom for p in PORTALE):            # portal, nie firma
            continue
        m = (it.get("metrics") or {}).get("organic") or {}
        lista.append({
            "domena": dom,
            "wspolne_frazy": it.get("intersections") or 0,
            "ruch": round(m.get("etv") or 0),
            "fraz_lacznie": m.get("count") or 0,
            "srednia_pozycja": round(it.get("avg_position") or 0, 1),
        })

    wynik_stron = ((strony.get("tasks") or [{}])[0].get("result") or [{}])[0]
    top_strony = []
    for it in (wynik_stron.get("items") or [])[:8]:
        m = (it.get("metrics") or {}).get("organic") or {}
        top_strony.append({
            "adres": it.get("page_address") or "",
            "fraz": m.get("count") or 0,
            "ruch": round(m.get("etv") or 0),
        })

    # Realny ruch całkowity — dokładany do listy konkurentów. Bez tego jedyną liczbą
    # w tabeli był ruch liczony na frazach wspólnych, co zaniża konkurentów kilkukrotnie.
    realny = {}
    if ruch_konk:
        for it in (((ruch_konk.get("tasks") or [{}])[0].get("result") or [{}])[0].get("items") or []):
            m = (it.get("metrics") or {}).get("organic") or {}
            realny[it.get("target") or ""] = round(m.get("etv") or 0)
    for k in lista:
        k["ruch_calkowity"] = realny.get(k["domena"])

    fraz = poz.get("count") or 0
    return {
        "dane_wiarygodne": fraz >= PROG_WIARYGODNOSCI,
        # Etykietę podaje dostawca, nie szablon — DataForSEO ma osobny koszyk pos_1
        # i pos_2_3, więc TOP 3 jest tu liczbą dokładną, nie przybliżeniem.
        "etykieta_czolo": "fraz w TOP 3",
        "ruch_nasz_calkowity": realny.get(domena),
        "zrodlo": "DataForSEO Labs · baza Google PL",
        "data_bazy": data_bazy(),
        "top3": top3,
        "top10": top10,
        "fraz_lacznie": poz.get("count") or 0,
        "ruch": round(poz.get("etv") or 0),
        "wzrosty": poz.get("is_up") or 0,
        "spadki": poz.get("is_down") or 0,
        "nowe": poz.get("is_new") or 0,
        "utracone": poz.get("is_lost") or 0,
        "konkurenci": lista[:8],
        "frazy": _frazy(frazy) if frazy else [],
        "podstron_widocznych": wynik_stron.get("total_count") or 0,
        "top_podstrony": top_strony,
    }


def bez_etykiet_zrodel(tekst: str, warianty: list[str]) -> str:
    """Usuwa podpisy źródeł z treści odpowiedzi AI Overview.

    Google podpisuje akapity nazwą źródła („Wikipedia +5", „Twój StartUp"), a API
    wkleja te podpisy do pola z treścią. Bez ich odcięcia każde cytowanie wyglądałoby
    jak wymienienie marki w zdaniu — a to zupełnie inna, znacznie mocniejsza rzecz.
    Wykryte na twojstartup.pl: 7 z 10 rzekomych „wymienień" to były same podpisy.

    Wycinamy tylko linie, które w CAŁOŚCI są nazwą marki (opcjonalnie z „+N").
    Zdanie zawierające nazwę w treści zostaje nietknięte.
    """
    if not tekst:
        return ""
    # Odnośniki też nie są wymienieniem marki. DataForSEO wkleja cytowania jako
    # linki markdown — „...magazynowych.[](https://www.tebim.pro/blog/...)" — więc
    # domena trafiała się w URL-u i każde cytowanie liczyło się jako wzmianka.
    # Zostawiamy etykietę linku (to bywa prawdziwy tekst), wycinamy sam adres.
    tekst = re.sub(r"\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1), tekst)
    tekst = re.sub(r"https?://\S+", " ", tekst)

    wynik = []
    for linia in tekst.splitlines():
        goła = re.sub(r"[\s*•\-–]+", " ", linia).strip().lower()
        goła = re.sub(r"\s*\+\s*\d+\s*$", "", goła).strip()
        if goła and any(goła == w for w in warianty):
            continue                      # sam podpis źródła — pomijamy
        wynik.append(linia)
    return "\n".join(wynik)


def analizuj_ai_overview(odp: dict, domena: str, marka: str = "") -> dict:
    """Sekcja 2 — widoczność w AI Overviews (llm_mentions, platform=google)."""
    wynik = ((odp.get("tasks") or [{}])[0].get("result") or [{}])[0]
    items = wynik.get("items") or []

    # Cytowanie jako źródło i wymienienie z nazwy to DWIE RÓŻNE rzeczy. Google potrafi
    # zbudować odpowiedź na czyjejś treści, nie podając nazwy firmy — użytkownik widzi
    # wtedy odpowiedź, ale nie markę. Zweryfikowane na żywo: dla „dodatkowa praca online"
    # twojstartup.pl jest 5. źródłem, a w tekście odpowiedzi nie pada ani razu.
    warianty = warianty_marki(marka, domena) if (marka or domena) else []

    wzmianki = []
    for it in items:
        tekst_odp = it.get("answer") or ""
        bez_podpisow = bez_etykiet_zrodel(tekst_odp, warianty).lower()
        wzmianki.append({
            "wymieniona": any(w in bez_podpisow for w in warianty),
            "prompt": it.get("question", ""),
            # Pełna treść odpowiedzi Google — mamy ją w odpowiedzi API i nie kosztuje
            # nic dodatkowo. Bez niej raport pokazywał samą frazę i pozycję, czyli
            # najmniej interesującą część tego, za co zapłaciliśmy.
            "tekst": it.get("answer") or "",
            "wolumen": it.get("ai_search_volume") or 0,
            "zrodla": [(s.get("domain") or "") for s in (it.get("sources") or [])],
            "pozycja": next(
                (i + 1 for i, s in enumerate(it.get("sources") or [])
                 if domena.lower() in (s.get("domain") or "").lower()),
                None,
            ),
        })

    pozycje = [w["pozycja"] for w in wzmianki if w["pozycja"]]
    total = wynik.get("total_count", 0)
    return {
        "wymienionych": sum(1 for w in wzmianki if w["wymieniona"]),
        "liczba_wzmianek": total,
        "pobrano": len(items),
        # Średnią liczymy z pobranych pozycji, a tych bywa mniej niż wszystkich fraz
        # (zapytanie ma limit). Raport MUSI to zaznaczyć, inaczej podaje średnią z próbki
        # jako średnią z całości — przy 10 pobranych z 72 to zupełnie inna liczba.
        "srednia_pozycja": round(sum(pozycje) / len(pozycje), 2) if pozycje else None,
        "probka_niepelna": bool(total and len(items) < total),
        "wzmianki": sorted(wzmianki, key=lambda w: w["wolumen"], reverse=True),
    }


# ══════════════════════════════════════════════════════════════════
#  ZBIERANIE DANYCH (płatne — używać świadomie)
# ══════════════════════════════════════════════════════════════════
def zapytaj_ai_mode(prompt: str, nazwa_fixture=None) -> dict:
    """Google AI Mode — konwersacyjny tryb wyszukiwarki. Inny endpoint i inny kształt
    odpowiedzi niż llm_responses, dlatego osobna funkcja.
    NIEZWERYFIKOWANE: kształt odpowiedzi nie był jeszcze sprawdzony na żywym wywołaniu
    (saldo na zerze). Parser jest defensywny, ale traktuj wynik ostrożnie."""
    return dfs.wywolaj(
        "serp/google/ai_mode/live/advanced",
        [{"keyword": prompt, "location_code": LOKALIZACJA_PL,
          "language_code": "pl", "device": "desktop"}],
        nazwa_fixture,
    )


def zapytaj_llm(prompt: str, silnik=SILNIK_DOMYSLNY, nazwa_fixture=None) -> dict:
    dostawca, model = silnik
    if (dostawca, model) == ("google", "ai_mode"):
        return zapytaj_ai_mode(prompt, nazwa_fixture)
    return dfs.wywolaj(
        f"ai_optimization/{dostawca}/llm_responses/live",
        [{
            "user_prompt": prompt,
            "model_name": model,
            "web_search": True,
            "web_search_country_iso_code": "PL",
        }],
        nazwa_fixture,
    )


def dane_seo(domena: str, nazwa_fixture: str = "") -> tuple[dict, dict, dict, dict, dict, float]:
    """Pięć wywołań Labs = cała sekcja 'Raport Zero'. Razem ok. $0.06."""
    baza = {"target": domena, "location_code": LOKALIZACJA_PL, "language_name": JEZYK_PL}
    rank = dfs.wywolaj("dataforseo_labs/google/domain_rank_overview/live",
                       [baza], f"{nazwa_fixture}_rank" if nazwa_fixture else None)
    konk = dfs.wywolaj("dataforseo_labs/google/competitors_domain/live",
                       [{**baza, "limit": 15}], f"{nazwa_fixture}_konk" if nazwa_fixture else None)
    strony = dfs.wywolaj("dataforseo_labs/google/relevant_pages/live",
                         [{**baza, "limit": 10}], f"{nazwa_fixture}_strony" if nazwa_fixture else None)
    # Realny ruch konkurentow. UWAGA: metryki z competitors_domain sa liczone WYLACZNIE
    # na frazach wspolnych z badana domena (zweryfikowane: count == intersections w kazdym
    # wierszu, np. youtube.com "677 fraz"). Do porownania skali potrzebny jest osobny
    # endpoint. Zwalidowane wzgledem Ahrefs na 9 domenach - mediana odchylenia ok. 10%.
    # Badana domena jest PIERWSZYM wierszem competitors_domain, więc trzeba ją odfiltrować —
    # inaczej trafia do listy dwa razy i zjada slot ósmemu konkurentowi (pokazywał „—").
    konkurenci_dom = [
        i.get("domain") for i in
        (((konk.get("tasks") or [{}])[0].get("result") or [{}])[0].get("items") or [])
        if i.get("domain") and i["domain"] != domena
        and not any(p in i["domain"] for p in PORTALE)
    ][:8]
    ruch_konk = dfs.wywolaj(
        "dataforseo_labs/google/bulk_traffic_estimation/live",
        [{"targets": [domena] + konkurenci_dom, "location_code": LOKALIZACJA_PL,
          "language_name": JEZYK_PL}],
        f"{nazwa_fixture}_ruch" if nazwa_fixture else None,
    )
    frazy = dfs.wywolaj("dataforseo_labs/google/ranked_keywords/live",
                        # 100, nie 15: z 15 najwyzej rankujacych fraz nie da sie zlozyc
                        # przekroju handlowe/informacyjne (patrz pula_fraz). Koszt rosnie
                        # o ok. $0.01, a analiza luki przestaje byc obciazona doborem proby.
                        [{**baza, "limit": 100,
                          "order_by": ["ranked_serp_element.serp_item.etv,desc"]}],
                        f"{nazwa_fixture}_frazy" if nazwa_fixture else None)
    koszt = sum(o.get("cost", 0) for o in (rank, konk, strony, frazy, ruch_konk))
    return rank, konk, strony, frazy, ruch_konk, koszt


# Platformy, o które można pytać llm_mentions. Endpoint available_filters (darmowy)
# potwierdza, że filtr `platform` istnieje — wcześniej nie wysyłaliśmy go wcale
# i dostawaliśmy domyślnie google/google_ai_overview, przez co raport pokazywał
# tylko AI Overviews, choć baza ma więcej. To samo ograniczenie mieliśmy po stronie
# SE Ranking i tam też było nasze, nie dostawcy.
PLATFORMY_WZMIANEK = {
    "google":     "Google AI Overviews",
    "chat_gpt":   "ChatGPT",
    "perplexity": "Perplexity",
    "gemini":     "Google Gemini",
}


def wzmianki_ai_overview(domena: str, limit: int = 10, nazwa_fixture=None,
                         platforma: str = "google") -> dict:
    zadanie = {
        "language_name": JEZYK_PL,
        "location_code": LOKALIZACJA_PL,
        "target": [{"domain": domena}],
        "limit": limit,
    }
    if platforma and platforma != "google":
        # NIEZWERYFIKOWANE na żywym wywołaniu — saldo DataForSEO na zerze.
        # Filtr potwierdzony w available_filters, wartości wzięte z listy providerów
        # llm_responses, ale odpowiedzi dla innych platform jeszcze nie widzieliśmy.
        zadanie["filters"] = [["platform", "=", platforma]]
    return dfs.wywolaj("ai_optimization/llm_mentions/search/live", [zadanie], nazwa_fixture)


# ══════════════════════════════════════════════════════════════════
#  SKŁADANIE RAPORTU
# ══════════════════════════════════════════════════════════════════
def scal_powtorzenia(proby: list[dict]) -> dict:
    """Kilka odpowiedzi na TO SAMO pytanie -> jeden wiersz z licznikiem trafień.

    PO CO PYTAĆ WIĘCEJ NIŻ RAZ. Modele są niedeterministyczne: ta sama fraza zadana
    ponownie daje inną odpowiedź i inny zestaw wymienionych firm. Pojedynczy strzał
    mówi więc tyle co rzut monetą — „nie wymienili nas" może znaczyć „nie jesteście
    widoczni" albo „tym razem trafiło inaczej".

    Przy trzech próbach rozróżnienie jest jakościowe: 0/3 to nieobecność, 3/3 to
    stabilna obecność, a 1/3 to widoczność przypadkowa — i akurat ta trzecia
    odpowiedź jest najczęstsza i najciekawsza dla klienta.

    Źródła i marki scalamy sumą: jeśli model wymienił konkurenta choć raz, to znaczy,
    że go zna. Zgubienie tego przez uśrednianie zaniżałoby listę konkurencji.
    """
    if not proby:
        return {}
    pierwsza = dict(proby[0])
    trafien = sum(1 for p in proby if p.get("wspomniana"))
    cytowan = sum(1 for p in proby if p.get("cytowana"))

    zrodla, marki = [], []
    for p in proby:
        for u in (p.get("zrodla") or []):
            if u not in zrodla:
                zrodla.append(u)
        for m in (p.get("marki") or []):
            if m not in marki:
                marki.append(m)

    # Do raportu bierzemy odpowiedź z próby, w której firma się POJAWIŁA — bo to ona
    # jest dowodem. Gdy nie pojawiła się nigdy, pierwsza jest równie dobra.
    z_trafieniem = next((p for p in proby if p.get("wspomniana")), proby[0])

    pierwsza.update({
        "odpowiedz": z_trafieniem.get("odpowiedz", ""),
        "wspomniana": trafien > 0,
        "cytowana": cytowan > 0,
        "zrodla": zrodla,
        "marki": marki,
        "prob": len(proby),
        "trafien": trafien,
        "cytowan": cytowan,
    })
    return pierwsza


def podsumuj(wiersze: list[dict], ai_overview: dict | None) -> dict:
    """Liczby na pierwszą stronę raportu — to je klient zapamięta."""
    ile = len(wiersze) or 1
    wspomniana = sum(1 for w in wiersze if w["wspomniana"])
    cytowana = sum(1 for w in wiersze if w["cytowana"])

    # najczęściej powtarzający się konkurenci w odpowiedziach AI
    licznik: dict[str, int] = {}
    for w in wiersze:
        for marka in w["marki"]:
            licznik[marka] = licznik.get(marka, 0) + 1
    konkurenci = sorted(licznik.items(), key=lambda x: x[1], reverse=True)[:10]

    # Rozbicie na silniki — przy kilku modelach jedna liczba zbiorcza zaciera obraz.
    # „2/10 wzmianek" nic nie mówi; „ChatGPT 0/5, Perplexity 2/5" mówi wszystko.
    per_silnik = {}
    for w in wiersze:
        s_ = w.get("silnik_nazwa") or "—"
        d = per_silnik.setdefault(s_, {"nazwa": s_, "udzial": w.get("silnik_udzial"),
                                       "pytan": 0, "wspomniana": 0, "cytowana": 0})
        d["pytan"] += 1
        d["wspomniana"] += bool(w["wspomniana"])
        d["cytowana"] += bool(w["cytowana"])

    return {
        "per_silnik": sorted(per_silnik.values(),
                             key=lambda x: -(x["udzial"] or 0)),
        "promptow": len(wiersze),
        "wspomniana": wspomniana,
        "cytowana": cytowana,
        "udzial_wspomnien": round(100 * wspomniana / ile),
        "konkurenci": [{"marka": m, "wystapien": n} for m, n in konkurenci],
        "wzmianki_aio": (ai_overview or {}).get("liczba_wzmianek"),
        "srednia_pozycja_aio": (ai_overview or {}).get("srednia_pozycja"),
    }


def zbuduj_raport(firma: dict, wiersze: list[dict], ai_overview: dict | None,
                  koszt: float = 0.0, seo: dict | None = None) -> dict:
    """Pełna struktura raportu: treść stała + dane firmy. Front renderuje z tego stronę do druku."""
    return {
        "firma": {
            "nazwa": firma.get("nazwa", ""),
            "domena": firma.get("domena", ""),
            "url": firma.get("url", ""),
            "branza": firma.get("branza", ""),
        },
        "podsumowanie": podsumuj(wiersze, ai_overview),
        "prompty": wiersze,
        "ai_overview": ai_overview,
        "seo": seo,
        "tresc_stala": TRESC_STALA,
        "koszt_api": round(koszt, 4),
    }


PROMPT_GENERATORA = """Jesteś analitykiem widoczności marek w wyszukiwarkach AI.
Na podstawie danych o firmie wygeneruj {ile} pytań, jakie REALNY KLIENT wpisałby do ChatGPT
szukając takich usług — i w odpowiedzi na które ta firma POWINNA się pojawić.

ZASADY:
- Pytania po polsku, naturalne, tak jak pisze człowiek (nie słowa kluczowe).
- NIE wymieniaj nazwy firmy w pytaniu — sprawdzamy, czy AI wskaże ją samo.
- Mieszaj typy pytań: polecenie firmy, porównanie, pytanie o cenę, pytanie lokalne
  (jeśli znasz miasto firmy), pytanie problemowe.
- Każde pytanie ma dotyczyć usług, które ta firma faktycznie świadczy.

Zwróć TYLKO listę pytań."""


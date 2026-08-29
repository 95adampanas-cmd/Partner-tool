"""
Mikroaudyt SEO/GEO — zbieranie danych i składanie raportu (Faza 2).

Struktura wg docs/audyt-struktura.md (wzorzec: audyt ICEA + uwagi specjalisty).

OSZCZĘDZANIE BUDŻETU: każda funkcja zbierająca ma tryb `offline` — czyta zapisaną
próbkę z fixtures/ zamiast wołać API. Cały rozwój parserów i szablonu robimy offline;
do API sięgamy dopiero przy realnym audycie.
"""

import re

import dfs

# Silnik domyślny: Perplexity sonar. Test na tym samym prompcie dał 9 marek konkurencyjnych
# za $0.006, podczas gdy ChatGPT (gpt-5.6-sol) dał 3 marki za $0.109 — 18x drożej.
SILNIK_DOMYSLNY = ("perplexity", "sonar")
SILNIK_CHATGPT = ("chat_gpt", "gpt-5.6-sol")

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
    "case_botland": {
        "naglowek": "Skala zjawiska — przykład z rynku",
        "tekst": "Sklep Botland zwiększył ruch z ChatGPT z **4 500 do 165 000 sesji w ciągu roku**. "
                 "To pokazuje, jak szybko rośnie ten kanał — i jak kosztowna jest w nim nieobecność.",
    },
}


# ══════════════════════════════════════════════════════════════════
#  PARSERY — działają na odpowiedziach API (offline na fixtures)
# ══════════════════════════════════════════════════════════════════
def _tekst_i_zrodla(wynik: dict) -> tuple[str, list[str]]:
    """Wyciąga treść odpowiedzi i cytowane URL-e z odpowiedzi llm_responses."""
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


def _marki_z_tekstu(tekst: str, pomijaj: str = "") -> list[str]:
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
        widziane.add(klucz)
        znalezione.append(nazwa)
    return znalezione


def analizuj_odpowiedz(odp: dict, marka: str, domena: str, prompt: str) -> dict:
    """Jeden wiersz tabeli 'przykładowe prompty' — wzór: moduł Semrush ze screena."""
    wynik = (odp.get("tasks") or [{}])[0].get("result") or [{}]
    wynik = wynik[0] if wynik else {}
    tekst, zrodla = _tekst_i_zrodla(wynik)

    wspomniana = marka.lower() in tekst.lower()
    cytowana = any(domena.lower() in (u or "").lower() for u in zrodla)

    return {
        "prompt": prompt,
        "model": wynik.get("model_name", ""),
        "odpowiedz": tekst,
        "wspomniana": wspomniana,
        "cytowana": cytowana,
        "marki": _marki_z_tekstu(tekst, pomijaj=marka),
        "zrodla": zrodla,
        "koszt": wynik.get("money_spent", 0),
    }


def analizuj_ai_overview(odp: dict, domena: str) -> dict:
    """Sekcja 2 — widoczność w AI Overviews (llm_mentions, platform=google)."""
    wynik = ((odp.get("tasks") or [{}])[0].get("result") or [{}])[0]
    items = wynik.get("items") or []

    wzmianki = []
    for it in items:
        wzmianki.append({
            "prompt": it.get("question", ""),
            "wolumen": it.get("ai_search_volume") or 0,
            "zrodla": [(s.get("domain") or "") for s in (it.get("sources") or [])],
            "pozycja": next(
                (i + 1 for i, s in enumerate(it.get("sources") or [])
                 if domena.lower() in (s.get("domain") or "").lower()),
                None,
            ),
        })

    pozycje = [w["pozycja"] for w in wzmianki if w["pozycja"]]
    return {
        "liczba_wzmianek": wynik.get("total_count", 0),
        "pobrano": len(items),
        "srednia_pozycja": round(sum(pozycje) / len(pozycje), 2) if pozycje else None,
        "wzmianki": sorted(wzmianki, key=lambda w: w["wolumen"], reverse=True),
    }


# ══════════════════════════════════════════════════════════════════
#  ZBIERANIE DANYCH (płatne — używać świadomie)
# ══════════════════════════════════════════════════════════════════
def zapytaj_llm(prompt: str, silnik=SILNIK_DOMYSLNY, nazwa_fixture=None) -> dict:
    dostawca, model = silnik
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


def wzmianki_ai_overview(domena: str, limit: int = 10, nazwa_fixture=None) -> dict:
    return dfs.wywolaj(
        "ai_optimization/llm_mentions/search/live",
        [{
            "language_name": JEZYK_PL,
            "location_code": LOKALIZACJA_PL,
            "target": [{"domain": domena}],
            "limit": limit,
        }],
        nazwa_fixture,
    )


# ══════════════════════════════════════════════════════════════════
#  SKŁADANIE RAPORTU
# ══════════════════════════════════════════════════════════════════
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

    return {
        "promptow": len(wiersze),
        "wspomniana": wspomniana,
        "cytowana": cytowana,
        "udzial_wspomnien": round(100 * wspomniana / ile),
        "konkurenci": [{"marka": m, "wystapien": n} for m, n in konkurenci],
        "wzmianki_aio": (ai_overview or {}).get("liczba_wzmianek"),
        "srednia_pozycja_aio": (ai_overview or {}).get("srednia_pozycja"),
    }


def zbuduj_raport(firma: dict, wiersze: list[dict], ai_overview: dict | None,
                  koszt: float = 0.0) -> dict:
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


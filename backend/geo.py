"""
Techniczny audyt GEO — czy modele AI MOGĄ przeczytać stronę i co im to utrudnia.

Zasada nadrzędna (PRD): zero halucynacji. Każde ustalenie jest FAKTEM zmierzonym
na stronie klienta i ma dołączony dowód — kod HTTP, fragment robots.txt, listę
znalezionych typów schema. Czego nie da się zmierzyć, o tym nie piszemy.

Trzy poziomy, których NIE wolno mieszać:
  BLOKADA — udowodniona przyczyna. Bot dostaje odmowę albo zakaz. Tu wolno napisać
            „dlatego modele Was nie znają".
  BRAK    — brakujący element, który utrudnia maszynie zrozumienie strony.
            Tu piszemy „utrudnia", NIGDY „dlatego nie jesteście cytowani".
  OK      — sprawdzone i w porządku.

Najważniejsza lekcja z testów: robots.txt to tylko DEKLARACJA. brantt.pl nie blokuje
tam niczego, a serwer LiteSpeed odsyła GPTBotowi, PerplexityBotowi i ClaudeBotowi
HTTP 403 — Googlebotowi 200. Sam audyt deklaratywny tego nie widzi, dlatego
sprawdzamy dostęp EMPIRYCZNIE, podszywając się pod boty.

Koszt: 0 zł. Same żądania HTTP do strony klienta.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin
import json
import re

import requests
from bs4 import BeautifulSoup

PRZEGLADARKA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Boty zbierające treść dla modeli AI.
# nazwa -> (silnik, udział w rynku PL wg StatCounter, pełny User-Agent, skutek blokady)
#
# Udział decyduje o wadze ustalenia. Blokada Bytespidera i blokada GPTBota to
# w polskich realiach dwie zupełnie różne sprawy — pierwsza jest przypisem,
# druga odcina 86% rynku.
BOTY = {
    "GPTBot": ("ChatGPT", 86.4,
               "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
               "GPTBot/1.1; +https://openai.com/gptbot",
               "ChatGPT nie pobiera treści strony"),
    "OAI-SearchBot": ("ChatGPT", 86.4,
                      "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                      "OAI-SearchBot/1.0; +https://openai.com/searchbot",
                      "strona nie trafia do wyszukiwarki ChatGPT"),
    "PerplexityBot": ("Perplexity", 6.18,
                      "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                      "PerplexityBot/1.0; +https://perplexity.ai/perplexitybot",
                      "Perplexity nie indeksuje strony"),
    "Google-Extended": ("Gemini i AI Overviews", 3.22, "",
                        "treść nie zasila Gemini ani AI Overviews"),
    "ClaudeBot": ("Claude", 0.71,
                  "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                  "ClaudeBot/1.0; +claudebot@anthropic.com",
                  "Claude nie pobiera treści strony"),
    "anthropic-ai": ("Claude", 0.71, "", "Claude nie pobiera treści strony"),
    "CCBot": ("Common Crawl", 0.0, "",
              "strona wypada ze zbioru, na którym uczy się wiele modeli"),
    "Bytespider": ("ByteDance", 0.0, "", "treść nie zasila modeli ByteDance"),
    "Applebot-Extended": ("Apple Intelligence", 0.0, "", "treść nie zasila Apple Intelligence"),
    "meta-externalagent": ("Meta AI", 0.0, "", "treść nie zasila modeli Meta"),
}

# ── Boty UŻYTKOWE — te decydują o widoczności, a ich brakowało ──────────
#
# ROZRÓŻNIENIE, KTÓRE ZMIENIA WNIOSEK CAŁEJ SEKCJI. Boty wyżej zbierają treść do
# TRENOWANIA modeli. Poniższe pobierają stronę DOPIERO WTEDY, GDY UŻYTKOWNIK O COŚ
# PYTA — i to one rozstrzygają, czy asystent może w ogóle pokazać firmę.
#
# Bez tego podziału audyt kłamał. Sprawdzone na sortlist.pl 24.09.2026: blokują
# GPTBota (trenowanie), ale przepuszczają ChatGPT-User (odpowiadanie na żywo).
# Nasz raport mówił na to „ChatGPT nie pobiera treści strony" — nieprawda, pobiera.
# Klient dostałby polecenie naprawy konfiguracji ustawionej wzorowo.
#
# Zablokowanie bota TRENINGOWEGO to decyzja biznesowa („nie chcemy, żeby modele
# uczyły się na naszych tekstach"), nie usterka. Zablokowanie bota UŻYTKOWEGO to
# realna utrata widoczności.
BOTY_UZYTKOWE = {
    "ChatGPT-User": ("ChatGPT", 86.4, "",
                     "ChatGPT nie wejdzie na stronę, gdy klient zapyta o taką firmę"),
    "OAI-SearchBot": ("ChatGPT", 86.4, "",
                      "strona nie trafia do wyszukiwarki ChatGPT"),
    "Perplexity-User": ("Perplexity", 6.18, "",
                        "Perplexity nie zacytuje strony w odpowiedzi"),
    "PerplexityBot": ("Perplexity", 6.18, "", "Perplexity nie indeksuje strony"),
    "Claude-User": ("Claude", 0.71, "",
                    "Claude nie wejdzie na stronę, odpowiadając na pytanie o branżę"),
    "Claude-SearchBot": ("Claude", 0.71, "", "strona nie trafia do wyszukiwarki Claude"),
    "DuckAssistBot": ("DuckDuckGo AI", 0.0, "", "asystent DuckDuckGo nie cytuje strony"),
    "MistralAI-User": ("Mistral", 0.0, "", "Mistral nie wejdzie na stronę"),
    "meta-externalfetcher": ("Meta AI", 0.0, "", "Meta AI nie pobierze strony na żądanie"),
}

# Boty użytkowe dokładamy do wspólnej listy, ale pamiętamy, które są które —
# raport musi mówić o nich innym językiem.
NAZWY_UZYTKOWE = frozenset(BOTY_UZYTKOWE)
BOTY = {**BOTY, **{k: v for k, v in BOTY_UZYTKOWE.items() if k not in BOTY}}

# Poniżej tego udziału blokada jest przypisem, a nie problemem biznesowym.
PROG_ISTOTNOSCI = 3.0

SCHEMA_OPIS = {
    "Organization": "kim jest firma",
    "LocalBusiness": "firma lokalna — adres, godziny, obszar działania",
    "Service": "oferowane usługi",
    "Product": "produkty",
    "FAQPage": "pytania i odpowiedzi",
    "Article": "treści eksperckie",
    "Person": "osoby — sygnał autorstwa",
    "BreadcrumbList": "struktura serwisu",
    "Review": "opinie",
    "AggregateRating": "oceny zbiorcze",
}


def _pobierz(url, ua=PRZEGLADARKA, timeout=12):
    try:
        r = requests.get(url, headers={"User-Agent": ua}, timeout=timeout)
        return r
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  A. TEST EMPIRYCZNY — czy bot FAKTYCZNIE dostaje stronę
# ══════════════════════════════════════════════════════════════════
def test_dostepu(url: str) -> dict:
    """Pobiera stronę jako każdy z botów i porównuje z przeglądarką.

    To jedyny sposób, żeby wykryć blokadę na poziomie serwera, WAF-a czy hostingu —
    w robots.txt nie ma po niej śladu. Wykryte na brantt.pl: LiteSpeed odsyła
    botom AI 403, a Googlebotowi 200.
    """
    baza = _pobierz(url)
    if baza is None:
        return {"dziala": False, "wyniki": []}
    dl_bazowa = len(baza.text)

    testowalne = {n: d for n, d in BOTY.items() if d[2]}

    def sprawdz(poz):
        nazwa, (silnik, udzial, ua, skutek) = poz
        r = _pobierz(url, ua)
        if r is None:
            return {"bot": nazwa, "silnik": silnik, "udzial": udzial, "skutek": skutek,
                    "kod": None, "blokada": False, "powod": "brak odpowiedzi"}
        # Odmowa dostępu: 401/403/429 albo strona okrojona do szczątków.
        odmowa = r.status_code in (401, 403, 429, 451)
        okrojona = (dl_bazowa > 2000 and len(r.text) < dl_bazowa * 0.2)
        return {"bot": nazwa, "silnik": silnik, "udzial": udzial, "skutek": skutek,
                "kod": r.status_code, "dlugosc": len(r.text),
                "blokada": odmowa or okrojona,
                "powod": (f"serwer odsyła HTTP {r.status_code}" if odmowa
                          else "serwer zwraca stronę okrojoną do szczątków" if okrojona else ""),
                "serwer": r.headers.get("server", "")}

    with ThreadPoolExecutor(max_workers=5) as pool:
        wyniki = list(pool.map(sprawdz, testowalne.items()))
    return {"dziala": True, "dlugosc_bazowa": dl_bazowa, "wyniki": wyniki,
            "kod_przegladarki": baza.status_code}


# ══════════════════════════════════════════════════════════════════
#  B. DEKLARACJE — robots.txt, nagłówki, meta
# ══════════════════════════════════════════════════════════════════
def sprawdz_robots(baza: str) -> dict:
    r = _pobierz(urljoin(baza, "/robots.txt"))
    if r is None or r.status_code != 200 or not r.text.strip():
        return {"jest": False, "zablokowane": [], "dowod": "", "sitemap": [],
                "content_signal": {}}

    tresc = r.text
    bloki, biezacy, sitemapy, sygnal = {}, [], [], {}
    for linia in tresc.splitlines():
        czysta = linia.split("#")[0].strip()
        if ":" not in czysta:
            continue
        klucz, wartosc = (c.strip() for c in czysta.split(":", 1))
        k = klucz.lower()
        if k == "user-agent":
            biezacy = [wartosc]
            bloki.setdefault(wartosc.lower(), [])
        elif k == "disallow" and biezacy:
            for ua in biezacy:
                bloki.setdefault(ua.lower(), []).append(wartosc)
        elif k == "sitemap":
            sitemapy.append(czysta.split(":", 1)[1].strip())
        elif k == "content-signal":
            # Nowszy standard obok Allow/Disallow. Niesie INTENCJĘ, której z samego
            # Disallow odczytać się nie da: „search=yes,ai-input=yes,ai-train=no"
            # znaczy „pokazujcie nas, ale nie uczcie się na nas". Firma z takim
            # wpisem świadomie zarządza widocznością w AI — to zupełnie co innego
            # niż firma, która przypadkiem zablokowała wszystko.
            for para in wartosc.split(","):
                if "=" in para:
                    nazwa, val = (x.strip().lower() for x in para.split("=", 1))
                    sygnal[nazwa] = val

    zablokowane = []
    for bot, (silnik, udzial, _ua, skutek) in BOTY.items():
        reguly = bloki.get(bot.lower())
        if reguly and any(x.strip() == "/" for x in reguly):
            zablokowane.append({"bot": bot, "silnik": silnik, "udzial": udzial,
                                "skutek": skutek,
                                # To pole rozstrzyga, czy mówimy o utraconej
                                # widoczności, czy o świadomej decyzji biznesowej.
                                "rola": "uzytkowy" if bot in NAZWY_UZYTKOWE
                                        else "treningowy"})

    dowod, ua_biezacy = [], None
    interesujace = {z["bot"].lower() for z in zablokowane}
    for linia in tresc.splitlines():
        czysta = linia.strip()
        if czysta.lower().startswith("user-agent:"):
            ua_biezacy = czysta.split(":", 1)[1].strip().lower()
        if ua_biezacy in interesujace and czysta:
            dowod.append(czysta)
    return {"jest": True, "zablokowane": zablokowane, "dowod": "\n".join(dowod[:12]),
            "sitemap": sitemapy, "content_signal": sygnal}


def _schema_z_html(soup) -> tuple[list[str], list[str]]:
    """Zwraca (typy schema, wartości sameAs). sameAs to jawne powiązanie strony
    z profilami firmy — tak maszyna łączy witrynę z konkretnym PODMIOTEM."""
    typy, same_as = [], []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            dane = json.loads(tag.string or "")
        except Exception:
            continue
        stos = [dane]
        while stos:
            el = stos.pop()
            if isinstance(el, list):
                stos.extend(el)
            elif isinstance(el, dict):
                t = el.get("@type")
                if isinstance(t, str):
                    typy.append(t)
                elif isinstance(t, list):
                    typy.extend(x for x in t if isinstance(x, str))
                sa = el.get("sameAs")
                if isinstance(sa, str):
                    same_as.append(sa)
                elif isinstance(sa, list):
                    same_as.extend(x for x in sa if isinstance(x, str))
                stos.extend(v for v in el.values() if isinstance(v, (dict, list)))
    for tag in soup.find_all(attrs={"itemtype": True}):
        typy.append(str(tag["itemtype"]).rstrip("/").split("/")[-1])
    return sorted(set(typy)), sorted(set(same_as))


def sprawdz_strone(url: str) -> dict:
    r = _pobierz(url)
    if r is None:
        return {}
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    title = (soup.title.string or "").strip() if soup.title else ""
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    opis = (md.get("content") or "").strip() if md else ""
    mr = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    meta_robots = (mr.get("content") or "").strip().lower() if mr else ""
    h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    lang = ((soup.html.get("lang") if soup.html else "") or "").strip()
    schema, same_as = _schema_z_html(soup)

    czysty = BeautifulSoup(html, "html.parser")
    for t in czysty(["script", "style", "nav", "footer"]):
        t.decompose()
    slow = len(" ".join(czysty.get_text(" ").split()).split())

    return {
        "title": title, "opis": opis, "h1": h1, "lang": lang,
        "schema": schema, "same_as": same_as,
        "meta_robots": meta_robots,
        "x_robots_tag": (r.headers.get("X-Robots-Tag") or "").lower(),
        "slow_tresci": slow, "skryptow": len(soup.find_all("script")),
        "serwer": r.headers.get("server", ""),
    }


# ══════════════════════════════════════════════════════════════════
#  USTALENIA — to, co trafia do raportu
# ══════════════════════════════════════════════════════════════════
def zbuduj_ustalenia(dostep: dict, robots: dict, strona: dict, firma: dict) -> list[dict]:
    u = []
    BRAK = "nie do ustalenia"

    # ── 1. Realna odmowa dostępu. Najmocniejsze ustalenie w całym audycie.
    odmowy = [w for w in (dostep.get("wyniki") or []) if w.get("blokada")]
    if odmowy:
        istotne = [w for w in odmowy if w["udzial"] >= PROG_ISTOTNOSCI]
        glowne = istotne or odmowy
        # Udział liczymy TYLKO dla silników odciętych CAŁKOWICIE. OpenAI ma dwa roboty
        # i bywa, że jeden dostaje 403, a drugi 200 — wtedy dostęp nie jest zamknięty
        # i dopisanie tych 86% do sumy byłoby zawyżeniem.
        przechodza = {w["silnik"] for w in dostep["wyniki"] if not w.get("blokada")}
        odciete = {w["silnik"]: w["udzial"] for w in istotne if w["silnik"] not in przechodza}
        suma = sum(odciete.values())
        czesciowe = sorted({w["silnik"] for w in istotne} & przechodza)
        u.append({
            "waga": "blokada",
            "tytul": "Serwer odmawia dostępu robotom AI",
            "fakt": "Sprawdziliśmy to bezpośrednio — pobraliśmy stronę podszywając się pod "
                    "każdego z robotów. " + "; ".join(
                        f"{w['bot']} ({w['silnik']}): {w['powod']}" for w in glowne)
                    + (f". Całkowicie odcięte silniki odpowiadają za około {suma:.0f}% "
                       "polskiego rynku zapytań do AI." if suma else "")
                    + ("".join(
                        f" W przypadku silnika {s} blokada jest częściowa — jeden z jego "
                        "robotów dostaje odmowę, inny nie, więc dostęp jest ograniczony, "
                        "ale nie zamknięty." for s in czesciowe) if czesciowe else ""),
            "dowod": "\n".join(
                f"{w['bot']:16} HTTP {w['kod']}   {w.get('dlugosc', 0):>7} znaków"
                for w in dostep["wyniki"])
                + f"\n{'Przeglądarka':16} HTTP {dostep.get('kod_przegladarki')}   "
                  f"{dostep.get('dlugosc_bazowa', 0):>7} znaków"
                + (f"\n\nSerwer: {strona.get('serwer', '')}" if strona.get("serwer") else ""),
            "co_zrobic": "To jest twarda przyczyna — model nie ma jak poznać treści strony. "
                         "Blokada siedzi w konfiguracji serwera lub firewalla (nie w robots.txt), "
                         "więc zmiany w treści nic nie dadzą, dopóki nie zostanie zdjęta. "
                         "Do sprawdzenia z hostingiem lub administratorem.",
        })

    # ── 2. Zakazy zadeklarowane w robots.txt
    zab = robots.get("zablokowane") or []

    # PODZIAŁ, KTÓRY DECYDUJE O TREŚCI WNIOSKU. Bot UŻYTKOWY pobiera stronę, gdy
    # klient o coś pyta — jego zablokowanie to realna utrata widoczności. Bot
    # TRENINGOWY zbiera materiał do uczenia modelu; jego zablokowanie to świadoma
    # decyzja właściciela treści, nie usterka.
    #
    # Bez tego podziału raport kłamał. Sprawdzone na sortlist.pl: blokują GPTBota
    # (trenowanie), ale przepuszczają ChatGPT-User (odpowiadanie na żywo) — a my
    # pisaliśmy „ChatGPT nie pobiera treści strony". Klient dostałby polecenie
    # naprawy konfiguracji ustawionej wzorowo.
    uzytkowe = [z for z in zab if z.get("rola") == "uzytkowy"]
    treningowe = [z for z in zab if z.get("rola") != "uzytkowy"]
    istotne_r = [z for z in uzytkowe if z["udzial"] >= PROG_ISTOTNOSCI]
    drobne_r = [z for z in uzytkowe if z["udzial"] < PROG_ISTOTNOSCI]

    if istotne_r:
        u.append({
            "waga": "blokada",
            "tytul": "Strona jest zamknięta dla robotów, które odpowiadają klientom",
            "fakt": "; ".join(f"{z['bot']} ({z['silnik']}) — {z['skutek']}" for z in istotne_r)
                    + ". To nie są roboty trenujące modele, tylko te, które wchodzą na "
                      "stronę DOKŁADNIE WTEDY, gdy ktoś pyta asystenta o firmę z Waszej "
                      "branży. Zamknięte drzwi oznaczają, że asystent odpowie z tego, "
                      "co znalazł u konkurencji.",
            "dowod": robots.get("dowod", ""),
            "co_zrobic": "Usunąć reguły Disallow dla tych robotów w robots.txt. "
                         "Blokadę robotów TRENINGOWYCH można spokojnie zostawić — "
                         "to dwie różne sprawy.",
        })
    if drobne_r:
        u.append({
            "waga": "drobne",
            "tytul": "Zamknięte dla asystentów o znikomym udziale w Polsce",
            "fakt": "Zablokowane: " + ", ".join(f"{z['bot']} ({z['silnik']})" for z in drobne_r)
                    + ". Te silniki mają w Polsce znikomy udział, więc nie ma to wpływu "
                      "na widoczność — odnotowujemy dla porządku.",
            "dowod": "", "co_zrobic": "",
        })

    # Blokada botów treningowych NIE jest usterką. Odnotowujemy ją jako fakt, bo
    # bywa przemyślaną polityką — i klient ma widzieć, że to rozumiemy.
    if treningowe and not uzytkowe:
        u.append({
            "waga": "ok",
            "tytul": "Roboty trenujące modele zablokowane, odpowiadające — wpuszczone",
            "fakt": "Zablokowane: " + ", ".join(f"{z['bot']}" for z in treningowe)
                    + ". To roboty zbierające materiał do UCZENIA modeli, a nie te, "
                      "które pobierają stronę, odpowiadając na pytanie użytkownika. "
                      "Taka konfiguracja chroni treści przed trenowaniem, nie tracąc "
                      "widoczności w odpowiedziach — i to jest ustawienie poprawne.",
            "dowod": "", "co_zrobic": "",
        })
    elif treningowe:
        u.append({
            "waga": "drobne",
            "tytul": "Roboty trenujące modele są zablokowane",
            "fakt": "Zablokowane: " + ", ".join(f"{z['bot']}" for z in treningowe)
                    + ". To decyzja o tym, czy modele mogą uczyć się na Waszych "
                      "treściach — osobna sprawa od widoczności i nie zaliczamy jej "
                      "jako błędu.",
            "dowod": "", "co_zrobic": "",
        })

    sygnal = robots.get("content_signal") or {}
    if sygnal:
        czytelnie = {"search": "wyszukiwarki", "ai-input": "użycie w odpowiedziach AI",
                     "ai-train": "trenowanie modeli"}
        opis = "; ".join(f"{czytelnie.get(k, k)}: {'tak' if v == 'yes' else 'nie'}"
                         for k, v in sygnal.items())
        u.append({
            "waga": "ok",
            "tytul": "Strona deklaruje wprost, na co pozwala modelom AI",
            "fakt": f"Nagłówek Content-Signal w robots.txt — {opis}. To nowszy sposób "
                    "zapisania zgody niż samo Allow/Disallow: pozwala oddzielić "
                    "„pokazujcie nas w odpowiedziach\" od „uczcie się na naszych "
                    "tekstach\". Świadome ustawienie tego wyprzedza większość rynku.",
            "dowod": "", "co_zrobic": "",
        })

    if not odmowy and not zab:
        u.append({"waga": "ok", "tytul": "Roboty AI mają dostęp do strony",
                  "fakt": "Ani robots.txt, ani serwer nie blokują robotów modeli AI — "
                          "sprawdzone testem dostępu.", "dowod": "", "co_zrobic": ""})

    if not strona:
        return u

    # ── 3. Zakaz indeksowania ukryty w nagłówku lub meta
    for pole, gdzie in (("x_robots_tag", "nagłówku HTTP X-Robots-Tag"),
                        ("meta_robots", "znaczniku <meta name=\"robots\">")):
        wart = strona.get(pole) or ""
        if "noindex" in wart:
            u.append({
                "waga": "blokada",
                "tytul": f"Strona ma zakaz indeksowania w {gdzie}",
                "fakt": f"Wartość: „{wart}”. To wyklucza stronę z wyników wyszukiwania, "
                        "a przez to również z odpowiedzi opartych na wyszukiwarce.",
                "dowod": "", "co_zrobic": "Usunąć noindex, jeśli strona ma być widoczna.",
            })

    # ── 4. Dane strukturalne
    schema = strona.get("schema") or []
    if not schema:
        u.append({"waga": "brak", "tytul": "Brak danych strukturalnych (schema.org)",
                  "fakt": "Na stronie głównej nie ma ani jednego znacznika schema.org.",
                  "dowod": "",
                  "co_zrobic": "Dodać co najmniej Organization (kim jest firma) i Service "
                               "lub Product (co oferuje) — to format, w którym maszyna czyta "
                               "fakty wprost, zamiast wyciągać je z tekstu."})
    elif not ({"Organization", "LocalBusiness"} & set(schema)):
        u.append({"waga": "brak", "tytul": "Dane strukturalne bez opisu samej firmy",
                  "fakt": f"Znaleziono: {', '.join(schema[:8])}. Brakuje typu Organization "
                          "lub LocalBusiness, czyli tego, który mówi, KIM jest firma.",
                  "dowod": "", "co_zrobic": "Dodać Organization z nazwą, adresem, NIP-em i kontaktem."})
    else:
        rozp = [f"{s} ({SCHEMA_OPIS[s]})" for s in schema if s in SCHEMA_OPIS]
        u.append({"waga": "ok", "tytul": "Dane strukturalne obecne",
                  "fakt": "Znaleziono: " + ("; ".join(rozp[:5]) or ", ".join(schema[:6])) + ".",
                  "dowod": "", "co_zrobic": ""})

    if schema and "FAQPage" not in schema:
        u.append({"waga": "brak", "tytul": "Brak sekcji FAQ w danych strukturalnych",
                  "fakt": "Nie znaleziono znacznika FAQPage.", "dowod": "",
                  "co_zrobic": "Pytania i odpowiedzi to materiał, po który modele sięgają "
                               "najchętniej — mają gotową odpowiedź na gotowe pytanie."})

    # ── 5. sameAs — powiązanie witryny z podmiotem
    if schema and not (strona.get("same_as") or []):
        u.append({"waga": "brak", "tytul": "Brak powiązania z profilami firmy (sameAs)",
                  "fakt": "Dane strukturalne nie zawierają pola sameAs, czyli odnośników "
                          "do profili firmy w innych serwisach.",
                  "dowod": "",
                  "co_zrobic": "Dodać sameAs z adresami profili (LinkedIn, Facebook, wizytówka "
                               "Google, katalogi branżowe). To jawna informacja dla maszyny, "
                               "że strona i te profile opisują ten sam podmiot."})

    # ── 6. Podstawy on-page
    t = strona.get("title") or ""
    if not t:
        u.append({"waga": "brak", "tytul": "Brak tytułu strony (<title>)",
                  "fakt": "Strona główna nie ma znacznika title.", "dowod": "",
                  "co_zrobic": "Dodać tytuł z nazwą firmy i główną usługą."})
    elif len(t) < 25:
        u.append({"waga": "brak", "tytul": "Bardzo krótki tytuł strony",
                  "fakt": f"Tytuł ma {len(t)} znaków: „{t}”.", "dowod": "",
                  "co_zrobic": "Uzupełnić o to, czym firma się zajmuje i dla kogo."})
    if not (strona.get("opis") or ""):
        u.append({"waga": "brak", "tytul": "Brak meta description",
                  "fakt": "Strona główna nie ma opisu w meta description.", "dowod": "",
                  "co_zrobic": "Dodać 1–2 zdania streszczające ofertę."})

    h1 = strona.get("h1") or []
    if not h1:
        u.append({"waga": "brak", "tytul": "Brak nagłówka H1",
                  "fakt": "Na stronie głównej nie ma nagłówka H1 — czyli zdania, które "
                          "wprost mówi, czym firma się zajmuje.", "dowod": "",
                  "co_zrobic": "Dodać jeden H1 z jasnym opisem działalności."})
    elif len(h1) > 3:
        u.append({"waga": "brak", "tytul": f"Aż {len(h1)} nagłówków H1 na jednej stronie",
                  "fakt": "Znaleziono: " + "; ".join(x[:40] for x in h1[:4]) + "…",
                  "dowod": "", "co_zrobic": "Zostawić jeden H1 — inaczej temat strony jest niejasny."})

    if not (strona.get("lang") or ""):
        u.append({"waga": "brak", "tytul": "Brak deklaracji języka",
                  "fakt": "Znacznik <html> nie ma atrybutu lang.", "dowod": "",
                  "co_zrobic": 'Dodać lang="pl".'})

    slow = strona.get("slow_tresci") or 0
    if slow < 120:
        u.append({"waga": "brak", "tytul": "Bardzo mało treści w kodzie strony",
                  "fakt": f"W surowym HTML naliczyliśmy {slow} słów przy "
                          f"{strona.get('skryptow', 0)} skryptach.",
                  "dowod": "",
                  "co_zrobic": "Jeśli treść dogrywa się JavaScriptem, roboty AI mogą jej "
                               "nie zobaczyć. Kluczowe informacje powinny być w kodzie "
                               "serwowanym od razu."})

    # ── 7. Tożsamość podmiotu
    brakujace = [n for n, k in (("nazwa prawna", "nazwa_prawna"), ("NIP", "nip"),
                                ("adres", "adres"), ("telefon", "telefon"), ("e-mail", "email"))
                 if (firma.get(k) or BRAK) == BRAK]
    if brakujace and firma:
        u.append({"waga": "brak", "tytul": "Niepełne dane identyfikujące firmę",
                  "fakt": "Na przeszukanych podstronach nie znaleźliśmy: "
                          + ", ".join(brakujace) + ".",
                  "dowod": "",
                  "co_zrobic": "Komplet danych rejestrowych pozwala powiązać stronę "
                               "z konkretnym podmiotem."})
    return u


def audyt_geo(url: str, firma: dict | None = None) -> dict:
    """Cały techniczny audyt GEO. Bez kosztów API."""
    firma = firma or {}
    p = urlparse(url)
    baza = f"{p.scheme}://{p.netloc}"
    dostep = test_dostepu(url)
    robots = sprawdz_robots(baza)
    strona = sprawdz_strone(url)
    ustalenia = zbuduj_ustalenia(dostep, robots, strona, firma)
    return {
        "ustalenia": ustalenia,
        "blokady": sum(1 for x in ustalenia if x["waga"] == "blokada"),
        "braki": sum(1 for x in ustalenia if x["waga"] == "brak"),
        "ok": sum(1 for x in ustalenia if x["waga"] == "ok"),
        "pomiary": {k: strona.get(k) for k in
                    ("title", "opis", "lang", "schema", "same_as", "slow_tresci", "serwer")},
    }

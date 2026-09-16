"""
Claude jako silnik językowy narzędzia.

DLACZEGO NATYWNE SDK, A NIE WARSTWA ZGODNOŚCI. Osiem z dziewięciu naszych zadań to
jeden strzał: prompt wchodzi, wynik wychodzi. Tylko czat prowadzi pętlę z narzędziem.
Przy takim rozkładzie warstwa pośrednia (LiteLLM pod Agents SDK) kosztowałaby nas
dokładnie to, po co tu przyszliśmy: cache promptu i Batch API są specyficzne dla
Anthropic i przez taki adapter albo nie przechodzą, albo przechodzą po cichu bez
efektu. Wolimy mniej magii i pełną kontrolę nad tym, co leci w żądaniu.

CO ZOSTAŁO NA OPENAI — świadomie, jeden agent. `agent_pytajacy` w audycie GEO nie
używa modelu do pracy, tylko go MIERZY: pyta „kogo polecasz" i sprawdza, czy padnie
nazwa badanej firmy. Przełączenie go na Claude nie zmieniłoby dostawcy, tylko
przedmiot pomiaru — raport przestałby mówić „jesteś widoczny w ChatGPT". Patrz
komentarz przy nim w app.py.

PUŁAPKA CACHE, WARTA ZAPAMIĘTANIA. Anthropic cache'uje tylko prefiks dłuższy niż
próg modelu (Sonnet 1024 tokeny, Haiku 2048). Krótszy blok z `cache_control`
przechodzi BEZ BŁĘDU i bez efektu — kod wygląda, jakby cache działał, a rachunek
mówi co innego. Dlatego nie ufamy deklaracji: `_da_sie_cachowac()` sprawdza długość
i włącza cache tylko wtedy, gdy blok realnie przekracza próg. Reszta to zwykły
prompt. To ta sama zasada, co przy fałszywych zerach — brak efektu ma być widoczny.

BATCH KOSZTUJE POŁOWĘ, ALE PŁACI SIĘ CZASEM. Message Batches to tryb asynchroniczny:
zlecasz i wracasz (deklarowane do 24h, w praktyce zwykle minuty). Nadaje się do
roboty hurtowej, której nikt nie ogląda na żywo — przebadanie wszystkich partnerów
od nowa, maile do wielu firm naraz. NIE nadaje się pod przycisk, po którym człowiek
czeka na wynik. Dlatego batch jest tu osobną funkcją, a nie domyślnym trybem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import os
import re
import time

import anthropic
from pydantic import BaseModel

# ── Modele ────────────────────────────────────────────────────────────
# Podział wg ryzyka, nie wg ceny: tam, gdzie wynik czyta człowiek albo trafia do
# maila do partnera, stoi model mocniejszy. Klasyfikacja i tagowanie idą na tani.
MOCNY = "claude-sonnet-5"
TANI = "claude-haiku-4-5-20251001"

# Minimalna długość prefiksu, żeby cache w ogóle zadziałał. Wartości z dokumentacji
# Anthropic; gdyby się zmieniły, objawem będzie cache bez oszczędności, nie awaria.
PROGI_CACHE = {MOCNY: 1024, TANI: 2048}

# Ceny za milion tokenów (wejście, wyjście) — wyłącznie do szacunku w logu.
# Rachunek jest u dostawcy; to ma tylko dawać rząd wielkości przy testach.
CENY = {MOCNY: (2.0, 10.0), TANI: (1.0, 5.0)}

# Ile znaków polskiego tekstu przypada na jeden token. ZMIERZONE 16.09.2026 przez
# count_tokens na pięciu naszych prawdziwych promptach: 1,83 / 1,87 / 1,87 / 1,93 /
# 1,93. Pierwsza wersja zakładała 2,7 — wartość z intuicji o angielskim — i myliła
# się o 40%: profil Last Agency wychodził na 931 tokenów przy prawdziwych 1300,
# czyli kod wyłączyłby cache dla bloku, który próg spokojnie przekracza.
#
# Polski ma więcej tokenów na znak niż angielski (odmiana, ogonki), więc szacowanie
# „po angielsku" zawsze zaniża. Używamy tego TYLKO do wstępnej oceny; rozstrzyga
# sprawdz_cache() prawdziwym wywołaniem count_tokens.
ZNAKI_NA_TOKEN = 1.9

MAX_TOKENOW = 4096
MAX_PETLI = 6          # ile razy czat może sięgnąć po narzędzie, zanim przerwiemy


class BladClaude(Exception):
    """Awaria modelu. Rzucamy zamiast zwracać pustkę — brak danych i brak odpowiedzi
    to dwie różne rzeczy, a mylenie ich kosztowało nas już raport pełen zer."""


_klient_ = None


def klient() -> anthropic.Anthropic:
    global _klient_
    if _klient_ is None:
        kl = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not kl:
            raise BladClaude(
                "Brak ANTHROPIC_API_KEY w .env — bez niego nie działa nic poza "
                "audytem GEO, który chodzi na kluczu OpenAI.")
        _klient_ = anthropic.Anthropic(api_key=kl, max_retries=3)
    return _klient_


# ══════════════════════════════════════════════════════════════════════
#  Zadanie — odpowiednik dawnego Agenta
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Zadanie:
    """Jedno zadanie dla modelu.

    `staly` to część promptu, która NIGDY się nie zmienia między firmami — profil
    Last Agency, zasady ekstrakcji. Tylko ona nadaje się do cache. `instrukcje` to
    reszta systemowego promptu. Rozdzielamy je, bo cache obejmuje PREFIKS: cokolwiek
    zmiennego trafi przed blok stały, unieważnia go przy każdym wywołaniu.
    """
    nazwa: str
    instrukcje: str
    model: str = MOCNY
    schemat: type[BaseModel] | None = None
    staly: str = ""
    max_tokenow: int = MAX_TOKENOW
    narzedzia: list[dict] = field(default_factory=list)


@dataclass
class Wynik:
    """Nazwa pola `final_output` jest celowa — tak nazywał to Agents SDK i dzięki
    temu migracja nie dotyka dziewięciu miejsc użycia wyniku, tylko samej linii
    wywołania."""
    final_output: object
    odwiedzone: list[str] = field(default_factory=list)
    uzycie: dict = field(default_factory=dict)


def _da_sie_cachowac(tekst: str, model: str) -> bool:
    """Czy blok ma szansę przekroczyć próg cache. Szacunek po znakach — celowo
    ostrożny, bo cache poniżej progu nie zgłasza błędu, tylko nic nie robi."""
    return len(tekst) / ZNAKI_NA_TOKEN >= PROGI_CACHE.get(model, 1024)


def _system(z: Zadanie) -> list[dict]:
    """System prompt jako bloki. Stały prefiks idzie PIERWSZY i dostaje cache_control
    tylko wtedy, gdy realnie przekracza próg — inaczej byłaby to ozdoba w kodzie."""
    bloki = []
    if z.staly:
        blok = {"type": "text", "text": z.staly}
        if _da_sie_cachowac(z.staly, z.model):
            blok["cache_control"] = {"type": "ephemeral"}
        bloki.append(blok)
    if z.instrukcje:
        bloki.append({"type": "text", "text": z.instrukcje})
    return bloki


def _zuzycie(odp) -> dict:
    u = getattr(odp, "usage", None)
    return {
        "wejscie": getattr(u, "input_tokens", 0),
        "wyjscie": getattr(u, "output_tokens", 0),
        "cache_zapis": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_odczyt": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def _narzedzie_schematu(schemat: type[BaseModel]) -> dict:
    """Wymuszony output strukturalny realizujemy przez tool use: model musi wywołać
    narzędzie o zadanym schemacie, więc nie ma jak zwrócić prozy zamiast danych."""
    return {
        "name": "zapisz_wynik",
        "description": "Zapisz wynik w wymaganej strukturze.",
        "input_schema": schemat.model_json_schema(),
    }


def _wywolaj(z: Zadanie, wiadomosci: list[dict], tools=None, tool_choice=None):
    kw = dict(model=z.model, max_tokens=z.max_tokenow,
              system=_system(z), messages=wiadomosci)
    if tools:
        kw["tools"] = tools
    if tool_choice:
        kw["tool_choice"] = tool_choice
    try:
        return klient().messages.create(**kw)
    except anthropic.APIStatusError as e:
        raise BladClaude(f"[{z.nazwa}] Claude odmówił: HTTP {e.status_code} — {e}") from e
    except anthropic.APIConnectionError as e:
        raise BladClaude(f"[{z.nazwa}] Brak połączenia z Claude: {e}") from e


# Narzędzie, które faktycznie coś pobrało, zaczyna odpowiedź od znacznika
# "[TREŚĆ <pełny adres>]". Odmowa i błąd pobrania go NIE mają — dzięki temu na
# liście źródeł ląduje wyłącznie to, co naprawdę zostało przeczytane.
RE_ZRODLO = re.compile(r"^\[TREŚĆ (https?://[^\]]+)\]")


def _adres_z_tresci(tresc: str) -> str:
    m = RE_ZRODLO.match(tresc)
    return m.group(1) if m else ""


def _tekst_z(odp) -> str:
    return "".join(b.text for b in odp.content
                   if getattr(b, "type", "") == "text").strip()


def uruchom_sync(z: Zadanie, wejscie: str) -> Wynik:
    """Jeden strzał albo pętla z narzędziami — zależnie od tego, co ma Zadanie."""
    if z.schemat is not None:
        odp = _wywolaj(z, [{"role": "user", "content": wejscie}],
                       tools=[_narzedzie_schematu(z.schemat)],
                       tool_choice={"type": "tool", "name": "zapisz_wynik"})
        for blok in odp.content:
            if getattr(blok, "type", "") == "tool_use":
                return Wynik(z.schemat.model_validate(blok.input), uzycie=_zuzycie(odp))
        raise BladClaude(f"[{z.nazwa}] Model nie zwrócił struktury mimo wymuszenia.")

    if not z.narzedzia:
        odp = _wywolaj(z, [{"role": "user", "content": wejscie}])
        return Wynik(_tekst_z(odp), uzycie=_zuzycie(odp))

    return _petla_narzedzi(z, wejscie)


def _petla_narzedzi(z: Zadanie, wejscie: str) -> Wynik:
    """Pętla tool use. Limit obrotów jest twardy: model, który nie może znaleźć
    odpowiedzi, potrafi otwierać kolejne podstrony bez końca — a każda to nasze
    żądanie do cudzego serwera i nasz token."""
    wiadomosci = [{"role": "user", "content": wejscie}]
    odwiedzone, uzycie = [], {}
    wykonaj = {n["name"]: n["wykonaj"] for n in z.narzedzia}
    opisy = [{k: v for k, v in n.items() if k != "wykonaj"} for n in z.narzedzia]
    odp = None

    for _ in range(MAX_PETLI):
        odp = _wywolaj(z, wiadomosci, tools=opisy)
        for k, v in _zuzycie(odp).items():
            uzycie[k] = uzycie.get(k, 0) + v

        if odp.stop_reason != "tool_use":
            return Wynik(_tekst_z(odp), odwiedzone, uzycie)

        wiadomosci.append({"role": "assistant", "content": odp.content})
        wyniki = []
        for blok in odp.content:
            if getattr(blok, "type", "") != "tool_use":
                continue
            # Źródła zbieramy TU, w miejscu wywołania narzędzia. Poprzednia wersja
            # wyciągała je z obiektów zwracanych przez SDK i cicho gubiła —
            # odpowiedzi wyglądały poprawnie, a lista źródeł była pusta.
            #
            # Bierzemy adres z ODPOWIEDZI narzędzia, nie z tego, o co model poprosił:
            # model podaje zwykle samą ścieżkę ("/oferta"), a użytkownikowi trzeba
            # pokazać pełny, klikalny URL. Kanoniczną wersję zna narzędzie, bo to
            # ono skleja adres i sprawdza domenę.
            tresc = str(wykonaj[blok.name](**(blok.input or {})))
            zrodlo = _adres_z_tresci(tresc)
            if zrodlo and zrodlo not in odwiedzone:
                odwiedzone.append(zrodlo)
            wyniki.append({"type": "tool_result", "tool_use_id": blok.id,
                           "content": tresc})
        wiadomosci.append({"role": "user", "content": wyniki})

    return Wynik(_tekst_z(odp) if odp else "", odwiedzone, uzycie)


async def uruchom(z: Zadanie, wejscie: str) -> Wynik:
    """Wersja asynchroniczna — SDK jest synchroniczne, więc oddajemy je wątkowi,
    żeby nie blokować pętli zdarzeń serwera."""
    return await asyncio.to_thread(uruchom_sync, z, wejscie)


# ══════════════════════════════════════════════════════════════════════
#  Diagnostyka cache
# ══════════════════════════════════════════════════════════════════════
def policz_tokeny(tekst: str, model: str = MOCNY) -> int:
    """Prawdziwa liczba tokenów, prosto od Anthropic. Osobne, tanie wywołanie."""
    r = klient().messages.count_tokens(
        model=model,
        system=[{"type": "text", "text": tekst}],
        messages=[{"role": "user", "content": "."}])
    return r.input_tokens


def sprawdz_cache(zadania: list[Zadanie]) -> list[dict]:
    """Czy bloki stałe faktycznie przekraczają próg. Do odpalenia po każdej zmianie
    profilu — bo cache poniżej progu milczy, zamiast krzyczeć."""
    raport = []
    for z in zadania:
        if not z.staly:
            continue
        prog = PROGI_CACHE.get(z.model, 1024)
        tok = policz_tokeny(z.staly, z.model)
        raport.append({"zadanie": z.nazwa, "model": z.model, "tokenow": tok,
                       "prog": prog, "cache_dziala": tok >= prog})
    return raport


# ══════════════════════════════════════════════════════════════════════
#  Batch — połowa ceny, kosztem czekania
# ══════════════════════════════════════════════════════════════════════
def batch_wyslij(zadania: list[tuple[str, Zadanie, str]]) -> str:
    """Zlecenie hurtowe. Lista (identyfikator, Zadanie, wejście) -> id partii.

    Identyfikator wraca razem z wynikiem i to jedyny sposób, żeby dopasować
    odpowiedź do firmy — kolejność NIE jest gwarantowana.
    """
    prosby = []
    for ident, z, wejscie in zadania:
        params = {"model": z.model, "max_tokens": z.max_tokenow,
                  "system": _system(z),
                  "messages": [{"role": "user", "content": wejscie}]}
        if z.schemat is not None:
            params["tools"] = [_narzedzie_schematu(z.schemat)]
            params["tool_choice"] = {"type": "tool", "name": "zapisz_wynik"}
        prosby.append({"custom_id": ident, "params": params})
    partia = klient().messages.batches.create(requests=prosby)
    return partia.id


def batch_stan(id_partii: str) -> dict:
    p = klient().messages.batches.retrieve(id_partii)
    licz = p.request_counts
    return {"id": p.id, "status": p.processing_status,
            "gotowe": getattr(licz, "succeeded", 0),
            "bledy": getattr(licz, "errored", 0) + getattr(licz, "canceled", 0),
            "w_toku": getattr(licz, "processing", 0)}


def batch_wyniki(id_partii: str, schemat: type[BaseModel] | None = None) -> dict:
    """Wyniki po identyfikatorach. Pozycje, które padły, mają wartość None —
    rozróżnienie „nie wyszło" od „wyszło puste" jest tu tak samo ważne jak w audycie."""
    out = {}
    for w in klient().messages.batches.results(id_partii):
        if w.result.type != "succeeded":
            out[w.custom_id] = None
            continue
        tresc = w.result.message.content
        if schemat is not None:
            out[w.custom_id] = next(
                (schemat.model_validate(b.input) for b in tresc
                 if getattr(b, "type", "") == "tool_use"), None)
        else:
            out[w.custom_id] = "".join(
                b.text for b in tresc if getattr(b, "type", "") == "text").strip()
    return out


def batch_czekaj(id_partii: str, co_ile: int = 20, limit_sekund: int = 3600) -> dict:
    """Odpytuje partię do skutku. Dla zadań nocnych — nie dla ścieżki z przyciskiem."""
    koniec = time.time() + limit_sekund
    while time.time() < koniec:
        stan = batch_stan(id_partii)
        if stan["status"] == "ended":
            return stan
        time.sleep(co_ile)
    raise BladClaude(f"Partia {id_partii} nie skończyła się w {limit_sekund} s.")

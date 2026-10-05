"""
Dostęp do narzędzia: jedno wspólne hasło dla całego działu.

Po co: na serwerze każdy, kto zna adres, odpalałby audyty na naszych kluczach
OpenAI i DataForSEO i czytał bazę partnerów. Konta per osoba to dziś przerost
formy — narzędzia używa kilka osób z jednego działu.

HASŁO NIE SIEDZI W KODZIE. Kod jest na GitHubie, hasło w zmiennej HASLO_DOSTEPU
(.env lokalnie, Environment na Renderze). Bez zmiennej:
  - lokalnie narzędzie jest otwarte (praca na własnym komputerze),
  - na Renderze (zmienna RENDER ustawiana przez Render) — zamknięte dla wszystkich.
    Zapomniane hasło przy wdrożeniu nie może znaczyć „otwarte dla świata".

SESJA to podpisane ciasteczko: termin ważności + podpis HMAC. Klucz podpisu
pochodzi z hasła, więc zmiana hasła wylogowuje wszystkich — dokładnie to, czego
się chce, gdy hasło wyciekło.
"""

import hashlib
import hmac
import os
import threading
import time

CIASTECZKO = "pt_sesja"
WAZNOSC_SESJI = 30 * 24 * 3600          # 30 dni — narzędzie do codziennej pracy

# Blokada zgadywania: hasło jest krótkie, więc bez limitu prób dałoby się je
# odgadnąć słownikiem. 10 pomyłek z jednego adresu → kwadrans przerwy.
MAX_PROB = 10
OKNO_PROB = 15 * 60
_proby: dict[str, list[float]] = {}
_zamek = threading.Lock()


def haslo() -> str:
    return os.environ.get("HASLO_DOSTEPU", "").strip()


def na_serwerze() -> bool:
    return bool(os.environ.get("RENDER"))


def wlaczone() -> bool:
    """Czy wymagamy logowania. Na serwerze — zawsze."""
    return bool(haslo()) or na_serwerze()


def _klucz() -> bytes:
    return hashlib.sha256(b"partner-tool-sesja|" + haslo().encode()).digest()


def _podpis(tresc: str) -> str:
    return hmac.new(_klucz(), tresc.encode(), hashlib.sha256).hexdigest()


def sprawdz_haslo(podane: str) -> bool:
    h = haslo()
    # compare_digest: porównanie w stałym czasie — czas odpowiedzi nie zdradza,
    # ile pierwszych znaków się zgadza.
    return bool(h) and hmac.compare_digest(podane.encode(), h.encode())


def utworz_sesje(teraz: float | None = None) -> str:
    wygasa = str(int((teraz or time.time()) + WAZNOSC_SESJI))
    return f"{wygasa}.{_podpis(wygasa)}"


def sesja_wazna(token: str | None, teraz: float | None = None) -> bool:
    if not token or "." not in token or not haslo():
        return False
    wygasa, podpis = token.split(".", 1)
    if not wygasa.isdigit() or not hmac.compare_digest(podpis, _podpis(wygasa)):
        return False
    return int(wygasa) > (teraz or time.time())


def zablokowany(adres: str, teraz: float | None = None) -> bool:
    teraz = teraz or time.time()
    with _zamek:
        swieze = [t for t in _proby.get(adres, []) if teraz - t < OKNO_PROB]
        _proby[adres] = swieze
        return len(swieze) >= MAX_PROB


def nieudana_proba(adres: str, teraz: float | None = None) -> None:
    with _zamek:
        _proby.setdefault(adres, []).append(teraz or time.time())


def wyczysc_proby(adres: str) -> None:
    with _zamek:
        _proby.pop(adres, None)

"""
Klient DataForSEO — mikroaudyt SEO/GEO (Faza 2).

Zasada oszczędzania budżetu: KAŻDA odpowiedź ląduje w fixtures/*.json.
Parsowanie i szablon raportu rozwijamy potem offline na zapisanych próbkach — za darmo.
Do API wracamy dopiero, gdy potrzebujemy nowego kształtu danych.

Każde wywołanie wypisuje koszt i saldo, żeby nie przepalić kredytu przez przypadek.
"""

from pathlib import Path
import base64
import json
import os
import urllib.error
import urllib.request
import time

from dotenv import load_dotenv

KATALOG = Path(__file__).resolve().parent
load_dotenv(KATALOG / ".env", override=True)
FIXTURES = KATALOG / "fixtures"
FIXTURES.mkdir(exist_ok=True)

BAZA = "https://api.dataforseo.com/v3"


def _auth() -> str:
    login = os.environ.get("DATAFORSEO_LOGIN", "")
    haslo = os.environ.get("DATAFORSEO_PASSWORD", "")
    if not login or not haslo:
        raise RuntimeError("Brak DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD w .env")
    return "Basic " + base64.b64encode(f"{login}:{haslo}".encode()).decode()


# API bywa niestabilne: potrafi zerwać połączenie (WinError 10054) albo odesłać
# status 20000 Ok z pustym `result`. Bez ponawiania jedno takie potknięcie wywala
# cały audyt — już PO opłaceniu wcześniejszych wywołań. Ponawiamy tylko błędy
# sieciowe i 5xx; błędnego loginu czy złego zapytania powtarzać nie ma sensu.
PROBY = 3
ODSTEPY = (1.5, 4.0)


def _zapytaj(req: urllib.request.Request, timeout: int) -> dict:
    ostatni = None
    for nr in range(PROBY):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code < 500:
                raise                      # 401, 403, 404 — ponawianie nic nie da
            ostatni = e
        except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError) as e:
            ostatni = e
        if nr < PROBY - 1:
            czekaj = ODSTEPY[min(nr, len(ODSTEPY) - 1)]
            print(f"  [ponawiam za {czekaj}s — {type(ostatni).__name__}: {ostatni}]")
            time.sleep(czekaj)
    raise ostatni


def saldo() -> float | None:
    """Darmowe — sprawdzenie stanu konta. None, gdy API nie odpowiedziało sensownie."""
    req = urllib.request.Request(f"{BAZA}/appendix/user_data", headers={"Authorization": _auth()})
    try:
        d = _zapytaj(req, 30)
        return (((d.get("tasks") or [{}])[0].get("result") or [{}])[0]
                .get("money", {}).get("balance"))
    except Exception:
        return None


def pobierz(endpoint: str, nazwa_fixture: str | None = None) -> dict:
    """GET — używane przez endpointy informacyjne (listy modeli, lokalizacji). Zwykle darmowe."""
    req = urllib.request.Request(f"{BAZA}/{endpoint}", headers={"Authorization": _auth()})
    odp = _zapytaj(req, 60)
    nazwa = nazwa_fixture or endpoint.replace("/", "_")
    (FIXTURES / f"{nazwa}.json").write_text(
        json.dumps(odp, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[GET {endpoint}] koszt: ${odp.get('cost', 0)} -> fixtures/{nazwa}.json")
    return odp


def wywolaj(endpoint: str, dane: list | None = None, nazwa_fixture: str | None = None) -> dict:
    """POST do DataForSEO. Zapisuje surową odpowiedź do fixtures/ i pokazuje koszt.

    endpoint: np. "ai_optimization/llm_mentions/search/live"
    dane: lista zadań (DataForSEO zawsze przyjmuje listę)
    """
    body = json.dumps(dane or [{}]).encode()
    req = urllib.request.Request(
        f"{BAZA}/{endpoint}",
        data=body,
        headers={"Authorization": _auth(), "Content-Type": "application/json"},
    )
    odp = _zapytaj(req, 180)

    nazwa = nazwa_fixture or endpoint.replace("/", "_")
    (FIXTURES / f"{nazwa}.json").write_text(
        json.dumps(odp, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    zadanie = (odp.get("tasks") or [{}])[0]
    print(f"[{endpoint}]")
    print(f"  status : {odp.get('status_code')} {odp.get('status_message')}")
    print(f"  zadanie: {zadanie.get('status_code')} {zadanie.get('status_message')}")
    print(f"  KOSZT  : ${odp.get('cost', 0)}")
    print(f"  fixture: fixtures/{nazwa}.json")
    return odp


def wczytaj(nazwa: str) -> dict:
    """Odczyt zapisanej próbki — do pracy offline, bez kosztu."""
    return json.loads((FIXTURES / f"{nazwa}.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    print(f"Saldo: ${saldo()}")

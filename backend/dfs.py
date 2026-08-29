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
import urllib.request

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


def saldo() -> float:
    """Darmowe — sprawdzenie stanu konta."""
    req = urllib.request.Request(f"{BAZA}/appendix/user_data", headers={"Authorization": _auth()})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return d["tasks"][0]["result"][0]["money"]["balance"]


def pobierz(endpoint: str, nazwa_fixture: str | None = None) -> dict:
    """GET — używane przez endpointy informacyjne (listy modeli, lokalizacji). Zwykle darmowe."""
    req = urllib.request.Request(f"{BAZA}/{endpoint}", headers={"Authorization": _auth()})
    odp = json.loads(urllib.request.urlopen(req, timeout=60).read())
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
    odp = json.loads(urllib.request.urlopen(req, timeout=180).read())

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

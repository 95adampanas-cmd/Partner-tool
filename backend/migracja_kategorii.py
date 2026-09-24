"""
Przepisanie kategorii zbadanych firm na nową listę — jednorazowo, po zmianie
KATEGORIE_PARTNEROW.

DLACZEGO TO NIE JEST ZWYKŁE PODMIENIENIE NAZW. Stare szufladki były szersze niż
nowe kategorie: „Budowa stron i sklepów" to dziś ALBO „Strony www", ALBO „Sklepy
internetowe", a której użyć, rozstrzyga oferta konkretnej firmy — nie nazwa. Tam,
gdzie mapa nazw wystarcza (`app.STARE_KATEGORIE`), używamy jej i nie płacimy za nic.
Tam, gdzie nie wystarcza, pytamy model — ale o SAMĄ kategorię i na podstawie danych,
które już mamy w bazie. Zero ponownego scrapowania.

Model: Haiku. To klasyfikacja jednego pola z gotowego opisu, a nie research.

Domyślnie tylko POKAZUJE, co by zrobił. Zapis dopiero z `--zapisz`:

    python migracja_kategorii.py                       # podgląd
    python migracja_kategorii.py --zapisz              # przepisanie bazy
    python migracja_kategorii.py --wszystkie --zapisz  # także rekordy o nazwach
                                                       # zbieżnych ze starą listą
"""

from __future__ import annotations

import sys

from pydantic import BaseModel

import app
import baza
import claude


class Kategoria(BaseModel):
    kategoria: str
    powod: str


def _zadanie() -> claude.Zadanie:
    return claude.Zadanie(
        nazwa="migracja-kategorii",
        model=claude.TANI,
        schemat=Kategoria,
        instrukcje=(
            "Przypisujesz firmę do JEDNEJ kategorii partnerskiej. Przepisz nazwę "
            "znak w znak z listy poniżej — inna nazwa jest bezużyteczna, bo nie "
            "istnieje w interfejsie." + app._NOWA_LINIA * 2 +
            "USŁUGI — firmy, które coś robią DLA klienta:" + app._NOWA_LINIA +
            app._LISTA_USLUGOWE + app._NOWA_LINIA * 2 +
            "SaaS I PRODUKTY — firmy, które sprzedają WŁASNE oprogramowanie:" +
            app._NOWA_LINIA + app._LISTA_SAAS + app._NOWA_LINIA * 2 +
            # Te same reguły co przy researchu. Gdyby migracja miała własne,
            # ta sama firma dostałaby inną kategorię zależnie od tego, czy
            # przeszła przez research dziś, czy przed zmianą listy.
            app.REGULY_KATEGORII + app._NOWA_LINIA * 2 +
            "W `powod` napisz jedno zdanie, na jakiej podstawie. Człowiek to czyta."
        ),
    )


def _opis(f: dict) -> str:
    """Wejście dla modelu — tylko to, co już mamy zapisane."""
    uslugi = ", ".join((f.get("uslugi") or [])[:15])
    return app._NOWA_LINIA.join([
        f"Nazwa: {f.get('nazwa') or ''}",
        f"Adres: {f.get('url') or ''}",
        f"Branża: {f.get('branza') or ''}",
        f"Usługi: {uslugi}",
        f"Opis: {f.get('opis') or ''}",
        f"SEO w ofercie: {f.get('seo_zakres') or ''}",
    ])


def _brak_danych(f: dict) -> bool:
    """Czy o firmie wiadomo cokolwiek poza adresem.

    Rozstrzygają BRANŻA i USŁUGI, a nie opis. Opis bywa wypełniony nawet wtedy,
    gdy nic nie ustalono — Brantt ma tam zdanie „nie da się ustalić profilu firmy
    z dostarczonego tekstu", które ma 60 znaków i przechodziło każdy test na
    długość. Model dostawał to jako materiał i odpowiadał „<UNKNOWN>".
    """
    uslugi = [u for u in (f.get("uslugi") or []) if u and u != app.BRAK]
    branza = (f.get("branza") or "").strip()
    return not uslugi and branza in ("", app.BRAK)


def main() -> int:
    zapis = "--zapisz" in sys.argv
    wszystkie = "--wszystkie" in sys.argv
    firmy = baza.firmy()
    zadanie = _zadanie()

    print(f"Firm w bazie: {len(firmy)}")
    print(f"Tryb: {'ZAPIS DO BAZY' if zapis else 'podgląd (dodaj --zapisz)'}")
    print("=" * 74)

    zmienione = pominiete = bledy = bez_danych = 0
    for f in firmy:
        stara = (f.get("kategoria") or "").strip()

        # UWAGA NA POZORNIE AKTUALNE NAZWY. Cztery stare szufladki nazywają się
        # tak samo jak nowe kategorie („Strategia i doradztwo"), ale nadawał je
        # model, który wybierał z listy DZIESIĘCIU opcji. Przy dwudziestu dziewięciu
        # ta sama firma bywa czymś innym: „agencja kreatywna e-commerce" pod starą
        # listą nie miała gdzie trafić poza doradztwem, a dziś jest „Branding i PR".
        # Dlatego `--wszystkie` przepytuje też te rekordy.
        if stara in app.KATEGORIE_PARTNEROW and not wszystkie:
            pominiete += 1
            continue

        # Firma, o której research nic nie ustalił (scraper trafił na loader albo
        # zabezpieczenie) — nie ma z czego klasyfikować. Pytanie modelu dałoby tu
        # kategorię wziętą z nazwy domeny, czyli zmyśloną. „Bez kategorii" jest
        # uczciwsze i od razu widać, że firmę trzeba zbadać ponownie.
        if _brak_danych(f):
            print(f"  {(f.get('nazwa') or '?')[:28]:30} bez danych z researchu — zostawiam")
            bez_danych += 1
            continue

        nowa = None if wszystkie else app.STARE_KATEGORIE.get(stara, None)
        skad = "mapa nazw"
        powod = ""

        if nowa is None:
            # Stara nazwa nie ma jednoznacznego odpowiednika ALBO pole było puste
            # („nie do ustalenia"). W obu przypadkach pytamy model — z pustym polem
            # też warto, bo dane o firmie w bazie są, a kategorii nie było.
            try:
                w = claude.uruchom_sync(zadanie, _opis(f))
                nowa, powod, skad = w.final_output.kategoria, w.final_output.powod, "model"
            except Exception as e:
                print(f"  BŁĄD | {f.get('nazwa')}: {type(e).__name__}")
                bledy += 1
                continue

        if nowa not in app.KATEGORIE_PARTNEROW:
            # Model wymyślił nazwę spoza listy. Zostawiamy STARĄ wartość — wpisanie
            # nieistniejącej kategorii jest gorsze niż zostawienie przestarzałej,
            # bo firma znika z każdego filtru zamiast wisieć pod czytelnym chipem.
            print(f"  BŁĄD | {f.get('nazwa')}: model zwrócił {nowa!r} — poza listą")
            bledy += 1
            continue

        print(f"  {f.get('nazwa')[:28]:30} {stara or '(puste)':26} -> {nowa:32} [{skad}]")
        if powod:
            print(f"  {'':30} {powod[:100]}")
        if zapis:
            baza.zapisz_firme({**f, "kategoria": nowa}, f.get("tryb") or "partner")
        zmienione += 1

    print("=" * 74)
    print(f"Do zmiany: {zmienione} | już aktualne: {pominiete} | bez danych: {bez_danych} | błędy: {bledy}")
    if not zapis and zmienione:
        print("Nic nie zapisano. Uruchom z --zapisz, żeby przepisać bazę.")
    return 1 if bledy else 0


if __name__ == "__main__":
    raise SystemExit(main())

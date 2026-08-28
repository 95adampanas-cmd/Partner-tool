"""
Test filtra wyszukiwania — pokazuje, CO akceptujemy i CO odrzucamy (z powodem).

Uruchomienie (z folderu backend/):
    python test_filtr.py

Wynik ląduje w pliku raport_filtr.txt (czytelne polskie znaki).
Przydatne przy KPI z PRD: „szukaj podobnych" — trafność min. 60%.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from collections import Counter

import app

ZAPYTANIA = [
    "agencja kreatywna branding Polska",
    "agencja e-commerce PrestaShop Polska",
    "software house tworzenie stron WordPress Polska",
    "agencja social media Polska",
]


def powod_odrzucenia(url: str, tytul: str) -> str | None:
    """Dlaczego wynik nie przechodzi. None = przechodzi."""
    u = url.lower()
    domena = urlparse(u).netloc.replace("www.", "")
    if not domena:
        return "brak domeny"
    if any(d in domena for d in app.DOMENY_ODPADAJACE):
        return "katalog/portal/social"
    if domena.endswith(app.OBCE_TLD):
        return "obca domena"
    if u.split("?")[0].endswith(app.ROZSZERZENIA):
        return "plik (jpg/pdf)"
    if app.czy_konkurent_w_wyniku(tytul, url):
        return "agencja SEO"
    return None


def main():
    linie, licznik = [], Counter()
    wszystkie_ok = []

    for zapytanie in ZAPYTANIA:
        linie.append("=" * 78)
        linie.append(f"ZAPYTANIE: {zapytanie}")
        linie.append("=" * 78)

        wyniki = app.tavily_search(zapytanie, max_results=15)
        widziane = set()

        for r in wyniki:
            url, tytul = r.get("url", ""), (r.get("title") or "").strip()
            powod = powod_odrzucenia(url, tytul)

            if powod:
                licznik[f"ODRZUT: {powod}"] += 1
                linie.append(f"  [X] {powod:22} {tytul[:40]}")
                linie.append(f"      {url[:88]}")
                continue

            strona = app.normalizuj_url(url)
            domena = urlparse(strona).netloc
            if domena in widziane:
                licznik["ODRZUT: duplikat domeny"] += 1
                linie.append(f"  [X] {'duplikat domeny':22} {tytul[:40]}")
                continue
            widziane.add(domena)

            uciety = bool(urlparse(url).path.strip("/"))
            licznik["PRZECHODZI"] += 1
            if uciety:
                licznik["  (w tym ucięte do str. głównej)"] += 1
            linie.append(f"  [OK]{' UCIETY ->' if uciety else '          '} {tytul[:40]}")
            linie.append(f"      {url[:88]}")
            if uciety:
                linie.append(f"      => {strona}")
            wszystkie_ok.append(strona)

        linie.append("")

    # Kontrola żywotności na zaakceptowanych
    linie.append("=" * 78)
    linie.append("KONTROLA ŻYWOTNOŚCI (na zaakceptowanych stronach)")
    linie.append("=" * 78)
    with ThreadPoolExecutor(max_workers=12) as pool:
        stany = list(pool.map(app.sprawdz_zywotnosc, wszystkie_ok))
    for strona, stan in zip(wszystkie_ok, stany):
        licznik[f"ŻYWOTNOŚĆ: {stan}"] += 1
        if stan != "zywa":
            znacznik = "[X] MARTWA " if stan == "martwa" else "[?] NIEPEWNA"
            linie.append(f"  {znacznik} {strona}")

    linie.append("")
    linie.append("=" * 78)
    linie.append("PODSUMOWANIE")
    linie.append("=" * 78)
    for klucz, ile in licznik.most_common():
        linie.append(f"  {ile:4}  {klucz}")

    przeszlo = licznik["PRZECHODZI"]
    martwe = licznik["ŻYWOTNOŚĆ: martwa"]
    finalne = przeszlo - martwe
    linie.append("")
    linie.append(f"  FINALNIE NA LIŚCIE: {finalne} firm "
                 f"(przeszło filtr: {przeszlo}, odpadło jako martwe: {martwe})")

    with open("raport_filtr.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(linie))
    print("Raport zapisany: raport_filtr.txt")


if __name__ == "__main__":
    main()

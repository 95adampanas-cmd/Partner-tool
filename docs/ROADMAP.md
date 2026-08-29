# ROADMAP — Partner Tool

> Status: ⬜ do zrobienia · 🟡 w toku · ✅ zrobione
> Terminy z PRD: **Faza 1 → 30.09.2026** · Faza 2 → 10.10.2026 · walidacja → 15.10.2026

## Faza 0 — Setup ✅
- ✅ PRD v1.0 (`docs/PRD.md`) + recenzja z wyłapanymi lukami
- ✅ Struktura repo + dokumenty (PRD, ROADMAP, DECISIONS, DATA-MODEL, email-examples)
- ✅ `.env` z kluczami (OPENAI_API_KEY, TVLY_API_KEY)
- ✅ Domknięte luki: model danych, persona (= osoba decyzyjna), definicja konkurenta
- ⬜ **Repo na GitHub + push** ← jedyne, co zostało z Fazy 0

## Faza 1 — Rdzeń MVP (termin: 30.09.2026) 🟡

### F1 — Research firmy po URL ✅
- ✅ Scraper wielostronicowy z priorytetem grup (kontakt → o nas → realizacje → oferta)
- ✅ Ekstrakcja LLM → structured output (`Firma`), 20 pól
- ✅ Flaga konkurenta wg testu „czym firma nazywa samą siebie"
- ✅ Braki jako „nie do ustalenia" — zero halucynacji
- ✅ Dane spółki: nazwa prawna, NIP, adres, miasto
- ✅ Osoba decyzyjna: imię, stanowisko, bezpośredni kontakt
- ✅ Karta firmy w UI + źródło danych (które podstrony)

### F2 — Szukaj podobnych ✅
- ✅ Tavily + deterministyczny filtr (katalogi, rankingi, ogłoszenia, obce domeny, pliki)
- ✅ Kontrola żywotności stron (żywa / martwa / niepewna)
- ✅ Normalizacja głębokich linków do strony głównej (odzyskiwanie realnych firm)
- ✅ Sterowanie tagami — user wybiera usługi definiujące podobieństwo
- ✅ `test_filtr.py` — powtarzalny audyt jakości filtra

### F3 — Generowanie draftu maila ✅
- ✅ Baza wiedzy mailingu (`docs/email-examples.md`)
- ✅ 3 style równolegle (rzeczowy / partnerski / ekspercki), oparte na researchu
- ✅ Kopiowanie do schowka, ponowne generowanie

### F4 — Eksport CSV 🟡
- ✅ Zaznaczanie firm + podgląd tabeli przed pobraniem
- ✅ Download w przeglądarce (dysk Render jest efemeryczny)
- ⬜ **Nazwy kolumn zgodne z importem Pipedrive** — obecne to szkic, do potwierdzenia

### Ponad zakres MVP (zrobione wcześniej) ✅
- ✅ **Tryb B — szukanie po branży i mieście** (bez firmy wejściowej), 4 warianty zapytania
- ✅ Aplikacja webowa: sidebar, 5 sekcji, lista → szczegóły, ikony SVG, branding Last Agency

### Wdrożenie ⬜
- ⬜ Repo na GitHub
- ⬜ Render + zmienne środowiskowe (OPENAI_API_KEY, TVLY_API_KEY)
- ⬜ Walidacja na próbce z zespołem (KPI: trafność 60%, konkurent 80%)

## Faza 2 — Mikroaudyt SEO/GEO (termin: 10.10.2026) 🟡
- ✅ Klucz DataForSEO (płatne API)
- ✅ Labs: pozycje, ruch, konkurenci, frazy, podstrony (5 wywołań, ~$0.06)
- ✅ AI Search: prompty generowane przez nasz model → Perplexity sonar
- ✅ AI Overviews: llm_mentions + analiza luki (SERP, $0.002/fraza)
- ✅ Raport jako dokument + druk do PDF (`@media print`)
- ⬜ **Case study Last Agency** — `TRESC_STALA["case"]`, dziś `pokaz: False`
      (był tam Botland, usunięty — to nie jest klient Last Agency)

### ⬜ OTWARTE: zweryfikować liczbę fraz względem Senuto/Ahrefs
**Blokada:** brak dostępu do Senuto/Ahrefs po stronie Last Agency (stan: 29.08.2026).

**Problem.** Dla elektromaniacy.pl DataForSEO podaje **748 fraz łącznie / 42 w TOP3**,
a audyt ICEA (Senuto) — **655 fraz w samym TOP3**. Rząd wielkości różnicy.

**Co już wiadomo (zweryfikowane, nie domysł):**
- Szacunki **ruchu się zgadzają** — porównanie z Ahrefs na 9 domenach dało medianę
  odchylenia ok. 10% (beafoto −2%, gospy +2%, nocnylowca −7%, szpiegujemy +8%,
  dzikaknieja −11%, alfatronik −12%, elektromaniacy +16%, spy-center −22%, enexus −36%).
- Skoro ruch się zgadza, brakujące frazy nie generują ruchu → różnica siedzi w **długim ogonie**.
- Potwierdza to nasz rozkład pozycji: tylko 30 fraz na pozycjach 51–100, podczas gdy
  strona z 14 tys. ruchu powinna mieć ich setki. Wygląda na próg wolumenu w bazie.
- `dataforseo_labs/status` (darmowy) potwierdza, że dane są świeże — to nie nieaktualność.

**Czego NIE wiadomo:** czy proporcja jest stała między domenami. Mamy n=1.
Nie wolno tego uogólniać w rozmowie z partnerem.

**Jak zweryfikować, gdy będzie dostęp:** wziąć 2–3 domeny, zestawić liczbę fraz
i TOP3 z Senuto/Ahrefs i z naszego narzędzia. Jeśli proporcja stała → można podać
przelicznik. Jeśli nie → ta sekcja potrzebuje innego źródła danych.

**Obejście na teraz (wdrożone, commit b0ee953):** pod sekcją SEO jest podpis źródła
z datą aktualizacji bazy — konwencja z audytu ICEA („Dane z narzędzia Senuto").
Liczby zostają widoczne, ale opisane, więc SEO-wiec partnera czyta „inne narzędzie",
a nie „błędne dane".

## Faza 3+ — odłożone
Patrz PRD sekcja 6.

---

**Aktualnie pracujemy nad:** Faza 2 — mikroaudyt działa end-to-end i jest zweryfikowany
względem audytu ICEA. Do zrobienia: wdrożenie (GitHub + Render) i case study Last Agency.

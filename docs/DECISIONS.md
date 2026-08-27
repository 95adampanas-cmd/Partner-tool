# DECISIONS — log decyzji

> Ważne decyzje + uzasadnienie („czemu tak"). Format: data + decyzja + powód.

## 2026-08-27 — Scoring usunięty, narzędzie dostarcza dane
**Decyzja:** Narzędzie NIE ocenia wartości firmy. Wyciąga dane + oznacza konkurenta; ocenę robi user.
**Powód:** Ocena wartości to decyzja biznesowa Partnership Managera. Narzędzie ma być rzetelnym
źródłem danych, nie wyrocznią. (Wnioski z poprzedniego narzędzia: scoring był ciągle dostrajany
i tak wymagał weryfikacji człowieka.)

## 2026-08-27 — Definicja konkurenta: test „czym firma nazywa samą siebie"
**Decyzja:** Konkurent = firma, która **przedstawia się** jako agencja SEO/SEM/GEO/pozycjonowania
(czyli walczy o ten sam budżet klienta). Decyduje **pozycjonowanie marki** (nagłówek, „kim jesteśmy"),
a NIE to, czy słowo „SEO" pada gdziekolwiek na stronie.
Wzmianki poboczne, które **NIE** czynią konkurenta: „optymalizacja SEO" na liście kilkunastu usług,
SEO jako dodatek do wdrożenia, „Pozycjonowanie" w formularzu/menu, „strona zoptymalizowana pod SEO".
**Powód:** Pierwsza wersja promptu („główna, eksponowana oferta") **nie zadziałała** — test na Tebimie
dał fałszywie `konkurent=true`, bo model zobaczył „optymalizacja SEO" wśród usług. Po przejściu na test
„czym firma nazywa samą siebie" + przykład-kotwica: Tebim → `false`, lastagency.pl → `true` (poprawnie).
KPI zakłada 80% trafności, więc reguła musi być testowalna, nie ocenna.
**Uwaga:** scraping wielostronicowy **zwiększa** ryzyko fałszywych alarmów (więcej wzmianek SEO w tekście),
więc ta reguła jest tym ważniejsza.

## 2026-08-27 — Deterministyczne zadania jako zwykłe funkcje, nie tool calle
**Decyzja:** Filtrowanie, mapowanie pól, budowa CSV, blocklisty — zwykły kod Pythona.
LLM tylko tam, gdzie potrzebne jest rozumienie języka (ekstrakcja, generowanie zapytania, mail).
**Powód:** Zapisane w PRD jako zasada. Potwierdzone praktyką: w Partner-Finderze agent
z tool+filtr+structured output naraz był niestabilny (raz 0 firm, raz 10). Po rozdzieleniu —
LLM generuje zapytanie, kod filtruje — wyniki stały się powtarzalne. Dodatkowo tańsze.

---

## Do rozstrzygnięcia (otwarte)

### 1. Zakres scrapowania — homepage nie wystarczy ⚠️
Funkcja 1 wymaga: wielkość zespołu, case studies, liczba projektów, kontakt. Te dane **prawie
nigdy nie są na stronie głównej** — są w `/o-nas`, `/realizacje`, `/kontakt`.
Opcje: (a) scrape homepage + wykryte podstrony z menu, (b) stała lista typowych ścieżek,
(c) sitemap.xml. → decyzja przed startem F1.

### 2. Definicja „persony"
Osoba decyzyjna (imię + stanowisko) czy typ profilu klienta? → wpływa na prompt i na mail.

### 3. Kolumny Pipedrive
Jakie dokładnie pola przyjmuje import? Bez tego mapowanie w F4 to zgadywanie.

### 4. Model LLM + budżet
Który model do ekstrakcji? Przy ~500 zł/mies. i wielostronicowym scrapowaniu warto policzyć
koszt na 1 research × zakładany wolumen.

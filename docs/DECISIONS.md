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

## 2026-08-27 — „Szukaj podobnych": krótkie zapytanie + odsiewanie konkurentów
**Decyzja:** (1) Do generowania zapytania przekazujemy **max 5 usług**, wcześniej **deterministycznie
wycinając usługi konkurencyjne** (SEO, SEM, pozycjonowanie, Google/Meta Ads). (2) Zapytanie ma
**max 5-8 słów**, bez miasta, którego nie było w danych. (3) Wyniki, które w tytule nazywają się
agencją SEO/SEM, są **odsiewane** — z licznikiem `odsiani_konkurenci`. (4) Odsiewamy też artykuły,
poradniki, definicje, konferencje i agregatory (useme, rocketreach…).
**Powód:** Test na firmie brantt (agencja kreatywna) zwracał **same agencje SEO**. Przyczyna:
do zapytania szło wszystkie 25 usług firmy — w tym „SEO, Google Ads, Meta Ads" — więc sami
prosiliśmy wyszukiwarkę o konkurentów. Model dokładał też miasto z powietrza („Poznań").
Po zmianie: `agencja kreatywna branding design logo Polska` → 10 realnych agencji kreatywnych.
KPI zakłada trafność 60% — te filtry są warunkiem jej osiągnięcia.

## 2026-08-27 — Agencja SEM / Google Ads = partner komplementarny, NIE konkurent
**Decyzja:** Z listy „podobnych" odsiewamy **tylko jawne agencje SEO/pozycjonowania**
(„Agencja SEO", „pozycjonowanie stron"). Agencje SEM, Google Ads, marketingowe i 360 **zostają** —
nawet jeśli mają SEO wśród usług. Zasada ta sama co przy fladze konkurenta: liczy się **rdzeń oferty**.
**Powód:** Decyzja Adama na przykładzie orangejuice.pl — agencja od płatnych kampanii to dobry
partner (oni płatne, my organiczne). Pierwsza wersja filtra wykluczała każdy tytuł ze słowem
„SEO/SEM/PPC", co wycinało wartościowych partnerów. Jeśli firma jednak okaże się konkurentem,
wyjdzie to na karcie po researchu (flaga) — lepiej pokazać za dużo niż zgubić partnera.

## 2026-08-27 — Twardy filtr śmieci w wynikach wyszukiwania
**Decyzja:** Odrzucamy deterministycznie: katalogi firm (infoisinfo, biznesfinder, panoramafirm,
pkt.pl, aleo, zleca, Trustpilot…), portale i fora, strony przeglądowe (`/tag/`, `/tematy/`, `/karta/`,
`/kategoria/`), pliki (`.jpg`, `.pdf`…), obce domeny (`.es`, `.de`…) oraz **zestawienia typu
„50 agencji digital", „10 Najlepszych Agencji"** (regex: liczba + agencje/firmy).
**Powód:** Zgłoszenie Adama („czasem linki z dupy, na 2 jpg"). Test na zapytaniu „agencja
marketingowa Polska": przed filtrem 10 wyników, z czego 4 to katalogi i listicle; po filtrze
**8 realnych firm, same strony główne**.

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

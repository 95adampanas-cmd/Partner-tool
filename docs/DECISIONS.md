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

## 2026-08-28 — Głęboki link ucinamy do strony głównej (zamiast odrzucać firmę)
**Decyzja:** Wynik wyszukiwania **normalizujemy do strony głównej** domeny. Odrzucamy w całości
tylko domeny, które nie są firmami (katalogi, portale, social, media, obce TLD, pliki).
**Powód:** Audyt filtra (pytanie Adama „czy nie odrzucamy sporej ilości firm"). Okazało się, że
tak — Tavily często zwraca głęboki link (`/tag/`, `/baza-wiedzy/`, `/artykul/`) na domenie
**realnej firmy**, a my wyrzucaliśmy ją przez ścieżkę. Traciliśmy m.in. **Convertis (z listy seed)**,
Webtom, JustIdea, Cyrek Digital.
**Pomiar na 75 wynikach z 5 zapytań:** przed 55 przechodzi (73%) → po **63 (84%)**,
w tym **51 głębokich linków uciętych** do strony głównej. Odrzucane pozostałe 12 to faktycznie
katalogi (infoisinfo, biznesfinder, clutch, sortlist), profile (LinkedIn, Instagram, useme) i media.
**Skutek uboczny:** tytuł z artykułu nie opisuje firmy → w takim wypadku jako nazwę pokazujemy domenę.
**Znana strata (świadoma):** firmy widoczne wyłącznie jako wizytówka w katalogu (Southpeople,
Via Design, DeGie Design) — mamy tylko URL katalogu, nie ich stronę.

## 2026-08-28 — Strona niedostępna ≠ firma martwa
**Decyzja:** Kontrola żywotności ma trzy stany: `zywa`, `martwa`, `niepewna`. Odrzucamy **tylko
potwierdzone trupy** (parking domeny, „under construction", pusta strona). Blokada bota
(Cloudflare) lub timeout → firma **zostaje z adnotacją** „nie udało się zweryfikować".
**Powód:** Pierwsza wersja traktowała każdą nieosiągalną stronę jako martwą — wypadały firmy
za Cloudflare. To łamało zasadę z PRD (ryzyko „Blokada scrapera": *oznaczać jako niedostępną,
nie pomijać*). Dodatkowo regex na zestawienia („50 agencji") łapał firmy z cyfrą w nazwie
(„360agencja.pl", „Grupa 3 Agencja") — zakotwiczony na początku tytułu.

## 2026-08-28 — NIE odzyskujemy firm z wizytówek w katalogach
**Decyzja:** Wyniki będące wizytówką w katalogu (`infoisinfo.pl/karta/...`, `useme.com/roles/...`)
odrzucamy i **nie próbujemy** wyciągać z nich prawdziwej domeny firmy.
**Powód:** Decyzja Adama. Koszt (parsowanie HTML każdego katalogu z osobna, kruche i różne dla
każdego serwisu) nie równoważy zysku — w audycie to ~4 firmy na 60 wyników (~7%). Wracamy do tematu
tylko jeśli w praktyce okaże się, że brakuje leadów.

## 2026-08-28 — „Szukaj podobnych" sterowane tagami użytkownika
**Decyzja:** „Szukaj podobnych" to **osobna sekcja**, nie przycisk na karcie firmy. Flow:
wybierasz zbadaną firmę wzorcową → **zaznaczasz jej usługi**, które mają definiować podobieństwo →
LLM buduje zapytanie **wokół tych tagów**. Zapytanie nadal układa LLM (naturalna fraza), ale
tematem sterują wskazówki użytkownika.
**Powód:** Decyzja Adama — „to Ty decydujesz, co znaczy podobna". Wcześniej model sam wybierał,
które z 25 usług są istotne, i trafiał losowo. Teraz dla brantt: tagi `branding + strategia marki`
→ „agencja kreatywna branding strategia marki Polska"; tagi `strony www + WordPress + React`
→ „agencja kreatywna strony internetowe WordPress React Polska" — dwa różne, trafne zestawy firm.
**Wyjątek w promptcie:** zakaz słów SEO/SEM/marketing obowiązuje tylko, gdy model dodaje je OD SIEBIE.
Jeśli user świadomie zaznaczy np. „Google Ads", wybór jest uszanowany.

## 2026-08-28 — UI: aplikacja z sidebarem, sekcja Firmy jako lista → szczegóły
**Decyzja:** Zamiast landing page — układ aplikacji: sidebar z sekcjami (Research po URL,
Szukaj po branży, Szukaj podobnych, Firmy, Eksport). Sekcja „Firmy" to **lista** zbadanych firm;
klik otwiera pełną kartę.
**Powód:** Decyzja Adama (wzór: dashboard Tavily). Każda funkcja ma swoje miejsce zamiast wisieć
w jednym scrollu. Rozdzielenie: Research/Szukaj = ekrany wejścia, Firmy = workspace, Eksport = wyjście.

## 2026-08-28 — „Szukaj po branży": 4 warianty zapytania zamiast jednego
**Decyzja:** Tryb B nie wysyła jednego zapytania. LLM rozpisuje branżę (+ miasto) na **4 różne
frazy** — nazwa branży, synonim, konkretna usługa, inna usługa — które lecą **równolegle** do
Tavily. Wyniki są scalane, deduplikowane po domenie i dopiero potem filtrowane.
**Powód:** Uwaga Adama: „czy to jak zwykłe Google? to trzeba coś dodać". Miał rację — jedno
zapytanie zwracało TOP10 najlepiej wypozycjonowanych, a PRD mówi wprost, że problemem jest
**dotarcie do firm, które NIE są na topowych pozycjach**. Jedna fraza mijała się z celem produktu.
**Efekt (agencja brandingowa Kraków):** 12 firm zamiast 10, w tym **5 zupełnie nowych**
(total-design, happyrebels, connectthedots, ivento, studionoto) — mniejsze studia niewidoczne
na najbardziej oczywistą frazę.
**Koszt:** 4 zapytania Tavily zamiast 1 (przy limicie 1000/mies. to ~250 wyszukiwań miesięcznie)
+ 1 tanie wywołanie LLM (nano) na warianty. Dodane presety branż w UI (klik zamiast pisania).

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

## 2026-09-04 — Flaga konkurenta zastąpiona faktem „ma SEO w ofercie"

**Było:** model orzekał `konkurent: true/false` na podstawie testu „czym firma nazywa
samą siebie". W wyszukiwaniu taką firmę dodatkowo USUWANO z listy — czyli narzędzie
podejmowało decyzję zespołu, a odrzuconych nikt nie widział.

**Jest:** `ma_seo: bool` + `seo_zakres: str`. Fakt: czy firma sprzedaje SEO/SEM jako
usługę, jakie dokładnie i jak dużą część oferty stanowią. Nikt przez to nie wypada
z listy, a kolory flagi są neutralne — wcześniej czerwień przy „Konkurent" podpowiadała
„odpuść", zanim człowiek zdążył spojrzeć.

**Dlaczego:** decyzja Adama — ocenia zespół, nie narzędzie. Ta sama agencja bywa
konkurentem i najlepszym partnerem, zależnie od tego, po co do niej piszemy.
Sam `true/false` tego nie rozstrzyga: widoczni.com i Sellision mają oba `ma_seo = true`,
ale u pierwszych SEO to „jeden z głównych filarów", a u drugich „dodatek obok wdrożeń
e-commerce". Stary system pokazałby je jako czerwone i zielone.

**Zgodność z PRD:** PRD mówi „oznacza konkurenta", czyli TAG, nie filtr. Usuwanie firm
z wyników nigdy nie było wymagane — ta zmiana przybliża nas do PRD, nie oddala.

**Migracja:** `baza._przenies_konkurent_na_ma_seo()` przepisuje stare rekordy przy
starcie. Zachowawczo: `konkurent = true` znaczyło „SEO jest rdzeniem", więc firma SEO
na pewno ma. Ale `konkurent = false` NIE znaczyło „nie ma SEO" — tylko „to nie rdzeń".
Takich firm nie da się zaklasyfikować ze starych danych, więc `seo_zakres` mówi wprost,
że trzeba je zbadać ponownie, zamiast zmyślać odpowiedź.

## 2026-09-11 — Dane finansowe firm: odpuszczone

**Cel:** dołożyć do karty firmy przychód i zysk partnera.

**Wynik: nie ma darmowego źródła programowego.** Sprawdzone sześć ścieżek, wszystkie
empirycznie, nie z opisów:

| Źródło | Wynik |
|---|---|
| KRS API (`api-krs.ms.gov.pl`) | tylko *wzmianki*, że sprawozdanie złożono — zero liczb |
| RDF stary (`ekrs.ms.gov.pl/rdf`) | Incapsula, 1160 bajtów wyzwania zamiast treści |
| RDF nowy (`rdf-przegladarka.ms.gov.pl`) | Incapsula, to samo |
| Biała lista VAT (`wl-api.mf.gov.pl`) | działa i jest darmowa, ale finansów nie ma |
| `dane.gov.pl` | tylko sprawozdania funduszy publicznych, nie spółek |
| OpenAPI portalu PRS | host wewnętrzny ministerstwa, nieosiągalny z zewnątrz |

**Dlaczego jawne dane nie są dostępne maszynowo.** Sprawozdania leżą w RDF jako
załączniki: XML w trzech schematach (mikro, małe, pełne) plus stare skany PDF.
Wyciągnięcie z tego liczby „przychód" wymaga pobrania i sparsowania — i to jest
dokładnie produkt, który sprzedaje BizRaport. Płaci się im za parsowanie, nie za dane.

**Dlaczego nie scrapujemy.** Incapsula to postawione zabezpieczenie, nie niewygodny
interfejs — jej obejście to inna kategoria niż czytanie otwartej strony, a mówimy
o systemie Ministerstwa Sprawiedliwości. Ten sam argument, co przy LinkedIn w PRD
i przy Mapach Google we wrześniu.

**Dlaczego nie płacimy.** Nie ustaliliśmy, czy przychód partnera w ogóle zmienia
decyzję o kontakcie. Dopóki na to nie ma odpowiedzi, abonament kupuje kolumnę w CSV,
nie zmianę w procesie.

**Gdyby wrócić do tematu:** najpierw sprawdzić RĘCZNIE na pięciu firmach
(przeglądarka RDF jest bezpłatna i wpuszcza człowieka), czy liczba wpływa na decyzję.
Dopiero potem BizRaport — 100 zapytań testowych bez karty.

**Zostaje za darmo z KRS:** regularność składania sprawozdań, rok wpisu i kapitał
zakładowy. To nie przychód, ale mówi coś o kondycji i nic nie kosztuje.

---

## Czat do pogłębienia researchu tylko w granicach domeny firmy
*11.09.2026*

Research wyciąga 20 pól raz. Pytania spoza tej dwudziestki — „czy obsługują B2B",
„ile biorą za wdrożenie" — padają na karcie firmy i agent doczytuje je ze strony.

**Narzędzie `otworz_podstrone` sprawdza domenę przed pobraniem.** Bez tego `/api/czat`
jest otwartym proxy: wystarczy poprosić agenta o dowolny adres, żeby nasz serwer
pobrał go i zwrócił treść. Adres spoza domeny badanej firmy dostaje odmowę, a nie
cichy brak wyniku — agent ma widzieć, że odbił się od granicy.

**Pod odpowiedzią stoi lista faktycznie otwartych podstron.** Model, który niczego
nie znalazł, potrafi odpowiedzieć pewnym tonem. Pusta lista źródeł jest jedynym
widocznym sygnałem, że zmyślił. To ta sama zasada, co przy audycie: liczba bez
źródła jest nieweryfikowalna, więc bezużyteczna.

**Historia rozmowy nie idzie do bazy.** Czat jest notatnikiem roboczym — utrwalamy
to, co człowiek przeniesie do researchu, nie każdą próbę.

**Pułapka SDK, warta zapamiętania.** Wynik narzędzia przychodzi w `new_items` jako
**słownik**, nie obiekt. Pierwsza wersja czytała go przez `getattr(raw_item, "output")`
i zawsze dostawała pustkę. Objaw był zdradliwy: odpowiedzi wyglądały poprawnie,
brakowało tylko źródeł — czyli awarii nie widać było tam, gdzie się patrzy.
To kolejny przypadek tego samego wzorca co „fałszywe zera": brak danych, który
wygląda jak poprawna odpowiedź.

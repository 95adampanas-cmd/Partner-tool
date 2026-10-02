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
„czym firma nazywa samą siebie" + przykład-kotwica: Tebim → `false`, grupa-icea.pl → `true` (poprawnie).
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

---

## Przejście z GPT na Claude — z jednym wyjątkiem
*16.09.2026*

Cała praca językowa idzie na Claude: ekstrakcja, maile, czat, kategorie, warianty
zapytań, prompty do audytu. Podział modeli wg ryzyka, nie wg ceny — Sonnet tam, gdzie
wynik czyta człowiek albo trafia do maila do partnera; Haiku do klasyfikacji
i tagowania.

**`agent_pytajacy` zostaje na OpenAI i to nie jest niedokończona migracja.** On jako
jedyny nie *używa* modelu, tylko go **mierzy**: udaje asystenta, któremu klient zadaje
pytanie, a my sprawdzamy, czy padnie nazwa badanej firmy. Klienci partnera pytają
ChatGPT. Po przeniesieniu na Claude raport dalej pokazywałby tabelę i dalej wyglądał
poprawnie — tyle że mówiłby „nie widać Cię w Claude". Ten sam kształt, inne znaczenie.
Test `sprawdz_modele()` pilnuje tego, bo to jest zmiana, którą ktoś zrobi w dobrej
wierze, „dla spójności".

**Natywne SDK Anthropic zamiast warstwy zgodności.** Osiem z dziewięciu zadań to jeden
strzał prompt→wynik; tylko czat prowadzi pętlę z narzędziem. Przy takim rozkładzie
adapter (LiteLLM pod Agents SDK) kosztowałby dokładnie to, po co przyszliśmy: cache
promptu i Batch API są specyficzne dla Anthropic i przez adapter albo nie przechodzą,
albo przechodzą bez efektu.

**Output strukturalny przez wymuszony tool use.** Model musi wywołać narzędzie
o zadanym schemacie, więc nie ma jak zwrócić prozy zamiast danych. Wybrane zamiast
nowszych mechanizmów, bo działa na przypiętej wersji SDK i nie wymaga ruszania
`pydantic-core` (próba upgrade'u wywróciłaby środowisko).

**Pułapka cache, warta zapamiętania.** Anthropic cache'uje tylko prefiks dłuższy niż
próg modelu — Sonnet 1024 tokeny, Haiku 2048. Krótszy blok z `cache_control` przechodzi
**bez błędu i bez efektu**: kod wygląda, jakby cache działał, a rachunek mówi co innego.
Dlatego `_da_sie_cachowac()` sprawdza długość i włącza cache tylko realnie, a test
wypisuje stan każdego bloku. To ta sama klasa błędu co fałszywe zera — brak efektu ma
być widoczny.

**Profil ICEA jako osobny plik.** Wcześniej kontekst „kim jesteśmy" był rozsypany
po dwóch promptach, więc nie dało się go ani cache'ować (cache obejmuje prefiks — musi
być jednym blokiem), ani poprawić w jednym miejscu. Teraz `profil.py`. Stan na dziś:
sam profil ma ~930 tokenów, czyli **pod progiem**; sklejony z zasadami maila daje 1347
i cache działa. Case studies zostały puste — `[DO UZUPEŁNIENIA]` — i dopóki tam stoją,
prompt maila zawiera **jawny zakaz** powoływania się na jakiekolwiek wyniki. Wymyślona
liczba w pierwszym mailu do partnera to nie literówka, tylko wpadka wizerunkowa.

**Czego NIE zrobiliśmy: nie dopchaliśmy profilu watą, żeby przekroczyć próg.** To
kosztowałoby tokeny przy każdym wywołaniu, żeby zaoszczędzić na cache, i wsadzało
modelowi wypełniacz do kontekstu. Cache włączy się sam, gdy profil urośnie treścią.

### Uzupełnienie po pierwszym uruchomieniu na prawdziwym kluczu
*16.09.2026, tego samego dnia*

**Szacunek długości promptu mylił się o 40%.** Zakładaliśmy 2,7 znaku na token —
wartość z intuicji o angielskim. Pomiar `count_tokens` na pięciu naszych promptach dał
**1,83–1,93**: polski ma więcej tokenów na znak przez odmianę i ogonki. Skutek był
konkretny i cichy: profil ICEA wychodził na 931 tokenów przy prawdziwych 1300,
więc kod **wyłączyłby cache dla bloku, który próg spokojnie przekracza** — i nikt by
się nie dowiedział, bo objawem jest tylko wyższy rachunek. Stała poprawiona na 1,9,
szacunek trafia teraz w ±2%. Rozstrzyga i tak `stan_cache()` prawdziwym pomiarem.

**Cache przy zimnym starcie płaci trzy razy.** Trzy style maila lecą równolegle, więc
przy pustym cache wszystkie trzy startują, zanim którakolwiek zdąży zapisać: trzy
zapisy zamiast jednego zapisu i dwóch odczytów. Zmierzone. Przy ciepłym cache wszystkie
trzy czytają (0 zapisów, 3 × 1876 odczytu). **Zostawiamy równolegle**: sekwencyjnie to
44 s zamiast 26 s, a różnica w koszcie to ułamek centa raz na okno bezczynności.
Wariant „pierwszy osobno, potem dwa równolegle" też sprawdzony — działa, ale nie warto
komplikować kodu dla tej kwoty.

**Źródła w czacie bierzemy z odpowiedzi narzędzia, nie z żądania modelu.** Model prosi
o samą ścieżkę („/oferta"), a użytkownik ma zobaczyć klikalny adres. Kanoniczny URL zna
narzędzie, bo to ono skleja adres i sprawdza domenę. Przy okazji znacznik `[TREŚĆ …]`
robi za filtr: odmowa i nieudane pobranie go nie mają, więc na liście źródeł ląduje
wyłącznie to, co naprawdę zostało przeczytane.

---

## Jeden dostawca danych SEO — SE Ranking usunięty
*16.09.2026*

Dwóch dostawców to podwójny kod, podwójne fixtures i podwójne pytanie „skąd ta liczba".
Zostaje DataForSEO — szerszy (9 endpointów wobec 5) i to on był domyślny.

**Rozdzielenie okazało się czyste.** Każde wywołanie `seranking.*` siedziało wewnątrz
`if dostawca == "seranking"`; ścieżka DataForSEO nie dotykała tego modułu w żadnym
miejscu. Usunięcie to były wycinki gałęzi, nie przeplatanie kodu.

**Nie tracimy Google AI Mode.** Przy pierwszym sprawdzeniu wyglądało na to, że tracimy:
SE Ranking ma pięć silników wzmianek, DataForSEO cztery. Ale AI Mode jest u DataForSEO
dostępny osobnym endpointem (`serp/google/ai_mode/live/advanced`) i chodzi w sekcji
pytań klientów. Znika tylko z sekcji **wzmianek** — z dwóch miejsc zostaje jedno.

**Jak to sprawdziliśmy — i dlaczego pierwszy punkt odniesienia trzeba było wyrzucić.**
Przed usunięciem przejechaliśmy ścieżkę DataForSEO offline, na zapisanych odpowiedziach,
i porównaliśmy wynik po zmianie. Pierwsza próba szła na fixtures elektromaniacy.pl
i dała **same zera** — bo te pliki to zapisane BŁĘDY API (status 40201, puste konto),
leżące w katalogu jak zwykłe dane. Punkt odniesienia z samych zer przeszedłby po każdej
zmianie i nie mierzyłby niczego. Przepisany na tebim.pro (status 20000): ruch 1347,
TOP 3 = 5, ośmiu konkurentów, 5 wzmianek, trzy pytania z różnymi wynikami. Po usunięciu
— **suma kontrolna identyczna**. Harness odmawia teraz pracy na zapisanym błędzie.

**Wniosek na przyszłość: fixtures mogą być zapisanymi awariami.** `dfs.wywolaj` zapisuje
odpowiedź niezależnie od jej statusu, więc katalog `fixtures/` miesza prawdziwe dane
z błędami konta. Kto będzie z nich korzystał, ma sprawdzać `status_code == 20000`,
zanim cokolwiek z nich policzy.

**Co zostaje mimo jednego dostawcy:**
- pole `dostawca` w raporcie i w bazie — cztery zapisane audyty mają `"seranking"`
  i muszą dalej dać się otworzyć;
- pole `etykieta_czolo` — raport ma podpisywać liczbę nazwą metryki, a stare audyty
  niosą tu inną wartość.

**Cena tej decyzji.** Znika jedyna alternatywa, więc awaria albo puste saldo DataForSEO
zabiera **cały** raport SEO. Przeżyje tylko sekcja pytań klientów, bo chodzi na naszym
kluczu OpenAI — i to jest dziś jej najważniejsze uzasadnienie. Sprawdzone: przy pustym
saldzie audyt zwraca czytelny błąd `typ: api`, a nie raport z zer.

Test UI dorósł przy okazji o pięć przypadków: formularz audytu pojawia się dopiero po
wybraniu firmy, więc największy szablon w aplikacji nie był sprawdzany wcale — a ta
zmiana ruszyła w nim siedem miejsc.

---

## Menu usług wygrywa z landingiem ze stopki
*16.09.2026*

Tebim ma stronę `/pozycjonowanie` opisującą pełny proces SEO: audyt, analiza
konkurencji, link building, comiesięczne raporty, horyzont 2–3 miesięcy, estymacja
kosztów. Na tej podstawie ekstrakcja postawiła `ma_seo = true` — i **to była pomyłka**.

Rozstrzygnęło sprawdzenie, SKĄD ta strona jest linkowana: wyłącznie z
`div.footer-menu-container`. Menu USŁUGI ma dziesięć pozycji i wszystkie dotyczą
PrestaShopa; SEO nie ma tam wcale. Tytuł strony — „Pozycjonowanie **Kalisz** — SEO dla
stron www i sklepów" — dopowiada resztę: to landing pod lokalną frazę, utrzymywany dla
widoczności, nie pozycja w ofercie. Adam potwierdził od strony biznesowej: leady SEO
Tebim przekazuje ICEA w kanale referral.

**Reguła, która z tego wynika i siedzi teraz w prompcie ekstrakcji:** ofertą firmy jest
jej MENU USŁUG. Osobna strona pod frazę, nieobecna w menu, nie czyni usługi częścią
oferty — choćby opisywała pełny proces. Przy rozbieżności wygrywa menu, a `seo_zakres`
ma **nazwać rozbieżność wprost**, żeby człowiek zobaczył podstawę werdyktu, a nie sam
werdykt.

**Dlaczego to nie jest drobiazg.** Landing pod lokalną frazę to standardowa praktyka
SEO — każda agencja, która sama siebie pozycjonuje, takie strony ma. Bez tej reguły
narzędzie systematycznie zawyżałoby `ma_seo` u firm, które o SEO tylko piszą, a nie
sprzedają go. Czyli dokładnie odwrotnie, niż chce definicja zawężona we wrześniu.

**Jak to wykryliśmy:** nie testem, tylko konfrontacją z rzeczywistością — Adam zna tego
partnera i zaprzeczył werdyktowi, a screen z menu usług rozstrzygnął spór. Ta sama
lekcja, co przy fałszywych zerach: liczba była prawdziwa, znaczenie inne niż etykieta.

### Scraper wyrzucał menu usług razem z nawigacją
*16.09.2026, ciąg dalszy sprawy Tebimu*

Porównanie listy usług na karcie z menu USŁUGI na stronie pokazało dwie rozbieżności:
u nas było „Pozycjonowanie", którego w menu nie ma, a nazwy brzmiały ogólnie
(„Integracje E-commerce" zamiast „Integracje PrestaShop").

**Pierwsza diagnoza była błędna.** Uznałem, że model parafrazuje nazwy, i dopisałem do
promptu regułę „przepisuj dosłownie". Po niej nic się nie poprawiło — bo model *już*
przepisywał dosłownie. Sprawdzenie, co faktycznie dostaje na wejściu, wykazało coś
innego: **pozycji z menu nie było tam w ogóle.**

Przyczyna siedziała w `tekst_ze_strony`: `soup(["script", "style", "nav"])` usuwało
`<nav>`, a razem z nim menu usług. Komentarz w tej funkcji ostrzegał, żeby nie wycinać
`<footer>` (bo tam są dane firmowe) — o nawigacji nikt nie pomyślał. Model dostawał
więc tylko sekcję „Nasze Usługi" ze strony głównej, czyli **skróconą zajawkę**: sześć
pozycji o nazwach ogólnych zamiast dziesięciu konkretnych. Wyciągaliśmy gorszą
z dwóch dostępnych list i wychodziła z tego generyczna agencja zamiast wyspecjalizowanej.

**Naprawa:** menu ratujemy PRZED usunięciem `<nav>` i doklejamy osobnym, opisanym
blokiem `[MENU GŁÓWNE SERWISU]`. Osobnym, bo model ma wiedzieć, że to oferta, a nie
zdanie z treści strony. Nie zgadujemy przy tym, co jest usługą — odsiewamy tylko
pozycje, które nigdy nią nie są (kontakt, blog, kariera, wybór języka, telefon),
a resztę rozstrzyga model.

**Filtr trzeba było poprawić od razu po napisaniu.** Pierwsza wersja szukała PODCIĄGU
i słowo „sklep" — dodane, żeby odsiewać koszyk — wycięło „Sklep B2B PrestaShop"
i „Utrzymanie sklepu PrestaShop", czyli połowę oferty. Teraz porównujemy całą nazwę.

**Wynik:** 10 z 10 usług dokładnie jak w menu (było 1 z 6), bez „Pozycjonowania",
bez nazw generycznych.

**Lekcja:** zanim poprawisz prompt, sprawdź, co model dostaje na wejściu. Instrukcja
„czytaj z menu usług" była niewykonalna, bo menu nie było w danych — a wyglądała
sensownie i przeszłaby każdy przegląd kodu.

---

## Dwa ciche ścięcia wyników wyszukiwania
*16.09.2026*

Użytkownik dostawał 12 firm i nagłówek „ZNALEZIONE FIRMY (12)", który sugerował, że
tyle właśnie znaleziono. Naprawdę znajdowaliśmy znacznie więcej i wyrzucaliśmy resztę
w dwóch miejscach, jedno po drugim:

```
filtruj_firmy(..., limit=18)   →   zostaja[:12]
```

Przy Mapach wyglądało to tak: Google oddaje 40 firm (2 strony po 20), 7 odpada bez
strony WWW, zostaje 33 — ścinamy do 18, sprawdzamy żywotność (czyli **płacimy 18
żądań HTTP**), po czym zostawiamy 12. Dwadzieścia jeden firm, za które zapłaciliśmy
Google, szło do kosza bez śladu w interfejsie.

**Naprawa:** limit filtra podniesiony do 60 (tyle wynosi sufit Map), drugie ścięcie
usunięte. Liczniki liczymy teraz z całości — wcześniej „3 już masz" znaczyło „3 wśród
pierwszych dwunastu", czyli co innego, niż mówiła etykieta.

**Przy okazji: braliśmy z Map dwie trzecie tego, co się da.** W kodzie stało `stron=2`,
a sufit API to trzy strony. Zmierzone na trzech zapytaniach — Warszawa 60, Leszno 60,
Wielkopolska 60 — Google przestaje oddawać `nextPageToken` po 60 firmach niezależnie
od wielkości rynku. Jedno dodatkowe płatne zapytanie daje 50% więcej firm.

**Efekt na „agencja interaktywna / Leszno":**

| źródło | przed | po |
|---|---|---|
| Mapy | 12 | **43** |
| Wyszukiwarka | 12 | **31** |

Czas wzrósł z 10 do 13 sekund — tyle kosztuje sprawdzenie żywotności większej liczby
stron. Warte tego.

**Lekcja:** limit dopisany „na wszelki wypadek" przy jednej ścieżce zostaje na zawsze
i staje się niewidzialnym sufitem produktu. Ten kosztował nas 2/3 wyników z płatnego
API i nie zgłaszał się niczym — bo interfejs uczciwie pokazywał to, co dostał.

---

## Miasto idzie do Map jako OBSZAR, nie jako tekst zapytania
*22.09.2026*

Adam pokazał Mapy Google w przeglądarce dla „doradztwo e-commerce" w Poznaniu —
kilkanaście firm. Nasze narzędzie na to samo zapytanie zwracało **jedną**.

Sprawdzenie surowej odpowiedzi API wykazało, że to nie nasz filtr: Google oddał jedną
firmę. Przyczyna leżała w sposobie pytania. Doklejaliśmy miasto do treści zapytania
(`"doradztwo e-commerce poznań"`), a Places dopasowuje `textQuery` **dosłownie** —
szuka wizytówek, które mają Poznań w nazwie albo opisie. Zostawała jedna, która
przypadkiem ma „Agencja e-commerce Poznań" w nazwie.

Mapy w przeglądarce nigdy nie szukają „po tekście z miastem" — szukają w **wycinku
mapy**. Places ma na to osobny parametr i my go nie używaliśmy.

**Zmierzone na tej samej frazie:**

| jak pytamy | wynik |
|---|---|
| miasto w treści zapytania | **1** |
| obszar Poznania, `locationBias` | **22** |
| obszar Poznania, `locationRestriction` | 21 |
| obszar Wielkopolski | 22 |

Wybraliśmy **bias, nie restriction**: firma z Lubonia pod Poznaniem to nadal dobry
trop, a twarde odcięcie by ją wyrzuciło. Różnicą między 22 a 21 są właśnie obrzeża.

**Kluczowy szczegół: sam parametr nie wystarczy.** Zapytanie z miastem w tekście
ORAZ z `locationBias` dawało dalej 1 firmę — tekst wygrywa i zawęża wynik. Trzeba
było przestać doklejać miasto do frazy.

**Nazwy zostają nazwami.** Użytkownik dalej wpisuje „Poznań", „Leszno", „powiat
gnieźnieński", „Wielkopolska” — nikt nie podaje współrzędnych. Google sam zamienia
nazwę na prostokąt (`viewport`) i zna granice miast, powiatów i województw:
Leszno 8×7 km, Poznań 24×23 km, powiat gnieźnieński 41×57 km, Wielkopolska 283×225 km.
Rozpoznany obszar zapamiętujemy na czas życia procesu — granice się nie zmieniają,
a każde rozpoznanie to osobne płatne zapytanie.

**Dlaczego pokazujemy obszar w interfejsie.** Rozpoznanie bywa nietrafione:
„powiat leszczyński" Google rozumie jako „Powiat Leszno" i oddaje prostokąt 8×7 km,
czyli samo miasto. Bez pokazania, co zrozumiał, wyniki cicho zmieniają znaczenie.
Teraz pod listą stoi „Obszar: Województwo wielkopolskie · 283 × 225 km".

**Zerowy prostokąt to nie obszar.** Wpisane „Kostrzyca Dolna" (nazwa zmyślona) Google
„rozpoznał" jako „Kostrzyca" o wymiarach 0×0 km i zwrócił trzy przypadkowe firmy —
czyli wyglądało na działające. Prostokąt węższy niż 1 km odrzucamy i wracamy do starego
sposobu, mówiąc o tym użytkownikowi wprost.

**Efekt końcowy, przez całe API z filtrami:** Poznań 1 → **20** firm, Wielkopolska → **43**.

**Lekcja:** objaw był niewidoczny, bo wyniki przychodziły — tylko było ich absurdalnie
mało. Żaden test tego nie łapał, bo testowaliśmy na szerokiej frazie („agencja
interaktywna Leszno" dawała 60) i wszystko wyglądało dobrze. Im węższa fraza — a takie
są w presetach — tym mocniej to cięło.

---

## Google jako trzecie źródło — przez DataForSEO, nie Custom Search
*22.09.2026*

Tavily i Google widzą inny wycinek internetu. Zmierzone na „agencja digital advisory":
pierwsza dziewiątka z Tavily pokrywała się z pierwszą dziesiątką Google w **trzech
domenach**. Żadne nie jest lepsze — razem dają więcej kandydatów niż każde osobno.

**Zaczęliśmy od Google Custom Search API i był to błąd, którego dało się uniknąć.**
Wybrałem je, bo „mają 100 darmowych zapytań dziennie" — z pamięci, bez sprawdzenia,
czy to nadal prawda. Moduł powstał, przeszedł testy i był bezużyteczny: Google wygasza
przeszukiwanie otwartej sieci. Od 20.01.2026 nowe wyszukiwarki nie mogą go włączyć,
a całe API przestaje działać 01.01.2027. Gdy padło pytanie, czy da się to obejść,
sprawdzenie zajęło trzy minuty — i trzeba je było zrobić na początku, nie na końcu.

Następca, na który kieruje Google — Vertex AI Search, w międzyczasie przemianowany
na **Agent Search** — też nie robi otwartej sieci. Ich własna instrukcja migracji nosi
tytuł „Migrate from Custom Search **Site Restricted** JSON API" i opisuje produkt jako
„Google-quality, **site-restricted** search": podajesz listę domen, które mają być
przeszukiwane. To zamiennik dla wariantu, który i tak przeszukiwał tylko wskazane
witryny.

**Co zamiast: DataForSEO, które już mamy.** Ich `serp/google/organic/live/advanced`
zwraca prawdziwe wyniki Google z polską lokalizacją, ~$0,002 za frazę. Wołaliśmy je
od dawna w analizie luki GEO — trzeba było tylko opakować.

Moduł zwraca kształt zgodny z Tavily (`url`, `title`, `content`), więc wyniki idą tym
samym filtrem: jedno miejsce decyduje, co jest firmą, niezależnie od źródła.
Bierzemy wyłącznie pozycje `type == "organic"` — SERP zawiera też `people_also_ask`,
`video` i `popular_products`, a to nie są firmy, tylko elementy strony wyników.

**Miasto doklejamy DO FRAZY, inaczej niż w Mapach.** Tam było to błędem, bo Places
dopasowuje tekst dosłownie do wizytówki. Tutaj przeszukujemy treść stron, więc miasto
w zapytaniu działa tak, jak człowiek by tego oczekiwał.

**Jeden depozyt, dwie funkcje.** Ten sam rachunek obsługuje mikroaudyt i to źródło.
Dziś saldo jest ujemne, więc oba zwracają czytelny błąd `typ: api` — nie raport z zer
i nie pustą listę firm.

**Lekcja, droższa niż powinna:** przy integracji z cudzym API najpierw sprawdzasz, czy
ono nadal robi to, co pamiętasz, a dopiero potem piszesz kod. Wersja na Custom Search
działała poprawnie — i to było najgorsze, bo nic nie sygnalizowało, że jest ślepa.

---

## Audyt GEO bez DataForSEO — drugi silnik i powtórzenia
*23.09.2026*

Audyt stał dotąd na jednym dostawcy: puste saldo DataForSEO kładło cały raport poza
sekcją „pytania klientów", która jako jedyna chodziła na naszym kluczu OpenAI. Adam
poprosił o wariant, który działa wyłącznie na kluczach, które mamy.

**Claude jako drugi mierzony asystent.** Sprawdzone: nasz klucz Anthropic obsługuje
ich serwerowe narzędzie `web_search`, więc Claude odpowiada jak asystent z dostępem
do sieci — 36 źródeł i konkretne polskie agencje przy pierwszym teście. Nie idzie to
przez `claude.py`, bo tam `Zadanie` opisuje NASZE narzędzia, a tu potrzebne jest
narzędzie serwerowe dostawcy — inny kształt żądania.

**Nie chodzi o zasięg Claude (0,71% rynku), tylko o drugi niezależny pomiar.** Przy
jednym modelu nie da się odróżnić jego cechy od stanu rynku. Zmierzone na Tebimie,
to samo pytanie:

| | firma wymieniona | źródeł | konkurentów |
|---|---|---|---|
| ChatGPT | **tak** | 1 | 0 |
| Claude | **nie** | 9 | 7 |

Dwa modele, przeciwne odpowiedzi. Przy jednym silniku raport twierdziłby jedno albo
drugie z równym przekonaniem.

**Powtórzenia: każde pytanie zadawane do trzech razy.** Modele są niedeterministyczne
— ta sama fraza pytana ponownie daje inną odpowiedź i inny zestaw firm. Zmierzone na
trzech próbach tego samego pytania: **NIE, NIE, TAK**. Pojedynczy strzał był więc
rzutem monetą; trzy próby dają uczciwy wynik „1 z 3 — widoczność przypadkowa", i to
jest inny wniosek niż „3 z 3". Przy okazji lista źródeł urosła z 9 do 26, a lista
konkurentów z 7 do 18 — bo scalamy sumą: jeśli model wymienił konkurenta choć raz,
to znaczy, że go zna.

Powtórzenia działają **tylko na silnikach z własnym kluczem**. Przez DataForSEO każde
powtórzenie mnożyłoby rachunek u dostawcy, a tu płacimy wyłącznie za tokeny.

Do raportu trafia odpowiedź z próby, w której firma się POJAWIŁA — bo to ona jest
dowodem. Gdy nie pojawiła się nigdy, pierwsza jest równie dobra.

**Pełny audyt GEO bez DataForSEO, zmierzony:** 2 silniki × 2 pytania × 2 próby = 128 s
i $0,188. Do tego sekcje, które i tak były darmowe: techniczny audyt GEO (`geo.py`,
10 botów, robots.txt) i analiza cytowanych źródeł.

**Czego wciąż brakuje z listy Adama:** własne prompty wpisywane ręcznie (pytania od
handlowców), podpowiedzi Google jako źródło promptów, sprawdzenie czy klient figuruje
na cytowanych stronach rankingów, oraz AI Overviews — te ostatnie bez SerpApi zostają
robotą ręczną.

**Czego NIE zrobiliśmy i dlaczego:** Perplexity i Gemini wymagają kluczy, których nie
mamy. Zgodnie z poleceniem — bez nich, zamiast dokładać rachunki.


## Zmiana marki na ICEA — jedno źródło nazwy, nie dziesięć

**Data:** 25.09.2026

Narzędzie mówiło dwiema markami naraz: w kodzie, promptach i sidebarze było
Last Agency, a materiały wysyłane partnerom i klientom (`szablon_dokumentu.html`)
były podpisane ICEA. Materiał wychodzi od tej samej osoby co mail, więc partner
widział dwie nazwy w jednym wątku.

**Co się zmieniło.** Nazwa siedziała w siedmiu miejscach i każde z nich widzi
człowiek: profil agencji (`profil_icea.md`, dawniej `profil_last_agency.md`),
plik synergii, wzorce maili, instrukcja ekstrakcji researchu, tytuł strony
i stopka sidebara, stopki eksportu i okładki, arkusz stylów. Wszystkie idą teraz
pod ICEA, a `sprawdz_marke()` w testach patrzy na nie naraz — pojedynczo każde
wygląda na dopilnowane, a wystarczy jedno zapomniane, żeby wyszedł mail podpisany
nazwą, która już nie istnieje.

**Akcent dostał nazwę od roli, nie od barwy.** Zmienne CSS nazywały się `--orange`
i trzymały pomarańcz Last Agency. Po zmianie marki nazwa przestałaby być prawdą,
więc są to dziś `--akcent`, `--akcent-2`, `--akcent-dim` z niebieskim ICEA
(#5768ff). Ten sam błąd nie powtórzy się przy kolejnej zmianie.

**Znak firmowy zamiast napisu.** W sidebarze był tekst w `<div>` z krojem Georgia.
Jest wordmark SVG — dokładnie ten sam plik, który stoi w nagłówku materiałów
wysyłanych partnerom, w białej wersji na ciemne tło.

**Case study wróciło.** `TRESC_STALA["case"]` było wyłączone (`pokaz: False`), bo
Botland nie był klientem agencji, pod którą działało narzędzie, a powoływanie się
na cudzy projekt w raporcie dla partnera jest ryzykowne. Pod marką ICEA to projekt
własny — ten sam, który jest dowodem w dokumencie dla klienta. Liczby przepisane
z niego co do jednej, razem z zastrzeżeniem, że to jedna branża i jeden punkt wyjścia.

**Czego NIE zrobiliśmy.** Ciemny motyw narzędzia został. Dokument dla klienta jest
jasny, bo idzie do druku i do skrzynki; narzędzie pracuje po kilka godzin dziennie
na jednym ekranie i przerabianie go na jasny motyw to osobna decyzja, nie skutek
uboczny zmiany nazwy.

**Szkice maili w bazie** przepisał `migracja_marki.py` (35 rekordów, kopia bazy
przed zapisem). To szkice do wysłania, nie zapis tego, co wysłano — narzędzie
maili nie wysyła. Gdyby zostały po staremu, pierwszy skopiowany szkic wyszedłby
pod nieistniejącą marką.


## Nawigacja to miejsca, nie narzędzia

**Data:** 25.09.2026

Sześć z czternastu pozycji w menu zaczynało się od pytania „którą firmę?" —
Rozmowa, Maile, Mikroaudyt, Audyt GEO, Dokument i Szukaj podobnych. Każde
narzędzie miało własną listę tych samych firm i własny krok wyboru. Praca nad
jednym partnerem znaczyła sześć razy wybrać go od nowa.

**Co się zmieniło.** Firmę wybiera się RAZ, wchodząc w nią z listy. Narzędzia są
w zakładkach jej karty: Przegląd, Widoczność (oba audyty), Synergia, Maile,
Materiały. W menu zostały dwa rodzaje miejsc: PRACA (Partnerzy, Do zbadania,
Pozyskiwanie) i PRZEGLĄD (Maile, Audyty, Eksport). Z czternastu pozycji zostało
sześć, z jedenastu sekcji — sześć.

**Karta renderuje się od nowa przy każdym wejściu.** Wcześniej każda firma miała
własny `<div class="panel">` chowany przez `display:none` i wszystkie leżały
w DOM-ie naraz. Narzędzia piszą po stałych identyfikatorach (`rozmowa-box`,
`audytgeo-raport`), więc dwie karty naraz biłyby się o te same id. Jedna karta na
ekranie to jedna karta w drzewie.

**Narzędzia nie zostały przepisane.** Każde z nich pomijało krok wyboru, gdy jego
zmienna stanu była ustawiona — karta ustawia ją, wchodząc w zakładkę. Dzięki temu
przebudowa dotknęła powłoki, a nie ośmiu działających formularzy.

**Widoki zbiorcze zamiast kolejnego wyboru firmy.** „Maile" w menu to dziś
biblioteka wszystkich szkiców pogrupowanych po firmach, a „Audyty" to historia
pomiarów — bo tego z karty jednej firmy nie widać, a porównanie dwóch pomiarów
wymaga spojrzenia z góry.

**Motyw jasny, identyfikacja ICEA.** Treść na bieli, nawigacja na granacie
(#000623) — ten sam kontrast, co w materiałach wysyłanych partnerom. Nagłówki
sekcji i kart idą szeryfem (Instrument Serif), tym samym, którym pisane są tytuły
w dokumentach. Narzędzie i materiał wyglądają wreszcie jak jedna rzecz.

**Przegląd czyta się jak materiał, nie jak formularz.** Research zbiera kilkanaście
pól i wszystkie leżały w jednej siatce — zrzut z bazy. Teraz jest kolejność: kim
firma jest, trzy liczby, co robi, co zrobiła, a dopiero na końcu dane rejestrowe
i źródła. Listy dłuższe niż sześć pozycji zwijają się: zmierzone na Sellision, 20
usług i 13 realizacji to 33 ponumerowane wiersze, których nikt nie czyta.

**Szukanie na liście partnerów.** Przy 180 firmach chipy kategorii przestają
wystarczać. Filtruje przy pisaniu, po tym, co widać w wierszu: nazwa, adres,
branża, kategoria, miasto.

**Czego NIE zrobiliśmy.** Ścieżka Klientów została wyłączona jak była
(`POKAZUJ_KLIENTOW`), a listy nie dostały sortowania ani kolumn statusu — to
wymaga najpierw decyzji, co jest statusem partnera, a tej jeszcze nie ma.


## Audyty SEO/GEO mierzą klienta partnera, nie partnera

**Data:** 02.10.2026

Zakładka „Widoczność" w karcie partnera audytowała samego partnera (tebim.pro).
Model dostawał pytania o agencję PrestaShop, a raport szedł z nagłówkiem
„materiał przygotowany dla: Tebim" — wynik, którego nie wysyła się nikomu, bo
partner nie jest naszym klientem, tylko drogą do jego klientów.

**Co się zmieniło.** Zakładka nazywa się „Audyty SEO/GEO" i działa jak Materiały:
krok 01 to klient partnera (z portfolio z researchu albo wpisany ręcznie, adres
strony wymagany), krok 02 to pomiar — audyt GEO albo mikroaudyt. Oba mierzą stronę
KLIENTA, a raport z każdego z nich idzie do klienta od partnera: „otrzymujesz ten
materiał od firmy, z którą pracujesz: Tebim", wstęp o tym, co Tebim zbudował,
pełny pomiar z wykresami, case Botland, podział ról, kontakt.

**Decyzje Adama:** audyt samego partnera znika (tylko klienci); Materiały zostają
obok jako szybki dokument na 3 pytaniach (~$0,05), audyt to pełny pomiar (~$0,75);
mikroaudyt DataForSEO też jest per klient.

**Jak klient dostaje to, co partner ma z researchu.** Klient nie przechodzi
researchu — jest tylko nazwa i adres. `_przygotuj_klienta()` czyta jego stronę
główną (jedno żądanie HTTP) i pyta Haiku o kategorię w słowach, którymi szuka go
jego klient („sklep z tytoniem online"). Kategoria idzie do podpowiedzi Google —
sama nazwa „Trafika" dawała podpowiedzi o godzinach otwarcia kiosków.

**Pytania o kategorię klienta, nigdy o agencję** (`PYTANIA_KLIENTA`) — ta sama
zasada, którą Materiały mają od początku. Zmierzone na żywo dla Trafiki: cztery
pytania o tytoń, papierosy i kawę, ChatGPT wymienił zamiast niej Żabkę Jush,
delio, Allegro i Lisek.

**Dwa systemy, wspólne pola.** `RAPORT_GEO_SYSTEM` (nadawca ICEA) i
`RAPORT_KLIENTA_SYSTEM` (nadawca partner) różnią się tylko blokiem o odbiorcy;
lista pól raportu jest jedna. Wariant klienta nie może odziedziczyć „ZMIANA
ODBIORCY" — model pisałby wtedy do Trafiki, że nie ma żadnego partnera. Test
pilnuje obu.

**Sekcja Google w raporcie z mikroaudytu.** Mikroaudyt mierzy też zwykłe Google
(frazy, pozycje, ruch, konkurenci), a dokument tego nie pokazywał. Teraz ma
sekcję z tabelą fraz — pojawia się tylko, gdy są dane; audyt GEO jej nie ma,
zamiast pokazywać zera.

**Klient wspólny dla Materiałów i Audytów** — wybierasz Trafikę raz. Przy wejściu
w innego partnera klient się czyści. Audyt zapisuje się pod adresem klienta,
a widok „Audyty" czyta partnera z raportu (json_extract) i prowadzi do jego karty.


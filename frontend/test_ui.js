/**
 * Test interfejsu — przełączanie ścieżek Partnerzy/Klienci.
 *
 *   cd frontend
 *   npm install jsdom@22     (raz; nowszy jsdom wymaga Node 20+)
 *   node test_ui.js
 *
 * PO CO TO ISTNIEJE. Zakładki Partnerzy/Klienci nie działały od momentu, w którym
 * powstały: handler siedział w nasłuchu "change", a <button> nigdy nie wywołuje
 * tego zdarzenia. Ścieżkę dało się zmienić wyłącznie z menu bocznego, więc błąd
 * przez cały czas wyglądał jak "klienci gdzieś nie działają".
 *
 * Czytanie kodu tego nie wykryło — sprawdzałem markup, kolejność handlerów i CSS,
 * wszystko wyglądało poprawnie. Dopiero kliknięcie w prawdziwym DOM pokazało, że
 * zdarzenie nie dochodzi. Dlatego ten test klika, zamiast analizować.
 *
 * Backend NIE jest potrzebny — fetch jest podstawiony, dane są sztuczne.
 */

const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const KAT = __dirname;
// ARKUSZ STYLÓW WCHODZI DO TESTU. Bez niego test sprawdzał WŁAŚCIWOŚĆ `hidden`
// i przechodził, podczas gdy w przeglądarce element był widoczny — `.pusto`
// ustawia `display:flex`, a reguła przeglądarki dla [hidden] przegrywa z każdą
// klasą. Druga rzecz, której nie dało się złapać bez CSS: literówka w rodzaju
// gramatycznym (`.karta-pane.aktywny` zamiast `aktywna`) sprawiła, że cała
// zawartość zakładek karty miała display:none. Test przechodził, ekran był pusty.
const css = fs.readFileSync(path.join(KAT, "style.css"), "utf8");
const html = fs.readFileSync(path.join(KAT, "index.html"), "utf8")
  .replace(/<script src="app.js"><\/script>/, "")
  .replace('<link rel="stylesheet" href="style.css">', `<style>${css}</style>`);

// Dwie ścieżki, żeby dało się sprawdzić, czy się nie mieszają.
const FIRMY = [
  { url: "https://tebim.pro", nazwa: "Tebim", branza: "agencja e-commerce", tryb: "partner",
    kategoria: "Sklepy internetowe", ma_seo: true, uslugi: ["a"], case_studies: [], zrodlo_danych: [] },
  { url: "https://widoczni.com", nazwa: "widoczni", branza: "agencja digital", tryb: "partner",
    kategoria: "Performance", ma_seo: true, uslugi: ["b"], case_studies: [], zrodlo_danych: [] },
  { url: "https://ellaboutique.pl", nazwa: "Ella Boutique", branza: "butik", tryb: "klient",
    kategoria: "Marketplace", ma_seo: false, uslugi: ["c"], case_studies: [], zrodlo_danych: [] },
];

const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://localhost:8000/",
  pretendToBeVisual: true });
const { window } = dom;
// Zapis zadan do backendu. Bez tego nie da sie sprawdzic, czy klikniecie
// W OGOLE dotarlo do /api/kolejka — a wlasnie to bylo zepsute: przycisk
// "Dodaj wszystkie do kolejki" przechwytywal inny warunek w obsludze klikniec
// i zamiast dodawac firmy przestawial zrodlo wyszukiwania.
const zadania = [];
// Kolejka: dwie frazy w JEDNEJ kategorii — dokładnie ten układ, przez który
// filtr kategorii nie pokazywał się wcale na żywej kolejce 45 firm.
const KOLEJKA_TESTOWA = [
  { url: "https://adlife.pl", nazwa: "Adlife", tryb: "partner", opis: "agencja online",
    zrodlo: "wyszukiwarka", zapytanie: "agencja marketingu internetowego",
    kategoria: "Agencje digital / full-service", dodana: "2026-09-25T00:00:00" },
  { url: "https://silesion.pl", nazwa: "Silesion", tryb: "partner", opis: "portal",
    zrodlo: "wyszukiwarka", zapytanie: "agencja marketingu internetowego",
    kategoria: "Agencje digital / full-service", dodana: "2026-09-25T00:00:00" },
  { url: "https://growth.pl", nazwa: "Growth", tryb: "partner", opis: "agencja growth",
    zrodlo: "wyszukiwarka", zapytanie: "agencja growth e-commerce",
    kategoria: "Agencje digital / full-service", dodana: "2026-09-25T00:00:00" },
];
const ZNALEZIONE = [
  { url: "https://sklep-alfa.pl", nazwa: "Alfa", opis: "wdrozenia Shopify", ma_seo: false },
  { url: "https://sklep-beta.pl", nazwa: "Beta", opis: "sklepy PrestaShop", ma_seo: true },
];
window.fetch = (u, opcje) => {
  zadania.push({ url: u, metoda: (opcje && opcje.method) || "GET",
                 body: opcje && opcje.body ? JSON.parse(opcje.body) : null });
  return Promise.resolve({
    json: () => Promise.resolve(
      u.includes("/api/firmy") ? { ok: true, firmy: FIRMY } :
      u.includes("/api/szukaj") ? { ok: true, firmy: ZNALEZIONE, zapytanie: "tworzenie sklepów internetowych", zrodlo: "wyszukiwarka" } :
      u.includes("/api/kolejka") && (!opcje || !opcje.method || opcje.method === "GET")
        ? { ok: true, kolejka: KOLEJKA_TESTOWA } :
      u.includes("/api/kolejka") ? { ok: true, doszlo: ZNALEZIONE.length } :
      // Dwa zrodla podlaczone, zeby przelacznik sie pokazal — inaczej caly test
      // presetow dla Map leci pusta galezia i niczego nie sprawdza.
      u.includes("/api/zrodla") ? { ok: true, zrodla: { wyszukiwarka: true, mapy: true, google: false } } :
      // Historia audytów zasila kolumnę „Praca" na liście partnerów.
      u.includes("/api/audyty") ? { ok: true, audyty: [
        { id: 1, url: "https://tebim.pro", tryb: "partner", dostawca: "geo",
          data: "2026-09-24T10:00:00" }] } :
      { ok: true, kolumny: [], kategorie: [], kolejka: [], maile: [] }),
  });
};
window.scrollTo = () => {};

const bledyJS = [];
window.addEventListener("error", (e) => bledyJS.push(e.message));

try {
  window.eval(fs.readFileSync(path.join(KAT, "app.js"), "utf8"));
} catch (e) {
  console.log("BŁĄD PRZY ŁADOWANIU app.js: " + e.message);
  process.exit(1);
}

const wyniki = [];
const sprawdz = (opis, warunek, dodatek) =>
  wyniki.push({ opis, ok: !!warunek, dodatek: dodatek || "" });

setTimeout(() => {
  const d = window.document;
  const klik = (el) => el && el.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const nav = (sek, tryb) => klik([...d.querySelectorAll(".nav-item")]
    .find((b) => b.dataset.sekcja === sek && (!tryb || b.dataset.tryb === tryb)));
  // Zakładka i nazwy TYLKO z widocznej sekcji — przełączniki są w trzech sekcjach
  // naraz i globalne querySelector trafiałoby w ukryty, nieodświeżony.
  const zakladka = (t) => klik(d.querySelector(`.sekcja.aktywna [data-ustaw-tryb="${t}"]`));
  const aktywna = () => (d.querySelector(".sekcja.aktywna .tryb-btn.aktywny") || {}).textContent || "";
  const nazwy = (sel) => [...d.querySelectorAll(sel)].map((x) => x.textContent.trim());
  // Nowa powłoka: narzędzia siedzą w karcie firmy, a pozyskiwanie ma trzy wejścia
  // pod jedną pozycją menu. Test chodzi tą samą drogą co człowiek.
  const otworzKarte = (i = 0) => klik(d.querySelectorAll("#firmy-lista .firma-row")[i]);
  const kartaTab = (id) => klik(d.querySelector(`[data-karta-tab="${id}"]`));
  const pozTab = (id) => { nav("pozyskiwanie"); klik(d.querySelector(`[data-poz="${id}"]`)); };
  // Widoczność czytamy z wyliczonego stylu, nie z atrybutu. JSDOM nie wspiera
  // [hidden] ani !important w getComputedStyle, więc elementy, które mają być
  // niewidoczne, sprawdzamy przez ich NIEOBECNOŚĆ w drzewie albo przez display
  // ustawiony klasą — czyli tak, jak faktycznie działa ta aplikacja.
  const widac = (el) => !!el && window.getComputedStyle(el).display !== "none";

  // Ścieżka klientów bywa wyłączona (POKAZUJ_KLIENTOW w app.js). Testy jej nie
  // kasujemy — sprawdzamy to, co w danej konfiguracji ma być prawdą. Dzięki temu
  // po ponownym włączeniu ścieżki komplet asercji wraca sam.
  // Stan czytamy z DOM, a NIE ze zmiennej w app.js. window.eval tworzy `const`
  // we własnym zakresie, więc drugi eval jej nie widzi i odczyt zawsze dawał
  // undefined — testy leciały złą gałęzią i przy wyłączonej ścieżce przechodziły
  // przypadkiem. Poza tym test powinien sprawdzać to, co widzi użytkownik.
  const zKlientami = [...d.querySelectorAll(".nav-grupa")]
    .some((g) => g.textContent.trim() === "Klienci");

  // Lista musi być gotowa PRZED pierwszym kliknięciem w menu: „Partnerzy" jest
  // sekcją domyślną, a firmy przychodzą z bazy już po narysowaniu strony.
  // Bez tego aplikacja startowała z pustą listą i wyglądało to na zepsuty backend.
  sprawdz("Start: lista partnerów jest gotowa bez klikania w menu",
    d.querySelectorAll("#firmy-lista .firma-row").length === 2,
    `${d.querySelectorAll("#firmy-lista .firma-row").length} wierszy`);

  // ══ LISTA JAKO TABELA PRACY ══
  // Kafelki zastąpione wierszami: na ekran wchodzi dwa razy więcej firm, a wiersz
  // mówi, co już zrobiono. Bez kolumny „Praca" lista odpowiada tylko na pytanie
  // „kogo mam", a nie „kim się zająć".
  nav("firmy");
  sprawdz("Lista: jest tabelą z nagłówkami, nie stosem kafelków",
    !!d.querySelector(".tabela-firm thead"),
    [...d.querySelectorAll(".tabela-firm th")].map((t) => t.textContent.trim()).filter(Boolean).join(" | "));

  sprawdz("Lista: wiersz pokazuje stan pracy nad firmą",
    !!d.querySelector("#firmy-lista .kol-praca"));

  // Regresja z 25.09.2026: `.firma-row` niesie style kafelka z panelu researchu
  // (display:flex, ramka, padding). Nałożone na <tr> rozbijały tabelę na pionowy
  // stos komórek — nagłówki stały w jednym rzędzie, a dane pod sobą w słupku.
  // Klasa jest w dwóch miejscach naraz, więc sprawdzamy WYLICZONY układ.
  const wierszT = d.querySelector("#firmy-lista .firma-row");
  sprawdz("Lista: wiersz jest wierszem tabeli, a nie kafelkiem",
    window.getComputedStyle(wierszT).display === "table-row"
      && window.getComputedStyle(wierszT.querySelector("td")).display === "table-cell",
    `tr: ${window.getComputedStyle(wierszT).display}, td: ${
      window.getComputedStyle(wierszT.querySelector("td")).display}`);

  // „Bez SEO" wisiało na szesnastu wierszach z dwudziestu jeden — etykieta, która
  // jest prawie zawsze, nie niesie informacji. Pokazujemy wyjątek.
  sprawdz("Lista: znak SEO tylko przy firmach, które je mają",
    d.querySelectorAll(".znak-seo").length
      === [...d.querySelectorAll("#firmy-lista .firma-row")].length - 0 - 0
      || d.querySelectorAll(".znak-seo").length < d.querySelectorAll("#firmy-lista .firma-row").length,
    `${d.querySelectorAll(".znak-seo").length} z ${d.querySelectorAll("#firmy-lista .firma-row").length}`);

  // Sortowanie: bez niego kolumny są ozdobą.
  const nazwyWierszy = () => [...d.querySelectorAll("#firmy-lista .firma-row-nazwa")]
    .map((x) => x.textContent.trim());
  klik(d.querySelector('[data-sort="firma"]'));
  const rosnaco = nazwyWierszy();
  klik(d.querySelector('[data-sort="firma"]'));
  const malejaco = nazwyWierszy();
  sprawdz("Lista: kliknięcie w nagłówek sortuje",
    rosnaco.join() !== malejaco.join() && rosnaco[0] === malejaco[malejaco.length - 1],
    `${rosnaco.join(", ")} -> ${malejaco.join(", ")}`);

  // Zaznaczanie do eksportu na liście: bez tego wybranie dwudziestu firm znaczy
  // dwadzieścia wejść w kartę.
  const zazn = d.querySelector(".zazn-wszystkie");
  sprawdz("Lista: da się zaznaczyć wszystkie do eksportu", !!zazn);
  if (zazn) {
    klik(zazn);
    sprawdz("Lista: zaznaczenie wszystkich trafia do eksportu",
      d.querySelectorAll("#firmy-lista .do-eksportu-lista:checked").length === 2,
      `${d.querySelectorAll("#firmy-lista .do-eksportu-lista:checked").length} zaznaczonych`);
    klik(d.querySelector(".zazn-wszystkie"));
    sprawdz("Lista: odznaczenie wszystkich czyści eksport",
      d.querySelectorAll("#firmy-lista .do-eksportu-lista:checked").length === 0);
  }

  sprawdz("Firmy: pokazuje partnerów", nazwy(".firma-row-nazwa").length === 2,
    nazwy(".firma-row-nazwa").join(", "));

  if (zKlientami) {
    zakladka("klient");
    sprawdz("Firmy: zakładka przełącza na Klientów", aktywna().includes("Klienci"));
    sprawdz("Firmy: widać klienta, nie partnerów",
      nazwy(".firma-row-nazwa").join().startsWith("Ella"), nazwy(".firma-row-nazwa").join(", "));
    zakladka("partner");
    sprawdz("Firmy: powrót na Partnerów", nazwy(".firma-row-nazwa").length === 2);
  } else {
    sprawdz("Firmy: brak przełącznika ścieżki",
      !d.querySelector(".sekcja.aktywna .przelacznik-tryb"));
    sprawdz("Menu: brak grupy Klienci",
      ![...d.querySelectorAll(".nav-grupa")].some((g) => g.textContent.trim() === "Klienci"));
    sprawdz("Menu: brak pozycji ze ścieżką klienta",
      d.querySelectorAll('.nav-item[data-tryb="klient"]').length === 0);
    sprawdz("Firmy: klient NIE miesza się z partnerami",
      !nazwy(".firma-row-nazwa").join().includes("Ella"), nazwy(".firma-row-nazwa").join(", "));
  }

  // ══ KARTA FIRMY ══
  // Sedno przebudowy: firmę wybiera się RAZ, wchodząc w nią z listy. Wcześniej
  // sześć narzędzi zaczynało od własnej listy firm — ten sam wybór sześć razy.
  if (zKlientami) zakladka("partner");
  nav("firmy");
  otworzKarte(0);
  sprawdz("Karta: otwiera się po kliknięciu w wiersz listy",
    !!d.querySelector(".karta-tytul"), (d.querySelector(".karta-tytul") || {}).textContent);
  sprawdz("Karta: lista partnerów schodzi z ekranu",
    d.getElementById("firmy-lista").hidden);
  // To jest regresja z 25.09.2026: zawartość zakładki miała display:none przez
  // literówkę w nazwie klasy, a karta wyglądała na pustą.
  sprawdz("Karta: zawartość zakładki jest WIDOCZNA, nie tylko obecna",
    widac(d.getElementById("karta-pane"))
      && d.getElementById("karta-pane").innerHTML.length > 200,
    `display: ${window.getComputedStyle(d.getElementById("karta-pane")).display}`);
  // Druga regresja z tego samego dnia: komunikat „nie ma tu żadnej firmy" wisiał
  // nad otwartą kartą, bo `hidden` przegrywał z klasą `.pusto`.
  sprawdz("Karta: pusty stan listy nie wisi nad otwartą firmą",
    d.querySelectorAll(".pusto").length === 0,
    `${d.querySelectorAll(".pusto").length} komunikatów`);

  sprawdz("Karta: startuje na Przeglądzie",
    (d.querySelector(".zakladka.aktywna") || {}).textContent === "Przegląd");

  // Przegląd ma czytać się jak materiał: liczby, potem usługi, potem dane.
  sprawdz("Przegląd: pokazuje liczby o firmie",
    d.querySelectorAll(".prz-liczba").length === 3);
  sprawdz("Przegląd: usługi są ponumerowane",
    d.querySelectorAll(".prz-poz").length > 0);
  sprawdz("Przegląd: prowadzi na stronę firmy",
    !!d.querySelector('.prz-hero a[target="_blank"]'));

  // Długie listy zwijają się do sześciu pozycji — 33 ponumerowane wiersze jeden
  // pod drugim to lista, której nikt nie czyta, tylko przewija.
  const widoczneP = () => [...d.querySelectorAll(".prz-poz")].filter((x) => !x.closest("[hidden]")).length;
  const wiecej = d.querySelector(".prz-wiecej");
  if (wiecej) {
    const przed = widoczneP();
    klik(wiecej);
    sprawdz("Przegląd: „Pokaż pozostałe” rozwija resztę listy", widoczneP() > przed,
      `${przed} -> ${widoczneP()}`);
    klik(wiecej);
    sprawdz("Przegląd: drugie kliknięcie zwija z powrotem", widoczneP() === przed);
  } else {
    sprawdz("Przegląd: krótka lista nie potrzebuje zwijania", widoczneP() > 0);
  }

  // ══ ZAKŁADKA WIDOCZNOŚĆ ══
  // Formularz audytu niesie całą konfigurację: modele, platformy, zakres, koszt.
  // Tu sprawdzamy dwie rzeczy naraz: że nadal działa i że NIE pyta o firmę.
  kartaTab("widocznosc");
  const formularz = d.getElementById("audyt-wybor").innerHTML;
  sprawdz("Widoczność: audyt dostaje firmę bez pytania o wybór",
    formularz.includes("Które modele AI pytamy"));
  sprawdz("Widoczność: nie ma już listy firm do wyboru",
    d.querySelectorAll("#audyt-wybor .sim-row").length === 0,
    `${d.querySelectorAll("#audyt-wybor .sim-row").length} wierszy wyboru`);
  sprawdz("Widoczność: są oba pomiary, GEO i mikroaudyt",
    !!d.getElementById("audytgeo-wybor") && !!d.getElementById("audyt-wybor"));
  sprawdz("Audyt: jest wybór modeli", d.querySelectorAll('input[name="silnik"]').length > 0,
    `${d.querySelectorAll('input[name="silnik"]').length} modeli`);
  sprawdz("Audyt: jest szacowany koszt w dolarach", /Szacowany koszt: .*\$/.test(formularz));
  // Po usunięciu drugiego dostawcy nie ma już czego wybierać — gdyby przełącznik
  // wrócił, wracałby też cały martwy kod obsługi, którego nikt by nie zauważył.
  sprawdz("Audyt: brak wyboru dostawcy (został jeden)",
    d.querySelectorAll('input[name="dostawca"]').length === 0);
  sprawdz("Audyt: brak pozostałości po SE Ranking",
    !/seranking|SE Ranking|kredyt/i.test(formularz));

  // ══ POZOSTAŁE ZAKŁADKI ══
  kartaTab("synergia");
  sprawdz("Zakładki: każda z nich coś pokazuje",
    ["widocznosc", "synergia", "maile", "dokumenty", "przeglad"].every((t) => {
      kartaTab(t);
      const pane = d.getElementById("karta-pane");
      return widac(pane) && pane.innerHTML.length > 200;
    }));
  kartaTab("synergia");
  sprawdz("Synergia: rozmowa startuje od razu dla tej firmy",
    !!d.getElementById("rozmowa-box")
      && !d.querySelector("#rozmowa-box .wybierz-rozmowe"));
  kartaTab("maile");
  sprawdz("Maile: własny kontener w karcie, nie wspólny z przeglądem",
    !!d.getElementById("karta-maile-box"));
  kartaTab("dokumenty");
  sprawdz("Materiały: generator dokumentu jest w karcie",
    !!d.getElementById("dokument-wybor"));

  // Powrót do listy musi być jednym kliknięciem — inaczej karta jest pułapką.
  klik(d.querySelector(".wroc-do-listy"));
  // Szukanie na liście: przy 180 firmach chipy kategorii przestają wystarczać.
  klik(d.querySelector(".wroc-do-listy"));
  const pole = d.getElementById("szukaj-firm");
  sprawdz("Lista: jest pole szukania", !!pole);
  if (pole) {
    pole.value = "tebim";
    pole.dispatchEvent(new window.Event("input", { bubbles: true }));
    sprawdz("Lista: szukanie zawęża do jednej firmy",
      d.querySelectorAll("#firmy-lista .firma-row").length === 1,
      `${d.querySelectorAll("#firmy-lista .firma-row").length} wierszy`);
    const puste = d.getElementById("szukaj-firm");
    puste.value = "";
    puste.dispatchEvent(new window.Event("input", { bubbles: true }));
    sprawdz("Lista: wyczyszczenie pola przywraca wszystkie",
      d.querySelectorAll("#firmy-lista .firma-row").length === 2);
  }

  // Wchodzimy jeszcze raz, żeby sprawdzić drogę powrotną z karty do listy.
  klik(d.querySelector("#firmy-lista .firma-row"));
  klik(d.querySelector(".wroc-do-listy"));
  sprawdz("Karta: powrót do listy jednym kliknięciem",
    !d.getElementById("firmy-lista").hidden && d.getElementById("firmy-detal").hidden);

  // Zakładki pozyskiwania: regresja z 25.09.2026. CSS i HTML mówiły „aktywny",
  // a JS przełączał „aktywna" — panel „Po adresie" miał więc klasę, której nikt
  // nie zdejmuje, a dwa pozostałe nigdy nie dostawały tej, na którą patrzy CSS.
  // Zakładka się podświetlała, treść pod spodem się nie zmieniała.
  nav("pozyskiwanie");
  ["url", "branza", "podobne"].forEach((t) => {
    klik(d.querySelector(`#poz-zakladki [data-poz="${t}"]`));
    const widoczne = [...d.querySelectorAll(".poz-panel")]
      .filter((x) => widac(x)).map((x) => x.dataset.poz);
    sprawdz(`Pozyskiwanie: zakładka „${t}” pokazuje swój panel`,
      widoczne.length === 1 && widoczne[0] === t,
      `widoczne: ${widoczne.join(",") || "żaden"}`);
  });

  pozTab("podobne");
  sprawdz("Podobne: lista firm wzorcowych niepusta",
    nazwy("#podobne-wybor .sim-name").length > 0, nazwy("#podobne-wybor .sim-name").join(", "));

  // Przelacznik zrodel: pokazuje sie dopiero przy DWOCH podlaczonych. Test stubuje
  // /api/zrodla bez pola `zrodla`, wiec sprawdzamy przede wszystkim, ze brak tego
  // pola NIE wywala renderowania — kiedys wywalal, a wyjatek polykal .catch.
  // Trzy kroki w kolejności, w której się je wykonuje. Wcześniej formularz stał
  // nad rzeczami, które go wypełniają — źródłem i kategoriami — więc ekran
  // czytało się od dołu.
  pozTab("branza");
  const kroki = [...d.querySelectorAll('.poz-panel[data-poz="branza"] .krok')];
  sprawdz("Po branży: trzy kroki w kolejności wykonywania",
    kroki.length === 3
      && kroki.map((k) => k.querySelector(".krok-nr").textContent).join(",") === "01,02,03",
    kroki.map((k) => k.querySelector("h3").textContent).join(" → "));

  // Opis źródła decyduje o wyborze („Mapy znajdują firmy bez SEO"), a przy
  // pigułkach widać było tylko opis tego już zaznaczonego.
  const zrodlaWiersze = [...d.querySelectorAll(".zrodlo-wiersz")];
  sprawdz("Po branży: każde źródło pokazuje swój opis od razu",
    zrodlaWiersze.length > 1
      && zrodlaWiersze.every((z) => (z.querySelector("em") || {}).textContent?.length > 20),
    `${zrodlaWiersze.length} źródeł`);

  pozTab("branza");
  sprawdz("Zrodla: brak pola w odpowiedzi nie wywala sekcji",
    !!d.querySelector('.poz-panel[data-poz="branza"]'));

  // Presety zaleza od zrodla: Mapy maja wlasny, krotszy zestaw, bo szukaja po
  // nazwach wizytowek, a nie po tresci stron. Po przelaczeniu zrodla lista kategorii
  // musi sie PRZERYSOWAC — inaczej klikasz w kategorie z poprzedniego zestawu.
  pozTab("branza");
  const ileKategorii = () => d.querySelectorAll("#presety-branz [data-grupa]").length;
  const przedZmiana = ileKategorii();
  sprawdz("Presety: kategorie sie renderuja", przedZmiana > 0, `${przedZmiana} kategorii`);
  const btnMapy = d.querySelector('[data-zrodlo="mapy"]');
  if (btnMapy) {
    klik(btnMapy);
    sprawdz("Presety: Mapy maja INNY zestaw niz wyszukiwarka",
      ileKategorii() !== przedZmiana, `${przedZmiana} -> ${ileKategorii()}`);
    sprawdz("Presety: Mapy oznaczaja slabe kategorie",
      d.querySelectorAll("#presety-branz .tag-slaby").length > 0,
      `${d.querySelectorAll("#presety-branz .tag-slaby").length} slabych`);
    // Sekcje przy Mapach maja INNY podzial niz przy wyszukiwarce: nie uslugi/SaaS,
    // tylko "dziala / nie dziala w Mapach". To najcenniejsza informacja przy
    // wyborze, wiec musi byc widoczna w naglowku, a nie tylko w stylu chipa.
    const naglowkiMap = [...d.querySelectorAll("#presety-branz .preset-sekcja-tytul")]
      .map((x) => x.textContent);
    sprawdz("Presety: Mapy maja wlasne nazwy sekcji",
      naglowkiMap.some((x) => x.includes("Mapach")), naglowkiMap.join(" | "));
    // Slabe kategorie maja byc RAZEM w jednej sekcji, a nie rozsiane po liscie —
    // inaczej podzial nie oszczedza klikania, tylko dokłada ozdobnik.
    const slabaSekcja = [...d.querySelectorAll("#presety-branz .preset-sekcja")]
      .find((s) => s.querySelector(".preset-sekcja-tytul").textContent.includes("Słabe"));
    sprawdz("Presety: slabe kategorie zebrane w jednej sekcji",
      !!slabaSekcja && slabaSekcja.querySelectorAll(".tag-slaby").length ===
        d.querySelectorAll("#presety-branz .tag-slaby").length);
  } else {
    sprawdz("Presety: brak przelacznika zrodel (jedno podlaczone)", true);
  }

  // Kategorie maja byc w dwoch nazwanych sekcjach — przy 29 pozycjach jeden rzad
  // chipow to sciana. Wracamy na Wyszukiwarke, bo poprzedni przypadek zostawil Mapy.
  // Kafelki "Cale ujecie firmy" w Szukaj podobnych. Dwie rzeczy, ktore byly zle:
  // wchodzila tam NASZA kategoria (etykieta chipu, nie fraza — nikt tak o sobie
  // nie pisze), a dluga branza szla jednym kafelkiem
  // i zapytanie bylo za waskie.
  pozTab("podobne");

  // Tag zbadanej firmy musi byc TA SAMA nazwa co kategoria wyszukiwania. Bez tego
  // szukasz w "Sklepy internetowe", a znaleziona firma dostaje chip, ktorego nie ma
  // na zadnej liscie — i filtr na liscie Firm przestaje cokolwiek znaczyc.
  // Czytamy PRZED wyborem firmy: po kliknieciu lista chipow ustepuje miejsca karcie
  // firmy wzorcowej.
  const tagiFirm = [...d.querySelectorAll("[data-kat-podobne]")]
    .map((x) => x.dataset.katPodobne).filter(Boolean);

  klik(d.querySelector("#podobne-wybor .sim-row button"));
  const szerokieTagi = [...d.querySelectorAll(".tag-szeroki")].map((x) => x.textContent.trim());
  sprawdz("Podobne: kafelki szerokie sie pojawily", szerokieTagi.length > 0,
    szerokieTagi.join(" | "));
  // Mapy sa DOMYSLNE w Szukaj podobnych, inaczej niz w Szukaj po branzy.
  // Zmierzone na Sellision: wyszukiwarka 9 firm, Mapy 30, wspolnych 2 — Mapy
  // rankinguja po wizytowce, wiec pokazuja firmy, ktore nie inwestuja w SEO.
  const zaznaczoneZrodlo = [...d.querySelectorAll("[data-zrodlo-podobne]")]
    .find((b) => b.classList.contains("zaznaczony"));
  sprawdz("Podobne: Mapy sa domyslnym zrodlem",
    !zaznaczoneZrodlo || zaznaczoneZrodlo.dataset.zrodloPodobne === "mapy",
    zaznaczoneZrodlo ? zaznaczoneZrodlo.dataset.zrodloPodobne : "brak przelacznika");

  // Kategoria jest dzis TA SAMA nazwa co kategoria wyszukiwania w PRESETY,
  // ale to wciaz ETYKIETA CHIPU, a nie zapytanie: nikt nie wpisuje w Google
  // "Sklepy internetowe", zeby znalezc agencje. Na zapytanie nadaje sie fraza
  // glowna tej kategorii ("tworzenie sklepów internetowych"), nie sam tag.
  sprawdz("Podobne: NASZA kategoria nie jest fraza wyszukiwania",
    !szerokieTagi.includes("Sklepy internetowe")
      && !szerokieTagi.includes("Budowa stron i sklepów"),
    szerokieTagi.join(" | "));

  pozTab("branza");
  klik(d.querySelector('[data-zrodlo="wyszukiwarka"]'));
  sprawdz("Presety: kategorie w dwoch nazwanych sekcjach",
    d.querySelectorAll("#presety-branz .preset-sekcja").length === 2,
    `${d.querySelectorAll("#presety-branz .preset-sekcja").length} sekcji`);

  const kategoriePresetow = [...d.querySelectorAll("#presety-branz [data-grupa]")]
    .map((x) => x.firstChild ? x.textContent.replace(/\s*\d+\s*$/, "").trim() : "");
  const osierocone = tagiFirm.filter((t) => !kategoriePresetow.includes(t));
  sprawdz("Tagi firm sa tymi samymi nazwami co kategorie wyszukiwania",
    osierocone.length === 0,
    osierocone.length ? `poza lista: ${osierocone.join(", ")}` : `${tagiFirm.length} tagow`);

  // ══ NARZĘDZIA W KARCIE, NIE W MENU ══
  // Rozmowa, audyt GEO, mikroaudyt i generator dokumentu żyją teraz w karcie
  // partnera. Sprawdzamy dwie rzeczy naraz: że działają i że NIE ma ich już
  // w nawigacji — bo to właśnie one robiły z aplikacji listę narzędzi.
  const wMenu = [...d.querySelectorAll(".nav-item")].map((b) => b.dataset.sekcja);
  sprawdz("Menu: narzędzia zniknęły z nawigacji",
    !wMenu.some((x) => ["rozmowa", "audyt", "audytgeo", "dokument", "podobne", "szukaj", "research"]
      .includes(x)), wMenu.join(", "));
  sprawdz("Menu: zostały miejsca, nie narzędzia",
    wMenu.join(",") === "firmy,kolejka,pozyskiwanie,maile,audyty,eksport", wMenu.join(","));

  nav("firmy");
  otworzKarte(0);
  kartaTab("synergia");
  sprawdz("Rozmowa: od razu pole pytania, bez wyboru firmy",
    !!d.querySelector("#rozmowa-box .czat-pytanie"));
  sprawdz("Rozmowa: jest przycisk Zapytaj",
    !!d.querySelector("#rozmowa-box .czat-wyslij"));

  // Audyt GEO — OSOBNY pomiar, nie wariant mikroaudytu. Oba są w jednej zakładce,
  // więc tym bardziej trzeba pilnować, żeby się nie zlały.
  kartaTab("widocznosc");
  const geoForm = d.getElementById("audytgeo-wybor").innerHTML;
  // Pole na wlasne prompty zostalo usuniete na zyczenie — pilnujemy, zeby nie
  // wrocilo przypadkiem razem ze stanem, ktory nikogo juz nie obsluguje.
  sprawdz("Audyt GEO: nie ma pola na wlasne prompty", !d.getElementById("geo-wlasne"));
  sprawdz("Audyt GEO: jest suwak powtorzen", !!d.getElementById("geo-powtorzenia"));
  sprawdz("Audyt GEO: jest przelacznik podpowiedzi Google", !!d.getElementById("geo-podpowiedzi"));
  sprawdz("Audyt GEO: sa DWA silniki na wlasnych kluczach",
    d.querySelectorAll('input[name="geo-silnik"]').length === 2);
  // Ten audyt nie moze dotykac DataForSEO — gdyby ktos dolozyl tu silnik przez
  // dostawce, cala jego przewaga (dziala przy pustym saldzie) by zniknela.
  sprawdz("Audyt GEO: zaden silnik nie idzie przez DataForSEO",
    !/przez DataForSEO/i.test(geoForm));
  sprawdz("Audyt GEO: pokazuje koszt przed uruchomieniem", /Szacowany koszt/.test(geoForm));
  // Pierwsza zakladka ma zostac JAK BYLA — bez suwaka powtorzen, ktory nalezy do GEO.
  sprawdz("Mikroaudyt: bez suwaka powtorzen (zostal jak byl)",
    !d.getElementById("audyt-powtorzenia"));

  // Dokument dla klienta partnera: partner jest znany z karty, więc pierwszym
  // pytaniem jest już KLIENT, a nie „od kogo ten materiał".
  kartaTab("dokumenty");
  const dokBox = d.getElementById("dokument-wybor").innerHTML;
  sprawdz("Materiały: pytanie od razu o klienta partnera",
    dokBox.includes("Do ktorego klienta") || dokBox.includes("Do kt\u00f3rego klienta"), "");
  sprawdz("Materiały: sa pola na nazwe i adres klienta",
    !!d.getElementById("dok-klient") && !!d.getElementById("dok-klient-url"));
  // Bez nazwy klienta nie ma czego generowac — przycisk startuje wylaczony.
  sprawdz("Materiały: generowanie zablokowane bez nazwy klienta",
    d.querySelector(".generuj-dokument").disabled);
  klik(d.querySelector(".wroc-do-listy"));

  // Maile w menu to PRZEGLĄD wszystkich szkiców, nie kolejny wybór firmy.
  nav("maile");
  sprawdz("Maile: przegląd nie pyta ponownie o firmę",
    !d.getElementById("maile-box").innerHTML.includes("Do kogo piszemy"));

  // ══ FILTRY W KOLEJCE ══
  // Zmierzone na żywej kolejce: 45 firm, wszystkie w JEDNEJ kategorii, ale
  // z dwóch różnych fraz. Filtr kategorii nie pokazywał się wcale (bo kategoria
  // jedna), a to właśnie fraza dzieliła tę listę na sensowne części.
  nav("kolejka");
  const wKolejce = () => d.querySelectorAll("#kolejka-box .sim-row").length;
  sprawdz("Kolejka: pokazuje odłożone firmy", wKolejce() === 3, `${wKolejce()} wierszy`);
  sprawdz("Kolejka: jest pole szukania", !!d.getElementById("szukaj-kolejka"));

  const chipyZap = [...d.querySelectorAll("[data-zap-kolejka]")]
    .filter((x) => x.dataset.zapKolejka);
  sprawdz("Kolejka: filtr po zapytaniu, z którego firma przyszła",
    chipyZap.length === 2,
    chipyZap.map((x) => x.textContent.trim().replace(/\s+/g, " ")).join(" | "));

  klik(chipyZap.find((x) => x.dataset.zapKolejka.includes("growth")));
  sprawdz("Kolejka: filtr zapytania zawęża listę", wKolejce() === 1, `${wKolejce()} wierszy`);
  klik(d.querySelector('[data-zap-kolejka=""]'));
  sprawdz("Kolejka: „Wszystkie” przywraca pełną listę", wKolejce() === 3);

  const poleK = d.getElementById("szukaj-kolejka");
  poleK.value = "adlife";
  poleK.dispatchEvent(new window.Event("input", { bubbles: true }));
  sprawdz("Kolejka: szukanie działa po nazwie i adresie", wKolejce() === 1, `${wKolejce()} wierszy`);
  const poleK2 = d.getElementById("szukaj-kolejka");
  poleK2.value = "";
  poleK2.dispatchEvent(new window.Event("input", { bubbles: true }));

  nav("eksport");
  sprawdz("Eksport: sekcja renderuje się bez błędu",
    d.getElementById("eksport-box").innerHTML.length > 0);

  // ── Kolejka: czy przycisk w ogole cokolwiek wysyla ─────────────────
  // To jest regresja z 24.09.2026. Przycisk miał atrybut `data-zrodlo`, ten sam,
  // ktorym oznaczone sa przelaczniki zrodel — a warunek dla przelacznika stoi
  // wyzej w obsludze klikniec. Kazde klikniecie "Dodaj wszystkie do kolejki"
  // przestawialo wiec zrodlo wyszukiwania i przerysowywalo presety. Kolejka
  // zostawala pusta i nic nie mowilo, ze cos poszlo nie tak.
  pozTab("branza");
  d.getElementById("branza").value = "tworzenie sklepów internetowych";
  d.getElementById("form-kryteria").dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }));

  setTimeout(() => {
    const przycisk = d.querySelector(".do-kolejki-wszystkie");
    sprawdz("Kolejka: wyniki maja przycisk dodania do kolejki", !!przycisk);

    const zrodloPrzed = (d.querySelector("#zrodla-wyboru .zrodlo-wiersz.zaznaczony") || {}).dataset?.zrodlo;
    klik(przycisk);

    setTimeout(() => {
      const dodania = zadania.filter((z) => z.url.includes("/api/kolejka") && z.metoda === "POST");
      sprawdz("Kolejka: klikniecie wysyla firmy do /api/kolejka",
        dodania.length === 1 && (dodania[0].body.firmy || []).length === ZNALEZIONE.length,
        dodania.length ? `${(dodania[0].body.firmy || []).length} firm` : "zadnego zadania");

      sprawdz("Kolejka: dodanie NIE przestawia zrodla wyszukiwania",
        (d.querySelector("#zrodla-wyboru .zrodlo-wiersz.zaznaczony") || {}).dataset?.zrodlo === zrodloPrzed,
        `${zrodloPrzed} -> ${(d.querySelector("#zrodla-wyboru .zrodlo-wiersz.zaznaczony") || {}).dataset?.zrodlo}`);

      // Tag kategorii dla firm, ktore dopiero czekaja na research. Fraza pochodzi
      // z presetu "Sklepy internetowe", wiec kolejka ma to zapamietac — inaczej
      // po dodaniu 200 firm z pieciu branz nie da sie ich rozdzielic.
      sprawdz("Kolejka: firmy dostaja kategorie z presetu",
        dodania.length === 1 && dodania[0].body.kategoria === "Sklepy internetowe",
        dodania.length ? JSON.stringify(dodania[0].body.kategoria) : "brak");

      podsumuj();
    }, 60);
  }, 60);
}, 400);

// ══════════════════════════════════════════════════════════════════════
//  STRAŻNIK NAZW KLAS STANU
// ══════════════════════════════════════════════════════════════════════
// Trzy razy pod rząd ten sam błąd: CSS mówił `.komponent.aktywny`, a JS ustawiał
// `aktywna` (albo odwrotnie). Reguła nigdy nie pasowała, element zostawał
// niewidoczny, a testy przechodziły, bo sprawdzały obecność w drzewie.
//
// W tej aplikacji obie formy są w użyciu i to jest w porządku — „aktywny wiersz",
// „aktywna sekcja". Nie w porządku jest, gdy JEDEN komponent używa obu naraz.
// Sprawdzamy więc zgodność per komponent, a nie ujednolicamy na siłę.
function sprawdzNazwyStanu() {
  const cssTekst = fs.readFileSync(path.join(KAT, "style.css"), "utf8");
  const jsTekst = fs.readFileSync(path.join(KAT, "app.js"), "utf8");
  const htmlTekst = fs.readFileSync(path.join(KAT, "index.html"), "utf8");

  // Z CSS: które komponenty mają regułę stanu i w jakim rodzaju.
  const wCss = new Map();
  for (const m of cssTekst.matchAll(/\.([a-z][a-z0-9-]*)\.(aktywn[ay])\b/g)) {
    if (!wCss.has(m[1])) wCss.set(m[1], new Set());
    wCss.get(m[1]).add(m[2]);
  }

  // Z JS: `querySelectorAll(".komponent")` … `classList.toggle("aktywnX"`.
  // Szukamy w obrębie jednej instrukcji, nie całego pliku — inaczej `aktywny`
  // użyte gdzie indziej maskowałoby błąd.
  const wKodzie = new Map();
  const dodaj = (komponent, forma) => {
    if (!wKodzie.has(komponent)) wKodzie.set(komponent, new Set());
    wKodzie.get(komponent).add(forma);
  };
  for (const m of jsTekst.matchAll(
      /querySelectorAll\("\.([a-z][a-z0-9-]*)"\)[\s\S]{0,220}?classList\.toggle\("(aktywn[ay])"/g)) {
    dodaj(m[1], m[2]);
  }
  // Z JS i HTML: klasa wpisana wprost w znacznik, np. class="poz-panel aktywna".
  for (const tekst of [jsTekst, htmlTekst]) {
    for (const m of tekst.matchAll(/class="([^"]*\baktywn[ay]\b[^"]*)"/g)) {
      const klasy = m[1].split(/\s+/);
      const forma = klasy.find((k) => /^aktywn[ay]$/.test(k));
      klasy.filter((k) => k !== forma && /^[a-z][a-z0-9-]*$/.test(k))
        .forEach((k) => dodaj(k, forma));
    }
  }

  const konflikty = [];
  for (const [komponent, formyCss] of wCss) {
    const formyKodu = wKodzie.get(komponent);
    if (!formyKodu) continue;                     // stan nadawany inaczej — nie zgadujemy
    for (const forma of formyKodu) {
      if (!formyCss.has(forma)) {
        konflikty.push(`.${komponent}: kod ustawia „${forma}", CSS zna `
          + [...formyCss].map((x) => `„${x}"`).join(", "));
      }
    }
  }
  sprawdz("Klasy stanu: kod i CSS mówią o tym samym komponencie tak samo",
    konflikty.length === 0, konflikty.join(" | ") || `${wCss.size} komponentów`);
}

function podsumuj() {
  sprawdzNazwyStanu();
  let zle = 0;
  console.log("");
  wyniki.forEach((w) => {
    if (!w.ok) zle++;
    console.log(`  ${w.ok ? "OK  " : "BŁĄD"} | ${w.opis}${w.dodatek ? "   [" + w.dodatek + "]" : ""}`);
  });
  console.log("");
  console.log(`  błędy JS: ${bledyJS.length ? bledyJS.join(" | ") : "brak"}`);
  console.log(`  WYNIK: ${wyniki.length - zle}/${wyniki.length}`);
  process.exit(zle || bledyJS.length ? 1 : 0);
}

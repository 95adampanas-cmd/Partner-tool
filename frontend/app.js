// Partner Tool — aplikacja (sekcje + zakładki firm)
const BRAK = "nie do ustalenia";

let tabs = [];       // [{id, nazwa, firma}]
let activeId = null;
let tabSeq = 0;
let koszyk = [];     // firmy zaznaczone do eksportu
let kolumny = [];    // definicja kolumn CSV — z backendu (jedno źródło prawdy)

// Dwie ścieżki pozyskiwania: partnerzy i klienci. To NIE jest tylko etykieta —
// zmienia to, czego szukamy (dla partnera liczy sie komplementarnosc, dla klienta
// sklep ze słabą widocznością to najlepszy trop) i ton maila. Każda zbadana firma
// pamięta, w której ścieżce powstała, więc „Praca" potrafi je rozdzielić.
// ── WYŁĄCZNIK ŚCIEŻKI KLIENTÓW ───────────────────────────────────────
// false = interfejs pokazuje wyłącznie partnerów: znika grupa „Klienci" z menu
// i wszystkie przełączniki ścieżki. Model danych zostaje NIETKNIĘTY — kolumna
// `tryb` dalej jest w bazie, a firmy zbadane jako klienci czekają tam bez zmian.
//
// Dlaczego wyłącznik, a nie usunięcie: tryb siedzi w 169 miejscach w pięciu
// plikach i w trzech tabelach. Wycięcie tego to przepisywanie połowy aplikacji
// przy zerowym zysku — a powrót do klientów kosztuje wtedy tyle samo co teraz.
// Tak wystarczy zmienić to jedno słowo na true.
const POKAZUJ_KLIENTOW = false;

let tryb = "partner";
// Dla której ścieżki narysowano wspólne sekcje. Bez tego nie da się poznać, że
// user JUŻ przełączył ścieżkę, a na ekranie wisi jeszcze zawartość poprzedniej.
let trybPokazany = "partner";
// Zawężenie listy firm ustawiane przez kafel „z SEO w ofercie". null = pełna lista.
// Świadomie NIE jest trwałe: wejście do Firm z menu i zmiana ścieżki je zdejmują,
// żeby nikt nie oglądał niepełnej listy, nie wiedząc dlaczego.
let filtrFirm = null;
let szukajFirm = "";     // tekst wpisany w pole nad listą partnerów
const TRYBY = {
  partner: { nazwa: "Partnerzy", jeden: "partnera",
             opis: "Firmy, które mogą polecać nas swoim klientom albo odsprzedawać nasze usługi." },
  klient:  { nazwa: "Klienci", jeden: "klienta",
             opis: "Firmy, które mogą kupić SEO/GEO — im słabsza widoczność, tym większy potencjał." },
};

fetch("/api/columns").then((r) => r.json()).then((d) => { kolumny = d.kolumny || []; });

// Wczytanie pamięci przy starcie. Bez tego odświeżenie strony kasowało cały dzień
// pracy — research jednej firmy to ~30 s i kilka groszy, więc utrata dwudziestu
// to realna strata, nie niedogodność.
async function wczytajPamiec() {
  try {
    const d = await (await fetch("/api/firmy")).json();
    for (const f of d.firmy || []) {
      const id = "tab" + ++tabSeq;
      tabs.push({ id, nazwa: hostname(f.url), firma: f, tryb: f.tryb || "partner" });
      if (f.w_koszyku) koszyk.push({ ...f, tryb: f.tryb || "partner" });
    }
    odswiezBadge("badge-firmy", firmyTrybu().length);
    odswiezBadge("badge-eksport",
      koszyk.filter((f) => (f.tryb || "partner") === tryb).length);
    renderResearchPanel();
  } catch (e) {
    console.warn("Nie udało się wczytać zapisanych firm:", e);
  }
}
// Usunięcie grupy „Klienci" z menu. Robione w JS, nie przez skasowanie z HTML,
// żeby przywrócenie ścieżki nie wymagało odtwarzania znaczników.
if (!POKAZUJ_KLIENTOW) {
  document.querySelectorAll('.nav-item[data-tryb="klient"]').forEach((b) => b.remove());
  [...document.querySelectorAll(".nav-grupa")]
    .filter((g) => g.textContent.trim() === "Klienci")
    .forEach((g) => g.remove());
  // Nagłówek „Ścieżka: Partnerzy" też przestaje mieć sens, gdy ścieżka jest jedna.
  document.querySelectorAll("[data-tryb-naglowek]")
    .forEach((h) => h.removeAttribute("data-tryb-naglowek"));
}

wczytajPamiec();

// ══ Nawigacja między sekcjami ══
function pokazSekcje(nazwa) {
  document.querySelectorAll(".sekcja").forEach((s) =>
    s.classList.toggle("aktywna", s.dataset.sekcja === nazwa));
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("aktywny", b.dataset.sekcja === nazwa
      && (!b.dataset.tryb || b.dataset.tryb === tryb)));
  // Sekcje pozyskiwania są WSPÓLNE dla obu ścieżek — ten sam DOM obsługuje
  // partnerów i klientów. Przy zmianie ścieżki trzeba więc wyczyścić to, co
  // zostało po poprzedniej, inaczej firma zbadana jako partner widnieje na
  // ekranie klientów. Panel researchu filtrował po tryb poprawnie, ale nikt go
  // nie przerysowywał: pokazSekcje odświeżało eksport, podobne, audyt i firmy,
  // a research i szukaj pomijało.
  if (trybPokazany !== tryb) {
    ["research-wynik", "szukaj-wynik", "podobne-wynik", "podobne-tagi"]
      .forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = "";
      });
    otwartaGrupa = null;   // numery grup należą do poprzedniej ścieżki
    podobneKategoria = null;
    filtrKategorii = null;
    filtrKolejki = null;
    maileWybrana = null;
    maileAktywny = null;
    trybPokazany = tryb;
  }

  if (nazwa === "pozyskiwanie") renderPozyskiwanie();
  if (nazwa === "eksport") renderEksport();
  if (nazwa === "kolejka") renderKolejke();
  if (nazwa === "maile") renderMaile();
  if (nazwa === "audyty") renderAudyty();
  if (nazwa === "firmy") pokazListe();  // wejście z menu zawsze pokazuje listę

  // Liczniki w menu też są per-ścieżka — bez tego pokazują stan poprzedniej.
  odswiezBadge("badge-firmy", firmyTrybu().length);
  odswiezBadge("badge-kolejka", kolejkaTrybu().length);
  odswiezBadge("badge-maile", maileTrybu().length);
  odswiezBadge("badge-eksport",
    koszyk.filter((f) => (f.tryb || "partner") === tryb).length);
  // Sekcje pozyskiwania są wspólne dla obu ścieżek, więc muszą powiedzieć,
  // w której jesteśmy — inaczej nie wiadomo, czy badamy partnera czy klienta.
  document.querySelectorAll("[data-tryb-naglowek] .znacznik-tryb").forEach((e) => e.remove());
  document.querySelectorAll("[data-tryb-naglowek] h1").forEach((h) =>
    h.insertAdjacentHTML("beforebegin",
      `<span class="znacznik-tryb">Ścieżka: ${TRYBY[tryb].nazwa}</span>`));
  window.scrollTo(0, 0);
}
document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => {
    if (b.dataset.tryb) tryb = b.dataset.tryb;
    filtrFirm = null;   // wejscie z menu to zawsze pelna lista
    pokazSekcje(b.dataset.sekcja);
  }));

// ══ SEKCJA: Research po URL ══
const form = document.getElementById("form");
const btn = document.getElementById("btn");
const researchWynik = document.getElementById("research-wynik");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  let url = document.getElementById("url").value.trim();
  if (!url) return;
  if (!/^https?:\/\//i.test(url)) url = "https://" + url;

  researchWynik.innerHTML = loadingHTML("Zbieram dane… (strona główna + podstrony → ekstrakcja). ~20-40 s.");
  btn.disabled = true;
  try {
    const data = await research(url);
    if (!data.ok) {
      researchWynik.innerHTML = errorHTML(data.error);
    } else {
      researchWynik.innerHTML = "";
      otworzFirme(data.firma);
    }
  } catch (err) {
    researchWynik.innerHTML = errorHTML(err.message);
  } finally {
    btn.disabled = false;
  }
});

async function research(url) {
  const res = await fetch("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, tryb }),
  });
  return res.json();
}

// ══ Panel pod polem researchu ══
// Pusty ekran nic nie mówi. Przed pierwszym researchem tłumaczymy, CO wyciągamy;
// potem pokazujemy stan pracy i skrót do ostatnio zbadanych firm.
const ZBIERAMY = [
  ["tag", "Usługi i oferta", "pełna lista usług z podstron"],
  ["file", "Realizacje i case studies", "nazwy klientów, liczba wdrożeń"],
  ["users", "Wielkość zespołu", "jeśli firma ją podaje"],
  ["user", "Osoba decyzyjna", "imię, stanowisko, bezpośredni kontakt"],
  ["mail", "Kontakt firmowy", "telefon i e-mail ze strony"],
  ["building", "Dane spółki", "nazwa prawna, NIP, adres, miasto"],
  ["alert", "SEO w ofercie", "czy firma sprzedaje pozycjonowanie"],
  ["pin", "Źródło danych", "które podstrony odwiedziliśmy"],
];

function renderResearchPanel() {
  const box = document.getElementById("research-panel");

  if (!firmyTrybu().length) {
    box.innerHTML = `<div class="card panel-info">
      <div class="mono"><i class="sq"></i>Co zbierzemy ze strony</div>
      <div class="siatka-info">${ZBIERAMY.map(([ikona, tytul, opis]) => `
        <div class="info-poz">
          <svg class="ico"><use href="#i-${ikona}"/></svg>
          <div><b>${esc(tytul)}</b><span>${esc(opis)}</span></div>
        </div>`).join("")}</div>
      <p class="hint">Czego nie ma na stronie, oznaczamy jako „nie do ustalenia" — nigdy nie zgadujemy.</p>
    </div>`;
    return;
  }

  const moje = firmyTrybu();
  const zSeo = moje.filter((t) => t.firma.ma_seo).length;
  const ostatnie = moje.slice(-4).reverse();
  box.innerHTML = `
    <div class="kafle">
      ${kafel(moje.length, "zbadane firmy", "building", "firmy")}
      ${kafel(koszyk.filter((f) => (f.tryb || "partner") === tryb).length, "w eksporcie", "table", "eksport")}
      ${kafel(zSeo, "z SEO w ofercie", "search", "seo")}
    </div>
    <div class="card">
      <div class="mono"><i class="sq"></i>Ostatnio zbadane</div>
      <div class="similar-list">${ostatnie.map((t) => `
        <div class="sim-row firma-row" data-id="${t.id}" style="margin:0">
          <div class="sim-info">
            <span class="sim-name">${esc(t.firma.nazwa)}</span>
            <span class="firma-row-meta">${esc(hostname(t.firma.url))} · ${esc(t.firma.branza)}</span>
          </div>
          <button class="otworz" type="button">Otwórz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>`).join("")}</div>
    </div>`;
}

// Kafel jest przyciskiem, nie divem — liczba bez dojścia do tego, co liczy,
// zmusza użytkownika do szukania tych firm ręcznie w menu.
// <button> zamiast diva z onclickiem daje przy okazji obsługę klawiatury i focus.
function kafel(liczba, etykieta, ikona, cel) {
  return `<button class="kafel" type="button" data-kafel="${cel}"
      title="Pokaż: ${esc(etykieta)}">
    <svg class="ico"><use href="#i-${ikona}"/></svg>
    <div><b>${liczba}</b><span>${esc(etykieta)}</span></div>
    <svg class="ico xs kafel-strzalka"><use href="#i-arrow"/></svg>
  </button>`;
}

// ══ SEKCJA: Szukaj po branży ══
const formKryteria = document.getElementById("form-kryteria");
const btnKryteria = document.getElementById("btn-kryteria");
const szukajWynik = document.getElementById("szukaj-wynik");
// Kategoria ostatniego wyszukiwania — jedziemy z nią do kolejki.
let kategoriaZapytania = "";

// Presety branż — OSOBNE dla każdej ścieżki. Wcześniej była jedna płaska lista,
// renderowana raz przy starcie, więc w Klientach wyświetlały się kategorie
// partnerskie („agencja brandingowa"), co jest odwrotnością tego, kogo tam szukamy.
//
// PARTNER: firma, która obsługuje TYCH SAMYCH klientów co my, ale robi coś innego —
// buduje sklep, projektuje markę, prowadzi social media. Ma bazę klientów
// potrzebujących SEO i nie ma czym tego obsłużyć, więc może nas polecić.
// Dlatego na liście nie ma nikogo, kto sprzedaje pozycjonowanie.
//
// KLIENT: firma, która sama mogłaby kupić SEO/GEO. Kryterium jest odwrotne —
// tu słaba widoczność jest zaletą, bo znaczy potencjał.
const PRESETY = {
  // Kategorie WYWIEDZIONE z listy 35 realnych partnerów Adama (04.09.2026) — nie
  // z burzy mózgów. Każda ma za sobą co najmniej jedną firmę, która się broni.
  //
  // Dwie firmy z listy (webmetric.com, stonehengeagency.com) SPRZEDAJĄ SEO i mimo to
  // są dobrymi partnerami. Dlatego odsiew konkurentów został usunięty, a SEO jest
  // tylko tagiem — patrz DECISIONS 2026-09-04.
  //
  // ── PRESETY WYSZUKIWANIA — Wyszukiwarka i Google ─────────────────────
  //
  // Struktura od Adama (23.09.2026): 29 kategorii, 297 fraz. Każda kategoria ma
  // JEDNĄ frazę główną (najszerszą) i podkategorie, które zawężają.
  //
  // Piąty element to SEKCJA — „uslugi" albo „saas". Przy 29 kategoriach jeden rząd
  // chipów jest ścianą; podział na dwie nazwane grupy skraca skanowanie o połowę,
  // a granica jest naturalna: firmy usługowe kontra producenci oprogramowania.
  // (Czwarty element rezerwuje miejsce na flagę „słabe", której używają Mapy.)
  //
  // TE NAZWY SĄ JEDNOCZEŚNIE TAGAMI ZBADANYCH FIRM (KATEGORIE_PARTNEROW w app.py)
  // i muszą się zgadzać znak w znak. Przez jeden dzień były to dwie różne listy —
  // 29 kategorii do szukania i 10 szufladek nadawanych po researchu — i wyszło to
  // tak: szukałeś w „Sklepy internetowe", a znaleziona firma dostawała tag „Budowa
  // stron i sklepów", którego nie ma na żadnej liście wyboru. Filtr na liście Firm
  // i w „Szukaj podobnych" pokazywał wtedy trzy chipy na dziewiętnaście firm.
  // Zgodności pilnuje test `sprawdz_presety` w backend/test_filtr.py.
  partner: [
    ["Strony www", "tworzenie stron internetowych", [
      "projektowanie stron www", "strony www dla firm", "agencja interaktywna",
      "agencja WordPress", "strony WordPress", "agencja Webflow", "agencja Framer",
      "software house", "tworzenie aplikacji webowych", "tworzenie landing page",
      "opieka nad stroną WordPress", "audyt dostępności WCAG"
    ], null, "uslugi"],
    ["Sklepy internetowe", "tworzenie sklepów internetowych", [
      "agencja e-commerce", "software house e-commerce", "agencja Shopify", "wdrożenia Shoper",
      "wdrożenia IdoSell", "wdrożenia WooCommerce", "wdrożenia PrestaShop",
      "wdrożenia Magento", "wdrożenia Shopware", "sklep B2B", "platforma B2B wdrożenie",
      "migracja sklepu internetowego", "administracja sklepem internetowym",
      "outsourcing e-commerce", "prowadzenie sklepu internetowego"
    ], null, "uslugi"],
    ["Agencje digital / full-service", "agencja marketingowa", [
      "agencja digital marketingu", "agencja marketingu internetowego",
      "agencja reklamy internetowej", "agencja full-service", "agencja 360",
      "agencja marketingowa dla e-commerce", "marketing dla sklepów internetowych",
      "agencja marketingu B2B", "marketing przemysłowy", "agencja lead generation",
      "agencja growth marketingu", "marketing medyczny", "marketing dla deweloperów",
      "marketing dla branży beauty", "marketing dla hoteli"
    ], null, "uslugi"],
    ["Branding i PR", "agencja kreatywna", [
      "agencja brandingowa", "agencja komunikacji marketingowej", "agencja PR",
      "public relations", "studio graficzne", "identyfikacja wizualna", "projektowanie logo",
      "rebranding", "naming marki", "projektowanie opakowań", "agencja UX/UI", "audyt UX"
    ], null, "uslugi"],
    ["Strategia i doradztwo", "doradztwo biznesowe", [
      "konsulting e-commerce", "doradztwo e-commerce", "strategia e-commerce",
      "audyt e-commerce", "doradztwo marketingowe", "konsultant marketingowy",
      "agencja strategiczna", "strategia marketingowa", "strategia marki",
      "doradztwo strategiczne", "interim manager e-commerce", "e-commerce manager na zlecenie",
      "CMO na godziny", "fractional CMO", "szkolenia e-commerce", "szkolenia marketingowe",
      "mentoring e-commerce", "rekrutacja e-commerce", "dotacje na marketing"
    ], null, "uslugi"],
    ["Social media", "agencja social media", [
      "prowadzenie social media dla firm", "agencja influencer marketingu",
      "influencer marketing", "content marketing", "agencja contentowa",
      "marketing na TikToku", "agencja TikTok", "UGC dla marek"
    ], null, "uslugi"],
    ["Content produktowy", "fotografia produktowa", [
      "studio fotografii produktowej", "packshot", "wideo produktowe", "opisy produktów",
      "copywriting e-commerce", "grafiki do sklepu internetowego"
    ], null, "uslugi"],
    ["Performance", "reklama w internecie", [
      "agencja Google Ads", "agencja PPC", "agencja SEM", "Google Partner agencja",
      "agencja Meta Ads", "reklama na Facebooku", "reklama na TikToku", "agencja LinkedIn Ads",
      "kampanie produktowe Google", "agencja performance marketing", "marketing afiliacyjny",
      "sieć afiliacyjna"
    ], null, "uslugi"],
    ["Marketplace", "obsługa marketplace", [
      "agencja Allegro", "obsługa konta Allegro", "kampanie Allegro Ads", "agencja Amazon",
      "sprzedaż na Amazon", "Amazon FBA", "sprzedaż na Kaufland", "sprzedaż na eMAG",
      "integracja BaseLinker"
    ], null, "uslugi"],
    ["Ekspansja zagraniczna", "ekspansja zagraniczna", [
      "ekspansja zagraniczna e-commerce", "sprzedaż cross-border", "sprzedaż do Niemiec",
      "wejście na rynek niemiecki", "e-commerce Niemcy",
      "sklep internetowy na rynki zagraniczne", "lokalizacja sklepu internetowego",
      "tłumaczenia stron internetowych", "tłumaczenia sklepów internetowych",
      "doradztwo eksportowe", "internacjonalizacja firmy"
    ], null, "uslugi"],
    ["Fulfillment i logistyka", "fulfillment", [
      "fulfillment e-commerce", "magazyn fulfillment", "outsourcing logistyki e-commerce",
      "operator logistyczny 3PL", "magazyn dla sklepu internetowego", "logistyka e-commerce",
      "obsługa zwrotów e-commerce", "dropshipping", "wdrożenia WMS"
    ], null, "uslugi"],
    ["Księgowość i podatki", "biuro rachunkowe dla e-commerce", [
      "księgowość sklepu internetowego", "księgowość e-commerce", "VAT OSS",
      "doradca podatkowy e-commerce", "księgowość Amazon Allegro",
      "rozliczenia sprzedaży zagranicznej"
    ], null, "uslugi"],
    ["Analityka i CRO", "analityka internetowa", [
      "analityka e-commerce", "wdrożenia Google Analytics 4", "wdrożenia Google Tag Manager",
      "server-side tracking", "wdrożenie Consent Mode", "raporty Looker Studio",
      "raportowanie marketingowe", "business intelligence e-commerce",
      "optymalizacja konwersji", "audyt UX sklepu", "testy A/B",
      "integracje sklepu internetowego"
    ], null, "uslugi"],
    ["AI", "AI dla firm", [
      "agencja AI", "doradztwo AI", "wdrożenie AI w firmie", "wdrożenie ChatGPT w firmie",
      "agenci AI", "automatyzacja AI", "wdrożenia chatbotów", "asystent AI dla firm",
      "AI w e-commerce", "AI w marketingu", "szkolenia AI dla firm"
    ], null, "uslugi"],
    ["Automatyzacje", "automatyzacja procesów biznesowych", [
      "automatyzacja marketingu", "marketing automation", "wdrożenia marketing automation",
      "automatyzacja sprzedaży", "automatyzacja e-commerce", "agencja e-mail marketingu",
      "wdrożenia n8n", "wdrożenia Make", "wdrożenia Zapier", "automatyzacje no-code",
      "integracje API"
    ], null, "uslugi"],
    ["CRM", "CRM dla firm", [
      "wdrożenia CRM", "wdrożenie systemu CRM", "integrator CRM", "partner wdrożeniowy CRM",
      "konsultant CRM", "doradztwo CRM", "firma informatyczna CRM",
      "integracja CRM ze sklepem internetowym", "optymalizacja procesów sprzedaży"
    ], null, "uslugi"],
    ["ERP", "ERP dla firm", [
      "wdrożenia ERP", "wdrożenie systemu ERP", "integrator ERP", "partner wdrożeniowy ERP",
      "konsultant ERP", "firma informatyczna ERP", "ERP dla e-commerce",
      "integracja ERP ze sklepem internetowym", "integracje systemów", "wdrożenia PIM",
      "integracja EDI"
    ], null, "uslugi"],
    ["Prawo e-commerce", "prawo nowych technologii", [
      "kancelaria e-commerce", "prawnik e-commerce", "obsługa prawna sklepu internetowego",
      "regulamin sklepu internetowego", "RODO dla sklepów internetowych",
      "prawo konsumenckie e-commerce", "GPSR", "dyrektywa Omnibus", "prawo reklamy",
      "rejestracja znaku towarowego", "rzecznik patentowy", "umowy IT", "prawo IT"
    ], null, "uslugi"],
    ["Hosting i infrastruktura", "hosting dla sklepów internetowych", [
      "hosting WordPress", "hosting WooCommerce", "serwery dla e-commerce",
      "hosting zarządzany", "administracja serwerami", "CDN dla sklepu"
    ], null, "uslugi"],
    ["Platformy sklepowe", "oprogramowanie e-commerce", [
      "platforma sklepów internetowych", "sklep internetowy SaaS",
      "sklep internetowy w abonamencie", "platforma sklepów B2B",
      "oprogramowanie do sklepu internetowego"
    ], null, "saas"],
    ["Sprzedaż wielokanałowa", "sprzedaż wielokanałowa", [
      "system do sprzedaży wielokanałowej", "integrator marketplace", "integracje marketplace",
      "oprogramowanie do obsługi zamówień", "system PIM"
    ], null, "saas"],
    ["Opinie i zaufanie", "zbieranie opinii klientów", [
      "system opinii dla sklepów internetowych", "certyfikat zaufania sklepu internetowego",
      "opinie o produktach widget", "program recenzji produktów"
    ], null, "saas"],
    ["Marketing automation i e-mail", "narzędzia do marketing automation", [
      "system do automatyzacji marketingu", "system do e-mail marketingu",
      "narzędzie do newslettera", "platforma SMS marketingu", "powiadomienia web push",
      "platforma CDP", "marketing automation dla e-commerce"
    ], null, "saas"],
    ["Narzędzia dla sklepów", "aplikacje dla sklepów internetowych", [
      "wyszukiwarka produktowa dla sklepu", "rekomendacje produktowe", "live chat dla sklepu",
      "helpdesk dla e-commerce", "system do obsługi zwrotów",
      "program lojalnościowy e-commerce", "odzyskiwanie porzuconych koszyków",
      "system afiliacyjny dla sklepu", "generator opisów produktów AI"
    ], null, "saas"],
    ["Monitoring cen", "monitoring cen", [
      "monitoring cen konkurencji", "repricing", "automatyczna zmiana cen",
      "analiza cen e-commerce"
    ], null, "saas"],
    ["Monitoring marki", "monitoring internetu", [
      "monitoring marki", "monitoring mediów społecznościowych", "social listening",
      "monitoring mediów"
    ], null, "saas"],
    ["CRM i sprzedaż", "system CRM", [
      "polski system CRM", "CRM dla małych firm", "CRM dla e-commerce",
      "oprogramowanie do sprzedaży B2B"
    ], null, "saas"],
    ["Vendorzy SaaS", "oprogramowanie SaaS", [
      "polski SaaS dla e-commerce", "polski SaaS marketingowy", "narzędzia AI dla e-commerce",
      "polski startup AI", "aplikacje dla sklepów Shoper", "aplikacje IdoSell",
      "integracje BaseLinker", "moduły PrestaShop", "wtyczki WooCommerce polska firma",
      "moduły Magento", "startup SaaS Polska"
    ], null, "saas"],
    ["Programy partnerskie SaaS", "program partnerski", [
      "program partnerski dla agencji", "program partnerski dla agencji marketingowych",
      "program partnerski dla software house", "program poleceń dla agencji",
      "zostań partnerem technologicznym", "zostań partnerem e-commerce",
      "partner program agencja SaaS", "program afiliacyjny SaaS"
    ], null, "saas"],
  ],

  // ── PRESETY DLA MAP GOOGLE — inne, i to nie jest kosmetyka ───────────
  //
  // Mapy dopasowują do NAZWY firmy i KATEGORII WIZYTÓWKI, nie do treści strony.
  // Dlatego hasła są krótkie i ogólne: „projektant stron internetowych" zamiast
  // „wdrożenia Framer". Fraza, która świetnie działa w Google, w Mapach zwraca zero,
  // bo żadna wizytówka nie nazywa się „wdrożenia Consent Mode".
  //
  // Czwarty element `true` oznacza kategorię SŁABĄ w Mapach — jest, bo czasem coś
  // znajdzie, ale wiedza o tym, że to kiepskie miejsce do szukania, jest warta tyle
  // samo co sama fraza. Front pokazuje to przy kategorii, zamiast dać userowi
  // odkrywać to metodą pustych wyników.
  //
  // „Programy partnerskie SaaS" NIE MA tu wcale — wizytówka firmy nie mówi o tym,
  // że ma program partnerski. Ta kategoria istnieje tylko w Google/Tavily.
  // ── PRESETY DLA MAP GOOGLE — inne, i to nie jest kosmetyka ───────────
  //
  // Mapy dopasowują do NAZWY firmy i KATEGORII WIZYTÓWKI, nie do treści strony.
  // Dlatego hasła są krótkie i ogólne: „projektant stron internetowych" zamiast
  // „wdrożenia Framer". Fraza, która świetnie działa w Google, w Mapach zwraca zero,
  // bo żadna wizytówka nie nazywa się „wdrożenia Consent Mode".
  //
  // PODZIAŁ NA SEKCJE JEST TU INNY NIŻ PRZY WYSZUKIWARCE. Tam dzielimy na usługi
  // i SaaS, bo to naturalna granica rynku. Tu dzielimy na to, co w Mapach DZIAŁA,
  // i co nie — bo przy wyborze źródła jest to najcenniejsza informacja, jaką mamy.
  // Siedem kategorii jest słabych: wizytówki rzadko opisują się przez marketplace,
  // analitykę czy AI, więc tam trzeba iść do Wyszukiwarki albo Google.
  //
  // Czwarty element  niesie tę samą flagę do stylu chipa i ostrzeżenia
  // w panelu, piąty — przynależność do sekcji.
  //
  // „Programy partnerskie SaaS" NIE MA tu wcale — wizytówka firmy nie mówi o tym,
  // że ma program partnerski. Ta kategoria istnieje tylko w Google/Tavily.
  mapy: [
    ["Strony www", "projektant stron internetowych", [
      "agencja interaktywna", "software house", "firma programistyczna",
      "tworzenie stron internetowych", "strony www", "agencja WordPress"
    ], null, "mocne"],
    ["Sklepy internetowe", "tworzenie sklepów internetowych", [
      "agencja e-commerce", "software house e-commerce", "agencja Shopify",
      "wdrożenia sklepów internetowych", "outsourcing e-commerce"
    ], null, "mocne"],
    ["Agencje digital / full-service", "agencja marketingowa", [
      "agencja marketingu internetowego", "agencja reklamy internetowej",
      "agencja digital marketingu", "marketing internetowy", "agencja marketingowa B2B",
      "agencja marketingu medycznego"
    ], null, "mocne"],
    ["Branding i PR", "agencja brandingowa", [
      "agencja kreatywna", "agencja komunikacji", "studio graficzne", "projektowanie logo",
      "agencja PR", "public relations", "studio UX"
    ], null, "mocne"],
    ["Strategia i doradztwo", "doradztwo marketingowe", [
      "konsulting e-commerce", "doradztwo e-commerce", "konsultant ds. marketingu",
      "doradztwo biznesowe", "firma consultingowa", "agencja strategiczna",
      "szkolenia e-commerce", "szkolenia marketingowe"
    ], null, "mocne"],
    ["Social media", "agencja social media", [
      "marketing w mediach społecznościowych", "agencja influencer marketingu",
      "agencja content marketingowa"
    ], null, "mocne"],
    ["Content produktowy", "fotografia produktowa", [
      "studio fotografii produktowej", "packshot", "studio fotograficzne e-commerce",
      "produkcja wideo reklamowego"
    ], null, "mocne"],
    ["Performance", "agencja reklamowa", [
      "agencja Google Ads", "agencja SEM", "agencja PPC", "reklama internetowa",
      "agencja performance marketingu"
    ], null, "mocne"],
    ["Marketplace", "agencja Allegro", [
      "obsługa Allegro", "agencja marketplace", "agencja Amazon"
    ], true, "slabe"],
    ["Ekspansja zagraniczna", "biuro tłumaczeń", [
      "tłumaczenia stron internetowych", "lokalizacja oprogramowania", "doradztwo eksportowe"
    ], true, "slabe"],
    ["Fulfillment i logistyka", "fulfillment", [
      "magazyn fulfillment", "magazyn e-commerce", "usługi logistyczne dla e-commerce",
      "operator logistyczny", "centrum logistyczne"
    ], null, "mocne"],
    ["Księgowość i podatki", "biuro rachunkowe e-commerce", [
      "księgowość e-commerce", "biuro rachunkowe sklepy internetowe", "doradca podatkowy"
    ], null, "mocne"],
    ["Analityka i CRO", "analityka internetowa", [
      "agencja analityki internetowej", "optymalizacja konwersji", "audyt UX"
    ], true, "slabe"],
    ["AI", "agencja AI", [
      "sztuczna inteligencja dla firm", "wdrożenia AI", "doradztwo AI", "chatboty dla firm"
    ], true, "slabe"],
    ["Automatyzacje", "automatyzacja marketingu", [
      "marketing automation", "agencja e-mail marketingu",
      "automatyzacja procesów biznesowych"
    ], true, "slabe"],
    ["CRM", "wdrożenia CRM", [
      "firma informatyczna", "usługi informatyczne dla firm", "integrator systemów IT"
    ], null, "mocne"],
    ["ERP", "wdrożenia ERP", [
      "systemy ERP dla firm", "oprogramowanie dla firm", "firma informatyczna",
      "integrator systemów IT"
    ], null, "mocne"],
    ["Prawo e-commerce", "kancelaria prawa nowych technologii", [
      "kancelaria e-commerce", "kancelaria prawna IT", "rzecznik patentowy",
      "kancelaria patentowa", "radca prawny e-commerce"
    ], null, "mocne"],
    ["Hosting i infrastruktura", "hosting", [
      "hosting stron internetowych", "administracja serwerami", "centrum danych"
    ], true, "slabe"],
    ["SaaS i vendorzy", "producent oprogramowania", [
      "firma programistyczna", "software house", "oprogramowanie dla e-commerce",
      "oprogramowanie dla firm"
    ], true, "slabe"],
  ],
  klient: [
    ["Handel", "sklep internetowy", [
      "sklep internetowy", "hurtownia", "producent mebli", "producent odzieży",
      "sklep z elektroniką",
    ]],
    ["Usługi lokalne", "firma usługowa", [
      "klinika stomatologiczna", "gabinet medycyny estetycznej", "kancelaria prawna",
      "biuro rachunkowe", "szkoła językowa",
    ]],
    ["B2B i technologie", "firma B2B", [
      "firma produkcyjna", "SaaS", "firma logistyczna", "firma budowlana",
    ]],
    ["Turystyka i HoReCa", "hotel restauracja", [
      "hotel", "restauracja", "biuro podróży",
    ]],
  ],
};

// Która kategoria jest wybrana. null = żadna, widać sam wybór kafli.
// Osiemdziesiąt tagów naraz to ściana, w której nic nie widać.
let otwartaGrupa = null;
// Kategoria wybrana w "Szukaj podobnych". null = wszystkie firmy ścieżki.
let podobneKategoria = null;
// Zrodlo dla "Szukaj podobnych" — osobne od tego w "Szukaj po branzy",
// bo to dwa rozne zadania i user moze chciec innego zrodla w kazdym.
// Frazy od modelu, per firma. Trzymamy na czas sesji, zeby nie pytac modelu
// przy kazdym przerysowaniu formularza — a przerysowuje sie przy kazdym
// zaznaczeniu taga.
const frazyPodobnych = new Map();
// MAPY DOMYSLNIE — inaczej niz w "Szukaj po branzy", i to jest przemyslane.
// Zmierzone na Sellision: wyszukiwarka dala 9 firm, Mapy 30, wspolnych tylko 2.
// Dwadziescia osiem firm, ktorych wyszukiwarka nie znalazla wcale: prestashow.pl,
// welescode.pl, eniverse.pl, dih.pl... To wynika z tego, JAK obie rankinguja:
// wyszukiwarka premiuje tych, ktorzy zainwestowali w SEO, wiec przy branzy
// marketingowej zawsze wraca ta sama czolowka. Mapy rankinguja po wizytowce,
// gdzie SEO nie ma znaczenia — i tam sa wlasnie firmy mniej widoczne, czyli te,
// ktore latwiej pozyskac jako partnera.
// Wartosc startowa jest tymczasowa: `zrodlaDostepne` deklarowane jest NIZEJ, wiec
// odczyt tutaj konczy sie bledem "Cannot access before initialization" i cala
// aplikacja przestaje sie ladowac. Na Mapy przestawia nas odpowiedz /api/zrodla.
let zrodloPodobne = "wyszukiwarka";
// Kategoria wybrana na liscie Firm. null = wszystkie.
let filtrKategorii = null;
// To samo dla kolejki. Osobna zmienna, bo obie listy bywaja otwarte
// naprzemiennie i wspolny stan przenosilby filtr tam, gdzie go nie ustawiono.
let filtrKolejki = null;

// Źródło firm. "wyszukiwarka" = Tavily (kto jest wypozycjonowany),
// "mapy" = Google Maps (kto ma wizytówkę, niezależnie od SEO).
let zrodlo = "wyszukiwarka";
let zrodlaDostepne = { wyszukiwarka: true, mapy: false, google: false };

const ZRODLA = {
  wyszukiwarka: { nazwa: "Wyszukiwarka", ikona: "search",
                  opis: "Znajduje firmy widoczne w Google — czyli te, które już inwestują w SEO." },
  google:       { nazwa: "Google", ikona: "external",
                  opis: "Prawdziwy indeks Google. Widzi inny wycinek sieci niż Wyszukiwarka — na tej samej frazie pokrywają się mniej więcej w jednej trzeciej." },
  mapy:         { nazwa: "Mapy Google", ikona: "pin",
                  opis: "Znajduje każdą firmę z wizytówką, także bez SEO. Opis firmy pojawia się dopiero po researchu." },
};

fetch("/api/zrodla").then((r) => r.json()).then((d) => {
  // `|| zrodlaDostepne` NIE jest ozdobą: odpowiedź z ok:true, ale bez pola `zrodla`
  // ustawiała undefined, renderZrodla wywalało się na odczycie właściwości, a wyjątek
  // połykał .catch poniżej — przełącznik źródeł znikał bez śladu w konsoli.
  // Ten sam błąd mieliśmy już przy kolejce.
  if (d.ok) {
    zrodlaDostepne = d.zrodla || zrodlaDostepne;
    // Dostepnosc zrodel przychodzi PO pierwszym renderze, wiec domyslne zrodlo dla
    // "Szukaj podobnych" ustawiamy dopiero tutaj — inaczej stan zostalby na
    // wyszukiwarce, bo w chwili deklaracji zmiennej o Mapach jeszcze nie wiemy.
    if (zrodlaDostepne.mapy) zrodloPodobne = "mapy";
    renderZrodla();
  }
}).catch(() => {});

function renderZrodla() {
  const box = document.getElementById("zrodla-wyboru");
  if (!box) return;
  // Przy jednym podłączonym źródle przełącznik byłby przyciskiem bez wyboru.
  const podlaczone = Object.keys(ZRODLA).filter((k) => zrodlaDostepne[k]);
  if (podlaczone.length < 2) { box.innerHTML = ""; zrodlo = "wyszukiwarka"; return; }
  // Źródło, które zniknęło z konfiguracji, nie może zostać zaznaczone — inaczej
  // pierwsze kliknięcie „Szukaj" kończy się błędem o brakującym kluczu.
  if (!zrodlaDostepne[zrodlo]) zrodlo = podlaczone[0];
  box.innerHTML = `
    <div class="mono"><i class="sq"></i>Skąd bierzemy firmy</div>
    <div class="tagi wybieralne">${podlaczone.map((k) => [k, ZRODLA[k]]).map(([k, z]) => `
      <button class="tag${zrodlo === k ? " zaznaczony" : ""}" type="button"
              data-zrodlo="${k}" title="${escAttr(z.opis)}">
        <svg class="ico xs"><use href="#i-${z.ikona}"/></svg> ${esc(z.nazwa)}
      </button>`).join("")}</div>
    <p class="hint">${esc(ZRODLA[zrodlo].opis)}</p>`;
}

// Kolejka kandydatow: firmy znalezione, jeszcze niezbadane. Bez niej wyniki
// znikaly razem z zapytaniem — 12 znalezionych, 3 zbadane, 9 przepadalo.
let kolejka = [];
// Zaznaczenia do researchu masowego. Trzymamy URL-e, nie indeksy — lista
// przerysowuje sie po kazdej zbadanej firmie i indeksy przestalyby pasowac.
const kolejkaZaznaczone = new Set();

async function wczytajKolejke() {
  try {
    const d = await (await fetch("/api/kolejka")).json();
    kolejka = (d.ok && d.kolejka) || [];
  } catch { kolejka = []; }
  odswiezBadge("badge-kolejka", kolejkaTrybu().length);
}
function kolejkaTrybu() {
  return kolejka.filter((k) => (k.tryb || "partner") === tryb);
}
wczytajKolejke();
wczytajMaile();

async function dodajDoKolejki(firmy, zapytanie, zrodloNazwa, kategoria) {
  const res = await fetch("/api/kolejka", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ firmy, tryb, zapytanie, zrodlo: zrodloNazwa,
                           kategoria: kategoria || "" }),
  });
  const d = await res.json();
  await wczytajKolejke();
  return d.doszlo || 0;
}

async function usunZKolejki(url) {
  await fetch("/api/kolejka", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  await wczytajKolejke();
  renderKolejke();
}

function renderKolejke() {
  const box = document.getElementById("kolejka-box");
  if (!box) return;
  const moje = kolejkaTrybu();
  if (!moje.length) {
    box.innerHTML = `<div class="pusto">
      <svg class="ico xl"><use href="#i-inbox"/></svg>
      <p>Kolejka jest pusta.<br><span>Po wyszukaniu firm użyj przycisku
        <b>Dodaj do kolejki</b> — zostaną tu, dopóki ich nie zbadasz.</span></p></div>`;
    return;
  }
  // Filtr kategorii — ten sam mechanizm co na liście Firm i w „Szukaj podobnych".
  // Kolejka rośnie szybciej niż lista zbadanych: jedno kliknięcie „Dodaj wszystkie"
  // wrzuca kilkadziesiąt firm, a import z katalogu potrafi wrzucić kilkaset.
  // Kategoria jest tu tą, POD KTÓRĄ firmę znaleziono — research nadaje własną.
  const kat = (k) => k.kategoria || "Bez kategorii";
  const liczby = new Map();
  moje.forEach((k) => liczby.set(kat(k), (liczby.get(kat(k)) || 0) + 1));
  const widoczne = filtrKolejki ? moje.filter((k) => kat(k) === filtrKolejki) : moje;

  const filtrKat = liczby.size <= 1 ? "" : `
    <div class="filtr-kategorii tagi wybieralne">
      <button class="tag${filtrKolejki ? "" : " zaznaczony"}" type="button"
              data-kat-kolejka="">Wszystkie <em class="chip-licznik">${moje.length}</em></button>
      ${[...liczby.entries()].map(([nazwa, ile]) => `
        <button class="tag${filtrKolejki === nazwa ? " zaznaczony" : ""}" type="button"
                data-kat-kolejka="${escAttr(nazwa)}">
          ${esc(nazwa)} <em class="chip-licznik">${ile}</em>
        </button>`).join("")}
    </div>`;

  // Zaznaczenie liczymy z WIDOCZNYCH, nie z całej kolejki. Inaczej „Zaznacz
  // wszystkie" przy włączonym filtrze zaznaczałoby też firmy spoza niego —
  // i „Zbadaj zaznaczone (40)" ruszyłoby research na czymś, czego nie widać.
  const zazn = widoczne.filter((k) => kolejkaZaznaczone.has(k.url)).length;
  box.innerHTML = przelacznikTrybu(kolejka) + `<div class="card">
    <div class="mono"><span class="sq"></span> Czeka na research (${moje.length})</div>
    ${filtrKat}
    <div class="masowy-pasek">
      <label class="zazn-wszystkie">
        <input type="checkbox" id="zazn-wszystkie" ${zazn === widoczne.length && widoczne.length ? "checked" : ""}>
        <span>Zaznacz wszystkie</span>
      </label>
      <button class="akcja glowna zbadaj-zaznaczone" type="button" ${zazn ? "" : "disabled"}>
        <svg class="ico sm"><use href="#i-layers"/></svg>Zbadaj zaznaczone${zazn ? ` (${zazn})` : ""}
      </button>
      <span class="hint">Po trzy naraz. Awaria jednej firmy nie zatrzymuje reszty.</span>
    </div>
    <div id="masowy-postep"></div>
    <div class="similar-list">${widoczne.map((k) => `
      <div class="sim-row" data-url="${escAttr(k.url)}">
        <label class="zazn-firme">
          <input type="checkbox" class="zazn-kolejka" ${kolejkaZaznaczone.has(k.url) ? "checked" : ""}>
        </label>
        <div class="sim-info">
          <span class="sim-name">${esc(k.nazwa || hostname(k.url))}${
            k.kategoria ? `<span class="tag-kat">${esc(k.kategoria)}</span>` : ""}${
            k.ma_seo ? `<span class="tag-seo">SEO</span>` : ""}</span>
          <a class="sim-url" href="${escAttr(k.url)}" target="_blank" rel="noopener">${esc(hostname(k.url))}<svg class="ico xs"><use href="#i-external"/></svg></a>
          ${k.opis ? `<span class="sim-opis">${esc(k.opis.slice(0, 150))}${k.opis.length > 150 ? "…" : ""}</span>` : ""}
          <span class="kolejka-meta">${esc(k.zrodlo || "—")}${
            k.zapytanie ? ` · „${esc(k.zapytanie)}"` : ""} · ${esc((k.dodana || "").slice(0, 10))}</span>
        </div>
        <button class="researchuj" type="button">Researchuj<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        <button class="usun-z-kolejki" type="button" title="Usuń z kolejki">
          <svg class="ico xs"><use href="#i-x"/></svg></button>
      </div>`).join("")}</div>
  </div>`;
}

// Który zestaw presetów obowiązuje. Mapy mają własny, bo szukają po nazwach
// wizytówek, a nie po treści stron — te same frazy dają tam zero wyników.
// Ścieżka klientów ma swój niezależnie od źródła.
function presetyDlaZrodla() {
  if (tryb !== "partner") return PRESETY[tryb] || PRESETY.partner;
  return zrodlo === "mapy" ? PRESETY.mapy : PRESETY.partner;
}

// Z jakiej kategorii pochodzi ta fraza. Potrzebne kolejce: firma znaleziona,
// a jeszcze niezbadana, nie ma własnej kategorii — nadaje ją dopiero research.
// Do tego czasu jedyne, co o niej wiadomo, to CZEGO szukaliśmy, gdy się pojawiła.
//
// Czytamy z presetów zamiast pamiętać ostatnie kliknięcie, bo fraza w polu może
// przyjść trzema drogami: z chipu kategorii, z chipu podkategorii i z klawiatury.
// Zapamiętane kliknięcie kłamałoby w trzecim przypadku i po edycji frazy.
function kategoriaDlaFrazy(fraza) {
  const szukana = (fraza || "").trim().toLowerCase();
  if (!szukana) return "";
  for (const [nazwa, glowna, pod] of presetyDlaZrodla()) {
    if (glowna.toLowerCase() === szukana) return nazwa;
    if ((pod || []).some((x) => x.toLowerCase() === szukana)) return nazwa;
  }
  return "";
}

function renderPresety() {
  const grupy = presetyDlaZrodla();
  const wybrana = otwartaGrupa !== null ? grupy[otwartaGrupa] : null;

  // Chipy, nie kafle — ten sam wygląd, co filtr kategorii w „Szukaj podobnych".
  // Kafle zajmowały pół ekranu, zanim cokolwiek wybrałeś; tu wybór jest jednym
  // rzędem, a miejsce zostaje na to, po co się tu przyszło.
  // ── Kategorie, w dwóch nazwanych sekcjach ──
  // Jeden rząd 29 chipów to ściana. Granica „usługi kontra oprogramowanie" jest
  // naturalna i skraca skanowanie o połowę. Mapy nie mają sekcji — tam wszystko
  // ląduje w jednej grupie i to jest w porządku, bo jest ich 17.
  const chip = ([grupa, , pozycje, slabe], i) => `
    <button class="tag${otwartaGrupa === i ? " zaznaczony" : ""}${slabe ? " tag-slaby" : ""}"
            type="button" data-grupa="${i}" aria-pressed="${otwartaGrupa === i}"
            ${slabe ? 'title="W Mapach ta kategoria daje mało wyników — lepiej szukać przez Wyszukiwarkę albo Google"' : ""}>
      ${esc(grupa)} <em class="chip-licznik">${pozycje.length}</em>
    </button>`;

  // Sekcje są inne dla każdego źródła, bo co innego jest w nich warte pokazania.
  // Przy wyszukiwarce granica przebiega między firmami usługowymi a producentami
  // oprogramowania. Przy Mapach ważniejsze jest, czy kategoria w ogóle tam działa —
  // to oszczędza klikanie w rzeczy, które i tak zwrócą garść wyników.
  const sekcje = zrodlo === "mapy"
    ? [["mocne", "Dobrze działają w Mapach"],
       ["slabe", "Słabe w Mapach — lepiej przez Wyszukiwarkę lub Google"]]
    : [["uslugi", "Usługi i agencje"], ["saas", "SaaS i narzędzia"]];
  const zSekcjami = grupy.some((g) => g[4]);
  const kafle = (!zSekcjami
    ? `<div class="tagi wybieralne">${grupy.map(chip).join("")}</div>`
    : sekcje.map(([klucz, etykieta]) => {
        const wybrane = grupy.map((g, i) => [g, i]).filter(([g]) => g[4] === klucz);
        if (!wybrane.length) return "";
        return `<div class="preset-sekcja">
          <span class="mono preset-sekcja-tytul">${esc(etykieta)}</span>
          <div class="tagi wybieralne">${wybrane.map(([g, i]) => chip(g, i)).join("")}</div>
        </div>`;
      }).join(""));

  const panel = !wybrana ? "" : (() => {
    const [grupa, fraza, pozycje, slabe] = wybrana;
    return `
      <div class="preset-panel">
        <div class="preset-panel-head">
          <span class="mono">${esc(grupa)}</span>
          <button class="btn-lekki" type="button" data-grupa="${otwartaGrupa}">
            <svg class="ico xs"><use href="#i-x"/></svg>Zwiń</button>
        </div>
        ${slabe ? `<p class="ostrzezenie-inline">W Mapach ta kategoria daje mało wyników —
          wizytówki rzadko opisują się w ten sposób. Po takie firmy lepiej sięgnąć
          przez <b>Wyszukiwarkę</b> albo <b>Google</b>.</p>` : ""}
        <button class="tag tag-glowny" data-preset="${escAttr(fraza)}" type="button"
                title="Szuka szeroko w całej kategorii, zamiast jednej usługi">
          <svg class="ico xs"><use href="#i-target"/></svg>Cała kategoria: ${esc(fraza)}
        </button>
        <div class="tagi wybieralne">${pozycje.map((p) =>
          `<button class="tag" data-preset="${escAttr(p)}" type="button">${esc(p)}</button>`
        ).join("")}</div>
      </div>`;
  })();

  // Całość w karcie z nagłówkiem — tak samo jak „1. Wybierz firmę wzorcową"
  // w „Szukaj podobnych". Chipy bez ramki wisiały luzem pod polem wyszukiwania
  // i nie było widać, że są jednym narzędziem wyboru.
  document.getElementById("presety-branz").innerHTML = `
    <div class="card">
      <div class="mono"><span class="sq"></span> Wybierz kategorię partnera</div>
      ${kafle}${panel}
    </div>`;
}
renderPresety();

formKryteria.addEventListener("submit", async (e) => {
  e.preventDefault();
  const branza = document.getElementById("branza").value.trim();
  const miasto = document.getElementById("miasto").value.trim();
  if (!branza) return;
  // Bez miasta: „Poznań" nie jest częścią kategorii, a zapytanie z backendu
  // przychodzi już sklejone i nie dałoby się go dopasować do presetu.
  kategoriaZapytania = kategoriaDlaFrazy(branza);

  szukajWynik.innerHTML = loadingHTML("Szukam firm i sprawdzam, które strony żyją… ~10 s.");
  btnKryteria.disabled = true;
  try {
    const res = await fetch("/api/szukaj", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branza, miasto, tryb, zrodlo }),
    });
    const data = await res.json();
    szukajWynik.innerHTML = data.ok ? listaFirmHTML(data, "Znalezione firmy") : errorHTML(data.error);
  } catch (err) {
    szukajWynik.innerHTML = errorHTML(err.message);
  } finally {
    btnKryteria.disabled = false;
  }
});

// ══ SEKCJA: Firmy — lista, a po kliknięciu szczegóły ══
function otworzFirme(firma) {
  let wpis = tabs.find((t) => t.firma.url === firma.url);
  if (!wpis) {
    const id = "tab" + ++tabSeq;
    wpis = { id, nazwa: hostname(firma.url), firma, tryb: firma.tryb || tryb };
    tabs.push(wpis);
    odswiezBadge("badge-firmy", firmyTrybu().length);
    renderResearchPanel();
  }
  pokazSekcje("firmy");
  pokazDetal(wpis.id);
}

// widok listy
function pokazListe() {
  activeId = null;
  document.getElementById("firmy-detal").hidden = true;
  document.getElementById("firmy-lista").hidden = false;
  document.getElementById("firmy-pusto").hidden = firmyTrybu().length > 0 || !!filtrFirm;
  document.getElementById("firmy-head").hidden = false;
  renderListeFirm();
}

// Widok jednej firmy. KARTA JEST RENDEROWANA OD NOWA, a nie chowana i pokazywana
// jak wcześniej: narzędzia w zakładkach piszą po stałych identyfikatorach
// (`rozmowa-box`, `audytgeo-raport`…), więc dwie karty naraz w DOM-ie biłyby się
// o te same id. Jedna karta na ekranie to jedna karta w drzewie.
function pokazDetal(id) {
  activeId = id;
  document.getElementById("firmy-lista").hidden = true;
  document.getElementById("firmy-pusto").hidden = true;
  document.getElementById("firmy-head").hidden = true;
  document.getElementById("firmy-detal").hidden = false;
  renderKarte();
  window.scrollTo(0, 0);
}

// Wszystkie sekcje „Pracy" pokazują wyłącznie firmy z aktywnej ścieżki.
// Bez tego audyt partnera i audyt klienta lądowałyby na jednej liście, a to
// dwa różne procesy sprzedażowe.
function firmyTrybu() {
  return tabs.filter((t) => (t.tryb || "partner") === tryb);
}

// Stan koszyka trzymamy też w bazie — inaczej po odświeżeniu firmy wracały,
// ale zaznaczenia do eksportu już nie.
function zapiszKoszyk(url, w_koszyku) {
  fetch("/api/koszyk", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, w_koszyku }),
  }).catch(() => {});
}

function przelacznikTrybu(liczOd = tabs) {
  // Przy jednej ścieżce przełącznik byłby przyciskiem, który nic nie zmienia.
  if (!POKAZUJ_KLIENTOW) return "";
  return `<div class="przelacznik-tryb" role="tablist">
    ${Object.entries(TRYBY).map(([k, t]) => `
      <button class="tryb-btn ${tryb === k ? "aktywny" : ""}" data-ustaw-tryb="${k}"
        type="button" role="tab" aria-selected="${tryb === k}">${t.nazwa}
        <em>${liczOd.filter((x) => (x.tryb || "partner") === k).length}</em></button>`).join("")}
  </div>`;
}

function renderListeFirm() {
  const wszystkie = firmyTrybu();
  const poFladze = filtrFirm === "ma_seo" ? wszystkie.filter((t) => t.firma.ma_seo) : wszystkie;
  // Szukamy po nazwie, adresie i branży — czyli po tym, co widać w wierszu.
  // Szukanie po polach, których na liście nie ma, dawałoby wyniki bez wytłumaczenia.
  const fraza = szukajFirm.trim().toLowerCase();
  const lista = !fraza ? poFladze : poFladze.filter((t) => {
    const f = t.firma;
    return [f.nazwa, f.url, f.branza, f.kategoria, f.miasto]
      .some((x) => (x || "").toLowerCase().includes(fraza));
  });

  const narzedzia = document.getElementById("firmy-filtry");
  if (narzedzia && narzedzia.dataset.gotowe !== "1") {
    narzedzia.dataset.gotowe = "1";
    narzedzia.innerHTML = `<div class="lista-narzedzia">
      <input type="search" id="szukaj-firm" placeholder="Szukaj po nazwie, adresie, branży…"
             autocomplete="off" value="${escAttr(szukajFirm)}">
      <span class="mono" id="szukaj-licznik"></span>
    </div>`;
  }
  const licznik = document.getElementById("szukaj-licznik");
  if (licznik) licznik.textContent = fraza
    ? `${lista.length} z ${poFladze.length}`
    : `${wszystkie.length} ${wszystkie.length === 1 ? "firma" : "firm"}`;

  if (fraza && !lista.length) {
    document.getElementById("firmy-lista").innerHTML =
      `<div class="pusto"><p>Nic nie pasuje do „${esc(szukajFirm)}".</p></div>`;
    return;
  }

  // Filtr musi być WIDOCZNY i odwracalny jednym kliknięciem. Skrócona lista bez
  // wyjaśnienia wygląda jak zgubione firmy.
  const znacznik = filtrFirm === "ma_seo" ? `
    <div class="filtr-info">
      <span class="mono">Pokazuję ${lista.length} z ${wszystkie.length} — tylko z SEO w ofercie</span>
      <button class="btn-lekki" type="button" data-zdejmij-filtr>
        <svg class="ico xs"><use href="#i-x"/></svg>Pokaż wszystkie</button>
    </div>` : "";

  if (filtrFirm && !lista.length) {
    document.getElementById("firmy-lista").innerHTML = przelacznikTrybu() + znacznik +
      `<div class="pusto"><p>Żadna firma w tej ścieżce nie ma SEO w ofercie.</p></div>`;
    return;
  }

  // Filtr kategorii — ten sam mechanizm co w „Szukaj podobnych". Przy dziesięciu
  // firmach lista jeszcze się skanuje, przy pięćdziesięciu już nie.
  const kat = (t) => t.firma.kategoria && t.firma.kategoria !== BRAK
    ? t.firma.kategoria : "Bez kategorii";
  const liczby = new Map();
  lista.forEach((t) => liczby.set(kat(t), (liczby.get(kat(t)) || 0) + 1));
  const widoczne = filtrKategorii ? lista.filter((t) => kat(t) === filtrKategorii) : lista;

  const filtrKat = liczby.size <= 1 ? "" : `
    <div class="filtr-kategorii tagi wybieralne">
      <button class="tag${filtrKategorii ? "" : " zaznaczony"}" type="button"
              data-kat-firmy="">Wszystkie <em class="chip-licznik">${lista.length}</em></button>
      ${[...liczby.entries()].map(([nazwa, ile]) => `
        <button class="tag${filtrKategorii === nazwa ? " zaznaczony" : ""}" type="button"
                data-kat-firmy="${escAttr(nazwa)}">
          ${esc(nazwa)} <em class="chip-licznik">${ile}</em>
        </button>`).join("")}
    </div>`;

  document.getElementById("firmy-lista").innerHTML = przelacznikTrybu() + znacznik + filtrKat + widoczne.map((t) => {
    const f = t.firma;
    const wKoszyku = koszyk.some((k) => k.url === f.url);
    return `<div class="firma-row" data-id="${t.id}">
      <div class="firma-row-info">
        <div class="firma-row-top">
          <span class="firma-row-nazwa">${esc(f.nazwa)}</span>
          ${f.kategoria && f.kategoria !== BRAK
            ? `<span class="tag-kat">${esc(f.kategoria)}</span>` : ""}
          ${f.ma_seo
            ? `<span class="flaga mini ma-seo"><svg class="ico xs"><use href="#i-search"/></svg>Ma SEO</span>`
            : `<span class="flaga mini bez-seo">Bez SEO</span>`}
          ${wKoszyku ? `<span class="flaga mini w-eksporcie"><svg class="ico xs"><use href="#i-table"/></svg>W eksporcie</span>` : ""}
        </div>
        <span class="firma-row-meta">${esc(hostname(f.url))} · ${esc(f.branza)}</span>
      </div>
      <div class="firma-row-akcje">
        <button class="otworz" type="button">Otwórz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        <button class="usun" type="button" data-usun="${t.id}" title="Usuń z listy"><svg class="ico xs"><use href="#i-x"/></svg></button>
      </div>
    </div>`;
  }).join("");
}

function usunFirme(id) {
  // usuwamy też z bazy — inaczej firma wracałaby po odświeżeniu strony
  const wpis = tabs.find((t) => t.id === id);
  if (wpis) {
    fetch("/api/firmy/usun", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: wpis.firma.url }),
    }).catch(() => {});
    koszyk = koszyk.filter((k) => k.url !== wpis.firma.url);
  }
  tabs = tabs.filter((t) => t.id !== id);

  odswiezBadge("badge-firmy", firmyTrybu().length);
  renderResearchPanel();
  pokazListe();
}

function pole(etykieta, wartosc) {
  const brak = !wartosc || wartosc === BRAK;
  return `<div class="pole">
    <span class="pole-etykieta">${esc(etykieta)}</span>
    <span class="pole-wartosc ${brak ? "brak" : ""}">${esc(wartosc || BRAK)}</span>
  </div>`;
}


// ══ Kliknięcia (delegacja na całym dokumencie) ══
document.addEventListener("click", (e) => {
  // Przełącznik ścieżki Partnerzy/Klienci. Był w nasłuchu "change", a <button>
  // NIGDY nie wywołuje tego zdarzenia — zakładki nie działały od początku,
  // w żadnej sekcji. Ścieżkę dało się zmienić tylko z menu bocznego.
  const btnTryb = e.target.closest("[data-ustaw-tryb]");
  if (btnTryb) {
    tryb = btnTryb.dataset.ustawTryb;
    filtrFirm = null;        // filtry liczone były dla poprzedniej ścieżki
    filtrKategorii = null;
    podobneKategoria = null;
    const sekcja = document.querySelector(".sekcja.aktywna")?.dataset.sekcja;
    return pokazSekcje(sekcja || "firmy");
  }
  const usun = e.target.closest("[data-usun]");
  if (usun) { e.stopPropagation(); return usunFirme(usun.dataset.usun); }

  // Kafle statystyk prowadzą tam, gdzie te firmy naprawdę są.
  const kaf = e.target.closest("[data-kafel]");
  if (kaf) {
    const cel = kaf.dataset.kafel;
    if (cel === "eksport") { filtrFirm = null; return pokazSekcje("eksport"); }
    // „z SEO w ofercie" nie ma własnej sekcji — otwiera listę firm zawężoną
    // do tych z SEO, z widocznym znacznikiem i możliwością zdjęcia filtra.
    filtrFirm = cel === "seo" ? "ma_seo" : null;
    return pokazSekcje("firmy");
  }
  // Zakładki pozyskiwania i karty firmy — jeden mechanizm, dwa miejsca.
  const zakPoz = e.target.closest("#poz-zakladki .zakladka");
  if (zakPoz) { pozZakladka = zakPoz.dataset.poz; return renderPozyskiwanie(); }

  const zakKarty = e.target.closest("[data-karta-tab]");
  if (zakKarty) {
    kartaZakladka = zakKarty.dataset.kartaTab;
    document.querySelectorAll("[data-karta-tab]").forEach((b) =>
      b.classList.toggle("aktywna", b.dataset.kartaTab === kartaZakladka));
    return renderKartaPane();
  }

  if (e.target.closest(".wroc-do-listy")) return pokazListe();

  const wiecej = e.target.closest(".prz-wiecej");
  if (wiecej) {
    const reszta = wiecej.previousElementSibling;
    const schowane = reszta.hidden;
    reszta.hidden = !schowane;
    wiecej.innerHTML = schowane ? "Zwiń listę" : wiecej.dataset.etykieta;
    return;
  }

  // „Znajdź podobne" z karty: firma jest już wybrana, więc narzędzie nie ma
  // o co pytać — przenosimy ją razem z przejściem do pozyskiwania.
  if (e.target.closest(".podobne-do-tej")) {
    podobneWybrana = activeId;
    podobneTagi = new Set();
    resetPodobnychWynikow();
    pozZakladka = "podobne";
    pokazSekcje("pozyskiwanie");
    return renderPozyskiwanie();
  }

  const zAudytu = e.target.closest(".otworz-firme-z-audytu");
  if (zAudytu) { pokazSekcje("firmy"); return pokazDetal(zAudytu.dataset.id); }

  const zMaili = e.target.closest(".otworz-maile-firmy");
  if (zMaili) {
    kartaZakladka = "maile";
    pokazSekcje("firmy");
    return pokazDetal(zMaili.dataset.id);
  }

  if (e.target.closest("[data-zdejmij-filtr]")) { filtrFirm = null; return renderListeFirm(); }
  const wiersz = e.target.closest(".firma-row");
  if (wiersz) { pokazSekcje("firmy"); return pokazDetal(wiersz.dataset.id); }
  if (e.target.classList.contains("wroc")) return pokazListe();

  const katFirmy = e.target.closest("[data-kat-firmy]");
  if (katFirmy) {
    filtrKategorii = katFirmy.dataset.katFirmy || null;
    return renderListeFirm();
  }
  const katKolejki = e.target.closest("[data-kat-kolejka]");
  if (katKolejki) {
    filtrKolejki = katKolejki.dataset.katKolejka || null;
    return renderKolejke();
  }
  const katPodobne = e.target.closest("[data-kat-podobne]");
  if (katPodobne) {
    podobneKategoria = katPodobne.dataset.katPodobne || null;
    return renderPodobne();
  }
  const wzor = e.target.closest(".wybierz-wzor");
  if (wzor) { podobneWybrana = wzor.dataset.id; podobneTagi.clear(); resetPodobnychWynikow(); return renderPodobne(); }
  if (e.target.classList.contains("zmien-wzor")) {
    podobneWybrana = null; podobneTagi.clear();
    document.getElementById("podobne-wynik").innerHTML = "";
    return renderPodobne();
  }
  // ZAWĘŻONE DO KONTENERA PRZEŁĄCZNIKA, i to nie jest ozdobnik. Przycisk „Dodaj
  // wszystkie do kolejki" nosił `data-zrodlo` (żeby zapamiętać, skąd wyniki) —
  // a ten warunek stoi WYŻEJ w łańcuchu, więc przechwytywał jego kliknięcie,
  // przestawiał źródło wyszukiwania i przerysowywał presety. Do kolejki nigdy
  // nic nie doszło i nic o tym nie mówiło: przycisk wyglądał na klikalny,
  // sekcja „Do zbadania" była pusta. Sam atrybut też zmieniłem na
  // `data-kolejka-zrodlo` — dwie niezależne rzeczy nie mogą się nazywać tak samo.
  const btnZrodlo = e.target.closest("#zrodla-wyboru [data-zrodlo]");
  if (btnZrodlo) {
    zrodlo = btnZrodlo.dataset.zrodlo;
    // Indeksy grup różnią się między zestawami (26 vs 17), więc otwarta grupa
    // po przełączeniu wskazywałaby na zupełnie inną kategorię.
    otwartaGrupa = null;
    renderZrodla();
    return renderPresety();
  }
  const preset = e.target.closest("[data-preset]");
  if (preset) {
    document.getElementById("branza").value = preset.dataset.preset;
    return document.getElementById("miasto").focus();
  }
  // Rozwinięcie kategorii. Jedna naraz — dwie otwarte i znowu robi się ściana.
  const naglowekGrupy = e.target.closest("[data-grupa]");
  if (naglowekGrupy) {
    const i = Number(naglowekGrupy.dataset.grupa);
    otwartaGrupa = otwartaGrupa === i ? null : i;
    return renderPresety();
  }
  const tag = e.target.closest("[data-tag]");
  if (tag) {
    const t = tag.dataset.tag;
    podobneTagi.has(t) ? podobneTagi.delete(t) : podobneTagi.add(t);
    return renderPodobne();
  }
  if (e.target.classList.contains("szukaj-wg-tagow")) return szukajWgTagow(e.target);
  const zrobDok = e.target.closest(".zrob-dokument-audyt");
  if (zrobDok) return zrobDokumentZAudytu(zrobDok);
  if (e.target.closest(".pobierz-dokument-audyt")) return plikDokumentuAudytu(true);
  if (e.target.closest(".podglad-dokument-audyt")) return plikDokumentuAudytu(false);
  const wybDok = e.target.closest(".wybierz-dok");
  if (wybDok) { dokWybrana = wybDok.dataset.id; return renderDokument(); }
  if (e.target.classList.contains("zmien-dok")) {
    dokWybrana = null; dokHtml = null;
    document.getElementById("dokument-wynik").innerHTML = "";
    return renderDokument();
  }
  const katDok = e.target.closest("[data-dok-klient]");
  if (katDok) { dokKlient = katDok.dataset.dokKlient; return renderDokument(); }
  const genDok = e.target.closest(".generuj-dokument");
  if (genDok) return generujDokument(genDok);
  if (e.target.closest(".pobierz-dokument")) return plikDokumentu(true);
  if (e.target.closest(".podglad-dokument")) return plikDokumentu(false);
  const doKolejki = e.target.closest(".do-kolejki-wszystkie");
  if (doKolejki) return dodajWszystkieDoKolejki(doKolejki);
  const usunK = e.target.closest(".usun-z-kolejki");
  if (usunK) { e.stopPropagation(); return usunZKolejki(usunK.closest(".sim-row").dataset.url); }
  const czatB = e.target.closest(".czat-wyslij");
  if (czatB) return czatZapytaj(czatB);
  const zrPod = e.target.closest("[data-zrodlo-podobne]");
  if (zrPod) { zrodloPodobne = zrPod.dataset.zrodloPodobne; return renderPodobne(); }
  const zbZazn = e.target.closest(".zbadaj-zaznaczone");
  if (zbZazn) return zbadajZaznaczone(zbZazn);
  if (e.target.id === "zazn-wszystkie") {
    // Tylko WIDOCZNE. Przy włączonym filtrze kategorii zaznaczenie całej kolejki
    // wysłałoby do researchu firmy, których user nie ma na ekranie — a research
    // kosztuje i jest nieodwracalny.
    const moje = kolejkaTrybu()
      .filter((k) => !filtrKolejki || (k.kategoria || "Bez kategorii") === filtrKolejki);
    if (e.target.checked) moje.forEach((k) => kolejkaZaznaczone.add(k.url));
    else moje.forEach((k) => kolejkaZaznaczone.delete(k.url));
    return renderKolejke();
  }
  if (e.target.classList.contains("zazn-kolejka")) {
    const u = e.target.closest(".sim-row").dataset.url;
    kolejkaZaznaczone.has(u) ? kolejkaZaznaczone.delete(u) : kolejkaZaznaczone.add(u);
    return renderKolejke();
  }
  const wybMail = e.target.closest(".wybierz-mail");
  if (wybMail) { maileWybrana = wybMail.dataset.id; maileAktywny = null; return renderMaile(); }
  if (e.target.closest(".zmien-mail-firme")) { maileWybrana = null; maileAktywny = null; return renderMaile(); }
  const genW = e.target.closest(".generuj-warianty");
  if (genW) return generujWarianty(genW);
  const popr = e.target.closest(".popraw-mail");
  if (popr) {
    const id = Number(popr.closest(".mail-draft").dataset.mailId);
    maileAktywny = maileAktywny === id ? null : id;
    return renderMaile();
  }
  const wysl = e.target.closest(".wyslij-poprawke");
  if (wysl) return wyslijPoprawke(wysl);
  const oznW = e.target.closest(".oznacz-wyslany");
  if (oznW) {
    const d = oznW.closest(".mail-draft");
    const m = maileLista.find((x) => x.id === Number(d.dataset.mailId));
    return zmienStanMaila(Number(d.dataset.mailId), "PATCH", { wyslany: !(m && m.wyslany) });
  }
  const usM = e.target.closest(".usun-mail");
  if (usM) { e.stopPropagation(); return zmienStanMaila(Number(usM.closest(".mail-draft").dataset.mailId), "DELETE", {}); }
  const dalej = e.target.closest(".szukaj-dalej");
  if (dalej) return szukajWgTagow(dalej, true);

  const wg = e.target.closest(".wybierz-geo");
  if (wg) {
    geoWybrana = wg.dataset.id;
    document.getElementById("audytgeo-raport").innerHTML = "";
    return renderAudytGeo();
  }
  if (e.target.closest(".zmien-geo")) {
    geoWybrana = null;
    document.getElementById("audytgeo-raport").innerHTML = "";
    return renderAudytGeo();
  }
  const genGeo = e.target.closest(".generuj-geo");
  if (genGeo) return generujAudytGeo(genGeo);

  const wr = e.target.closest(".wybierz-rozmowe");
  if (wr) { rozmowaWybrana = wr.dataset.id; return renderRozmowa(); }
  if (e.target.closest(".zmien-rozmowe-firme")) { rozmowaWybrana = null; return renderRozmowa(); }

  const wa = e.target.closest(".wybierz-audyt");
  if (wa) { audytWybrana = wa.dataset.id; document.getElementById("audyt-raport").innerHTML = ""; return renderAudyt(); }
  if (e.target.classList.contains("zmien-audyt")) {
    audytWybrana = null; document.getElementById("audyt-raport").innerHTML = ""; return renderAudyt();
  }
  if (e.target.classList.contains("generuj-audyt")) return generujAudyt(e.target);
  if (e.target.classList.contains("drukuj")) return window.print();
  if (e.target.classList.contains("mail")) return generujMaile(e.target);
  if (e.target.classList.contains("researchuj")) return researchujZListy(e.target);
  if (e.target.classList.contains("kopiuj")) return kopiuj(e.target);
  if (e.target.classList.contains("pobierz-csv")) return pobierzCSV();
});

// Szukanie filtruje PRZY PISANIU, nie po opuszczeniu pola. Reszta formularzy
// siedzi w "change", bo tam liczy się wybór, a nie każdy znak — przy liście
// filtrowanej dopiero po blurze człowiek nie wie, czy pole w ogóle działa.
document.addEventListener("input", (e) => {
  if (e.target.id === "szukaj-firm") { szukajFirm = e.target.value; renderListeFirm(); }
});

document.addEventListener("change", (e) => {
  if (e.target.id === "audyt-aio") { audytAIO = e.target.checked; return renderAudyt(); }
  if (e.target.id === "audyt-seo") { audytSEO = e.target.checked; return renderAudyt(); }
  if (e.target.id === "audyt-ile") { audytIle = +e.target.value; return renderAudyt(); }
  if (e.target.name === "geo-silnik") {
    const v = e.target.value;
    geoSilniki = e.target.checked
      ? [...geoSilniki, v] : geoSilniki.filter((x) => x !== v);
    return renderAudytGeo();
  }
  if (e.target.id === "dok-klient") {
    dokKlient = e.target.value;
    const b = document.querySelector(".generuj-dokument");
    if (b) b.disabled = !dokKlient.trim();
    return;
  }
  if (e.target.id === "dok-klient-url") { dokKlientUrl = e.target.value; return; }
  if (e.target.id === "geo-ile") { geoIle = +e.target.value; return renderAudytGeo(); }
  if (e.target.id === "geo-powtorzenia") { geoPowtorzenia = +e.target.value; return renderAudytGeo(); }
  if (e.target.id === "geo-podpowiedzi") { geoPodpowiedzi = e.target.checked; return renderAudytGeo(); }
  if (e.target.name === "platforma") {
    const v = e.target.value;
    audytPlatformy = e.target.checked
      ? [...audytPlatformy, v] : audytPlatformy.filter((x) => x !== v);
    if (!audytPlatformy.length) audytPlatformy = [v];
    return renderAudyt();
  }
  if (e.target.name === "silnik") {
    const v = e.target.value;
    audytSilniki = e.target.checked ? [...audytSilniki, v] : audytSilniki.filter((x) => x !== v);
    if (!audytSilniki.length) audytSilniki = [v];   // zawsze co najmniej jeden
    return renderAudyt();
  }
  if (!e.target.classList.contains("do-eksportu")) return;
  const firma = firmaZPanelu(e.target.closest(".panel"));
  if (e.target.checked) {
    zapiszKoszyk(firma.url, true);
    if (!koszyk.some((k) => k.url === firma.url)) {
      // ścieżka bierze się z wpisu firmy, nie z aktualnie oglądanej zakładki —
      // firma zbadana jako klient ma trafić do eksportu klientów, nawet gdy
      // dodajemy ją będąc w widoku partnerów
      const w = tabs.find((t) => t.firma.url === firma.url);
      koszyk.push({ ...firma, tryb: (w && w.tryb) || firma.tryb || tryb });
    }
  } else {
    zapiszKoszyk(firma.url, false);
    koszyk = koszyk.filter((k) => k.url !== firma.url);
  }
  odswiezBadge("badge-eksport", koszyk.filter((f) => (f.tryb || "partner") === tryb).length);
  renderEksport();
  renderListeFirm(); // odśwież znacznik „w eksporcie" na liście
  renderResearchPanel();
});

function firmaZPanelu(panel) {
  return tabs.find((t) => t.id === panel.dataset.id)?.firma || {};
}

// ══ SEKCJA: Szukaj podobnych (wybór firmy → wybór tagów → szukanie) ══
let podobneWybrana = null;   // id wybranej firmy
let podobneTagi = new Set(); // zaznaczone usługi

function renderPodobne() {
  const wybor = document.getElementById("podobne-wybor");
  const tagiBox = document.getElementById("podobne-tagi");

  const moje = firmyTrybu();

  if (!moje.length) {
    wybor.innerHTML = `<div class="pusto">Najpierw zbadaj jakąś firmę
      (<b>Research po URL</b> albo <b>Szukaj po branży</b>) — podobnych szukamy na jej podstawie.</div>`;
    tagiBox.innerHTML = "";
    return;
  }

  const wpis = moje.find((t) => t.id === podobneWybrana);

  if (!wpis) {
    // Wybór po kategorii. Kategorię nadaje model przy researchu (pole `kategoria`),
    // a jej nazwy pochodzą z backendu — front ich nie wymyśla. Firmy zbadane przed
    // wprowadzeniem pola trafiają do „Bez kategorii", zamiast znikać z listy.
    const kat = (t) => t.firma.kategoria && t.firma.kategoria !== BRAK
      ? t.firma.kategoria : "Bez kategorii";
    const liczby = new Map();
    moje.forEach((t) => liczby.set(kat(t), (liczby.get(kat(t)) || 0) + 1));

    const widoczne = podobneKategoria
      ? moje.filter((t) => kat(t) === podobneKategoria) : moje;

    const chipy = [...liczby.entries()].map(([nazwa, ile]) => `
      <button class="tag${podobneKategoria === nazwa ? " zaznaczony" : ""}"
              type="button" data-kat-podobne="${escAttr(nazwa)}">
        ${esc(nazwa)} <em class="chip-licznik">${ile}</em>
      </button>`).join("");

    wybor.innerHTML = `<div class="card">
      <div class="mono"><span class="sq"></span> 1. Wybierz firmę wzorcową</div>
      ${liczby.size > 1 ? `
        <div class="filtr-kategorii tagi wybieralne">
          <button class="tag${podobneKategoria ? "" : " zaznaczony"}" type="button"
                  data-kat-podobne="">Wszystkie <em class="chip-licznik">${moje.length}</em></button>
          ${chipy}
        </div>` : ""}
      <div class="similar-list">${widoczne.map((t) => `
        <div class="sim-row wybierz-wzor" data-id="${t.id}">
          <div class="sim-info">
            <span class="sim-name">${esc(t.firma.nazwa)}${
              t.firma.kategoria && t.firma.kategoria !== BRAK
                ? `<span class="tag-kat">${esc(t.firma.kategoria)}</span>` : ""}</span>
            <a class="sim-url">${esc(hostname(t.firma.url))} · ${esc(t.firma.branza)}</a>
          </div>
          <button class="researchuj" type="button">Wybierz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>`).join("")}</div>
    </div>`;
    tagiBox.innerHTML = "";
    return;
  }

  wybor.innerHTML = `<div class="card">
    <div class="mono"><span class="sq"></span> Firma wzorcowa</div>
    <div class="wzor-head">
      <div>
        <div class="firma-row-nazwa">${esc(wpis.firma.nazwa)}</div>
        <span class="firma-row-meta">${esc(hostname(wpis.firma.url))} · ${esc(wpis.firma.branza)}</span>
      </div>
      <button class="btn-lekki zmien-wzor" type="button">Zmień firmę</button>
    </div>
  </div>`;

  // Szerokie ujęcia firmy — kafelki, które idą do wyszukiwarki jako gotowa fraza.
  //
  // KATEGORIA TU NIE WCHODZI, choć wchodziła. To nazwa CHIPU („Sklepy internetowe"),
  // a nie zdanie, które ktoś wpisuje w wyszukiwarkę — żadna firma nie opisuje się
  // słowami z naszego filtru. Odpowiednikiem kategorii nadającym się na zapytanie
  // jest jej fraza główna z PRESETY („tworzenie sklepów internetowych"), nie sama
  // etykieta.
  //
  // Resztę układa MODEL, nie my. Próba rozbijania pola `branza` wyrażeniem
  // regularnym nie broni się przy prawdziwych danych: mamy tam ukośniki, przecinki,
  // nawiasy, dwukropki i „i" raz łączące technologie, a raz przymiotniki. Rozbicie
  // „agencja marketingowa i brandingowa" po „ i " daje „agencja marketingowa
  // brandingowa" — ciąg, którego nikt nie wpisze. Szczegóły w api_frazy.
  const zapamietane = frazyPodobnych.get(wpis.firma.url);
  const szerokie = zapamietane
    ? zapamietane
    // Zanim model odpowie, pokazujemy samą branżę — pole nie może być puste,
    // bo user zdąży kliknąć „Szukaj" i zobaczy formularz bez żadnego ujęcia firmy.
    : [(wpis.firma.branza || "").trim()].filter((x) => x && x !== BRAK);

  if (!zapamietane && wpis.firma.branza && wpis.firma.branza !== BRAK) {
    fetch("/api/frazy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branza: wpis.firma.branza }),
    }).then((r) => r.json()).then((d) => {
      if (d.ok && (d.frazy || []).length) {
        frazyPodobnych.set(wpis.firma.url, d.frazy);
        renderPodobne();
      }
    }).catch(() => {});
  }

  const uslugi = (wpis.firma.uslugi || []).filter((u) => !szerokie.includes(u));

  const tagBtn = (t, szeroki) =>
    `<button class="tag${podobneTagi.has(t) ? " zaznaczony" : ""}${szeroki ? " tag-szeroki" : ""}"
      data-tag="${escAttr(t)}" type="button">${esc(t)}</button>`;

  tagiBox.innerHTML = `<div class="card">
    <div class="mono"><span class="sq"></span> 2. Zawęź wyszukiwanie <em class="opcjonalne">— opcjonalnie</em></div>
    <p class="hint">Bez zaznaczenia szukamy po branży: <b>${esc(wpis.firma.branza || wpis.firma.kategoria || "—")}</b>.
      Zaznacz tagi, jeśli chcesz węziej — im mniej i konkretniej, tym trafniej.</p>
    ${szerokie.length ? `<div class="grupa-tagow">
      <span class="preset-etykieta-mini">Całe ujęcie firmy</span>
      <div class="tagi wybieralne">${szerokie.map((t) => tagBtn(t, true)).join("")}</div>
    </div>` : ""}
    ${uslugi.length ? `<div class="grupa-tagow">
      <span class="preset-etykieta-mini">Pojedyncze usługi</span>
    </div>` : ""}
    <div class="tagi wybieralne">${uslugi.map((u) => tagBtn(u, false)).join("")}</div>
    ${zrodlaDostepne.mapy ? `
      <div class="zrodla-podobne">
        <span class="preset-etykieta-mini">Skąd szukamy</span>
        <div class="tagi wybieralne">${Object.entries(ZRODLA).map(([k, z]) => `
          <button class="tag${zrodloPodobne === k ? " zaznaczony" : ""}" type="button"
                  data-zrodlo-podobne="${k}" title="${escAttr(z.opis)}">
            <svg class="ico xs"><use href="#i-${z.ikona}"/></svg> ${esc(z.nazwa)}
          </button>`).join("")}</div>
      </div>` : ""}
    <button class="akcja glowna szukaj-wg-tagow" type="button" style="margin-top:18px">
      <svg class="ico sm"><use href="#i-search"/></svg>${
        podobneTagi.size
          ? `Szukaj podobnych (${podobneTagi.size} ${podobneTagi.size === 1 ? "tag" : "tagi"})`
          : "Szukaj podobnych po branży"
      }
    </button>
  </div>`;
}

// Wyniki NARASTAJĄ między rundami. Jedno wyszukiwanie zwraca kilka firm, a użytkownik
// zwykle chce zobaczyć więcej — nie te same od nowa. Trzymamy więc, co już pokazaliśmy,
// i wysyłamy to do backendu, żeby kolejna runda zwróciła coś innego.
let podobnePokazane = [];
let podobneRunda = 0;

function resetPodobnychWynikow() {
  podobnePokazane = [];
  podobneRunda = 0;
  const box = document.getElementById("podobne-wynik");
  if (box) box.innerHTML = "";
}

async function szukajWgTagow(przycisk, dalej = false) {
  const wpis = firmyTrybu().find((t) => t.id === podobneWybrana);
  if (!wpis) return;
  const box = document.getElementById("podobne-wynik");

  if (!dalej) resetPodobnychWynikow();
  podobneRunda += 1;

  const etykieta = przycisk.innerHTML;
  przycisk.disabled = true;
  przycisk.textContent = "Szukam… (~10 s)";
  if (!dalej) box.innerHTML = "";

  try {
    const res = await fetch("/api/similar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        firma: wpis.firma,
        tagi: [...podobneTagi],
        runda: podobneRunda,
        zrodlo: zrodloPodobne,
        pomin: podobnePokazane.map((f) => hostname(f.url)),
      }),
    });
    const data = await res.json();
    if (!data.ok) { box.innerHTML = errorHTML(data.error); return; }

    // Doklejamy tylko NOWE domeny — backend już je odsiewa, ale przy zmianie tagów
    // między rundami mogłyby wrócić, a lista z duplikatami niczego nie wnosi.
    const znane = new Set(podobnePokazane.map((f) => hostname(f.url)));
    const nowe = (data.firmy || []).filter((f) => !znane.has(hostname(f.url)));
    podobnePokazane = [...podobnePokazane, ...nowe];

    box.innerHTML = listaPodobnychHTML(data, nowe.length);
  } catch (err) {
    box.innerHTML = errorHTML(err.message);
  } finally {
    przycisk.disabled = false;
    przycisk.innerHTML = etykieta;
    renderPodobne();
  }
}

// Osobny renderer, bo lista podobnych narasta i ma własną stopkę z „Szukaj dalej".
function kategoriaWzorca() {
  // Kategoria firmy wzorcowej. W „Szukaj podobnych" nie ma pola z frazą — szukamy
  // PO FIRMIE, więc to jej kategoria mówi, co tu zbieramy. Znalezione firmy idą
  // do kolejki z tym samym tagiem i nie mieszają się z innym szukaniem.
  const wpis = firmyTrybu().find((t) => t.id === podobneWybrana);
  const k = wpis && wpis.firma.kategoria;
  return k && k !== BRAK ? k : "";
}

function listaPodobnychHTML(data, ileNowych) {
  if (!podobnePokazane.length) {
    return `<div class="card"><p class="sim-err">Nie znalazłem firm dla „${esc(data.zapytanie)}".
      Spróbuj innych tagów albo szukaj po samej branży.</p></div>`;
  }
  const wyczerpane = ileNowych === 0;
  return `<div class="card">
    <div class="mono"><span class="sq"></span> Podobne firmy (${podobnePokazane.length})</div>
    <p class="hint">Runda ${data.runda}: „${esc(data.zapytanie)}"${
      ileNowych ? ` · ${ileNowych} nowych` : " · nic nowego"
    }</p>
    <div class="similar-list">${podobnePokazane.map(wierszHTML).join("")}</div>
    <div class="dalej-pasek">
      <button class="btn-lekki szukaj-dalej" type="button">
        <svg class="ico xs"><use href="#i-search"/></svg>Szukaj dalej — inne ujęcie branży
      </button>
      <!-- Tego przycisku tu NIE BYŁO, a to jedyna lista, która narasta przez kilka
           rund. Dorobek kilku rund znikał przy przejściu do innej sekcji i zostawała
           tylko ta firma, którą akurat zbadałeś. -->
      <button class="btn-lekki do-kolejki-wszystkie" type="button"
              data-zapytanie="${escAttr(data.zapytanie || "")}"
              data-kolejka-zrodlo="${escAttr(zrodloPodobne)}"
              data-kolejka-kategoria="${escAttr(kategoriaWzorca())}">
        <svg class="ico xs"><use href="#i-inbox"/></svg>Dodaj wszystkie do kolejki
      </button>
      <span class="hint">${
        wyczerpane
          ? "Ostatnia runda nie dała nic nowego. Zmień tagi albo spróbuj jeszcze raz."
          : "Każda runda pyta o to samo inaczej i pomija firmy już pokazane."
      }</span>
    </div>
  </div>`;
}

function listaFirmHTML(data, naglowek) {
  if (!data.firmy.length) {
    return `<div class="card"><p class="sim-err">Nie znalazłem firm dla „${esc(data.zapytanie)}".
      Spróbuj innej branży albo bez miasta.</p></div>`;
  }
  return `<div class="card">
    <div class="mono"><span class="sq"></span> ${esc(naglowek)} (${data.firmy.length})</div>
    ${data.obszar ? `<p class="hint">Obszar: <b>${esc(data.obszar.nazwa)}</b>
      · ${data.obszar.km_ns} × ${data.obszar.km_we} km — tak Google zrozumiał wpisane
      miejsce. Nie zgadza się? Wpisz precyzyjniej (np. „powiat gnieźnieński").</p>` : ""}
    ${data.obszar_nierozpoznany ? `<p class="ostrzezenie-inline">Nie rozpoznałem tego
      miejsca na mapie, więc szukam po nazwie w treści — to daje ZNACZNIE mniej wyników.
      Spróbuj nazwy miasta, powiatu albo województwa.</p>` : ""}
    <p class="hint">Zapytanie: „${esc(data.zapytanie)}"${
      data.z_seo ? ` · ${data.z_seo} z SEO w ofercie` : ""
    }${data.odsiane_martwe ? ` · ${data.odsiane_martwe} martwych stron` : ""
    }${data.bez_strony ? ` · ${data.bez_strony} firm z Map bez strony WWW (pomijamy — nie ma czego zbadać)` : ""
    }${data.juz_zbadane ? ` · ${data.juz_zbadane} już masz` : ""}</p>
    <div class="similar-list">${data.firmy.map(wierszHTML).join("")}</div>
    <div class="dalej-pasek">
      <button class="btn-lekki do-kolejki-wszystkie" type="button"
              data-zapytanie="${escAttr(data.zapytanie || "")}"
              data-kolejka-zrodlo="${escAttr(data.zrodlo || "wyszukiwarka")}"
              data-kolejka-kategoria="${escAttr(kategoriaZapytania)}">
        <svg class="ico xs"><use href="#i-inbox"/></svg>Dodaj wszystkie do kolejki
      </button>
      <span class="hint">Wyniki znikają razem z zapytaniem. W kolejce zostaną,
        dopóki ich nie zbadasz.</span>
    </div>
  </div>`;
}

function wierszHTML(f) {
  // Tag, nie werdykt: mówi tylko, czy w opisie firmy pada SEO/SEM/pozycjonowanie.
  // Czy to konkurent, czy partner — ocenia zespół, nie narzędzie.
  return `<div class="sim-row" data-url="${escAttr(f.url)}">
    <div class="sim-info">
      <span class="sim-name">${esc(f.nazwa)}${
        f.ma_seo ? `<span class="tag-seo" title="W opisie firmy pada SEO / SEM / pozycjonowanie">SEO</span>` : ""
      }${
        // Firma już w bazie. Nie chowamy jej — może być trafna — ale mówimy wprost,
        // żeby nie płacić drugi raz za ten sam research.
        f.zbadana ? `<span class="tag-zbadana" title="Masz ją już w sekcji Firmy${
          f.zbadana_tryb && f.zbadana_tryb !== tryb ? `, w ścieżce ${TRYBY[f.zbadana_tryb]?.nazwa || f.zbadana_tryb}` : ""
        }">JUŻ ZBADANA${
          f.zbadana_tryb && f.zbadana_tryb !== tryb ? ` · ${esc(TRYBY[f.zbadana_tryb]?.nazwa || f.zbadana_tryb)}` : ""
        }</span>` : ""
      }</span>
      <a class="sim-url" href="${escAttr(f.url)}" target="_blank" rel="noopener">${esc(f.url)}<svg class="ico xs"><use href="#i-external"/></svg></a>
      ${f.opis ? `<span class="sim-opis">${esc(f.opis.slice(0, 150))}${f.opis.length > 150 ? "…" : ""}</span>` : ""}
      ${f.niepewna ? `<span class="niepewna"><svg class="ico xs"><use href="#i-alert"/></svg>nie udało się zweryfikować strony (blokada bota?)</span>` : ""}
    </div>
    <button class="researchuj${f.zbadana ? " btn-lekki" : ""}" type="button">${
      f.zbadana ? "Zbadaj ponownie" : "Researchuj"
    }<svg class="ico xs"><use href="#i-arrow"/></svg></button>
  </div>`;
}

async function researchujZListy(przycisk) {
  const row = przycisk.closest(".sim-row");
  przycisk.disabled = true;
  przycisk.textContent = "Zbieram… (~30 s)";
  try {
    const data = await research(row.dataset.url);
    if (!data.ok) {
      przycisk.disabled = false;
      przycisk.textContent = "Spróbuj ponownie";
      row.insertAdjacentHTML("beforeend", `<p class="sim-err">${esc(data.error)}</p>`);
    } else {
      otworzFirme(data.firma);
      przycisk.innerHTML = '<svg class="ico xs"><use href="#i-check"/></svg>Otwarto kartę';
      // Backend zdjął ją już z kolejki — front musi się o tym dowiedzieć,
      // inaczej licznik w menu i lista pokazują robotę, której nie ma.
      wczytajKolejke().then(() => {
        if (document.querySelector('.sekcja.aktywna')?.dataset.sekcja === "kolejka") renderKolejke();
      });
    }
  } catch (err) {
    przycisk.disabled = false;
    przycisk.textContent = "Spróbuj ponownie";
  }
}

// ══ Maile ══
async function generujMaile(przycisk) {
  const panel = przycisk.closest(".panel");
  const box = panel.querySelector(".mail-box");
  przycisk.disabled = true;
  przycisk.textContent = "Piszę… (~20 s)";
  box.innerHTML = "";
  try {
    const res = await fetch("/api/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ firma: firmaZPanelu(panel) }),
    });
    const data = await res.json();
    box.innerHTML = data.ok
      ? `<div class="card">
           <div class="mono"><span class="sq"></span> Propozycje maila</div>
           ${data.maile.map((m) => `<div class="mail-draft">
             <div class="mail-head"><span class="mail-styl">${esc(m.styl)}</span>
               <button class="kopiuj" type="button"><svg class="ico xs"><use href="#i-copy"/></svg>Kopiuj</button></div>
             <pre class="mail-tresc">${esc(m.tresc)}</pre>
           </div>`).join("")}
         </div>`
      : errorHTML(data.error);
  } catch (err) {
    box.innerHTML = errorHTML(err.message);
  } finally {
    przycisk.disabled = false;
    przycisk.innerHTML = '<svg class="ico sm"><use href="#i-mail"/></svg>Generuj maile';
  }
}

function kopiuj(przycisk) {
  const tresc = przycisk.closest(".mail-draft").querySelector(".mail-tresc").textContent;
  navigator.clipboard.writeText(tresc).then(() => {
    przycisk.innerHTML = '<svg class="ico xs"><use href="#i-check"/></svg>Skopiowano';
    setTimeout(() => (przycisk.innerHTML = '<svg class="ico xs"><use href="#i-copy"/></svg>Kopiuj'), 1500);
  });
}

// ══ SEKCJA: Mikroaudyt SEO/GEO ══
// Jedyna PŁATNA funkcja (DataForSEO) — pokazujemy koszt zanim user kliknie.
let audytWybrana = null;
let audytIle = 5;
let audytSilniki = ["chatgpt_wprost"];
// Silnik bazy SE Ranking dla sekcji wzmianek — ich dane pokrywaja 5 platform.
// Platformy, na ktorych DataForSEO sprawdza wzmianki o marce.
const PLATFORMY_DFS = {
  "google":     "Google AI Overviews",
  "chat_gpt":   "ChatGPT",
  "perplexity": "Perplexity",
  "gemini":     "Google Gemini",
};
let audytPlatformy = ["google"];

// ktore modele AI pytamy (mozna kilka naraz)
let audytAIO = true;

const KOSZT_PROMPT = 0.006;   // Perplexity sonar, zmierzone
const KOSZT_AIO = 0.11;       // llm_mentions, zmierzone
const KOSZT_SEO = 0.04;       // 3 wywolania Labs, zmierzone
// Zmierzone na tym samym prompcie: Perplexity dal 9 marek za $0.006,
// ChatGPT 3 marki za $0.109. Tanszy dal WIECEJ danych — ale ma 6% rynku PL.
// Modele potwierdzone darmowym endpointem DataForSEO — wszystkie z wyszukiwaniem w sieci.
const SILNIKI = {
  // Jedyny silnik na naszym wlasnym kluczu. Odkad DataForSEO jest jedynym dostawca
  // danych SEO, to JEDYNA sekcja audytu, ktora przezyje jego awarie albo puste saldo.
  chatgpt_wprost: { nazwa: "ChatGPT (bezpośrednio)", udzial: "86,4%", koszt: 0.012,
                    wlasny: true },
  // Drugi silnik na NASZYM kluczu. Nie chodzi o zasieg Claude (0,71% rynku), tylko
  // o to, ze dwa niezalezne pomiary tego samego sa warte wiecej niz jeden: przy
  // jednym modelu nie da sie odroznic jego cechy od stanu rynku. Zmierzone na
  // Tebimie: ChatGPT wymienil firme, Claude nie — i podal 7 konkurentow.
  claude_wprost:  { nazwa: "Claude (bezpośrednio)", udzial: "0,71%", koszt: 0.035,
                    wlasny: true },
  chatgpt:    { nazwa: "ChatGPT",       udzial: "86,4%", koszt: 0.109, dfs: true },
  perplexity: { nazwa: "Perplexity",    udzial: "6,18%", koszt: 0.006, dfs: true },
  gemini:     { nazwa: "Google Gemini", udzial: "3,22%", koszt: 0.020, dfs: true },
  claude:     { nazwa: "Claude",        udzial: "0,71%", koszt: 0.030, dfs: true },
  // Google AI Mode to konwersacyjny tryb wyszukiwarki, nie chatbot — StatCounter
  // go nie mierzy, wiec udzialu nie podajemy zamiast zmyslac liczbe.
  ai_mode:    { nazwa: "Google AI Mode", udzial: null,    koszt: 0.006, dfs: true,
                opis: "tryb konwersacyjny wyszukiwarki" },
};
// Ile razy zadajemy kazde pytanie. Jedna proba nie odroznia nieobecnosci od
// przypadku — zmierzone na Tebimie: 3 proby dostaly kolejno NIE, NIE, TAK.
// Dotyczy tylko silnikow na naszym kluczu; przez DataForSEO mnozylyby rachunek.
let audytPowtorzenia = 1;
let audytSEO = true;

// Każde pytanie idzie do każdego wybranego modelu, więc koszty się sumują.
// Które zaznaczone opcje przechodzą przez DataForSEO — żeby powiedzieć to PRZED
// audytem, a nie dopiero błędem 402 po minucie czekania.
function wymagaDFS() {
  const l = audytSilniki.filter((k) => SILNIKI[k]?.dfs).map((k) => SILNIKI[k].nazwa);
  if (audytSEO) l.push("Widoczność w Google");
  if (audytAIO) l.push("Widoczność w AI Overviews");
  return l.length ? l : null;
}

function pokrycieRynku() {
  // ChatGPT wprost i ChatGPT przez DataForSEO to TEN SAM silnik — liczenie obu
  // dalo by 172,8% rynku. Sumujemy unikalne udzialy, nie zaznaczenia.
  const udzialy = new Set(audytSilniki.map((k) => SILNIKI[k]?.udzial).filter(Boolean));
  const suma = [...udzialy].reduce((s, u) => s + parseFloat(u.replace(",", ".")), 0);
  return suma.toFixed(1).replace(".", ",") + "%";
}

function kosztSilnikow() {
  return audytSilniki.reduce((s, k) => s + (SILNIKI[k]?.koszt || 0), 0);
}

function renderAudyt() {
  const wybor = document.getElementById("audyt-wybor");
  const dostepne = firmyTrybu();
  if (!dostepne.length) {
    wybor.innerHTML = przelacznikTrybu() +
      `<div class="pusto"><svg class="ico xl"><use href="#i-inbox"/></svg>
      <p>Brak zbadanych firm w ścieżce <b>${TRYBY[tryb].nazwa}</b>.<br>
      <span>${esc(TRYBY[tryb].opis)}</span></p></div>`;
    return;
  }
  const wpis = dostepne.find((t) => t.id === audytWybrana);

  if (!wpis) {
    wybor.innerHTML = przelacznikTrybu() + `<div class="card">
      <div class="mono"><i class="sq"></i>Wybierz firmę do audytu</div>
      <div class="similar-list">${dostepne.map((t) => `
        <div class="sim-row wybierz-audyt" data-id="${t.id}">
          <div class="sim-info"><span class="sim-name">${esc(t.firma.nazwa)}</span>
            <span class="firma-row-meta">${esc(hostname(t.firma.url))} · ${esc(t.firma.branza)}</span></div>
          <button class="researchuj" type="button">Wybierz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>`).join("")}</div></div>`;
    return;
  }

  const koszt = (audytIle * kosztSilnikow() + (audytAIO ? KOSZT_AIO : 0)
    + (audytSEO ? KOSZT_SEO : 0)
    + (audytAIO ? KOSZT_AIO * (audytPlatformy.length - 1) : 0)).toFixed(3);
  wybor.innerHTML = `<div class="card">
    <div class="wzor-head">
      <div><div class="firma-row-nazwa">${esc(wpis.firma.nazwa)}</div>
        <span class="firma-row-meta">${esc(hostname(wpis.firma.url))}</span></div>
      <button class="btn-lekki zmien-audyt" type="button">Zmień firmę</button>
    </div>
  </div>
  <div class="card">
    <div class="mono"><i class="sq"></i>Które modele AI pytamy</div>
    <div class="akcje" style="margin-bottom:10px">
      ${Object.entries(SILNIKI).map(([k, m]) => `
        <label class="akcja check"><input type="checkbox" name="silnik" value="${k}"
          ${audytSilniki.includes(k) ? "checked" : ""}> ${m.nazwa}
          <span class="cena">${m.udzial || m.opis} · $${m.koszt}${
            m.wlasny ? " · nasz klucz" : m.dfs ? " · przez DataForSEO" : ""
          }</span></label>`).join("")}
    </div>
    ${wymagaDFS() ? `<p class="ostrzezenie-inline">Zaznaczone opcje wymagają konta
      <b>DataForSEO</b> ze środkami: ${wymagaDFS().join(", ")}. Jeśli saldo jest puste,
      audyt zakończy się błędem — odznacz je albo doładuj konto.</p>` : ""}
    <p class="hint" style="margin:0 0 16px">
      Każde pytanie trafia do <b>każdego</b> zaznaczonego modelu, więc koszty się sumują.
      Łączny udział wybranych: <b>${pokrycieRynku()}</b> polskiego rynku zapytań do AI.
      ${audytSilniki.length > 1
        ? " Przy kilku modelach widać, czy brak wzmianki dotyczy jednego silnika, czy wszystkich."
        : " Przy jednym modelu nie da się odróżnić cechy silnika od prawidłowości."}</p>

    ${audytAIO ? `
    <div class="mono"><i class="sq"></i>Wzmianki — z której platformy</div>
    <div class="akcje" style="margin-bottom:10px">
      ${Object.entries(PLATFORMY_DFS).map(([k, n]) => `
        <label class="akcja check"><input type="checkbox" name="platforma" value="${k}"
          ${audytPlatformy.includes(k) ? "checked" : ""}> ${n}</label>`).join("")}
    </div>
    <p class="hint" style="margin:0 0 16px">Baza DataForSEO — zapytania, przy których
      firma <b>już jest</b> cytowana. Każda platforma to osobne wywołanie
      (<b>+$${KOSZT_AIO}</b>).</p>` : ""}

    <div class="mono"><i class="sq"></i>Zakres audytu</div>
    <div class="akcje" style="margin-bottom:14px">
      <label class="akcja check"><input type="checkbox" id="audyt-seo" ${audytSEO ? "checked" : ""}>
        Widoczność w Google <span class="cena">+$${KOSZT_SEO}</span></label>
      <label class="akcja check"><input type="checkbox" id="audyt-aio" ${audytAIO ? "checked" : ""}>
        Widoczność w AI Overviews <span class="cena">+$${KOSZT_AIO}</span></label>
      <label class="akcja check" style="gap:12px">Liczba pytań
        <input type="range" id="audyt-ile" min="3" max="10" value="${audytIle}" style="width:110px">
        <b>${audytIle}</b></label>
    </div>
    <p class="hint">Szacowany koszt: <b class="cena-suma">$${koszt}</b>
      · pytania układa nasz model, odpowiedzi zbieramy z zaznaczonych silników.</p>
    <button class="akcja glowna generuj-audyt" type="button" style="margin-top:16px">
      <svg class="ico sm"><use href="#i-chart"/></svg>Wygeneruj audyt</button>
  </div>`;
}

async function generujAudyt(przycisk) {
  const wpis = tabs.find((t) => t.id === audytWybrana);
  const box = document.getElementById("audyt-raport");
  przycisk.disabled = true;
  przycisk.textContent = "Zbieram dane… (~60-90 s)";
  box.innerHTML = loadingHTML("Generuję pytania, pytam modele AI i sprawdzam widoczność…");
  try {
    const res = await fetch("/api/audyt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ firma: wpis.firma, ile_promptow: audytIle, silniki: audytSilniki,
                             ai_overview: audytAIO, seo: audytSEO, platformy: audytPlatformy }),
    });
    const data = await res.json();
    box.innerHTML = data.ok ? raportHTML(data.raport) : errorHTML(data.error);
  } catch (err) {
    box.innerHTML = errorHTML(err.message);
  } finally {
    przycisk.disabled = false;
    renderAudyt();
  }
}

// ── Render raportu — układ DOKUMENTU, nie dashboardu ──
function raportHTML(r) {
  const p = r.podsumowanie;
  const st = r.tresc_stala;
  const dzis = new Date().toLocaleDateString("pl-PL", { day: "numeric", month: "long", year: "numeric" });
  let nr = 0;

  return `<div class="raport" id="raport">

    <!-- STRONA TYTUŁOWA -->
    <section class="okladka">
      <div class="okladka-gora"><div class="logo">Last<em>Agency</em></div></div>
      <div class="okladka-srodek">
        <div class="mono"><i class="sq biala"></i>Analiza GEO</div>
        <h1>Widoczność w AI Search<br><span>${esc(r.firma.nazwa)}</span></h1>
        <p class="okladka-meta">${esc(r.firma.domena)} · ${esc(dzis)}</p>
      </div>
      <div class="okladka-dol mono">© 2026 ICEA · grupa-icea.pl</div>
    </section>

    <!-- KLUCZOWE LICZBY -->
    <section class="r-strona">
      ${naglowekSekcji(++nr, "Kluczowe liczby")}
      <div class="liczby">
        ${liczba(p.udzial_wspomnien + "%", "pytań, w których AI wymienia markę")}
        ${liczba(p.wspomniana + " / " + p.promptow, "zapytań ze wzmianką")}
        ${liczba(p.cytowana, "bezpośrednich cytowań strony")}
        ${r.ai_overview ? liczba(p.wzmianki_aio ?? "—", "fraz z AI Overview") : ""}
      </div>
      <p class="wiodacy">Sprawdziliśmy, jak modele AI odpowiadają na pytania, które zadaje realny
        klient szukający takich usług. <b>W żadnym z pytań nie padła nazwa firmy</b> — mierzymy,
        czy sztuczna inteligencja wskaże ją samodzielnie.</p>
      ${p.per_silnik && p.per_silnik.length ? `
      <table class="tabela-dok" style="margin-top:26px">
        <thead><tr><th>Model AI</th><th class="pr waska">Udział w PL</th>
          <th class="pr waska">Wzmianki</th><th class="pr waska">Cytowania</th></tr></thead>
        <tbody>${p.per_silnik.map((m) => `<tr>
          <td class="cel">${esc(m.nazwa)}</td>
          <td class="pr waska">${m.udzial != null
            ? String(m.udzial).replace(".", ",") + "%" : "—"}</td>
          <td class="pr waska">${m.wspomniana} / ${m.pytan}</td>
          <td class="pr waska">${m.cytowana} / ${m.pytan}</td></tr>`).join("")}</tbody>
      </table>
      <p class="metodyka">${p.per_silnik.length > 1
        ? `Te same pytania zadaliśmy <b>${p.per_silnik.length}</b> modelom, co pokrywa
           <b>${p.per_silnik.reduce((s, m) => s + (m.udzial || 0), 0).toFixed(1)
              .replace(".", ",")}%</b> polskiego rynku zapytań do AI. Różnice między
           wierszami pokazują, czy widoczność zależy od konkretnego silnika.`
        : `Pytania zadaliśmy jednemu modelowi. Wynik dotyczy
           <b>${String(p.per_silnik[0].udzial).replace(".", ",")}%</b> polskiego rynku —
           przy innym silniku mógłby wyglądać inaczej.`}</p>` : ""}
      <p class="metodyka">Ma to znaczenie przy porównywaniu z innymi analizami. Narzędzia
        monitorujące pytają zwykle wprost o markę („Kim są…", „oferta firmy…") i sprawdzają, czy
        model ją zna — tam wynik bywa bliski 100%. My zadajemy pytania klienta, który firmy
        <b>jeszcze nie zna</b>, więc mierzymy realną szansę na polecenie. Niższy wynik nie
        oznacza sprzeczności — to odpowiedź na trudniejsze pytanie.</p>
    </section>

    ${r.seo ? `
    <section class="r-strona">
      ${naglowekSekcji(++nr, "Widoczność w Google")}
      <div class="liczby">
        ${liczba(r.seo.ruch.toLocaleString("pl-PL"), "szacowany ruch organiczny / mies.")}
        ${liczba(r.seo.top3, r.seo.etykieta_czolo || "fraz w TOP 3")}
        ${liczba(r.seo.top10, "fraz w TOP 10")}
        ${liczba(r.seo.fraz_lacznie, "fraz widocznych łącznie")}
      </div>
      ${(() => {
        // Zdanie składamy z tego, co dostawca FAKTYCZNIE podał. Wcześniej było
        // wpisane na sztywno i przy SE Ranking wychodziło „Ruch generuje null
        // podstron", a liczbę z TOP 5 opisywało jako „w pierwszej trójce".
        const czolo = (r.seo.etykieta_czolo || "fraz w TOP 3")
          .replace(/^fraz w /, "").replace(/ \(.*\)$/, "");
        const zd = [`Strona jest widoczna na <b>${r.seo.fraz_lacznie}</b> fraz,
          z czego <b>${r.seo.top3}</b> w ${czolo === "TOP 3" ? "pierwszej trójce" : czolo}.`];
        if (r.seo.wzrosty != null && r.seo.spadki != null) {
          zd.push(`W ostatnim okresie <b>${r.seo.wzrosty}</b> pozycji wzrosło,
            <b>${r.seo.spadki}</b> spadło${r.seo.nowe != null
              ? `, pojawiło się <b>${r.seo.nowe}</b> nowych fraz, a <b>${r.seo.utracone}</b> utracono`
              : ""}.`);
        }
        if (r.seo.podstron_widocznych != null) {
          zd.push(`Ruch generuje <b>${r.seo.podstron_widocznych}</b> podstron.`);
        }
        return `<p>${zd.join(" ")}</p>`;
      })()}
      ${!r.seo.dane_wiarygodne ? `<p class="ostrzezenie"><b>Widoczność organiczna jest znikoma.</b>
        Przy tak małej liczbie fraz poniższe zestawienie konkurencji traktujcie jako orientacyjne —
        pokazuje, kto zajmuje te same zapytania, ale przy większej liczbie fraz obraz może się zmienić.</p>` : ""}
      ${r.seo.konkurenci.length ? `
      <table class="tabela-dok">
        <thead><tr><th>Konkurent w wynikach</th><th class="pr waska">Wspólne frazy</th>
          <th class="pr waska">Ruch łącznie</th><th class="pr waska">${r.seo.konkurenci.some((k) => k.podobienstwo != null)
            ? "Podobieństwo" : "Śr. pozycja"}</th></tr></thead>
        <tbody>${r.seo.konkurenci.map((k) => `<tr><td>${esc(k.domena)}</td>
          <td class="pr waska">${k.wspolne_frazy}</td>
          <td class="pr waska">${k.ruch_calkowity != null
            ? k.ruch_calkowity.toLocaleString("pl-PL") : "—"}</td>
          <td class="pr waska">${k.podobienstwo != null ? k.podobienstwo
            : (k.srednia_pozycja != null ? k.srednia_pozycja : "—")}</td></tr>`).join("")}</tbody>
      </table>
      ${r.seo.ruch_nasz_calkowity ? `<p class="metodyka">Kolumna „Ruch łącznie" to szacowany
        <b>całkowity</b> ruch organiczny domeny, nie tylko na frazach wspólnych — dzięki temu widać
        realną skalę. Dla porównania: badana strona ma
        <b>${r.seo.ruch_nasz_calkowity.toLocaleString("pl-PL")}</b> sesji miesięcznie.</p>` : ""}` : ""}
      ${r.seo.luka && r.seo.luka.length ? (() => {
        const luki = r.seo.luka.filter((w) => w.ma_aio && !w.cytowany_w_aio && !w.nieustalone);
        const stracone = luki.reduce((s, w) => s + (w.wolumen || 0), 0);
        const cytowani = r.seo.luka.filter((w) => w.cytowany_w_aio);
        const bezAio = r.seo.luka.filter((w) => w.ma_aio === false);
        return `<div class="wyimek luka-blok">
          <div class="mono"><i class="sq"></i>Luka między Google a AI</div>
          ${luki.length ? `<p>Na <b>${luki.length}</b> z ${r.seo.luka.length} sprawdzonych fraz Google
            pokazuje odpowiedź AI, w której <b>Państwa strona nie jest cytowana</b> — mimo pozycji
            w wynikach organicznych. To łącznie <b>${stracone.toLocaleString("pl-PL")}</b> wyszukiwań
            miesięcznie, przy których użytkownik dostaje gotową odpowiedź i może nie kliknąć w żaden wynik.</p>`
          : cytowani.length
          ? `<p><b>Na ${cytowani.length} z ${r.seo.luka.length} sprawdzonych fraz Państwa strona jest
              cytowana w odpowiedzi AI</b> — czyli tam, gdzie Google generuje gotową odpowiedź nad
              wynikami, pojawiacie się w niej Państwo. To mocna pozycja: użytkownik widzi Waszą treść
              nawet wtedy, gdy nie kliknie w żaden wynik.</p>`
          : `<p>Na sprawdzonych frazach Google <b>nie pokazuje</b> odpowiedzi AI — wyświetla klasyczne
              wyniki albo moduły dodatkowe.${r.ai_overview && r.ai_overview.liczba_wzmianek
              ? ` AI Overviews pojawiają się natomiast na innych zapytaniach — tam Państwa strona
                 jest cytowana na <b>${r.ai_overview.liczba_wzmianek}</b> frazach (sekcja dalej).`
              : ""}</p>`}
        </div>
        <table class="tabela-dok">
          <thead><tr><th>Fraza handlowa</th><th class="pr waska">Pozycja</th>
            <th class="pr waska">Wyszukiwań</th><th class="pr">AI Overview</th></tr></thead>
          <tbody>${r.seo.luka.map((w) => `<tr>
            <td>${esc(w.fraza)}</td>
            <td class="pr waska">${w.pozycja ? "#" + w.pozycja : "poza TOP100"}</td>
            <td class="pr waska">${(w.wolumen || 0).toLocaleString("pl-PL")}</td>
            <td class="pr">${
              !w.ma_aio ? `<span class="typ">brak AIO</span>`
              : w.cytowany_w_aio ? `<span class="typ handlowa">cytowani</span>`
              : w.nieustalone ? `<span class="typ">nie ustalono</span>`
              : `<span class="typ luka">nie cytują Was</span>`}</td>
          </tr>`).join("")}</tbody>
        </table>`;
      })() : ""}

      ${r.seo.frazy && r.seo.frazy.length ? `
      <table class="tabela-dok">
        <thead><tr><th>Fraza, na którą firma jest widoczna</th><th class="pr waska">Pozycja</th>
          <th class="pr waska">Wyszukiwań</th><th class="pr">Typ</th></tr></thead>
        <tbody>${r.seo.frazy.map((f) => `<tr>
          <td>${esc(f.fraza)}</td>
          <td class="pr waska">${f.pozycja ? "#" + f.pozycja : "—"}</td>
          <td class="pr waska">${(f.wolumen || 0).toLocaleString("pl-PL")}</td>
          <td class="pr"><span class="typ ${f.typ}">${f.typ === "handlowa" ? "handlowa" : "informacyjna"}</span></td>
        </tr>`).join("")}</tbody>
      </table>
      ${r.seo.frazy.filter((f) => f.typ === "informacyjna").length >= r.seo.frazy.length / 3
        ? `<p class="ostrzezenie">Znaczna część ruchu pochodzi z zapytań <b>informacyjnych</b>
            („co to jest…"), a nie zakupowych. Taki ruch buduje zasięg, ale rzadko kończy się
            zapytaniem ofertowym — to obszar o największym potencjale poprawy.</p>` : ""}` : ""}

      ${r.seo.zrodlo ? `<p class="zrodlo-danych">Dane: <b>${esc(r.seo.zrodlo)}</b>${
        r.seo.data_bazy ? ` · aktualizacja bazy ${esc(r.seo.data_bazy)}` : ""}. Narzędzia SEO
        korzystają z różnych baz fraz, więc liczby bezwzględne mogą się między nimi różnić;
        szacunki ruchu są porównywalne.</p>` : ""}

      ${r.seo.top_podstrony.length ? `
      <table class="tabela-dok">
        <thead><tr><th>Podstrony generujące ruch</th><th class="pr waska">Fraz</th><th class="pr waska">Ruch/mies.</th></tr></thead>
        <tbody>${r.seo.top_podstrony.map((s) => `<tr><td class="url">${esc(s.adres)}</td>
          <td class="pr waska">${s.fraz}</td><td class="pr waska">${s.ruch.toLocaleString("pl-PL")}</td></tr>`).join("")}</tbody>
      </table>` : ""}
    </section>` : ""}

    <!-- PYTANIA I ODPOWIEDZI -->
    <section class="r-strona">
      ${naglowekSekcji(++nr, "Jak AI odpowiada na pytania klientów")}
      ${r.prompty.map((w) => promptHTML(w, r.firma.nazwa)).join("")}
    </section>

    ${r.ai_overview ? `
    <section class="r-strona">
      ${naglowekSekcji(++nr, r.ai_overview.silnik_nazwa
          && r.ai_overview.silnik_nazwa !== "Google AI Overviews"
          ? `Widoczność w ${r.ai_overview.silnik_nazwa}`
          : "Widoczność w AI Overviews")}
      ${st.ai_overview.akapity.map((a) => `<p>${pogrub(a)}</p>`).join("")}
      ${r.ai_overview.platformy ? `
      <table class="tabela-dok" style="margin-bottom:26px">
        <thead><tr><th>Platforma AI</th><th class="pr waska">Fraz z cytowaniem</th>
          <th class="pr waska">Śr. pozycja</th></tr></thead>
        <tbody>${r.ai_overview.platformy.map((p) => `<tr>
          <td class="cel">${esc(p.nazwa)}</td>
          <td class="pr waska">${p.liczba != null ? p.liczba.toLocaleString("pl-PL") : "—"}</td>
          <td class="pr waska">${p.srednia != null ? p.srednia : "—"}</td></tr>`).join("")}</tbody>
      </table>
      <p class="metodyka">Różnica między platformami to sama w sobie informacja —
        firma może być mocno obecna w jednej i niewidoczna w drugiej, choć obie liczby
        są prawdziwe. Szczegóły poniżej dotyczą
        <b>${esc(r.ai_overview.silnik_nazwa || "pierwszej z nich")}</b>.</p>` : ""}

      ${r.ai_overview.wzmianki && r.ai_overview.wzmianki.length ? `
      <div class="liczby">
        ${liczba(r.ai_overview.liczba_wzmianek ?? "—", "fraz z AI Overview")}
        ${liczba(r.ai_overview.srednia_pozycja ?? "—", r.ai_overview.probka_niepelna
            ? `średnia pozycja z ${r.ai_overview.pobrano} zbadanych fraz`
            : "średnia pozycja cytowania")}
      </div>
      <table class="tabela-dok">
        <thead><tr><th>Zapytanie</th><th class="pr waska">Wyszukiwań/mies.</th>
          <th class="pr waska">Jako źródło</th><th class="pr">Nazwa firmy</th></tr></thead>
        <tbody>${r.ai_overview.wzmianki.slice(0, 10).map((w) => `
          <tr><td>${esc(w.prompt)}</td>
              <td class="pr waska">${w.wolumen ? w.wolumen.toLocaleString("pl-PL") : "—"}</td>
              <td class="pr waska">${w.pozycja ? "#" + w.pozycja : "—"}</td>
              <td class="pr">${w.wymieniona
                ? `<span class="typ handlowa">wymieniona</span>`
                : `<span class="typ">tylko źródło</span>`}</td></tr>`).join("")}</tbody>
      </table>
      ${(() => {
        // Bycie cytowanym źródłem a byciem wymienionym z nazwy to dwie różne rzeczy
        // i różnica jest praktyczna: w pierwszym przypadku użytkownik czyta odpowiedź
        // zbudowaną na treści firmy, ale jej nazwy nie widzi.
        const w = r.ai_overview.wzmianki.slice(0, 10);
        const nazwane = w.filter((x) => x.wymieniona).length;
        if (!w.length) return "";
        return `<p class="metodyka">Wśród ${w.length} zbadanych zapytań nazwa firmy pada
          w treści odpowiedzi <b>${nazwane} ${nazwane === 1 ? "raz" : "razy"}</b>.
          ${nazwane < w.length
            ? `W pozostałych Google buduje odpowiedź na Państwa treści, ale <b>nie podaje
               nazwy</b> — użytkownik musiałby rozwinąć panel źródeł, żeby ją zobaczyć.
               To słabsza forma widoczności i osobny obszar do poprawy.`
            : "To najmocniejsza forma widoczności — użytkownik widzi nazwę bez klikania."}</p>`;
      })()}

      ${r.ai_overview.wzmianki.some((w) => w.tekst) ? `
      <p class="metodyka" style="margin-top:26px">Poniżej rzeczywiste odpowiedzi, które
        Google pokazał na te zapytania. To <b>nie są nasze pytania</b> — to zapytania
        z bazy dostawcy, wybrane dlatego, że Państwa strona jest w nich cytowana.</p>
      ${r.ai_overview.wzmianki.filter((w) => w.tekst).slice(0, 3).map((w) => `
        <article class="pytanie">
          <div class="pytanie-glowa">
            <h3>${esc(w.prompt)}</h3>
            <span class="status cyt">Strona cytowana</span>
          </div>
          <blockquote>${formatujOdpowiedz(w.tekst, r.firma.nazwa)}</blockquote>
          <div class="pytanie-meta">
            <span>pozycja ${w.pozycja ? "#" + w.pozycja : "—"}</span>
            <span>${w.wolumen ? w.wolumen.toLocaleString("pl-PL") + " wyszukiwań/mies." : ""}</span>
            <span>${(w.zrodla || []).length} źródeł</span>
          </div>
        </article>`).join("")}` : ""}
      ${r.ai_overview.probka_niepelna ? `<p class="metodyka">Tabela pokazuje
        ${r.ai_overview.pobrano} fraz o największej liczbie wyszukiwań spośród
        <b>${r.ai_overview.liczba_wzmianek}</b>, na których strona pojawia się
        w AI Overviews. Średnia pozycja dotyczy tej próbki, nie wszystkich fraz.</p>` : ""}`
      : `<p class="ostrzezenie"><b>Nie znaleźliśmy ani jednej frazy</b>, przy której strona
          byłaby cytowana w AI Overviews. Przy zapytaniach, na które Google generuje odpowiedź
          AI, źródłem są dziś inne serwisy — a to właśnie ta odpowiedź trafia do użytkownika
          nad wynikami wyszukiwania.</p>`}
    </section>` : ""}

    <!-- SKĄD MODEL CZERPIE WIEDZĘ -->
    ${r.zrodla && r.zrodla.zrodel_lacznie ? `
    <section class="r-strona">
      ${naglowekSekcji(++nr, "Skąd AI czerpie wiedzę")}
      <p>Zadaliśmy modelowi${p.per_silnik && p.per_silnik.length === 1
          ? ` <b>${esc(p.per_silnik[0].nazwa)}</b>` : "om"}
        ${r.zrodla.pytan} pytania klienta i zebraliśmy wszystkie strony, na których
        oparł odpowiedzi. To pokazuje, komu w tej branży „ufa".</p>
      ${r.ai_overview && r.ai_overview.wzmianki && r.ai_overview.wzmianki.length ? `
      <p class="metodyka" style="margin-top:0">To <b>inny pomiar niż sekcja
        „${esc(r.ai_overview.silnik_nazwa || "Widoczność w AI Overviews")}"</b> powyżej.
        Tam liczyliśmy zapytania, przy których Google już Państwa cytuje. Tutaj pytamy
        sami — pytaniami klienta, który firmy nie zna — i sprawdzamy, czy model sięgnie
        po Państwa stronę z własnej inicjatywy. Obie liczby mogą się różnić i obie są
        prawdziwe.</p>` : ""}
      <div class="liczby">
        ${liczba(r.zrodla.zrodel_lacznie, "zacytowanych źródeł")}
        ${liczba(r.zrodla.domen_unikalnych, "unikalnych serwisów")}
        ${liczba(r.zrodla.nasze_cytowania, "cytowań Państwa strony")}
      </div>
      ${r.zrodla.nasze_cytowania
        ? `<p class="wyimek"><b>Państwa strona jest wśród źródeł</b> — model zacytował ją
            ${r.zrodla.nasze_cytowania} razy${r.zrodla.nasze_miejsce
              ? `, co daje ${r.zrodla.nasze_miejsce}. miejsce wśród wszystkich cytowanych
                 serwisów${r.zrodla.remisujacych
                   ? ` — ex aequo z ${r.zrodla.remisujacych} ${
                       r.zrodla.remisujacych === 1 ? "innym serwisem" : "innymi serwisami"}`
                   : ""}`
              : ""}. Oznacza to, że treść jest dla modelu dostępna i wiarygodna;
            jeśli mimo to marka nie pada w odpowiedziach, przyczyna leży w tym,
            <b>jak treść odpowiada na pytania klientów</b>, a nie w jej dostępności.</p>`
        : `<p class="ostrzezenie"><b>Odpowiadając na te pytania, model nie sięgnął
            po Państwa stronę ani razu.</b> Zbudował odpowiedzi wyłącznie na treściach
            konkurencji i serwisów branżowych${r.ai_overview && r.ai_overview.liczba_wzmianek
              ? ` — mimo że w ${esc(r.ai_overview.silnik_nazwa || "AI Overviews")} jesteście
                 cytowani na <b>${r.ai_overview.liczba_wzmianek}</b> frazach. Widoczność
                 w jednym kanale nie przenosi się automatycznie na drugi` : ""}.</p>`}
      <table class="tabela-dok">
        <thead><tr><th>Serwis, z którego model korzystał</th><th class="pr waska">Cytowań</th></tr></thead>
        <tbody>${r.zrodla.top_zrodla.map((z) => `<tr>
          <td>${esc(z.domena)}</td><td class="pr waska">${z.cytowan}</td></tr>`).join("")}</tbody>
      </table>
      <p class="metodyka">Obecność w serwisach z tej listy — katalogach, rankingach,
        zestawieniach branżowych — bezpośrednio zwiększa szansę na pojawienie się
        w odpowiedziach AI, bo to z nich model buduje rekomendacje.</p>
    </section>` : ""}

    <!-- CZY JESTEŚCIE TAM, SKĄD AI BIERZE ODPOWIEDZI -->
    ${(r.obecnosc_w_zrodlach || []).length ? `
    <section class="r-strona">
      ${naglowekSekcji(++nr, "Czy jesteście tam, skąd AI bierze odpowiedzi")}
      <p>Model nie zmyśla odpowiedzi — składa je z konkretnych stron. Sprawdziliśmy
        każdą z najczęściej cytowanych i to, czy Państwa firma jest na niej wymieniona.
        Rozróżniamy przy tym dwie rzeczy, bo znaczą co innego: <b>ranking lub katalog</b>,
        na który da się wejść, i <b>strona konkurenta</b>, która z natury Państwa nie
        wymieni.</p>
      <div class="przewin"><table class="rejestr">
        <thead><tr><th>Źródło</th><th>Typ</th><th class="num">Cytowań</th><th>Jesteście?</th></tr></thead>
        <tbody>${r.obecnosc_w_zrodlach.map((x) => `
          <tr>
            <td><a href="${escAttr(x.url)}" target="_blank" rel="noopener">${esc(x.domena)}</a>
              ${x.tytul ? `<br><span class="skutek">${esc(przytnij(x.tytul, 90))}</span>` : ""}</td>
            <td class="skutek">${x.typ === "ranking" ? "ranking / katalog" : "strona firmy"}</td>
            <td class="num">${x.cytowan}</td>
            <td>${x.stan === "jest" ? `<span class="status jest">tak</span>`
                : x.stan === "brak" ? `<span class="status brak">nie</span>`
                : `<span class="skutek">nie udało się pobrać</span>`}</td>
          </tr>`).join("")}
        </tbody>
      </table></div>
      ${(() => {
        const rank = r.obecnosc_w_zrodlach.filter((x) => x.typ === "ranking" && x.stan === "brak");
        return rank.length
          ? `<p class="uwaga"><b>Do zrobienia od razu:</b> model cytuje
             ${rank.length === 1 ? "zestawienie" : `${rank.length} zestawienia`},
             na ${rank.length === 1 ? "którym" : "których"} Państwa nie ma —
             ${rank.map((x) => esc(x.domena)).join(", ")}. Obecność w takim miejscu
             wchodzi do odpowiedzi AI, bo model czyta je przy każdym podobnym pytaniu.</p>`
          : `<p class="hint">Wśród cytowanych źródeł nie ma rankingów ani katalogów —
             model składa odpowiedzi głównie ze stron samych firm. To zmienia kierunek
             działań: zamiast wchodzić na listy, trzeba zadbać o to, żeby własna strona
             była dla modeli czytelna i jednoznaczna.</p>`;
      })()}
    </section>` : ""}

    <!-- TECHNICZNE WARUNKI WIDOCZNOŚCI -->
    ${r.techniczne && r.techniczne.ustalenia && r.techniczne.ustalenia.length ? `
    <section class="r-strona">
      ${naglowekSekcji(++nr, r.techniczne.blokady
          ? "Dlaczego AI nie widzi strony" : "Techniczne warunki widoczności")}
      <p>Sprawdziliśmy bezpośrednio na Państwa stronie, czy roboty modeli AI mogą
        pobrać jej treść i czy znajdują na niej informacje potrzebne do zrozumienia,
        kim jest firma. Każde ustalenie poniżej jest wynikiem pomiaru.</p>
      <div class="liczby">
        ${liczba(r.techniczne.blokady, r.techniczne.blokady === 1 ? "blokada" : "blokady")}
        ${liczba(r.techniczne.braki, "braków do uzupełnienia")}
        ${liczba(r.techniczne.ok, "elementów poprawnych")}
      </div>
      ${r.techniczne.ustalenia.map((u) => `
        <div class="ustalenie ${esc(u.waga)}">
          <div class="ust-naglowek">
            <span class="ust-znacznik ${esc(u.waga)}">${
              u.waga === "blokada" ? "blokada" : u.waga === "brak" ? "do poprawy"
              : u.waga === "drobne" ? "bez wpływu" : "w porządku"}</span>
            <b>${esc(u.tytul)}</b>
          </div>
          <p>${esc(u.fakt)}</p>
          ${u.dowod ? `<pre class="dowod">${esc(u.dowod)}</pre>` : ""}
          ${u.co_zrobic ? `<p class="ust-rada"><span>Co z tym zrobić</span>${esc(u.co_zrobic)}</p>` : ""}
        </div>`).join("")}
    </section>` : ""}

    <!-- RYNEK CHATBOTÓW -->
    <section class="r-strona">
      ${naglowekSekcji(++nr, st.rynek_chatbotow.naglowek)}
      ${st.rynek_chatbotow.akapity.map((a) => `<p>${pogrub(a)}</p>`).join("")}
      <div class="slupki">${st.rynek_chatbotow.udzialy.map(([n, v]) => `
        <div class="slupek"><span class="slupek-nazwa">${esc(n)}</span>
          <div class="slupek-tor"><div class="slupek-wypeln" style="width:${v}%"></div></div>
          <span class="slupek-proc">${v}%</span></div>`).join("")}</div>
      <p class="zrodlo-danych">${esc(st.rynek_chatbotow.zrodlo)}</p>
      ${st.case && st.case.pokaz ? `<div class="wyimek">
        <div class="mono"><i class="sq"></i>${esc(st.case.naglowek)}</div>
        <p>${pogrub(st.case.tekst)}</p>
      </div>` : ""}
    </section>

    ${p.konkurenci.length ? `
    <section class="r-strona">
      ${naglowekSekcji(++nr, "Kto pojawia się zamiast Państwa")}
      <p>Marki, które modele AI wymieniały w odpowiedziach na te same pytania. Im wyżej,
        tym częściej AI poleca je zamiast Państwa firmy.</p>
      <table class="tabela-dok">
        <thead><tr><th class="w-nr">#</th><th>Marka</th><th class="pr">Wystąpień</th></tr></thead>
        <tbody>${p.konkurenci.map((k, i) => `
          <tr><td class="w-nr">${i + 1}</td><td><b>${esc(k.marka)}</b></td>
              <td class="pr">${k.wystapien}</td></tr>`).join("")}</tbody>
      </table>
    </section>` : ""}

    <div class="r-stopka">
      <span class="mono">Partner Tool · ICEA · ${esc(dzis)}</span>
      <span class="hint">koszt danych $${r.koszt_api} · saldo $${r.saldo_po}</span>
      <button class="akcja glowna drukuj" type="button">
        <svg class="ico sm"><use href="#i-print"/></svg>Drukuj / zapisz PDF</button>
    </div>
  </div>`;
}

function naglowekSekcji(nr, tytul) {
  return `<h2 class="r-h2"><span class="r-nr">${String(nr).padStart(2, "0")}</span>${esc(tytul)}</h2>`;
}

function liczba(wartosc, opis) {
  return `<div class="liczba"><b>${wartosc}</b><span>${esc(opis)}</span></div>`;
}

function promptHTML(w, marka) {
  // Przy kilku probach liczy sie NIE to, czy marka padla, tylko W ILU. 1 z 3 to
  // widocznosc przypadkowa i to jest inny wniosek niz 3 z 3 — a wyglada tak samo,
  // jesli pokazac samo "wymieniona".
  const wiele = w.prob > 1;
  const status = w.wspomniana
    ? `<span class="status jest">Marka wymieniona${wiele ? ` — ${w.trafien} z ${w.prob}` : ""}</span>`
    : `<span class="status brak">Marka nieobecna${wiele ? ` — 0 z ${w.prob}` : ""}</span>`;
  const chwiejna = wiele && w.trafien > 0 && w.trafien < w.prob;
  return `<article class="pytanie">
    <div class="pytanie-glowa">
      <h3>${esc(w.prompt)}</h3>
      ${status}${w.cytowana ? `<span class="status cyt">Strona cytowana</span>` : ""}
    </div>
    ${chwiejna ? `<p class="hint">Widoczność <b>przypadkowa</b>: przy tym samym pytaniu
      model raz wymienia markę, raz nie. To słabszy wynik niż stała obecność —
      i mocniejszy niż całkowity brak.</p>` : ""}
    <blockquote>${formatujOdpowiedz(w.odpowiedz, marka)}</blockquote>
    <div class="pytanie-meta">
      <span>${esc(w.model)}</span>
      ${w.marki.length ? `<span>Obok wymienione: ${w.marki.slice(0, 6).map(esc).join(" · ")}</span>` : ""}
      <span>${w.zrodla.length} źródeł</span>
    </div>
  </article>`;
}

function pogrub(t) { return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }

function formatujOdpowiedz(tekst, marka) {
  let t = pogrub(przytnij(tekst || "", 800));
  if (marka) {
    // podświetlamy nazwę marki — od razu widać, w którym miejscu odpowiedzi padła
    const bezpieczna = marka.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    t = t.replace(new RegExp("(" + bezpieczna + ")", "gi"), "<mark>$1</mark>");
  }
  return t;
}

// Ucinanie w połowie słowa („rozważyć inne firmy z Ka…") wygląda niechlujnie
// w dokumencie dla klienta. Tniemy na końcu zdania albo akapitu.
function przytnij(tekst, limit) {
  if (tekst.length <= limit) return tekst;
  const kawalek = tekst.slice(0, limit);
  const koniec = Math.max(
    kawalek.lastIndexOf(". "), kawalek.lastIndexOf(".\n"),
    kawalek.lastIndexOf("!"), kawalek.lastIndexOf("?"), kawalek.lastIndexOf("\n\n")
  );
  if (koniec > limit * 0.45) return kawalek.slice(0, koniec + 1) + " […]";
  const spacja = kawalek.lastIndexOf(" ");   // awaryjnie: przynajmniej całe słowo
  return kawalek.slice(0, spacja > 0 ? spacja : limit) + " […]";
}

// ══ SEKCJA: Eksport ══
function renderEksport() {
  const box = document.getElementById("eksport-box");
  const doEksportu = koszyk.filter((f) => (f.tryb || "partner") === tryb);
  if (!doEksportu.length) {
    box.innerHTML = przelacznikTrybu(koszyk) +
      `<div class="pusto">Brak firm w ścieżce <b>${TRYBY[tryb].nazwa}</b> —
       zaznacz „Dodaj do eksportu" na karcie firmy.</div>`;
    return;
  }
  const naglowki = kolumny.map((k) => `<th>${esc(k.naglowek)}</th>`).join("");
  const wiersze = doEksportu.map((f) =>
    `<tr>${kolumny.map((k) => {
      const v = komorka(f[k.klucz]);
      return `<td class="${v === BRAK ? "brak" : ""}">${esc(v)}</td>`;
    }).join("")}</tr>`).join("");

  box.innerHTML = przelacznikTrybu(koszyk) + `<div class="card">
    <div class="mono"><span class="sq"></span> Do eksportu — ${TRYBY[tryb].nazwa} (${doEksportu.length})</div>
    <p class="hint">Dokładnie te kolumny i wartości trafią do pliku CSV.</p>
    <div class="tabela-scroll"><table class="tabela">
      <thead><tr>${naglowki}</tr></thead><tbody>${wiersze}</tbody>
    </table></div>
    <button class="akcja glowna pobierz-csv" type="button" style="margin-top:18px"><svg class="ico sm"><use href="#i-download"/></svg>Pobierz CSV</button>
  </div>`;
}

function komorka(v) {
  if (Array.isArray(v)) return v.length ? v.join(", ") : BRAK;
  if (typeof v === "boolean") return v ? "TAK" : "NIE";
  return v ?? BRAK;
}

async function pobierzCSV() {
  const res = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // eksportujemy tylko aktywną ścieżkę — jeden plik CSV = jeden proces sprzedażowy
    body: JSON.stringify({ firmy: koszyk.filter((f) => (f.tryb || "partner") === tryb) }),
  });
  if (!res.ok) return alert("Nie udało się wyeksportować.");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "partnerzy.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

// ══ Pomocnicze ══
function odswiezBadge(id, ile) {
  const b = document.getElementById(id);
  b.textContent = ile;
  b.hidden = ile === 0;
}
function loadingHTML(tekst) {
  return `<div class="card loading"><div class="spinner"></div><p>${esc(tekst)}</p></div>`;
}
function errorHTML(msg) {
  return `<div class="card error"><div class="mono"><span class="sq"></span> Błąd</div><p>${esc(msg)}</p></div>`;
}
function hostname(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}
function esc(s) {
  return String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
function escAttr(s) { return esc(s).replace(/"/g, "&quot;"); }

renderResearchPanel();  // stan startowy


async function dodajWszystkieDoKolejki(przycisk) {
  // Zbieramy z aktualnie wyświetlonej listy, a nie z zapamiętanej odpowiedzi —
  // user mógł w międzyczasie kliknąć „Szukaj dalej" i lista urosła.
  const wiersze = [...przycisk.closest(".card").querySelectorAll(".sim-row[data-url]")];
  const firmy = wiersze.map((w) => ({
    url: w.dataset.url,
    nazwa: (w.querySelector(".sim-name")?.textContent || "").replace(/\s*(SEO|JUŻ ZBADANA[^]*)$/, "").trim(),
    opis: w.querySelector(".sim-opis")?.textContent || "",
    ma_seo: !!w.querySelector(".tag-seo"),
  }));
  const etykieta = przycisk.innerHTML;
  przycisk.disabled = true;
  przycisk.textContent = "Dodaję…";
  try {
    const doszlo = await dodajDoKolejki(firmy, przycisk.dataset.zapytanie,
      przycisk.dataset.kolejkaZrodlo, przycisk.dataset.kolejkaKategoria);
    // Mówimy ILE realnie doszło: reszta to firmy już zbadane albo już w kolejce.
    przycisk.innerHTML = doszlo
      ? `<svg class="ico xs"><use href="#i-check"/></svg>Dodano ${doszlo} z ${firmy.length}`
      : `<svg class="ico xs"><use href="#i-check"/></svg>Wszystkie już masz`;
  } catch (e) {
    przycisk.innerHTML = etykieta;
    alert("Nie udało się dodać do kolejki: " + e.message);
  } finally {
    przycisk.disabled = false;
  }
}

// ══ MODUŁ: MAILE ══════════════════════════════════════════════════════
// Osobna sekcja w „Pracy", a nie dodatek do karty firmy. Pisanie maila to własny
// etap pracy: wybierasz firmę, generujesz warianty, poprawiasz je poleceniem
// i wracasz do tego, co już napisałeś.
//
// Biblioteka trzyma KAŻDĄ wersję, nie tylko ostatnią. Poprawka bywa gorsza od
// oryginału, a bez historii nie da się do niego wrócić — ta sama zasada, co przy
// historii audytów.
let maileWybrana = null;      // id firmy, do której piszemy
let maileLista = [];          // biblioteka z bazy
let maileAktywny = null;      // id wersji otwartej do poprawiania

async function wczytajMaile() {
  try {
    const d = await (await fetch("/api/maile")).json();
    maileLista = (d.ok && d.maile) || [];
  } catch { maileLista = []; }
  odswiezBadge("badge-maile", maileTrybu().length);
}

function maileTrybu() {
  return maileLista.filter((m) => (m.tryb || "partner") === tryb);
}

function maileFirmy(url) {
  return maileTrybu().filter((m) => m.url === url);
}

// `cel` bierze się stąd, że ten sam widok żyje w dwóch miejscach: w przeglądzie
// wszystkich maili i w karcie jednej firmy. Bez parametru oba musiałyby użyć tego
// samego identyfikatora kontenera i przepisywałyby się nawzajem.
function renderMaile(cel = "maile-box") {
  const box = document.getElementById(cel);
  if (!box) return;
  const firmy = firmyTrybu();

  if (!firmy.length) {
    box.innerHTML = `<div class="pusto">
      <svg class="ico xl"><use href="#i-inbox"/></svg>
      <p>Najpierw zbadaj jakąś firmę.<br><span>Mail piszemy na podstawie tego,
        co wiemy z researchu — bez danych byłby ogólnikiem.</span></p></div>`;
    return;
  }

  // ── Widok zbiorczy: wszystkie szkice, pogrupowane po firmach ──
  // W menu „Maile" to jest PRZEGLĄD, nie warsztat. Wybór firmy byłby tu siódmym
  // pytaniem „którą firmę?" w aplikacji — a od tego właśnie odchodzimy. Pisze się
  // w karcie partnera; tutaj się patrzy na całość i decyduje, co wysłać.
  if (cel === "maile-box") {
    const zSzkicami = firmy.filter((t) => maileFirmy(t.firma.url).length);
    if (!zSzkicami.length) {
      box.innerHTML = `<div class="pusto">
        <svg class="ico xl"><use href="#i-mail"/></svg>
        <p>Nie ma jeszcze żadnego szkicu.<br><span>Maile pisze się w karcie partnera,
          w zakładce Maile — na podstawie tego, co wiemy z researchu.</span></p></div>`;
      return;
    }
    box.innerHTML = zSzkicami.map((t) => {
      const wersje = maileFirmy(t.firma.url);
      return `<div class="card">
        <div class="wzor-head">
          <div>
            <div class="firma-row-nazwa">${esc(t.firma.nazwa)}</div>
            <span class="firma-row-meta">${esc(hostname(t.firma.url))} · ${wersje.length} ${
              wersje.length === 1 ? "szkic" : "szkice"}</span>
          </div>
          <button class="btn-lekki otworz-maile-firmy" type="button" data-id="${t.id}">
            Otwórz w karcie<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>
        ${bibliotekaHTML(wersje)}
      </div>`;
    }).join("");
    return;
  }

  const wpis = firmy.find((t) => t.id === maileWybrana);

  // ── Krok 1: wybór firmy ──
  if (!wpis) {
    const ile = (t) => maileFirmy(t.firma.url).length;
    box.innerHTML = przelacznikTrybu(tabs) + `<div class="card">
      <div class="mono"><span class="sq"></span> Do kogo piszemy</div>
      <div class="similar-list">${firmy.map((t) => `
        <div class="sim-row wybierz-mail" data-id="${t.id}">
          <div class="sim-info">
            <span class="sim-name">${esc(t.firma.nazwa)}${
              ile(t) ? `<span class="tag-zbadana">${ile(t)} w bibliotece</span>` : ""}</span>
            <a class="sim-url">${esc(hostname(t.firma.url))} · ${esc(t.firma.branza)}</a>
            ${t.firma.persona_imie && t.firma.persona_imie !== BRAK
              ? `<span class="sim-opis">Osoba decyzyjna: ${esc(t.firma.persona_imie)}${
                  t.firma.persona_stanowisko && t.firma.persona_stanowisko !== BRAK
                    ? ` — ${esc(t.firma.persona_stanowisko)}` : ""}</span>`
              : `<span class="sim-opis brak-osoby">Brak osoby decyzyjnej w danych — mail wyjdzie bezosobowy.</span>`}
          </div>
          <button class="researchuj" type="button">Wybierz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>`).join("")}</div>
    </div>`;
    return;
  }

  // ── Krok 2: warianty i biblioteka ──
  const wersje = maileFirmy(wpis.firma.url);
  box.innerHTML = `
    <div class="card">
      <div class="mono"><span class="sq"></span> Piszemy do</div>
      <div class="wzor-head">
        <div>
          <div class="firma-row-nazwa">${esc(wpis.firma.nazwa)}</div>
          <span class="firma-row-meta">${esc(hostname(wpis.firma.url))} · ${esc(wpis.firma.branza)}</span>
        </div>
        <button class="btn-lekki zmien-mail-firme" type="button">Zmień firmę</button>
      </div>
      <button class="akcja glowna generuj-warianty" type="button" style="margin-top:16px">
        <svg class="ico sm"><use href="#i-mail"/></svg>${
          wersje.length ? "Wygeneruj nowe warianty" : "Wygeneruj 3 warianty"}
      </button>
      ${wersje.length ? "" : `<p class="hint">Trzy style naraz: rzeczowy, partnerski, ekspercki.
        Potem każdy da się poprawić poleceniem.</p>`}
    </div>
    <div id="maile-wynik"></div>
    ${wersje.length ? bibliotekaHTML(wersje) : ""}`;
}

function bibliotekaHTML(wersje) {
  return `<div class="card">
    <div class="mono"><span class="sq"></span> Biblioteka (${wersje.length})</div>
    <p class="hint">Każda wersja zostaje — także ta sprzed poprawki.</p>
    ${wersje.map(mailHTML).join("")}
  </div>`;
}

function mailHTML(m) {
  const otwarty = maileAktywny === m.id;
  return `<div class="mail-draft${otwarty ? " otwarty" : ""}" data-mail-id="${m.id}">
    <div class="mail-head">
      <span class="mail-styl">${esc(m.styl || "—")}</span>
      ${m.wyslany ? `<span class="tag-zbadana">wysłany</span>` : ""}
      <span class="mail-data">${esc((m.data || "").replace("T", " ").slice(0, 16))}</span>
      <div class="mail-akcje">
        <button class="kopiuj" type="button"><svg class="ico xs"><use href="#i-copy"/></svg>Kopiuj</button>
        <button class="btn-lekki popraw-mail" type="button">
          <svg class="ico xs"><use href="#i-arrow"/></svg>${otwarty ? "Zwiń" : "Popraw"}</button>
        <button class="btn-lekki oznacz-wyslany" type="button" title="Narzędzie nie widzi Twojej skrzynki — zaznacz sam">
          <svg class="ico xs"><use href="#i-check"/></svg>${m.wyslany ? "Cofnij" : "Wysłany"}</button>
        <button class="usun-z-kolejki usun-mail" type="button" title="Usuń wersję">
          <svg class="ico xs"><use href="#i-x"/></svg></button>
      </div>
    </div>
    ${m.polecenie ? `<p class="mail-polecenie">Poprawka: „${esc(m.polecenie)}"</p>` : ""}
    <pre class="mail-tresc">${esc(m.tresc)}</pre>
    ${otwarty ? `
      <div class="mail-czat">
        <input class="mail-polecenie-input" type="text" autocomplete="off"
               placeholder="Co poprawić? np. „skróć do 3 zdań", „mniej formalnie", „dodaj pytanie na koniec"">
        <button class="akcja glowna wyslij-poprawke" type="button">
          <svg class="ico sm"><use href="#i-arrow"/></svg>Popraw
        </button>
      </div>
      <p class="hint">Powstanie NOWA wersja — ta zostaje nietknięta.</p>` : ""}
  </div>`;
}

async function generujWarianty(przycisk) {
  const wpis = firmyTrybu().find((t) => t.id === maileWybrana);
  if (!wpis) return;
  const box = document.getElementById("maile-wynik");
  const etykieta = przycisk.innerHTML;
  przycisk.disabled = true;
  przycisk.textContent = "Piszę… (~20 s)";
  box.innerHTML = "";
  try {
    const res = await fetch("/api/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ firma: wpis.firma, tryb }),
    });
    const d = await res.json();
    if (!d.ok) { box.innerHTML = errorHTML(d.error); return; }
    await wczytajMaile();
    renderMaile();
  } catch (e) {
    box.innerHTML = errorHTML(e.message);
  } finally {
    przycisk.disabled = false;
    przycisk.innerHTML = etykieta;
  }
}

async function wyslijPoprawke(przycisk) {
  const draft = przycisk.closest(".mail-draft");
  const pole = draft.querySelector(".mail-polecenie-input");
  const polecenie = (pole.value || "").trim();
  if (!polecenie) { pole.focus(); return; }

  const etykieta = przycisk.innerHTML;
  przycisk.disabled = true;
  przycisk.textContent = "Poprawiam…";
  try {
    const res = await fetch("/api/email/popraw", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: Number(draft.dataset.mailId), polecenie }),
    });
    const d = await res.json();
    if (!d.ok) {
      draft.insertAdjacentHTML("beforeend", `<p class="sim-err">${esc(d.error)}</p>`);
      return;
    }
    await wczytajMaile();
    maileAktywny = d.mail.id;   // otwieramy nową wersję — na niej pracujemy dalej
    renderMaile();
  } catch (e) {
    draft.insertAdjacentHTML("beforeend", `<p class="sim-err">${esc(e.message)}</p>`);
  } finally {
    przycisk.disabled = false;
    przycisk.innerHTML = etykieta;
  }
}

async function zmienStanMaila(id, akcja, dane) {
  await fetch("/api/maile", {
    method: akcja,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, ...dane }),
  });
  await wczytajMaile();
  renderMaile();
}


// ══ RESEARCH MASOWY ═══════════════════════════════════════════════════
// Bez tego kolejka byla pulapka: user dodawal 50 firm i badal je po jednej,
// 30 sekund kazda. Front steruje rownoleglością sam, bez nowego endpointu —
// dzieki temu widac postep firma po firmie, a awaria jednej nie przerywa reszty.
//
// Trzy naraz, nie wiecej: kazda firma to scrape kilku podstron plus wywolanie
// modelu. Przy dziesieciu rownoleglych ryzykujemy limity OpenAI i to, ze scraper
// zacznie wygladac dla stron jak atak.
const MASOWO_NARAZ = 3;

async function zbadajZaznaczone(przycisk) {
  const doZbadania = kolejkaTrybu()
    .filter((k) => (!filtrKolejki || (k.kategoria || "Bez kategorii") === filtrKolejki))
    .filter((k) => kolejkaZaznaczone.has(k.url));
  if (!doZbadania.length) return;

  const postep = document.getElementById("masowy-postep");
  przycisk.disabled = true;
  const stan = new Map(doZbadania.map((k) => [k.url, "czeka"]));

  const rysuj = () => {
    const gotowe = [...stan.values()].filter((s) => s !== "czeka" && s !== "trwa").length;
    postep.innerHTML = `<div class="masowy-postep">
      <div class="mono">Zbadano ${gotowe} z ${doZbadania.length}</div>
      <div class="pasek-postepu"><i style="width:${Math.round(gotowe / doZbadania.length * 100)}%"></i></div>
      <div class="masowy-lista">${doZbadania.map((k) => {
        const s = stan.get(k.url);
        const ikona = s === "ok" ? "check" : s === "trwa" ? "clock" : s === "czeka" ? "clock" : "alert";
        return `<span class="masowy-poz ${s}"><svg class="ico xs"><use href="#i-${ikona}"/></svg>${
          esc(k.nazwa || hostname(k.url))}${s !== "ok" && s !== "czeka" && s !== "trwa"
            ? `<em title="${escAttr(s)}">— nie udało się</em>` : ""}</span>`;
      }).join("")}</div>
    </div>`;
  };
  rysuj();

  // Prosta pula: trzy watki biora kolejne pozycje z tej samej listy.
  const kolejkaDoZrobienia = [...doZbadania];
  async function watek() {
    while (kolejkaDoZrobienia.length) {
      const k = kolejkaDoZrobienia.shift();
      stan.set(k.url, "trwa"); rysuj();
      try {
        const d = await research(k.url);
        stan.set(k.url, d.ok ? "ok" : (d.error || "błąd"));
        if (d.ok) kolejkaZaznaczone.delete(k.url);
      } catch (e) {
        stan.set(k.url, e.message || "błąd sieci");
      }
      rysuj();
    }
  }
  await Promise.all(Array.from({ length: MASOWO_NARAZ }, watek));

  // Odswiezamy komplet: zbadane firmy znikaja z kolejki i pojawiaja sie w Firmach.
  await wczytajKolejke();
  await wczytajMaile();
  renderKolejke();
  const nieudane = [...stan.values()].filter((s) => s !== "ok").length;
  document.getElementById("masowy-postep").innerHTML = `<div class="masowy-postep">
    <div class="mono">Gotowe: ${doZbadania.length - nieudane} z ${doZbadania.length}${
      nieudane ? ` · ${nieudane} nie wyszło` : ""}</div>
    ${nieudane ? `<p class="hint">Nieudane zostają w kolejce — najczęściej strona blokuje
      bota albo nie odpowiada. Spróbuj pojedynczo później.</p>` : ""}
  </div>`;
}


// ══ CZAT DO POGŁĘBIENIA RESEARCHU ═════════════════════════════════════
// Historia trzymana w pamięci przeglądarki, per firma. Świadomie NIE w bazie:
// to narzędzie pracy nad jedną firmą, nie komunikator. Gdyby wnioski z rozmów
// okazały się warte zachowania, dołożymy tabelę — ale nie zakładamy tego z góry.
// ══ MODUŁ: AUDYT GEO ══════════════════════════════════════════════════
// Osobna zakładka, nie wariant mikroaudytu. Tamten mierzy SEO i GEO przez
// DataForSEO i pada, gdy skończą się środki. Ten mierzy WYŁĄCZNIE widoczność
// w odpowiedziach AI i chodzi na kluczach, które już mamy.
//
// Raport renderujemy tą samą funkcją co mikroaudyt (`raportHTML`) — sekcje SEO
// i AI Overviews po prostu się nie pojawią, bo nie ma dla nich danych. Dzięki temu
// obie zakładki wyglądają spójnie i poprawka w jednym miejscu działa na oba.
let geoWybrana = null;
let geoPowtorzenia = 2;
let geoIle = 8;
let geoSilniki = ["chatgpt_wprost", "claude_wprost"];
let geoPodpowiedzi = true;

// Tylko silniki na NASZYCH kluczach — to definicja tego audytu.
const GEO_SILNIKI = {
  chatgpt_wprost: { nazwa: "ChatGPT", opis: "86,4% polskiego rynku zapytań do AI" },
  claude_wprost: { nazwa: "Claude", opis: "0,71% rynku, ale drugi niezależny pomiar" },
};

function renderAudytGeo() {
  const box = document.getElementById("audytgeo-wybor");
  if (!box) return;
  const firmy = firmyTrybu();

  if (!firmy.length) {
    box.innerHTML = `<div class="pusto">
      <svg class="ico xl"><use href="#i-target"/></svg>
      <p>Najpierw zbadaj jakąś firmę.<br><span>Audyt opiera się na danych
        z researchu — bez nich nie ma z czego ułożyć pytań.</span></p></div>`;
    return;
  }

  const wpis = firmy.find((t) => t.id === geoWybrana);

  // ── Krok 1: wybór firmy ──
  if (!wpis) {
    box.innerHTML = `<div class="card">
      <div class="mono"><span class="sq"></span> Kogo audytujemy</div>
      <div class="similar-list">${firmy.map((t) => `
        <div class="sim-row wybierz-geo" data-id="${t.id}">
          <div class="sim-info">
            <span class="sim-name">${esc(t.firma.nazwa)}</span>
            <a class="sim-url">${esc(hostname(t.firma.url))} · ${esc(t.firma.branza)}</a>
          </div>
          <button class="researchuj" type="button">Wybierz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>`).join("")}</div>
    </div>`;
    return;
  }

  // ── Krok 2: konfiguracja ──
  // Koszt liczony z góry, bo płacimy za tokeny i rośnie iloczynem:
  // silniki × pytania × powtórzenia. Przy trzech próbach i dwóch modelach to
  // sześć wywołań na jedno pytanie i lepiej wiedzieć to PRZED kliknięciem.
  const wywolan = geoSilniki.length * geoIle * geoPowtorzenia;
  const koszt = (geoSilniki.reduce((s, k) =>
    s + (k === "claude_wprost" ? 0.035 : 0.012), 0) * geoIle * geoPowtorzenia).toFixed(2);

  box.innerHTML = `
    <div class="card">
      <div class="wzor-head">
        <div>
          <div class="firma-row-nazwa">${esc(wpis.firma.nazwa)}</div>
          <span class="firma-row-meta">${esc(hostname(wpis.firma.url))} · ${esc(wpis.firma.branza)}</span>
        </div>
        <button class="btn-lekki zmien-geo" type="button">Zmień firmę</button>
      </div>
    </div>

    <div class="card">
      <div class="mono"><i class="sq"></i>Które modele pytamy</div>
      <div class="akcje" style="margin-bottom:16px">
        ${Object.entries(GEO_SILNIKI).map(([k, s]) => `
          <label class="akcja check"><input type="checkbox" name="geo-silnik" value="${k}"
            ${geoSilniki.includes(k) ? "checked" : ""}> ${esc(s.nazwa)}
            <span class="cena">${esc(s.opis)}</span></label>`).join("")}
      </div>
      <p class="hint">Oba na naszych kluczach — ten audyt nie dotyka DataForSEO.
        Przy jednym modelu nie da się odróżnić jego cechy od stanu rynku: na tym samym
        pytaniu ChatGPT wymienił badaną firmę, a Claude nie i podał siedmiu konkurentów.</p>

      <div class="mono"><i class="sq"></i>Zakres</div>
      <div class="akcje" style="margin-bottom:14px">
        <label class="akcja check">
          <input type="range" id="geo-ile" min="4" max="30" value="${geoIle}" style="width:110px">
          <b>${geoIle}</b> pytań</label>
        <label class="akcja check" title="Modele są niedeterministyczne — ta sama fraza pytana ponownie daje inną odpowiedź">
          <input type="range" id="geo-powtorzenia" min="1" max="3" value="${geoPowtorzenia}" style="width:70px">
          pytaj <b>${geoPowtorzenia}×</b></label>
        <label class="akcja check"><input type="checkbox" id="geo-podpowiedzi"
          ${geoPodpowiedzi ? "checked" : ""}> Dołóż podpowiedzi Google</label>
      </div>
      <p class="hint">Powtórzenia to nie ozdoba: przy trzech próbach tego samego pytania
        model odpowiedział kolejno <b>nie, nie, tak</b>. Pojedynczy strzał był rzutem
        monetą — trzy dają uczciwe „1 z 3, widoczność przypadkowa".</p>

      <p class="hint">Szacowany koszt: <b class="cena-suma">$${koszt}</b>
        · ${wywolan} wywołań (${geoSilniki.length} modele × ${geoIle} pytań × ${geoPowtorzenia})
        · liczyć kilka minut.</p>
      <button class="akcja glowna generuj-geo" type="button" style="margin-top:8px"
        ${geoSilniki.length ? "" : "disabled"}>
        <svg class="ico sm"><use href="#i-target"/></svg>Zrób audyt GEO</button>
    </div>`;
}

async function generujAudytGeo(przycisk) {
  const wpis = firmyTrybu().find((t) => t.id === geoWybrana);
  if (!wpis) return;
  const box = document.getElementById("audytgeo-raport");
  const etykieta = przycisk.innerHTML;
  przycisk.disabled = true;
  przycisk.textContent = "Pytam modele… (kilka minut)";
  box.innerHTML = "";
  try {
    const res = await fetch("/api/audyt-geo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        firma: wpis.firma, ile_promptow: geoIle, powtorzenia: geoPowtorzenia,
        silniki: geoSilniki, podpowiedzi: geoPodpowiedzi,
      }),
    });
    const d = await res.json();
    if (!d.ok) { box.innerHTML = errorHTML(d.error); return; }
    // Raport zostaje w pamięci: dokument składamy z TYCH SAMYCH danych, bez
    // powtarzania pomiaru. Drugi audyt tej samej firmy kosztowałby znowu.
    geoRaport = d.raport;
    box.innerHTML = raportHTML(d.raport) + dokumentZAudytuHTML();
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    box.innerHTML = errorHTML(e.message);
  } finally {
    przycisk.disabled = false;
    przycisk.innerHTML = etykieta;
  }
}

// ══ MODUŁ: ROZMOWA O FIRMIE ═══════════════════════════════════════════
// Osobna sekcja, nie dodatek do karty firmy — ta sama zasada co przy mailach.
// Dopytywanie to własny etap pracy: wchodzisz, wybierasz firmę, rozmawiasz.
//
// Wątek trzymamy w pamięci przeglądarki, nie w bazie. To notatnik roboczy:
// utrwalamy to, co przeniesiesz do researchu, nie każdą próbę.
const czatHistoria = new Map();   // url firmy -> [{rola, tresc, zrodla}]
let rozmowaWybrana = null;        // id firmy, o której rozmawiamy

function renderRozmowa() {
  const box = document.getElementById("rozmowa-box");
  if (!box) return;
  const firmy = firmyTrybu();

  if (!firmy.length) {
    box.innerHTML = `<div class="pusto">
      <svg class="ico xl"><use href="#i-search"/></svg>
      <p>Najpierw zbadaj jakąś firmę.<br><span>Rozmowa opiera się na danych
        z researchu — bez nich agent nie ma od czego zacząć.</span></p></div>`;
    return;
  }

  const wpis = firmy.find((t) => t.id === rozmowaWybrana);

  // ── Krok 1: wybór firmy ──
  if (!wpis) {
    const ile = (t) => (czatHistoria.get(t.firma.url) || []).length;
    box.innerHTML = `<div class="card">
      <div class="mono"><span class="sq"></span> O której firmie rozmawiamy</div>
      <div class="similar-list">${firmy.map((t) => `
        <div class="sim-row wybierz-rozmowe" data-id="${t.id}">
          <div class="sim-info">
            <span class="sim-name">${esc(t.firma.nazwa)}${
              ile(t) ? `<span class="tag-zbadana">${ile(t)} w wątku</span>` : ""}</span>
            <a class="sim-url">${esc(hostname(t.firma.url))} · ${esc(t.firma.branza)}</a>
          </div>
          <button class="researchuj" type="button">Wybierz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>`).join("")}</div>
    </div>`;
    return;
  }

  // ── Krok 2: wątek ──
  box.innerHTML = `
    <div class="card">
      <div class="mono"><span class="sq"></span> Rozmawiamy o</div>
      <div class="wzor-head">
        <div>
          <div class="firma-row-nazwa">${esc(wpis.firma.nazwa)}</div>
          <span class="firma-row-meta">${esc(hostname(wpis.firma.url))} · ${esc(wpis.firma.branza)}</span>
        </div>
        <button class="btn-lekki zmien-rozmowe-firme" type="button">Zmień firmę</button>
      </div>
    </div>
    <div class="card czat-karta">
      <div class="czat-watek"></div>
      <div class="mail-czat">
        <input class="czat-pytanie" type="text" autocomplete="off"
               placeholder="np. czy obsługują B2B? jakie mają technologie? kto jest klientem?">
        <button class="akcja glowna czat-wyslij" type="button">
          <svg class="ico sm"><use href="#i-arrow"/></svg>Zapytaj
        </button>
      </div>
      <p class="hint">Agent czyta WYŁĄCZNIE strony w domenie tej firmy. Pod odpowiedzią
        stoi lista podstron, które faktycznie otworzył — pusta oznacza, że niczego
        nie sprawdził.</p>
    </div>`;
  rysujCzat(box.querySelector(".czat-watek"), czatHistoria.get(wpis.firma.url) || [], false);
}

// Enter wysyla pytanie. W czacie to odruch — bez tego trzeba siegac myszka po
// kazdym zdaniu, a rozmowa ma byc szybsza od klikania po karcie firmy.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.classList.contains("czat-pytanie")) return;
  e.preventDefault();
  const b = e.target.closest(".czat-karta").querySelector(".czat-wyslij");
  if (b && !b.disabled) czatZapytaj(b);
});

async function czatZapytaj(przycisk) {
  const wpis = firmyTrybu().find((t) => t.id === rozmowaWybrana);
  if (!wpis) return;
  const karta = przycisk.closest(".czat-karta");
  const pole = karta.querySelector(".czat-pytanie");
  const watek = karta.querySelector(".czat-watek");
  const pytanie = (pole.value || "").trim();
  if (!pytanie) { pole.focus(); return; }

  const firma = wpis.firma;
  const klucz = firma.url;
  const hist = czatHistoria.get(klucz) || [];
  hist.push({ rola: "user", tresc: pytanie });
  czatHistoria.set(klucz, hist);
  pole.value = "";
  rysujCzat(watek, hist, true);

  przycisk.disabled = true;
  try {
    const res = await fetch("/api/czat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ firma, pytanie, historia: hist.slice(0, -1) }),
    });
    const d = await res.json();
    hist.push(d.ok
      ? { rola: "agent", tresc: d.odpowiedz, zrodla: d.zrodla || [] }
      : { rola: "agent", tresc: "Nie udało się: " + d.error, blad: true });
  } catch (e) {
    hist.push({ rola: "agent", tresc: "Nie udało się: " + e.message, blad: true });
  } finally {
    czatHistoria.set(klucz, hist);
    rysujCzat(watek, hist, false);
    przycisk.disabled = false;
  }
}

function rysujCzat(watek, hist, czeka) {
  watek.innerHTML = hist.map((w) => w.rola === "user"
    ? `<div class="czat-pytanie-wiersz">${esc(w.tresc)}</div>`
    : `<div class="czat-odpowiedz${w.blad ? " blad" : ""}">
         <pre>${esc(w.tresc)}</pre>
         ${(w.zrodla || []).length ? `<div class="czat-zrodla">
           ${w.zrodla.map((u) => `<a href="${escAttr(u)}" target="_blank" rel="noopener">${esc(hostname(u) + new URL(u).pathname)}</a>`).join("")}
         </div>` : ""}
       </div>`).join("")
    + (czeka ? `<div class="czat-odpowiedz czeka"><pre>Czytam ich stronę…</pre></div>` : "");
  watek.scrollTop = watek.scrollHeight;
}

// ══════════════════════════════════════════════════════════════════
//  DOKUMENT DLA KLIENTA PARTNERA
// ══════════════════════════════════════════════════════════════════
// Materiał wysyłany przez partnera DALEJ — do jego klienta. Wzór (ICEA) zostaje
// nietknięty; pod konkretną parę piszemy trzy sekcje. Szczegóły: backend/dokument.py.
let dokWybrana = null;      // id partnera
let dokKlient = "";         // nazwa klienta partnera
let dokKlientUrl = "";      // jego strona — bez niej nie ma czego sprawdzić
let dokHtml = null;         // ostatnio wygenerowany plik
let dokPlik = "";

function renderDokument() {
  const box = document.getElementById("dokument-wybor");
  if (!box) return;
  const firmy = firmyTrybu();

  if (!firmy.length) {
    box.innerHTML = `<div class="pusto">
      <svg class="ico xl"><use href="#i-inbox"/></svg>
      <p>Najpierw zbadaj partnera.<br><span>Dokument opiera się na tym, co partner
        realnie robi — bez researchu nie ma z czego pisać.</span></p></div>`;
    return;
  }

  const wpis = firmy.find((t) => t.id === dokWybrana);

  // ── Krok 1: dla którego partnera piszemy ──
  if (!wpis) {
    box.innerHTML = `<div class="card">
      <div class="mono"><span class="sq"></span> 1. Od kogo ten materiał idzie</div>
      <p class="hint">To partner wysyła dokument swojemu klientowi. My piszemy tekst,
        który on może podpisać.</p>
      <div class="similar-list">${firmy.map((t) => `
        <div class="sim-row wybierz-dok" data-id="${t.id}">
          <div class="sim-info">
            <span class="sim-name">${esc(t.firma.nazwa)}</span>
            <a class="sim-url">${esc(hostname(t.firma.url))} · ${esc(t.firma.branza)}</a>
          </div>
          <button class="researchuj" type="button">Wybierz<svg class="ico xs"><use href="#i-arrow"/></svg></button>
        </div>`).join("")}</div>
    </div>`;
    return;
  }

  // Klienci partnera pochodzą z `case_studies` — jedynego miejsca w researchu,
  // gdzie zapisujemy, dla kogo partner pracował. Pusta lista to nie błąd: nie
  // każdy partner pokazuje realizacje. Wtedy nazwę wpisuje człowiek.
  const klienci = (wpis.firma.case_studies || []).filter((c) => c && c !== BRAK);

  box.innerHTML = `
    <div class="card">
      <div class="wzor-head">
        <div>
          <div class="firma-row-nazwa">${esc(wpis.firma.nazwa)}</div>
          <span class="firma-row-meta">${esc(hostname(wpis.firma.url))} · ${esc(wpis.firma.branza)}</span>
        </div>
        <button class="btn-lekki zmien-dok" type="button">Zmień partnera</button>
      </div>
    </div>

    <div class="card">
      <div class="mono"><i class="sq"></i>2. Do którego klienta partnera</div>
      ${klienci.length ? `
        <p class="hint">Z realizacji partnera. Kliknij, żeby wstawić nazwę.</p>
        <div class="tagi wybieralne">${klienci.map((k) => `
          <button class="tag${dokKlient === k ? " zaznaczony" : ""}" type="button"
                  data-dok-klient="${escAttr(k)}">${esc(k)}</button>`).join("")}</div>`
        : `<p class="hint">Research nie zapisał realizacji tego partnera — wpisz klienta ręcznie.</p>`}
      <div class="akcje" style="margin:14px 0 10px">
        <input type="text" id="dok-klient" placeholder="Nazwa klienta" value="${escAttr(dokKlient)}">
        <input type="text" id="dok-klient-url" placeholder="https://strona-klienta.pl" value="${escAttr(dokKlientUrl)}">
      </div>
      <p class="hint">Adres strony jest potrzebny do mikroaudytu: sprawdzamy, czy roboty
        AI mają na nią wstęp. Bez adresu dokument powstanie, ale bez tej części.</p>

      <button class="akcja glowna generuj-dokument" type="button" ${dokKlient.trim() ? "" : "disabled"}>
        <svg class="ico sm"><use href="#i-inbox"/></svg>Generuj dokument
      </button>
      <p class="hint">Koszt: 3 pytania do ChatGPT + jedno napisanie tekstu. Około $0,05.
        Case study, nagroda i identyfikacja ICEA zostają w dokumencie bez zmian.</p>
    </div>`;

  // Kursor w polu, w którym user pisał — inaczej po każdym znaku ucieka na początek.
  const aktywne = document.activeElement;
  if (aktywne && aktywne.id === "dok-klient") document.getElementById("dok-klient").focus();
}

async function generujDokument(przycisk) {
  const wpis = firmyTrybu().find((t) => t.id === dokWybrana);
  if (!wpis) return;
  const wynik = document.getElementById("dokument-wynik");
  przycisk.disabled = true;
  wynik.innerHTML = loadingHTML("Pytam ChatGPT o kategorię klienta, sprawdzam roboty i piszę tekst… ~60 s.");
  try {
    const res = await fetch("/api/dokument", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        firma: wpis.firma,
        klient: { nazwa: dokKlient.trim(), url: dokKlientUrl.trim() },
      }),
    });
    const d = await res.json();
    if (!d.ok) { wynik.innerHTML = errorHTML(d.error); return; }

    dokHtml = d.html;
    dokPlik = d.plik;
    const b = d.badanie || {};
    wynik.innerHTML = `<div class="card">
      <div class="mono"><i class="sq"></i>Gotowe</div>
      <p class="hint">Pomiar, który wszedł do dokumentu: marka klienta padła w
        <b>${b.wspomniana} z ${b.prob}</b> odpowiedzi ChatGPT.
        ${(b.konkurenci || []).length ? `Zamiast niej wymienione: ${esc((b.konkurenci || []).join(", "))}.` : ""}</p>
      <ul class="hint">${(b.pytania || []).map((p) => `<li>„${esc(p)}"</li>`).join("")}</ul>
      <div class="akcje">
        <button class="akcja glowna pobierz-dokument" type="button">
          <svg class="ico sm"><use href="#i-table"/></svg>Pobierz plik</button>
        <button class="akcja podglad-dokument" type="button">
          <svg class="ico sm"><use href="#i-external"/></svg>Otwórz podgląd</button>
      </div>
    </div>`;
  } catch (e) {
    wynik.innerHTML = errorHTML(e.message);
  } finally {
    przycisk.disabled = false;
  }
}

function plikDokumentu(pobierz) {
  if (!dokHtml) return;
  const blob = new Blob([dokHtml], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  if (pobierz) {
    const a = document.createElement("a");
    a.href = url;
    a.download = dokPlik || "dokument.html";
    a.click();
  } else {
    window.open(url, "_blank");
  }
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}


// ══ DOKUMENT Z AUDYTU GEO ═════════════════════════════════════════════
// Zakładka pokazuje raport w narzędziu. To robi z niego PLIK do wysłania:
// ten sam wzór co materiał dla klienta partnera, wykresy z pomiaru, pełne
// odpowiedzi modeli. Szczegóły składania: backend/raport_geo.py.
let geoRaport = null;      // ostatni raport z audytu — źródło dokumentu
let geoDokHtml = null;     // wygenerowany plik
let geoDokPlik = "";

function dokumentZAudytuHTML() {
  return `<div class="card">
    <div class="mono"><i class="sq"></i>Dokument do wysłania</div>
    <p class="hint">Ten sam raport na wzorze ICEA: wykresy z pomiaru, konkurenci,
      źródła, ustalenia techniczne i pełne odpowiedzi modeli. Case study i identyfikacja
      zostają bez zmian. Pomiar jest już zrobiony — płacimy tylko za napisanie tekstu.</p>
    <div class="akcje">
      <button class="akcja glowna zrob-dokument-audyt" type="button">
        <svg class="ico sm"><use href="#i-inbox"/></svg>Zrób z tego dokument</button>
    </div>
    <div id="dokument-audyt-wynik"></div>
  </div>`;
}

async function zrobDokumentZAudytu(przycisk) {
  if (!geoRaport) return;
  const wynik = document.getElementById("dokument-audyt-wynik");
  przycisk.disabled = true;
  wynik.innerHTML = loadingHTML("Piszę dokument z tego audytu… ~40 s.");
  try {
    const res = await fetch("/api/dokument-audyt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raport: geoRaport }),
    });
    const d = await res.json();
    if (!d.ok) { wynik.innerHTML = errorHTML(d.error); return; }
    geoDokHtml = d.html;
    geoDokPlik = d.plik;
    wynik.innerHTML = `<div class="akcje" style="margin-top:12px">
      <button class="akcja glowna pobierz-dokument-audyt" type="button">
        <svg class="ico sm"><use href="#i-table"/></svg>Pobierz plik</button>
      <button class="akcja podglad-dokument-audyt" type="button">
        <svg class="ico sm"><use href="#i-external"/></svg>Otwórz podgląd</button>
    </div>`;
  } catch (e) {
    wynik.innerHTML = errorHTML(e.message);
  } finally {
    przycisk.disabled = false;
  }
}

function plikDokumentuAudytu(pobierz) {
  if (!geoDokHtml) return;
  const blob = new Blob([geoDokHtml], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  if (pobierz) {
    const a = document.createElement("a");
    a.href = url;
    a.download = geoDokPlik || "audyt.html";
    a.click();
  } else {
    window.open(url, "_blank");
  }
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}


// ══════════════════════════════════════════════════════════════════════
//  KARTA FIRMY — jedno miejsce pracy nad jednym partnerem
// ══════════════════════════════════════════════════════════════════════
// Wcześniej każde narzędzie zaczynało od pytania „którą firmę?" i sześć pozycji
// w menu robiło dokładnie to samo: pokazywało listę do wyboru. Firmę wybiera się
// teraz raz, wchodząc w nią z listy — a narzędzia są w zakładkach jej karty
// i dostają ją w stanie, bez pytania.
const ZAKLADKI_KARTY = [
  { id: "przeglad", nazwa: "Przegląd" },
  { id: "widocznosc", nazwa: "Widoczność" },
  { id: "synergia", nazwa: "Synergia" },
  { id: "maile", nazwa: "Maile" },
  { id: "dokumenty", nazwa: "Materiały" },
];
let kartaZakladka = "przeglad";

function kartaFirma() {
  return tabs.find((t) => t.id === activeId) || null;
}

function renderKarte() {
  const wpis = kartaFirma();
  const box = document.getElementById("firmy-detal");
  if (!wpis || !box) return;
  const f = wpis.firma;
  const wKoszyku = koszyk.some((k) => k.url === f.url);
  const ileMaili = maileFirmy(f.url).length;

  const droga = [f.kategoria && f.kategoria !== BRAK ? f.kategoria : null,
                 f.miasto && f.miasto !== BRAK ? f.miasto : null]
    .filter(Boolean).map(esc).join(" · ");

  box.innerHTML = `
    <button class="wroc wroc-do-listy" type="button">
      <svg class="ico xs"><use href="#i-back"/></svg>Wszyscy partnerzy</button>

    <div class="karta-head">
      <div class="karta-gora">
        <div>
          <div class="karta-eyebrow"><i class="sq"></i>Profil partnera${droga ? " · " + droga : ""}</div>
          <h1 class="karta-tytul">${esc(f.nazwa)}</h1>
          <a class="karta-url" href="${escAttr(f.url)}" target="_blank" rel="noopener">
            ${esc(hostname(f.url))}<svg class="ico xs"><use href="#i-external"/></svg></a>
        </div>
        <div class="karta-akcje">
          <button class="akcja podobne-do-tej" type="button">
            <svg class="ico sm"><use href="#i-target"/></svg>Znajdź podobne</button>
          <label class="akcja check">
            <input type="checkbox" class="do-eksportu" ${wKoszyku ? "checked" : ""}> W eksporcie
          </label>
          <button class="usun" type="button" data-usun="${wpis.id}" title="Usuń z listy">
            <svg class="ico xs"><use href="#i-x"/></svg></button>
        </div>
      </div>
      <div class="zakladki" role="tablist">
        ${ZAKLADKI_KARTY.map((z) => `
          <button class="zakladka ${kartaZakladka === z.id ? "aktywna" : ""}"
                  data-karta-tab="${z.id}" type="button" role="tab">${z.nazwa}${
            z.id === "maile" && ileMaili ? `<em>${ileMaili}</em>` : ""
          }</button>`).join("")}
      </div>
    </div>

    <div id="karta-pane" class="karta-pane aktywna"></div>`;

  renderKartaPane();
}

// Narzędzia dostają firmę przez swój stan — ten sam, którego używały przy wyborze
// z listy. Dzięki temu nie trzeba ich przepisywać: pomijają krok „wybierz firmę",
// bo firma jest już wybrana.
function renderKartaPane() {
  const wpis = kartaFirma();
  const pane = document.getElementById("karta-pane");
  if (!wpis || !pane) return;
  const id = wpis.id;

  if (kartaZakladka === "przeglad") {
    pane.innerHTML = przegladHTML(wpis.firma);
    return;
  }

  if (kartaZakladka === "widocznosc") {
    geoWybrana = id;
    audytWybrana = id;
    pane.innerHTML = `
      <div class="wiodacy" style="margin-bottom:18px">Dwa pomiary tej samej rzeczy z dwóch stron:
        pierwszy pyta modele naszymi kluczami, drugi dokłada dane z wyszukiwarki.</div>
      <div class="mono" style="margin-bottom:10px"><i class="sq"></i>Audyt GEO — widoczność w odpowiedziach AI</div>
      <div id="audytgeo-wybor"></div>
      <div id="audytgeo-raport"></div>
      <div class="mono" style="margin:34px 0 10px"><i class="sq"></i>Mikroaudyt SEO/GEO — z danymi z wyszukiwarki</div>
      <div id="audyt-wybor"></div>
      <div id="audyt-raport"></div>`;
    renderAudytGeo();
    renderAudyt();
    return;
  }

  if (kartaZakladka === "synergia") {
    rozmowaWybrana = id;
    pane.innerHTML = `<div id="rozmowa-box"></div>`;
    renderRozmowa();
    return;
  }

  if (kartaZakladka === "maile") {
    maileWybrana = id;
    pane.innerHTML = `<div id="karta-maile-box"></div>`;
    renderMaile("karta-maile-box");
    return;
  }

  if (kartaZakladka === "dokumenty") {
    dokWybrana = id;
    pane.innerHTML = `<div id="dokument-wybor"></div><div id="dokument-wynik"></div>`;
    renderDokument();
  }
}

// ── Przegląd: profil czytany jak materiał, nie jak formularz ─────────
// Research zbiera kilkanaście pól i wcześniej wszystkie leżały obok siebie
// w jednej siatce — czytało się to jak zrzut z bazy. Tu jest kolejność: kim ta
// firma jest, co robi, co zrobiła, a dopiero na końcu dane rejestrowe.
function przegladHTML(f) {
  const ma = (x) => x && x !== BRAK;
  const uslugi = (f.uslugi || []).filter(ma);
  const realizacje = (f.case_studies || []).filter(ma);
  const zrodla = (f.zrodlo_danych || []).filter(Boolean);

  const liczby = [
    [realizacje.length ? String(realizacje.length) : (ma(f.liczba_projektow) ? esc(f.liczba_projektow) : "—"),
     realizacje.length ? "Opisanych realizacji" : "Liczba projektów",
     realizacje.length ? "z researchu strony" : "deklaracja firmy"],
    [ma(f.wielkosc_zespolu) ? esc(f.wielkosc_zespolu) : "—", "Wielkość zespołu", "deklaracja firmy"],
    [String(uslugi.length || "—"), "Usług w ofercie", "zebranych z serwisu"],
  ];

  const sekcja = (etykieta, tytul, podpis, tresc) => !tresc ? "" : `
    <section class="prz-sekcja">
      <div>
        <div class="karta-eyebrow">${esc(etykieta)}</div>
        <h2>${esc(tytul)}</h2>
        ${podpis ? `<p class="prz-podpis">${esc(podpis)}</p>` : ""}
      </div>
      <div>${tresc}</div>
    </section>`;

  // SZEŚĆ I RESZTA POD PRZYCISKIEM. Zmierzone na Sellision: 20 usług i 13 realizacji
  // to 33 ponumerowane wiersze jeden pod drugim — lista, której nikt nie czyta,
  // tylko przewija. Pierwsze sześć mówi, czym firma jest; reszta jest na żądanie.
  const PELNA_LISTA = 6;
  const numerowane = (pozycje) => {
    const wiersz = (x, i) => `
      <div class="prz-poz">
        <span class="prz-nr">${String(i + 1).padStart(2, "0")}</span>
        <div><h3>${esc(x)}</h3></div>
      </div>`;
    if (pozycje.length <= PELNA_LISTA) return pozycje.map(wiersz).join("");
    const reszta = pozycje.length - PELNA_LISTA;
    return pozycje.slice(0, PELNA_LISTA).map(wiersz).join("")
      + `<div class="prz-reszta" hidden>${
          pozycje.slice(PELNA_LISTA).map((x, i) => wiersz(x, i + PELNA_LISTA)).join("")}</div>`
      + `<button class="prz-wiecej" type="button"
          data-etykieta="Pokaż pozostałe <em>+${reszta}</em>">Pokaż pozostałe
          <em>+${reszta}</em></button>`;
  };

  return `
    <div class="prz-hero">
      <div>
        <p class="prz-lead">${esc(f.opis)}</p>
        ${ma(f.seo_zakres) ? `<p class="uzasadnienie"><span class="etyk">Zakres SEO</span> ${esc(f.seo_zakres)}</p>` : ""}
        <div class="akcje" style="margin-top:16px">
          <a class="akcja" href="${escAttr(f.url)}" target="_blank" rel="noopener">
            <svg class="ico sm"><use href="#i-external"/></svg>Odwiedź stronę</a>
        </div>
      </div>
      <div class="card" style="margin:0">
        <div class="mono"><i class="sq"></i>Co o niej wiemy</div>
        <div class="pola" style="margin-top:12px">
          ${pole("Branża", f.branza)}
          ${pole("Kategoria", f.kategoria)}
          ${pole("Miasto", f.miasto)}
        </div>
        <p class="hint" style="margin-top:10px">${
          f.ma_seo
            ? "Ma SEO w ofercie — to fakt z opisu, nie ocena. Czy to konkurent, czy partner, rozstrzygasz Ty."
            : "Bez SEO w ofercie — uzupełniamy to, czego nie robi."
        }</p>
      </div>
    </div>

    <div class="prz-liczby">
      ${liczby.map(([b, opis, drobne]) => `
        <div class="prz-liczba"><b>${b}</b><span>${esc(opis)}</span><em>${esc(drobne)}</em></div>`).join("")}
    </div>

    ${sekcja("Zakres kompetencji", "Usługi i specjalizacje",
             "Zebrane z serwisu firmy, nie z katalogu.",
             uslugi.length ? numerowane(uslugi) : "")}

    ${sekcja("Udokumentowana praca", "Wybrane realizacje",
             "To, co firma sama pokazuje jako swoje.",
             realizacje.length ? numerowane(realizacje) : "")}

    ${sekcja("Kontakt i dane", "Z kim i z czym rozmawiamy", "",
      `<div class="prz-dane">
        ${pole("Osoba decyzyjna", f.persona_imie)}
        ${pole("Stanowisko", f.persona_stanowisko)}
        ${pole("Email osoby", f.persona_email)}
        ${pole("Telefon osoby", f.persona_telefon)}
        ${pole("Email firmy", f.email)}
        ${pole("Telefon firmy", f.telefon)}
        ${pole("Nazwa prawna", f.nazwa_prawna)}
        ${pole("NIP", f.nip)}
        ${pole("Adres", f.adres)}
      </div>`)}

    ${sekcja("Skąd to wiemy", "Źródła",
             "Podstrony, z których zebraliśmy dane. Każdą można sprawdzić.",
      zrodla.length ? `<ul class="zrodla-lista">${zrodla.map((u) =>
        `<li><a href="${escAttr(u)}" target="_blank" rel="noopener">${esc(u)}</a></li>`).join("")}</ul>` : "")}
  `;
}

// ══════════════════════════════════════════════════════════════════════
//  POZYSKIWANIE — trzy wejścia, jedna robota
// ══════════════════════════════════════════════════════════════════════
let pozZakladka = "url";

function renderPozyskiwanie() {
  document.querySelectorAll("#poz-zakladki .zakladka").forEach((b) =>
    b.classList.toggle("aktywna", b.dataset.poz === pozZakladka));
  document.querySelectorAll(".poz-panel").forEach((x) =>
    x.classList.toggle("aktywna", x.dataset.poz === pozZakladka));

  if (pozZakladka === "url") renderResearchPanel();
  if (pozZakladka === "branza") renderPresety();
  if (pozZakladka === "podobne") renderPodobne();
}

// ══════════════════════════════════════════════════════════════════════
//  AUDYTY — widok przekrojowy
// ══════════════════════════════════════════════════════════════════════
// Pojedynczy audyt robi się w karcie firmy. Tutaj widać, kto i kiedy był badany,
// bo tego z karty nie da się zobaczyć: żeby porównać dwa pomiary, trzeba wyjść
// ponad jedną firmę.
async function renderAudyty() {
  const box = document.getElementById("audyty-box");
  if (!box) return;
  box.innerHTML = loadingHTML("Wczytuję historię pomiarów…");
  try {
    const d = await (await fetch("/api/audyty")).json();
    const wszystkie = d.audyty || [];
    if (!wszystkie.length) {
      box.innerHTML = `<div class="pusto">
        <svg class="ico xl"><use href="#i-chart"/></svg>
        <p>Żaden audyt nie został jeszcze zapisany.<br><span>Audyt robi się w karcie
          partnera, w zakładce Widoczność.</span></p></div>`;
      return;
    }

    // Grupujemy po firmie, bo drugi pomiar tej samej firmy jest wart czegoś tylko
    // w zestawieniu z pierwszym.
    const wg = new Map();
    wszystkie.forEach((a) => {
      const k = a.url || "—";
      if (!wg.has(k)) wg.set(k, []);
      wg.get(k).push(a);
    });

    box.innerHTML = [...wg.entries()].map(([url, lista]) => {
      const wpis = tabs.find((t) => t.firma.url === url);
      const nazwa = wpis ? wpis.firma.nazwa : hostname(url);
      return `<div class="card">
        <div class="wzor-head">
          <div>
            <div class="firma-row-nazwa">${esc(nazwa)}</div>
            <span class="firma-row-meta">${esc(hostname(url))} · ${lista.length} ${
              lista.length === 1 ? "pomiar" : "pomiary"}</span>
          </div>
          ${wpis ? `<button class="btn-lekki otworz-firme-z-audytu" type="button"
            data-id="${wpis.id}">Otwórz kartę<svg class="ico xs"><use href="#i-arrow"/></svg></button>` : ""}
        </div>
        <table class="tabela"><thead><tr>
          <th>Kiedy</th><th>Czym</th><th>Ścieżka</th></tr></thead>
        <tbody>${lista.map((a) => `<tr>
          <td>${esc((a.data || "").slice(0, 16).replace("T", ", "))}</td>
          <td>${esc(a.dostawca === "geo" ? "Audyt GEO (nasze klucze)" : "Mikroaudyt SEO/GEO")}</td>
          <td>${esc(TRYBY[a.tryb]?.nazwa || a.tryb || "—")}</td>
        </tr>`).join("")}</tbody></table>
      </div>`;
    }).join("");
  } catch (e) {
    box.innerHTML = errorHTML(e.message);
  }
}

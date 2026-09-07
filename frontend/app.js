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
let tryb = "partner";
// Dla której ścieżki narysowano wspólne sekcje. Bez tego nie da się poznać, że
// user JUŻ przełączył ścieżkę, a na ekranie wisi jeszcze zawartość poprzedniej.
let trybPokazany = "partner";
// Zawężenie listy firm ustawiane przez kafel „z SEO w ofercie". null = pełna lista.
// Świadomie NIE jest trwałe: wejście do Firm z menu i zmiana ścieżki je zdejmują,
// żeby nikt nie oglądał niepełnej listy, nie wiedząc dlaczego.
let filtrFirm = null;
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
      document.getElementById("panels").insertAdjacentHTML("beforeend", panelHTML(id, f));
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
    trybPokazany = tryb;
  }

  if (nazwa === "research") renderResearchPanel();
  if (nazwa === "szukaj") renderPresety();   // inne kategorie dla partnera, inne dla klienta
  if (nazwa === "eksport") renderEksport();
  if (nazwa === "podobne") renderPodobne();
  if (nazwa === "audyt") renderAudyt();
  if (nazwa === "firmy") pokazListe();  // wejście z menu zawsze pokazuje listę

  // Liczniki w menu też są per-ścieżka — bez tego pokazują stan poprzedniej.
  odswiezBadge("badge-firmy", firmyTrybu().length);
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
  // Rozkład tej listy: 11 firm buduje strony i sklepy, 7 to marketing, 6 doradztwo,
  // 4 branding, 3 narzędzia. Presety odwzorowują te proporcje.
  //
  // Dwie firmy z listy (webmetric.com, stonehengeagency.com) SPRZEDAJĄ SEO i mimo to
  // są dobrymi partnerami. Dlatego odsiew konkurentów został usunięty, a SEO jest
  // tylko tagiem — patrz DECISIONS 2026-09-04.
  partner: [
    ["Budowa stron i sklepów", "agencja e-commerce", [
      "wdrożenia Shopify", "wdrożenia PrestaShop", "wdrożenia WooCommerce",
      "wdrożenia IdoSell", "tworzenie sklepów internetowych",
      "projektowanie stron internetowych", "software house", "agencja interaktywna",
      // Z usług 9 zbadanych partnerów: platformę B2B ma 4 z nich (Tebim, Devisu,
      // Sellision, wecanfly), aplikacje mobilne 2. Migracje to u wecanfly osobna
      // linia — pięć usług (WooCommerce, Magento, BigCommerce, Shopware, WordPress
      // -> Shopify). Sklep po migracji zawsze traci widoczność, więc to naturalny
      // moment na rozmowę o SEO.
      "platforma B2B", "migracja sklepu internetowego", "aplikacje mobilne",
    ]],
    ["Utrzymanie i administracja", "opieka nad stroną internetową", [
      // webinity.pl: opieka nad dziesiątkami serwisów naraz, bez budowania nowych.
      // Kategorie white-label ("white label WordPress", "podwykonawca dla agencji")
      // usunięte na wyraźną decyzję Adama 04.09.2026 — mimo że bravenew.agency
      // z jego listy tak się opisuje.
      "opieka nad stroną WordPress", "administracja sklepem internetowym",
    ]],
    ["Strategia i doradztwo", "konsulting e-commerce", [
      "doradztwo e-commerce", "digital advisory", "interim management e-commerce",
      "konsulting wzrostu e-commerce", "doradztwo strategiczne", "audyt e-commerce",
      "doradztwo marketingowe", "doradztwo biznesowe",
      "zarządzanie projektami IT", "analityka internetowa",
    ]],
    ["Branding i kreacja", "agencja brandingowa", [
      "agencja brandingowa", "agencja kreatywna", "branding produktowy",
      // brantt ma w usługach „opracowanie strategii marki" i „budowa marki",
      // adream „strategia komunikacji marki" — a żaden preset tego nie łapał.
      // To praca sprzed identyfikacji wizualnej, robią ją inne firmy.
      "strategia marki",
      "projektowanie opakowań", "identyfikacja wizualna", "studio graficzne",
      "agencja UX/UI", "optymalizacja konwersji CRO", "produkcja wideo",
      "fotografia produktowa",
    ]],
    ["Marketing poza SEO", "agencja marketingowa", [
      // "zewnętrzny dyrektor marketingu" to przepisana pozycja Adama "Zew. Dyrektor
      // Marketingu" — z OSOBY na USŁUGĘ. Narzędzie czyta strony firm, więc szuka
      // firmy oferującej taką rolę, nie człowieka na stanowisku.
      "agencja performance marketing", "agencja Google Ads", "agencja social media",
      "agencja digital marketingu", "agencja PR", "marketing automation",
      "influencer marketing", "e-mail marketing", "zewnętrzny dyrektor marketingu",
      "content marketing",   // widoczni i brantt — oni piszą, my optymalizujemy
    ]],
    ["Sprzedaż i marketplace", "wsparcie sprzedaży e-commerce", [
      // "outsourcing sprzedaży" — przepisany "Dyrektor sprzedaży", ta sama zasada.
      // "porównywarka cen" ma tysiące podpiętych sklepów: jeden partner = dostęp
      // do całego portfela sprzedawców.
      "agencja marketplace", "sprzedaż na Amazon", "integracje marketplace",
      "doradztwo sprzedaży B2B", "outsourcing sprzedaży", "porównywarka cen",
      "ekspansja zagraniczna e-commerce",   // widoczni i Sellision
    ]],
    ["Technologia, integracje i resellerzy", "wdrożenia systemów IT", [
      // Resellerzy z listy Adama. Nie ma ich wśród jego 35 najlepszych partnerów,
      // więc profil jest nieprzetestowany — ale mocny: taka firma ma bazę klientów
      // z wdrożonym systemem i nie ma czym zrobić im SEO.
      // Nazwy POLSKIE, nie "reseller". Sprawdzone: "reseller CRM" zwracalo
      // smartsalescrm.com, jetpackcrm.com i bigin.com — angielskie strony programów
      // partnerskich. Polskie firmy piszą o sobie "autoryzowany partner" albo
      // "partner wdrożeniowy".
      "oprogramowanie dla sklepów", "SaaS e-commerce", "headless commerce",
      "producent oprogramowania", "producent CMS",
      "integrator ERP", "integrator PIM", "wdrożenia CRM", "integracje płatności",
      "logistyka e-commerce",
      "autoryzowany partner CRM", "partner wdrożeniowy", "integrator systemów IT",
      "automatyzacja procesów",   // Growthmatic i Tribe47
    ]],
    ["AI i automatyzacja", "wdrożenia AI dla firm", [
      "agencja AI", "wdrożenia chatbotów", "narzędzia AI dla firm",
    ]],
    ["Wiedza i usługi prawne", "obsługa prawna e-commerce", [
      // "kancelaria prawa nowych technologii" to polska nazwa tego, co Adam
      // zapisał jako "kancelarie ai" — pod hasłem "kancelaria AI" wyszukiwarka
      // zwraca narzędzia AI dla prawników, nie kancelarie.
      "kancelaria prawna e-commerce", "kancelaria prawa nowych technologii",
      "regulaminy i RODO", "szkolenia e-commerce", "ekspert e-commerce",
    ]],
    ["Sieci i społeczności biznesowe", "organizacja zrzeszająca przedsiębiorców", [
      // Inny mechanizm niż reszta: do tych organizacji się WSTĘPUJE, a nie pisze
      // do nich z ofertą partnerstwa. Narzędzie pomaga je znaleźć i porównać,
      // decyzja o członkostwie zapada poza nim (BNI, kluby biznesu, grupy zakupowe).
      "stowarzyszenie branżowe", "klub biznesu", "grupa zakupowa",
      "networking biznesowy", "sieć aniołów biznesu",
    ]],
  ],
  // ⚠️ Zestaw startowy, do potwierdzenia z Adamem — kogo dokładnie chcemy
  // pozyskiwać jako klientów, nie jest jeszcze ustalone (otwarte w ROADMAP).
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
// Kategoria wybrana na liscie Firm. null = wszystkie.
let filtrKategorii = null;

// Źródło firm. "wyszukiwarka" = Tavily (kto jest wypozycjonowany),
// "mapy" = Google Maps (kto ma wizytówkę, niezależnie od SEO).
let zrodlo = "wyszukiwarka";
let zrodlaDostepne = { wyszukiwarka: true, mapy: false };

const ZRODLA = {
  wyszukiwarka: { nazwa: "Wyszukiwarka", ikona: "search",
                  opis: "Znajduje firmy widoczne w Google — czyli te, które już inwestują w SEO." },
  mapy:         { nazwa: "Mapy Google", ikona: "pin",
                  opis: "Znajduje każdą firmę z wizytówką, także bez SEO. Opis firmy pojawia się dopiero po researchu." },
};

fetch("/api/zrodla").then((r) => r.json()).then((d) => {
  if (d.ok) { zrodlaDostepne = d.zrodla; renderZrodla(); }
}).catch(() => {});

function renderZrodla() {
  const box = document.getElementById("zrodla-wyboru");
  if (!box) return;
  // Przy jednym podłączonym źródle przełącznik byłby przyciskiem bez wyboru.
  if (!zrodlaDostepne.mapy) { box.innerHTML = ""; zrodlo = "wyszukiwarka"; return; }
  box.innerHTML = `
    <div class="mono"><i class="sq"></i>Skąd bierzemy firmy</div>
    <div class="tagi wybieralne">${Object.entries(ZRODLA).map(([k, z]) => `
      <button class="tag${zrodlo === k ? " zaznaczony" : ""}" type="button"
              data-zrodlo="${k}" title="${escAttr(z.opis)}">
        <svg class="ico xs"><use href="#i-${z.ikona}"/></svg> ${esc(z.nazwa)}
      </button>`).join("")}</div>
    <p class="hint">${esc(ZRODLA[zrodlo].opis)}</p>`;
}

function renderPresety() {
  const grupy = PRESETY[tryb] || PRESETY.partner;
  const wybrana = otwartaGrupa !== null ? grupy[otwartaGrupa] : null;

  // Chipy, nie kafle — ten sam wygląd, co filtr kategorii w „Szukaj podobnych".
  // Kafle zajmowały pół ekranu, zanim cokolwiek wybrałeś; tu wybór jest jednym
  // rzędem, a miejsce zostaje na to, po co się tu przyszło.
  const kafle = `<div class="tagi wybieralne">${grupy.map(([grupa, , pozycje], i) => `
    <button class="tag${otwartaGrupa === i ? " zaznaczony" : ""}"
            type="button" data-grupa="${i}" aria-pressed="${otwartaGrupa === i}">
      ${esc(grupa)} <em class="chip-licznik">${pozycje.length}</em>
    </button>`).join("")}</div>`;

  const panel = !wybrana ? "" : (() => {
    const [grupa, fraza, pozycje] = wybrana;
    return `
      <div class="preset-panel">
        <div class="preset-panel-head">
          <span class="mono">${esc(grupa)}</span>
          <button class="btn-lekki" type="button" data-grupa="${otwartaGrupa}">
            <svg class="ico xs"><use href="#i-x"/></svg>Zwiń</button>
        </div>
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
    document.getElementById("panels").insertAdjacentHTML("beforeend", panelHTML(id, firma));
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

// widok szczegółów jednej firmy
function pokazDetal(id) {
  activeId = id;
  document.getElementById("firmy-lista").hidden = true;
  document.getElementById("firmy-pusto").hidden = true;
  document.getElementById("firmy-head").hidden = true;
  document.getElementById("firmy-detal").hidden = false;
  document.querySelectorAll("#panels .panel").forEach((p) => {
    p.style.display = p.dataset.id === id ? "block" : "none";
  });
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
  return `<div class="przelacznik-tryb" role="tablist">
    ${Object.entries(TRYBY).map(([k, t]) => `
      <button class="tryb-btn ${tryb === k ? "aktywny" : ""}" data-ustaw-tryb="${k}"
        type="button" role="tab" aria-selected="${tryb === k}">${t.nazwa}
        <em>${liczOd.filter((x) => (x.tryb || "partner") === k).length}</em></button>`).join("")}
  </div>`;
}

function renderListeFirm() {
  const wszystkie = firmyTrybu();
  const lista = filtrFirm === "ma_seo" ? wszystkie.filter((t) => t.firma.ma_seo) : wszystkie;

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
  document.querySelector(`#panels .panel[data-id="${id}"]`)?.remove();
  odswiezBadge("badge-firmy", firmyTrybu().length);
  renderResearchPanel();
  pokazListe();
}

function panelHTML(id, f) {
  const wKoszyku = koszyk.some((k) => k.url === f.url);
  return `<div class="panel" data-id="${id}">
    ${kartaHTML(f)}
    <div class="card">
      <div class="akcje">
        <button class="akcja mail" type="button"><svg class="ico sm"><use href="#i-mail"/></svg>Generuj maile</button>
        <label class="akcja check">
          <input type="checkbox" class="do-eksportu" ${wKoszyku ? "checked" : ""}> Dodaj do eksportu
        </label>
      </div>
    </div>
    <div class="mail-box"></div>
  </div>`;
}

function kartaHTML(f) {
  // Fakt, nie werdykt. Czy to konkurent, czy partner — ocenia zespół.
  const badge = f.ma_seo
    ? `<div class="flaga ma-seo"><svg class="ico xs"><use href="#i-search"/></svg>Ma SEO w ofercie</div>`
    : `<div class="flaga bez-seo"><svg class="ico xs"><use href="#i-check"/></svg>Bez SEO w ofercie</div>`;
  return `<div class="card firma">
    <div class="firma-head">
      <div>
        <h2 class="firma-nazwa">${esc(f.nazwa)}</h2>
        <a class="firma-url" href="${escAttr(f.url)}" target="_blank" rel="noopener">${esc(f.url)}<svg class="ico xs"><use href="#i-external"/></svg></a>
      </div>
      ${badge}
    </div>
    <p class="firma-opis">${esc(f.opis)}</p>
    <p class="uzasadnienie"><span class="etyk">Zakres SEO</span> ${esc(f.seo_zakres)}</p>

    <div class="pola">
      ${pole("Branża", f.branza)}
      ${pole("Wielkość zespołu", f.wielkosc_zespolu)}
      ${pole("Liczba projektów", f.liczba_projektow)}
      ${pole("Telefon (firma)", f.telefon)}
      ${pole("Email (firma)", f.email)}
    </div>

    <div class="pola dane-spolki">
      ${pole("Nazwa prawna", f.nazwa_prawna)}
      ${pole("NIP", f.nip)}
      ${pole("Adres", f.adres)}
      ${pole("Miasto", f.miasto)}
    </div>
    <div class="pola osoba">
      ${pole("Osoba decyzyjna", f.persona_imie)}
      ${pole("Stanowisko", f.persona_stanowisko)}
      ${pole("Email osoby", f.persona_email)}
      ${pole("Telefon osoby", f.persona_telefon)}
    </div>

    ${lista("Usługi", f.uslugi)}
    ${lista("Case studies / realizacje", f.case_studies)}

    <details class="zrodlo">
      <summary>Źródło danych (${(f.zrodlo_danych || []).length} podstron)</summary>
      <ul>${(f.zrodlo_danych || []).map((u) =>
        `<li><a href="${escAttr(u)}" target="_blank" rel="noopener">${esc(u)}</a></li>`).join("")}</ul>
    </details>
  </div>`;
}

function pole(etykieta, wartosc) {
  const brak = !wartosc || wartosc === BRAK;
  return `<div class="pole">
    <span class="pole-etykieta">${esc(etykieta)}</span>
    <span class="pole-wartosc ${brak ? "brak" : ""}">${esc(wartosc || BRAK)}</span>
  </div>`;
}

function lista(etykieta, elementy) {
  if (!elementy || !elementy.length) return "";
  return `<div class="lista">
    <span class="pole-etykieta">${esc(etykieta)}</span>
    <div class="tagi">${elementy.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>
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
  if (e.target.closest("[data-zdejmij-filtr]")) { filtrFirm = null; return renderListeFirm(); }
  const wiersz = e.target.closest(".firma-row");
  if (wiersz) { pokazSekcje("firmy"); return pokazDetal(wiersz.dataset.id); }
  if (e.target.classList.contains("wroc")) return pokazListe();

  const katFirmy = e.target.closest("[data-kat-firmy]");
  if (katFirmy) {
    filtrKategorii = katFirmy.dataset.katFirmy || null;
    return renderListeFirm();
  }
  const katPodobne = e.target.closest("[data-kat-podobne]");
  if (katPodobne) {
    podobneKategoria = katPodobne.dataset.katPodobne || null;
    return renderPodobne();
  }
  const wzor = e.target.closest(".wybierz-wzor");
  if (wzor) { podobneWybrana = wzor.dataset.id; podobneTagi.clear(); return renderPodobne(); }
  if (e.target.classList.contains("zmien-wzor")) {
    podobneWybrana = null; podobneTagi.clear();
    document.getElementById("podobne-wynik").innerHTML = "";
    return renderPodobne();
  }
  const btnZrodlo = e.target.closest("[data-zrodlo]");
  if (btnZrodlo) { zrodlo = btnZrodlo.dataset.zrodlo; return renderZrodla(); }
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

document.addEventListener("change", (e) => {
  if (e.target.id === "audyt-aio") { audytAIO = e.target.checked; return renderAudyt(); }
  if (e.target.id === "audyt-seo") { audytSEO = e.target.checked; return renderAudyt(); }
  if (e.target.id === "audyt-ile") { audytIle = +e.target.value; return renderAudyt(); }
  if (e.target.name === "dostawca") {
    audytDostawca = e.target.value;
    if (audytDostawca === "seranking") {
      // odznaczamy silniki idace przez DataForSEO — inaczej zostalyby zaznaczone
      // i audyt „na SE Ranking" siegalby po drugiego dostawce
      audytSilniki = audytSilniki.filter((k) => !SILNIKI[k]?.dfs);
      if (!audytSilniki.length) audytSilniki = ["chatgpt_wprost"];
    }
    return renderAudyt();
  }
  if (e.target.name === "platforma") {
    const v = e.target.value;
    audytPlatformy = e.target.checked
      ? [...audytPlatformy, v] : audytPlatformy.filter((x) => x !== v);
    if (!audytPlatformy.length) audytPlatformy = [v];
    return renderAudyt();
  }
  if (e.target.name === "silnik_sr") {
    const v = e.target.value;
    audytSilnikiSR = e.target.checked
      ? [...audytSilnikiSR, v] : audytSilnikiSR.filter((x) => x !== v);
    if (!audytSilnikiSR.length) audytSilnikiSR = [v];
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

  const uslugi = wpis.firma.uslugi || [];
  tagiBox.innerHTML = `<div class="card">
    <div class="mono"><span class="sq"></span> 2. Zaznacz usługi definiujące podobieństwo</div>
    <p class="hint">Im mniej i konkretniej, tym trafniejsze wyniki. Polecam 2-4 tagi.</p>
    <div class="tagi wybieralne">${uslugi.map((u) =>
      `<button class="tag ${podobneTagi.has(u) ? "zaznaczony" : ""}" data-tag="${escAttr(u)}" type="button">${esc(u)}</button>`
    ).join("")}</div>
    <button class="akcja glowna szukaj-wg-tagow" type="button" style="margin-top:18px" ${podobneTagi.size ? "" : "disabled"}>
      <svg class="ico sm"><use href="#i-search"/></svg>Szukaj podobnych${podobneTagi.size ? ` (${podobneTagi.size})` : ""}
    </button>
  </div>`;
}

async function szukajWgTagow(przycisk) {
  const wpis = tabs.find((t) => t.id === podobneWybrana);
  const box = document.getElementById("podobne-wynik");
  przycisk.disabled = true;
  przycisk.textContent = "Szukam… (~10 s)";
  box.innerHTML = "";
  try {
    const res = await fetch("/api/similar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ firma: wpis.firma, tagi: [...podobneTagi] }),
    });
    const data = await res.json();
    box.innerHTML = data.ok ? listaFirmHTML(data, "Podobne firmy") : errorHTML(data.error);
  } catch (err) {
    box.innerHTML = errorHTML(err.message);
  } finally {
    przycisk.disabled = false;
    renderPodobne();
  }
}

function listaFirmHTML(data, naglowek) {
  if (!data.firmy.length) {
    return `<div class="card"><p class="sim-err">Nie znalazłem firm dla „${esc(data.zapytanie)}".
      Spróbuj innej branży albo bez miasta.</p></div>`;
  }
  return `<div class="card">
    <div class="mono"><span class="sq"></span> ${esc(naglowek)} (${data.firmy.length})</div>
    <p class="hint">Zapytanie: „${esc(data.zapytanie)}"${
      data.z_seo ? ` · ${data.z_seo} z SEO w ofercie` : ""
    }${data.odsiane_martwe ? ` · ${data.odsiane_martwe} martwych stron` : ""
    }${data.bez_strony ? ` · ${data.bez_strony} firm z Map bez strony WWW (pomijamy — nie ma czego zbadać)` : ""
    }${data.juz_zbadane ? ` · ${data.juz_zbadane} już masz` : ""}</p>
    <div class="similar-list">${data.firmy.map(wierszHTML).join("")}</div>
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
let audytDostawca = "dataforseo";
let audytSilniki = ["chatgpt_wprost"];
// Silnik bazy SE Ranking dla sekcji wzmianek — ich dane pokrywaja 5 platform.
let audytSilnikiSR = ["ai-overview"];
// Platformy wzmianek u DataForSEO — ta sama idea co SILNIKI_SR, inny dostawca.
const PLATFORMY_DFS = {
  "google":     "Google AI Overviews",
  "chat_gpt":   "ChatGPT",
  "perplexity": "Perplexity",
  "gemini":     "Google Gemini",
};
let audytPlatformy = ["google"];

const SILNIKI_SR = {
  "ai-overview": "Google AI Overviews",
  "ai-mode":     "Google AI Mode",
  "chatgpt":     "ChatGPT",
  "perplexity":  "Perplexity",
  "gemini":      "Google Gemini",
};   // ktore modele AI pytamy (mozna kilka)   // jeden dostawca na audyt, nigdy dwaj naraz
let audytAIO = true;

const KOSZT_PROMPT = 0.006;   // Perplexity sonar, zmierzone
const KOSZT_AIO = 0.11;       // llm_mentions, zmierzone
const KOSZT_SEO = 0.04;       // 3 wywolania Labs, zmierzone
// Zmierzone na tym samym prompcie: Perplexity dal 9 marek za $0.006,
// ChatGPT 3 marki za $0.109. Tanszy dal WIECEJ danych — ale ma 6% rynku PL.
// Modele potwierdzone darmowym endpointem DataForSEO — wszystkie z wyszukiwaniem w sieci.
const SILNIKI = {
  // Jedyny silnik na naszym wlasnym kluczu — dziala niezaleznie od DataForSEO
  // i SE Ranking, wiec sekcja pytan nie pada razem z dostawca SEO.
  chatgpt_wprost: { nazwa: "ChatGPT (bezpośrednio)", udzial: "86,4%", koszt: 0.012,
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
let audytSEO = true;

// Każde pytanie idzie do każdego wybranego modelu, więc koszty się sumują.
// Które zaznaczone opcje przechodzą przez DataForSEO — żeby powiedzieć to PRZED
// audytem, a nie dopiero błędem 402 po minucie czekania.
function wymagaDFS() {
  const l = audytSilniki.filter((k) => SILNIKI[k]?.dfs).map((k) => SILNIKI[k].nazwa);
  if (audytDostawca !== "seranking") {
    if (audytSEO) l.push("Widoczność w Google");
    if (audytAIO) l.push("Widoczność w AI Overviews");
  }
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

  const sr = audytDostawca === "seranking";
  // SE Ranking rozlicza sie w kredytach, nie w dolarach — pokazujemy wlasciwa jednostke,
  // zamiast przeliczac jedno na drugie i sugerowac porownywalnosc, ktorej nie ma.
  const koszt = sr
    ? (audytIle * kosztSilnikow()).toFixed(3)
    : (audytIle * kosztSilnikow() + (audytAIO ? KOSZT_AIO : 0)
       + (audytSEO ? KOSZT_SEO : 0) + (audytAIO ? KOSZT_AIO * (audytPlatformy.length - 1) : 0)).toFixed(3);
  const kredyty = sr ? ((audytSEO ? 400 + 800 : 0) + (audytAIO ? 2000 * audytSilnikiSR.length : 0)) : 0;
  wybor.innerHTML = `<div class="card">
    <div class="wzor-head">
      <div><div class="firma-row-nazwa">${esc(wpis.firma.nazwa)}</div>
        <span class="firma-row-meta">${esc(hostname(wpis.firma.url))}</span></div>
      <button class="btn-lekki zmien-audyt" type="button">Zmień firmę</button>
    </div>
  </div>
  <div class="card">
    <div class="mono"><i class="sq"></i>Źródło danych SEO</div>
    <div class="akcje" style="margin-bottom:16px">
      <label class="akcja check"><input type="radio" name="dostawca" value="dataforseo"
        ${!sr ? "checked" : ""}> DataForSEO <span class="cena">rozliczenie w $</span></label>
      <label class="akcja check"><input type="radio" name="dostawca" value="seranking"
        ${sr ? "checked" : ""}> SE Ranking <span class="cena">rozliczenie w kredytach</span></label>
    </div>
    ${sr ? `<p class="hint" style="margin:-8px 0 16px">Dane o pozycjach dzielą się u nich
      na <b>TOP 1-5</b>, nie TOP 3 — raport podpisze tę liczbę zgodnie z tym, co
      faktycznie mierzy. Pytania klientów zadajemy niezależnie, naszym kluczem OpenAI.</p>` : ""}

    <div class="mono"><i class="sq"></i>Które modele AI pytamy</div>
    <div class="akcje" style="margin-bottom:10px">
      ${Object.entries(SILNIKI).filter(([, m]) => !sr || !m.dfs).map(([k, m]) => `
        <label class="akcja check"><input type="checkbox" name="silnik" value="${k}"
          ${audytSilniki.includes(k) ? "checked" : ""}> ${m.nazwa}
          <span class="cena">${m.udzial || m.opis} · $${m.koszt}${
            m.wlasny ? " · nasz klucz" : m.dfs ? " · przez DataForSEO" : ""
          }</span></label>`).join("")}
    </div>
    ${sr ? `<p class="hint" style="margin:0 0 16px">Przy SE Ranking pokazujemy tylko
      silniki na <b>naszym własnym kluczu</b> — audyt nie dotyka wtedy DataForSEO
      w żadnym miejscu. Modele z ich bazy wybierasz niżej, przy wzmiankach.</p>` : ""}
    ${wymagaDFS() ? `<p class="ostrzezenie-inline">Zaznaczone opcje wymagają konta
      <b>DataForSEO</b> ze środkami: ${wymagaDFS().join(", ")}. Jeśli saldo jest puste,
      audyt zakończy się błędem — odznacz je albo doładuj konto.</p>` : ""}
    <p class="hint" style="margin:0 0 16px">
      Każde pytanie trafia do <b>każdego</b> zaznaczonego modelu, więc koszty się sumują.
      Łączny udział wybranych: <b>${pokrycieRynku()}</b> polskiego rynku zapytań do AI.
      ${audytSilniki.length > 1
        ? " Przy kilku modelach widać, czy brak wzmianki dotyczy jednego silnika, czy wszystkich."
        : " Przy jednym modelu nie da się odróżnić cechy silnika od prawidłowości."}</p>

    ${!sr && audytAIO ? `
    <div class="mono"><i class="sq"></i>Wzmianki — z której platformy</div>
    <div class="akcje" style="margin-bottom:10px">
      ${Object.entries(PLATFORMY_DFS).map(([k, n]) => `
        <label class="akcja check"><input type="checkbox" name="platforma" value="${k}"
          ${audytPlatformy.includes(k) ? "checked" : ""}> ${n}</label>`).join("")}
    </div>
    <p class="hint" style="margin:0 0 16px">Baza DataForSEO — zapytania, przy których
      firma <b>już jest</b> cytowana. Każda platforma to osobne wywołanie
      (<b>+$${KOSZT_AIO}</b>).</p>` : ""}

    ${sr && audytAIO ? `
    <div class="mono"><i class="sq"></i>Wzmianki — z której platformy</div>
    <div class="akcje" style="margin-bottom:10px">
      ${Object.entries(SILNIKI_SR).map(([k, n]) => `
        <label class="akcja check"><input type="checkbox" name="silnik_sr" value="${k}"
          ${audytSilnikiSR.includes(k) ? "checked" : ""}> ${n}</label>`).join("")}
    </div>
    <p class="hint" style="margin:0 0 16px">To ich baza, odświeżana miesięcznie —
      pokazuje, gdzie firma <b>jest</b> cytowana, a nie odpowiada na nasze pytania.
      ${audytSilnikiSR.length > 1
        ? `Przy kilku platformach raport zestawi je obok siebie — a to właśnie różnica
           między nimi bywa wnioskiem: firma potrafi być pierwsza w Google AI Mode
           i nieobecna w ChatGPT.`
        : `Możesz zaznaczyć kilka — <b>2 000 kredytów za każdą</b>.`}</p>` : ""}

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
    <p class="hint">Szacowany koszt: <b class="cena-suma">$${koszt}</b>${
      kredyty ? ` + <b class="cena-suma">${kredyty.toLocaleString("pl-PL")} kredytów</b> SE Ranking` : ""}
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
      body: JSON.stringify({ firma: wpis.firma, ile_promptow: audytIle, dostawca: audytDostawca, silniki: audytSilniki, silniki_sr: audytSilnikiSR,
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
      <div class="okladka-dol mono">© 2026 Last Agency · lastagency.pl</div>
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
      <span class="mono">Partner Tool · Last Agency · ${esc(dzis)}</span>
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
  const status = w.wspomniana
    ? `<span class="status jest">Marka wymieniona</span>`
    : `<span class="status brak">Marka nieobecna</span>`;
  return `<article class="pytanie">
    <div class="pytanie-glowa">
      <h3>${esc(w.prompt)}</h3>
      ${status}${w.cytowana ? `<span class="status cyt">Strona cytowana</span>` : ""}
    </div>
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

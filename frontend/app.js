// Partner Tool — aplikacja (sekcje + zakładki firm)
const BRAK = "nie do ustalenia";

let tabs = [];       // [{id, nazwa, firma}]
let activeId = null;
let tabSeq = 0;
let koszyk = [];     // firmy zaznaczone do eksportu
let kolumny = [];    // definicja kolumn CSV — z backendu (jedno źródło prawdy)

fetch("/api/columns").then((r) => r.json()).then((d) => { kolumny = d.kolumny || []; });

// ══ Nawigacja między sekcjami ══
function pokazSekcje(nazwa) {
  document.querySelectorAll(".sekcja").forEach((s) =>
    s.classList.toggle("aktywna", s.dataset.sekcja === nazwa));
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("aktywny", b.dataset.sekcja === nazwa));
  if (nazwa === "eksport") renderEksport();
  if (nazwa === "podobne") renderPodobne();
  if (nazwa === "firmy") pokazListe();  // wejście z menu zawsze pokazuje listę
  window.scrollTo(0, 0);
}
document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => pokazSekcje(b.dataset.sekcja)));

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
    body: JSON.stringify({ url }),
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
  ["alert", "Flaga konkurenta", "czy rdzeniem oferty jest SEO/SEM"],
  ["pin", "Źródło danych", "które podstrony odwiedziliśmy"],
];

function renderResearchPanel() {
  const box = document.getElementById("research-panel");

  if (!tabs.length) {
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

  const konkurenci = tabs.filter((t) => t.firma.konkurent).length;
  const ostatnie = tabs.slice(-4).reverse();
  box.innerHTML = `
    <div class="kafle">
      ${kafel(tabs.length, "zbadane firmy", "building")}
      ${kafel(koszyk.length, "w eksporcie", "table")}
      ${kafel(konkurenci, konkurenci === 1 ? "konkurent" : "konkurenci", "alert")}
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

function kafel(liczba, etykieta, ikona) {
  return `<div class="kafel">
    <svg class="ico"><use href="#i-${ikona}"/></svg>
    <div><b>${liczba}</b><span>${esc(etykieta)}</span></div>
  </div>`;
}

// ══ SEKCJA: Szukaj po branży ══
const formKryteria = document.getElementById("form-kryteria");
const btnKryteria = document.getElementById("btn-kryteria");
const szukajWynik = document.getElementById("szukaj-wynik");

// presety branż — kategorie partnerskie Last Agency (PRD: dobre kategorie partnerów)
const PRESETY = [
  "agencja brandingowa", "agencja kreatywna", "software house", "agencja e-commerce",
  "agencja social media", "marketing automation", "doradztwo e-commerce",
  "agencja UX/UI", "kancelaria prawna e-commerce", "integrator ERP",
];
document.getElementById("presety-branz").innerHTML =
  PRESETY.map((p) => `<button class="tag" data-preset="${escAttr(p)}" type="button">${esc(p)}</button>`).join("");

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
      body: JSON.stringify({ branza, miasto }),
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
    wpis = { id, nazwa: hostname(firma.url), firma };
    tabs.push(wpis);
    document.getElementById("panels").insertAdjacentHTML("beforeend", panelHTML(id, firma));
    odswiezBadge("badge-firmy", tabs.length);
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
  document.getElementById("firmy-pusto").hidden = tabs.length > 0;
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

function renderListeFirm() {
  document.getElementById("firmy-lista").innerHTML = tabs.map((t) => {
    const f = t.firma;
    const wKoszyku = koszyk.some((k) => k.url === f.url);
    return `<div class="firma-row" data-id="${t.id}">
      <div class="firma-row-info">
        <div class="firma-row-top">
          <span class="firma-row-nazwa">${esc(f.nazwa)}</span>
          ${f.konkurent
            ? `<span class="flaga mini konkurent"><svg class="ico xs"><use href="#i-alert"/></svg>Konkurent</span>`
            : `<span class="flaga mini partner"><svg class="ico xs"><use href="#i-check"/></svg>Nie konkurent</span>`}
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
  tabs = tabs.filter((t) => t.id !== id);
  document.querySelector(`#panels .panel[data-id="${id}"]`)?.remove();
  odswiezBadge("badge-firmy", tabs.length);
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
  const badge = f.konkurent
    ? `<div class="flaga konkurent"><svg class="ico xs"><use href="#i-alert"/></svg>Konkurent</div>`
    : `<div class="flaga partner"><svg class="ico xs"><use href="#i-check"/></svg>Nie konkurent</div>`;
  return `<div class="card firma">
    <div class="firma-head">
      <div>
        <h2 class="firma-nazwa">${esc(f.nazwa)}</h2>
        <a class="firma-url" href="${escAttr(f.url)}" target="_blank" rel="noopener">${esc(f.url)}<svg class="ico xs"><use href="#i-external"/></svg></a>
      </div>
      ${badge}
    </div>
    <p class="firma-opis">${esc(f.opis)}</p>
    <p class="uzasadnienie"><span class="etyk">Flaga</span> ${esc(f.konkurent_uzasadnienie)}</p>

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
  const usun = e.target.closest("[data-usun]");
  if (usun) { e.stopPropagation(); return usunFirme(usun.dataset.usun); }
  const wiersz = e.target.closest(".firma-row");
  if (wiersz) { pokazSekcje("firmy"); return pokazDetal(wiersz.dataset.id); }
  if (e.target.classList.contains("wroc")) return pokazListe();

  const wzor = e.target.closest(".wybierz-wzor");
  if (wzor) { podobneWybrana = wzor.dataset.id; podobneTagi.clear(); return renderPodobne(); }
  if (e.target.classList.contains("zmien-wzor")) {
    podobneWybrana = null; podobneTagi.clear();
    document.getElementById("podobne-wynik").innerHTML = "";
    return renderPodobne();
  }
  const preset = e.target.closest("[data-preset]");
  if (preset) {
    document.getElementById("branza").value = preset.dataset.preset;
    return document.getElementById("miasto").focus();
  }
  const tag = e.target.closest("[data-tag]");
  if (tag) {
    const t = tag.dataset.tag;
    podobneTagi.has(t) ? podobneTagi.delete(t) : podobneTagi.add(t);
    return renderPodobne();
  }
  if (e.target.classList.contains("szukaj-wg-tagow")) return szukajWgTagow(e.target);
  if (e.target.classList.contains("mail")) return generujMaile(e.target);
  if (e.target.classList.contains("researchuj")) return researchujZListy(e.target);
  if (e.target.classList.contains("kopiuj")) return kopiuj(e.target);
  if (e.target.classList.contains("pobierz-csv")) return pobierzCSV();
});

document.addEventListener("change", (e) => {
  if (!e.target.classList.contains("do-eksportu")) return;
  const firma = firmaZPanelu(e.target.closest(".panel"));
  if (e.target.checked) {
    if (!koszyk.some((k) => k.url === firma.url)) koszyk.push(firma);
  } else {
    koszyk = koszyk.filter((k) => k.url !== firma.url);
  }
  odswiezBadge("badge-eksport", koszyk.length);
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

  if (!tabs.length) {
    wybor.innerHTML = `<div class="pusto">Najpierw zbadaj jakąś firmę
      (<b>Research po URL</b> albo <b>Szukaj po branży</b>) — podobnych szukamy na jej podstawie.</div>`;
    tagiBox.innerHTML = "";
    return;
  }

  const wpis = tabs.find((t) => t.id === podobneWybrana);

  if (!wpis) {
    wybor.innerHTML = `<div class="card">
      <div class="mono"><span class="sq"></span> 1. Wybierz firmę wzorcową</div>
      <div class="similar-list">${tabs.map((t) => `
        <div class="sim-row wybierz-wzor" data-id="${t.id}">
          <div class="sim-info">
            <span class="sim-name">${esc(t.firma.nazwa)}</span>
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
      <button class="wroc zmien-wzor" type="button" style="margin:0">Zmień firmę</button>
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
      data.odsiani_konkurenci ? ` · odsiano ${data.odsiani_konkurenci} agencji SEO` : ""
    }${data.odsiane_martwe ? ` · ${data.odsiane_martwe} martwych stron` : ""}</p>
    <div class="similar-list">${data.firmy.map(wierszHTML).join("")}</div>
  </div>`;
}

function wierszHTML(f) {
  return `<div class="sim-row" data-url="${escAttr(f.url)}">
    <div class="sim-info">
      <span class="sim-name">${esc(f.nazwa)}</span>
      <a class="sim-url" href="${escAttr(f.url)}" target="_blank" rel="noopener">${esc(f.url)}<svg class="ico xs"><use href="#i-external"/></svg></a>
      ${f.niepewna ? `<span class="niepewna"><svg class="ico xs"><use href="#i-alert"/></svg>nie udało się zweryfikować strony (blokada bota?)</span>` : ""}
    </div>
    <button class="researchuj" type="button">Researchuj<svg class="ico xs"><use href="#i-arrow"/></svg></button>
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

// ══ SEKCJA: Eksport ══
function renderEksport() {
  const box = document.getElementById("eksport-box");
  if (!koszyk.length) {
    box.innerHTML = `<div class="pusto">Koszyk pusty — zaznacz „Dodaj do eksportu" na karcie firmy.</div>`;
    return;
  }
  const naglowki = kolumny.map((k) => `<th>${esc(k.naglowek)}</th>`).join("");
  const wiersze = koszyk.map((f) =>
    `<tr>${kolumny.map((k) => {
      const v = komorka(f[k.klucz]);
      return `<td class="${v === BRAK ? "brak" : ""}">${esc(v)}</td>`;
    }).join("")}</tr>`).join("");

  box.innerHTML = `<div class="card">
    <div class="mono"><span class="sq"></span> Do eksportu (${koszyk.length})</div>
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
    body: JSON.stringify({ firmy: koszyk }),
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

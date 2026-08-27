// Partner Tool — frontend
const form = document.getElementById("form");
const urlInput = document.getElementById("url");
const btn = document.getElementById("btn");
const output = document.getElementById("output");
const koszykBar = document.getElementById("koszyk");
const koszykIle = document.getElementById("koszyk-ile");

let tabs = [];      // [{id, nazwa, firma}] lub {id, nazwa, typ:"eksport"}
let activeId = null;
let tabSeq = 0;
let koszyk = [];    // firmy zaznaczone do eksportu
let kolumny = [];   // definicja kolumn CSV — pobrana z backendu (jedno źródło prawdy)

fetch("/api/columns").then((r) => r.json()).then((d) => { kolumny = d.kolumny || []; });

const BRAK = "nie do ustalenia";

// ── Research po URL ──
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  let url = urlInput.value.trim();
  if (!url) return;
  if (!/^https?:\/\//i.test(url)) url = "https://" + url;

  output.hidden = false;
  output.innerHTML = loadingHTML("Zbieram dane… (strona główna + podstrony → ekstrakcja). ~20-40 s.");
  btn.disabled = true;

  try {
    const data = await research(url);
    if (!data.ok) {
      output.innerHTML = errorHTML(data.error);
    } else {
      tabs = [];
      activeId = null;
      output.innerHTML = `<div id="tabbar" class="tabbar"></div><div id="panels"></div>`;
      openTab(data.firma);
    }
  } catch (err) {
    output.innerHTML = errorHTML(err.message);
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

// ── Zakładki ──
function openTab(firma) {
  const id = "tab" + ++tabSeq;
  tabs.push({ id, nazwa: hostname(firma.url), firma });
  document.getElementById("panels").insertAdjacentHTML("beforeend", panelHTML(id, firma));
  setActive(id);
}

function setActive(id) {
  activeId = id;
  document.querySelectorAll("#panels .panel").forEach((p) => {
    p.style.display = p.dataset.id === id ? "block" : "none";
  });
  renderTabBar();
}

function closeTab(id) {
  tabs = tabs.filter((t) => t.id !== id);
  document.querySelector(`#panels .panel[data-id="${id}"]`)?.remove();
  if (activeId === id) {
    activeId = tabs.length ? tabs[tabs.length - 1].id : null;
    if (activeId) return setActive(activeId);
  }
  renderTabBar();
}

function renderTabBar() {
  const bar = document.getElementById("tabbar");
  if (!bar) return;
  bar.innerHTML = tabs.map((t) => `<div class="tab ${t.id === activeId ? "active" : ""}" data-id="${t.id}">
      <span class="tab-name">${esc(t.nazwa)}</span>
      <span class="tab-close" data-close="${t.id}" title="Zamknij">×</span>
    </div>`).join("");
}

// ── Zakładka podglądu eksportu ──
function otworzEksport() {
  let tab = tabs.find((t) => t.typ === "eksport");
  if (!tab) {
    const id = "tab" + ++tabSeq;
    tab = { id, nazwa: "📋 Eksport", typ: "eksport" };
    tabs.push(tab);
    document.getElementById("panels").insertAdjacentHTML(
      "beforeend",
      `<div class="panel" data-id="${id}"><div class="eksport-box"></div></div>`
    );
  }
  setActive(tab.id);
  renderEksport();
}

function renderEksport() {
  const tab = tabs.find((t) => t.typ === "eksport");
  if (!tab) return;
  const box = document.querySelector(`#panels .panel[data-id="${tab.id}"] .eksport-box`);
  if (!box) return;

  if (!koszyk.length) {
    box.innerHTML = `<div class="card"><div class="mono"><span class="sq"></span> EKSPORT</div>
      <p class="hint">Koszyk pusty — zaznacz „Dodaj do eksportu" na karcie firmy.</p></div>`;
    return;
  }

  const naglowki = kolumny.map((k) => `<th>${esc(k.naglowek)}</th>`).join("");
  const wiersze = koszyk.map((f) => {
    const komorki = kolumny.map((k) => {
      const v = komorka(f[k.klucz]);
      return `<td class="${v === BRAK ? "brak" : ""}">${esc(v)}</td>`;
    }).join("");
    return `<tr>${komorki}</tr>`;
  }).join("");

  box.innerHTML = `<div class="card">
    <div class="mono"><span class="sq"></span> PODGLĄD EKSPORTU (${koszyk.length})</div>
    <p class="hint">Dokładnie te kolumny i wartości trafią do CSV. Sprawdź mapowanie przed importem do Pipedrive.</p>
    <div class="tabela-scroll"><table class="tabela">
      <thead><tr>${naglowki}</tr></thead>
      <tbody>${wiersze}</tbody>
    </table></div>
    <button class="akcja pobierz-csv" type="button" style="margin-top:16px">Pobierz CSV ↓</button>
  </div>`;
}

function komorka(v) {
  if (Array.isArray(v)) return v.length ? v.join(", ") : BRAK;
  if (typeof v === "boolean") return v ? "TAK" : "NIE";
  return v ?? BRAK;
}

// ── Panel firmy ──
function panelHTML(id, f) {
  const wKoszyku = koszyk.some((k) => k.url === f.url);
  return `<div class="panel" data-id="${id}" data-url="${escAttr(f.url)}">
    ${kartaHTML(f)}
    <div class="card akcje">
      <button class="akcja szukaj" type="button">🔍 Szukaj podobnych</button>
      <button class="akcja mail" type="button">✉️ Generuj maile</button>
      <label class="akcja check">
        <input type="checkbox" class="do-eksportu" ${wKoszyku ? "checked" : ""}> Dodaj do eksportu
      </label>
    </div>
    <div class="similar-box"></div>
    <div class="mail-box"></div>
  </div>`;
}

function kartaHTML(f) {
  const badge = f.konkurent
    ? `<div class="flaga konkurent">⚠ KONKURENT</div>`
    : `<div class="flaga partner">✓ NIE KONKURENT</div>`;

  return `<div class="card firma">
    <div class="firma-head">
      <div>
        <h2 class="firma-nazwa">${esc(f.nazwa)}</h2>
        <a class="firma-url" href="${escAttr(f.url)}" target="_blank" rel="noopener">${esc(f.url)} ↗</a>
      </div>
      ${badge}
    </div>

    <p class="firma-opis">${esc(f.opis)}</p>
    <p class="uzasadnienie"><span class="mono-inline">FLAGA:</span> ${esc(f.konkurent_uzasadnienie)}</p>

    <div class="pola">
      ${pole("Branża", f.branza)}
      ${pole("Wielkość zespołu", f.wielkosc_zespolu)}
      ${pole("Liczba projektów", f.liczba_projektow)}
      ${pole("Telefon", f.telefon)}
      ${pole("Email", f.email)}
      ${pole("Persona", f.persona)}
    </div>

    ${lista("Usługi", f.uslugi)}
    ${lista("Case studies / realizacje", f.case_studies)}

    <details class="zrodlo">
      <summary>Źródło danych (${(f.zrodlo_danych || []).length} podstron)</summary>
      <ul>${(f.zrodlo_danych || []).map((u) => `<li><a href="${escAttr(u)}" target="_blank" rel="noopener">${esc(u)}</a></li>`).join("")}</ul>
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

// ── Kliknięcia (delegacja) ──
output.addEventListener("click", (e) => {
  const close = e.target.closest(".tab-close");
  if (close) return closeTab(close.dataset.close);

  const tab = e.target.closest(".tab");
  if (tab) return setActive(tab.dataset.id);

  if (e.target.classList.contains("szukaj")) return szukajPodobnych(e.target);
  if (e.target.classList.contains("mail")) return generujMaile(e.target);
  if (e.target.classList.contains("researchuj")) return researchujPodobna(e.target);
  if (e.target.classList.contains("kopiuj")) return kopiuj(e.target);
  if (e.target.classList.contains("pobierz-csv")) return pobierzCSV();
});

output.addEventListener("change", (e) => {
  if (e.target.classList.contains("do-eksportu")) {
    const firma = firmaZPanelu(e.target.closest(".panel"));
    if (e.target.checked) {
      if (!koszyk.some((k) => k.url === firma.url)) koszyk.push(firma);
    } else {
      koszyk = koszyk.filter((k) => k.url !== firma.url);
    }
    renderKoszyk();
  }
});

function firmaZPanelu(panel) {
  return tabs.find((t) => t.id === panel.dataset.id)?.firma || {};
}

// ── Szukaj podobnych ──
async function szukajPodobnych(przycisk) {
  const panel = przycisk.closest(".panel");
  const box = panel.querySelector(".similar-box");
  przycisk.disabled = true;
  przycisk.textContent = "Szukam… (~5 s)";
  box.innerHTML = "";
  try {
    const res = await fetch("/api/similar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ firma: firmaZPanelu(panel) }),
    });
    const data = await res.json();
    if (!data.ok) {
      box.innerHTML = errorHTML(data.error);
    } else if (!data.firmy.length) {
      box.innerHTML = `<div class="card"><p class="sim-err">Nie znalazłem podobnych firm.</p></div>`;
    } else {
      box.innerHTML = `<div class="card similar">
        <div class="mono"><span class="sq"></span> PODOBNE FIRMY (${data.firmy.length})</div>
        <p class="hint">Zapytanie: „${esc(data.zapytanie)}"</p>
        <div class="similar-list">${data.firmy.map(wierszHTML).join("")}</div>
      </div>`;
    }
  } catch (err) {
    box.innerHTML = errorHTML(err.message);
  } finally {
    przycisk.disabled = false;
    przycisk.textContent = "🔍 Szukaj podobnych";
  }
}

function wierszHTML(f) {
  return `<div class="sim-row" data-url="${escAttr(f.url)}">
    <div class="sim-info">
      <span class="sim-name">${esc(f.nazwa)}</span>
      <a class="sim-url" href="${escAttr(f.url)}" target="_blank" rel="noopener">${esc(f.url)} ↗</a>
    </div>
    <button class="researchuj" type="button">Researchuj →</button>
  </div>`;
}

async function researchujPodobna(przycisk) {
  const url = przycisk.closest(".sim-row").dataset.url;
  przycisk.disabled = true;
  przycisk.textContent = "Zbieram… (~30 s)";
  try {
    const data = await research(url);
    if (!data.ok) {
      przycisk.disabled = false;
      przycisk.textContent = "Spróbuj ponownie";
      przycisk.closest(".sim-row").insertAdjacentHTML("beforeend", `<p class="sim-err">⚠️ ${esc(data.error)}</p>`);
    } else {
      openTab(data.firma);
      przycisk.textContent = "✓ Otwarto kartę";
    }
  } catch (err) {
    przycisk.disabled = false;
    przycisk.textContent = "Spróbuj ponownie";
  }
}

// ── Maile ──
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
    if (!data.ok) {
      box.innerHTML = errorHTML(data.error);
    } else {
      box.innerHTML = `<div class="card maile">
        <div class="mono"><span class="sq"></span> PROPOZYCJE MAILA</div>
        ${data.maile.map((m, i) => `<div class="mail-draft">
          <div class="mail-head"><span class="mono-inline">WERSJA ${i + 1}</span>
            <button class="kopiuj" type="button">Kopiuj</button></div>
          <pre class="mail-tresc">${esc(m)}</pre>
        </div>`).join("")}
      </div>`;
    }
  } catch (err) {
    box.innerHTML = errorHTML(err.message);
  } finally {
    przycisk.disabled = false;
    przycisk.textContent = "✉️ Generuj maile";
  }
}

function kopiuj(przycisk) {
  const tresc = przycisk.closest(".mail-draft").querySelector(".mail-tresc").textContent;
  navigator.clipboard.writeText(tresc).then(() => {
    przycisk.textContent = "✓ Skopiowano";
    setTimeout(() => (przycisk.textContent = "Kopiuj"), 1500);
  });
}

// ── Koszyk eksportu ──
function renderKoszyk() {
  koszykIle.textContent = koszyk.length;
  koszykBar.hidden = koszyk.length === 0;
  renderEksport(); // odśwież podgląd, jeśli zakładka otwarta
}

async function pobierzCSV() {
  if (!koszyk.length) return;
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

document.getElementById("koszyk-podglad").addEventListener("click", otworzEksport);
document.getElementById("koszyk-pobierz").addEventListener("click", pobierzCSV);

// ── Pomocnicze ──
function loadingHTML(tekst) {
  return `<div class="card loading"><div class="spinner"></div><p>${esc(tekst)}</p></div>`;
}
function errorHTML(msg) {
  return `<div class="card error"><div class="mono"><span class="sq"></span> BŁĄD</div><p>${esc(msg)}</p></div>`;
}
function hostname(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}
function esc(s) {
  return String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
function escAttr(s) { return esc(s).replace(/"/g, "&quot;"); }

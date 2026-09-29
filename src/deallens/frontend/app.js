/* DealLens interface. A configured API supplies live data; otherwise the page uses a generated snapshot. */
(() => {
  "use strict";

  const app = document.getElementById("app");
  const state = { data: null, filter: "all", query: "", mode: "snapshot" };
  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
  const safeUrl = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? escape(url.href) : "#";
    } catch { return "#"; }
  };
  const date = (value) => value ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`)) : "Not recorded";
  const titleCase = (value) => value ? String(value).replaceAll("_", " ").toLowerCase().replace(/\b\w/g, ch => ch.toUpperCase()) : "Unclassified";
  const badge = (status) => `<span class="badge ${String(status).toLowerCase()}">${escape(status)}</span>`;
  const eyebrow = (text) => `<span class="eyebrow">${escape(text)}</span>`;

  function money(fact, perShare = false) {
    if (!fact || fact.amount == null) return null;
    const n = Number(fact.amount);
    if (!Number.isFinite(n)) return null;
    const sign = fact.currency === "GBP" ? "£" : `${fact.currency || ""} `;
    if (perShare) return `${sign}${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(n)} / share`;
    if (Math.abs(n) >= 1e9) return `${sign}${(n / 1e9).toLocaleString("en-GB", { maximumFractionDigits: 3 })}bn`;
    if (Math.abs(n) >= 1e6) return `${sign}${(n / 1e6).toLocaleString("en-GB", { maximumFractionDigits: 2 })}m`;
    return `${sign}${n.toLocaleString("en-GB", { maximumFractionDigits: 2 })}`;
  }

  function record(deal, index) {
    return `<a class="record-row" href="#deal/${encodeURIComponent(deal.id)}">
      <span class="record-index">${String(index + 1).padStart(2, "0")}</span>
      <span><span class="record-title">${escape(deal.name)}</span><span class="record-meta"><span>${escape(deal.id)}</span><span>${date(deal.announcement_date)}</span><span>${escape(titleCase(deal.transaction_status))}</span></span></span>
      <span class="record-trailing">${badge(deal.review_status)}${icon("arrow")}</span>
    </a>`;
  }

  function heroGraphic() {
    return `<div class="hero-art" aria-hidden="true"><svg viewBox="0 0 390 210">
      <ellipse class="orbit faint" cx="196" cy="105" rx="178" ry="70" transform="rotate(-21 196 105)"/>
      <ellipse class="orbit" cx="196" cy="105" rx="143" ry="55" transform="rotate(-21 196 105)"/>
      <path class="axis" d="M15 164 370 42M72 13 318 198"/>
      <circle class="node secondary" cx="53" cy="151" r="4"/><circle class="node hollow" cx="115" cy="51" r="6"/><circle class="node" cx="198" cy="104" r="8"/><circle class="node hollow" cx="292" cy="139" r="6"/><circle class="node secondary" cx="354" cy="60" r="4"/>
      <text x="182" y="84" class="t-strong">SOURCE</text><text x="34" y="175">RESEARCH</text><text x="283" y="163">REVIEW</text><text x="323" y="38">VERIFY</text>
    </svg></div>`;
  }

  function metric(label, number, note) {
    return `<div class="metric-card"><span class="metric-label">${escape(label)}</span><div class="metric-number">${escape(number)}</div><span class="metric-note">${note}</span></div>`;
  }

  function overview() {
    const d = state.data, s = d.summary;
    const rows = d.deals.slice(0, 3).map(record).join("");
    const max = Math.max(1, s.inventory);
    const stages = [["Draft", s.draft], ["Reviewed", s.reviewed], ["Verified", s.verified_status]];
    const pipeline = stages.map(([label, count]) => `<div class="pipeline-row"><span class="stage">${label}</span><span class="track"><span class="fill" style="width:${Math.min(100, count / max * 100)}%"></span></span><strong>${count}</strong></div>`).join("");
    const cohorts = d.portfolio.ev_cohorts;
    const chart = !cohorts.length
      ? `<div class="empty-chart"><div class="empty-message"><span>∅</span><strong>No verified valuation sample yet</strong><p>Disclosed EV enters analysis after human verification and QA.</p></div></div>`
      : `<div class="chart-bars" role="img" aria-label="Verified disclosed EV observations by currency">${cohorts.map(c => `<div class="chart-bar" style="height:${Math.max(8, c.n / Math.max(...cohorts.map(x => x.n)) * 87)}%" title="${escape(c.currency)}: ${c.n} observations"><b>${c.n}</b><span>${escape(c.currency || "Unknown")}</span></div>`).join("")}</div>`;
    return `${eyebrow("Research intelligence / workspace")}
      <div class="page-heading"><div><h1>Transaction overview</h1><p>An auditable view of the research inventory and the verified analytical sample.</p></div><span class="heading-aside">COVERAGE <strong>UK &amp; EUROPE</strong></span></div>
      <section class="hero"><div class="hero-copy"><span class="hero-tag">DEALLENS RESEARCH STANDARD</span><h2>See the deal.<br><em>Trace the evidence.</em></h2><p>Transaction terms, valuation context and source records in one workspace. Only verified, QA-publishable records enter the portfolio layer.</p></div>${heroGraphic()}</section>
      <div class="status-strip">${icon("info")}<span><strong>Sample integrity:</strong> ${escape(d.policy)}</span></div>
      <div class="section-head"><div><h2>Research at a glance</h2><p>Counts reflect the research data shown here.</p></div><span class="section-index">01 / COVERAGE</span></div>
      <div class="metric-grid">
        ${metric("Records tracked", s.inventory, "Validated research records")}
        ${metric("Verified sample", s.verified, "Eligible for portfolio analysis")}
        ${metric("Draft research", s.draft, "Provisional, excluded from aggregates")}
        ${metric("Source records", d.deals.reduce((n, deal) => n + deal.sources.length, 0), "Linked to tracked records")}
      </div>
      <div class="section-head"><div><h2>Coverage &amp; verification</h2><p>The analytical view expands as records pass review.</p></div><span class="section-index">02 / QUALITY</span></div>
      <div class="content-grid"><section class="panel"><div class="panel-head"><div><h3>Disclosed EV sample</h3><p>Verified observations grouped by currency</p></div><span class="panel-kicker">N = ${cohorts.reduce((n, c) => n + c.n, 0)}</span></div>${chart}<div class="panel-bottom">No currency conversion or inferred enterprise value.</div></section>
      <section class="panel"><div class="panel-head"><div><h3>Research status</h3><p>Records by human review stage</p></div><span class="panel-kicker">${s.inventory} TOTAL</span></div><div class="pipeline">${pipeline}</div><div class="pipeline-caption"><strong>${s.verified} eligible</strong> for published analytics. Status counts include inbox research; stage widths use the inventory as denominator.</div></section></div>
      <div class="section-head"><div><h2>Research ledger</h2><p>Open a record to inspect its terms and sources.</p></div><a class="back-link" href="#research">View all ${icon("arrow")}</a></div>
      <div class="research-list">${rows || `<div class="empty-list">No research records are present in this dataset.</div>`}</div>`;
  }

  function research() {
    const count = state.data.deals.length;
    return `${eyebrow("Source linked records")}
      <div class="page-heading"><div><h1>Research ledger</h1><p>Search transaction records and inspect the evidence behind each case.</p></div><span class="heading-aside">${count} RECORD${count === 1 ? "" : "S"}</span></div>
      <div class="toolbar"><label class="search-box">${icon("search")}<input id="research-search" type="search" placeholder="Search company, deal ID or sector" value="${escape(state.query)}" autocomplete="off" aria-label="Search research records"></label>
      <div class="filter-tabs" role="group" aria-label="Filter records">${["all", "draft", "reviewed", "verified"].map(filter => `<button type="button" data-filter="${filter}" class="${state.filter === filter ? "active" : ""}" aria-pressed="${state.filter === filter}">${titleCase(filter)}</button>`).join("")}</div></div>
      <div id="research-results" class="research-list"></div><p class="research-note">${icon("info")} Draft records remain visible for research review and are excluded from portfolio figures.</p>`;
  }

  function updateResearchResults() {
    const target = document.getElementById("research-results");
    if (!target) return;
    const query = state.query.trim().toLowerCase();
    const matches = state.data.deals.filter(d => (state.filter === "all" || d.review_status.toLowerCase() === state.filter)
      && [d.name, d.id, d.bidder, d.target, d.sector].some(v => String(v || "").toLowerCase().includes(query)));
    target.innerHTML = matches.length ? matches.map(record).join("") : `<div class="empty-list">No records match this search and filter.</div>`;
  }

  function formatObservation(cohort, value) {
    if (value == null) return "Unavailable";
    const number = Number(value);
    if (!Number.isFinite(number)) return "Unavailable";
    if (cohort.unit === "fraction") return `${(number * 100).toLocaleString("en-GB", { maximumFractionDigits: 1 })}%`;
    if (cohort.unit === "ratio") return `${number.toLocaleString("en-GB", { maximumFractionDigits: 2 })}x`;
    if (cohort.unit === "currency") return money({ amount: value, currency: cohort.currency });
    return `${number.toLocaleString("en-GB", { maximumFractionDigits: 2 })} ${cohort.unit}`;
  }

  function metricPanel(metric, title, description) {
    const report = state.data.metrics?.[metric];
    const cohorts = report?.cohorts || [];
    const count = cohorts.reduce((total, cohort) => total + cohort.n, 0);
    const body = cohorts.length ? cohorts.map(cohort => {
      const stats = cohort.statistics;
      const entries = cohort.observations.map(item => `<a class="observation-row" href="#deal/${encodeURIComponent(item.deal_id)}"><span>${escape(item.deal_id)}</span><strong>${escape(formatObservation(cohort, item.value))}</strong>${icon("arrow")}</a>`).join("");
      return `<div class="cohort-block"><div class="cohort-heading"><span>${escape(cohort.currency || cohort.unit)}</span><strong>n = ${cohort.n}</strong></div>
        <div class="cohort-stats"><div><small>LOWER QUARTILE</small><strong>${escape(formatObservation(cohort, stats.q25))}</strong></div><div><small>MEDIAN</small><strong>${escape(formatObservation(cohort, stats.median))}</strong></div><div><small>UPPER QUARTILE</small><strong>${escape(formatObservation(cohort, stats.q75))}</strong></div></div>
        <details class="basis-detail"><summary>Definition and comparison basis</summary><p>${escape(cohort.basis)}</p></details><div class="observation-list">${entries}</div></div>`;
    }).join("") : `<div class="empty-analysis"><strong>No verified observations</strong><p>There is no publishable ${escape(title.toLowerCase())} sample. Missing values stay unavailable until a deal passes the manual verification and QA gates.</p></div>`;
    const coverage = !report ? "This measure is unavailable in the current dataset."
      : report.eligible_n === 0 ? "No verified deals are available for this measure."
        : `${report.missing_n} of ${report.eligible_n} eligible deals have no meaningful observation for this measure.`;
    return `<section class="panel analysis-panel"><div class="panel-head"><div><h3>${escape(title)}</h3><p>${escape(description)}</p></div><span class="panel-kicker">N = ${count}</span></div><div class="analysis-body">${body}</div><div class="panel-bottom">${coverage}</div></section>`;
  }

  function analysisPage(page) {
    const pages = {
      valuation: { title: "Valuation", intro: "Comparable transaction multiples and disclosed enterprise values, with each basis kept separate.", sections: [["disclosed_ev", "Disclosed enterprise value", "Reported value in its original currency"], ["ev_ebitda", "EV / EBITDA", "Selected earnings period and definition"], ["ev_revenue", "EV / revenue", "Selected revenue period and definition"]] },
      premiums: { title: "Offer premiums", intro: "Selected offers compared with their stated unaffected price references.", sections: [["premium", "Offer premium", "Offer stage and reference price basis remain attached"]] },
      financing: { title: "Financing & leverage", intro: "Illustrative leverage results from explicit financing inputs, shown only where calculable.", sections: [["buyer_standalone_leverage", "Buyer standalone leverage", "Before the transaction"], ["leverage_before_synergy", "Pro forma leverage", "Before eligible cost synergies"], ["leverage_after_synergy", "Leverage after synergies", "Illustrative eligible synergy case"]] },
      synergies: { title: "Synergies", intro: "Disclosed cost synergy inputs and illustrative valuation adjustments, never treated as realised earnings.", sections: [["cost_synergy_ev", "Cost synergies / EV", "Eligible annual cost synergies against enterprise value"], ["synergy_adjusted_multiple", "Synergy-adjusted multiple", "Illustrative adjusted earnings basis"]] }
    };
    const item = pages[page];
    return `${eyebrow("Verified portfolio / comparable cohorts")}<div class="page-heading"><div><h1>${escape(item.title)}</h1><p>${escape(item.intro)}</p></div><span class="heading-aside">${state.data.summary.verified} VERIFIED DEAL${state.data.summary.verified === 1 ? "" : "S"}</span></div>
      <div class="status-strip">${icon("info")}<span>Only attested, QA-publishable records enter these summaries. Currency, period and definition are never silently pooled.</span></div>
      <div class="analysis-grid">${item.sections.map(([metric, title, description]) => metricPanel(metric, title, description)).join("")}</div>`;
  }

  function outcomesPage() {
    const p = state.data.portfolio;
    const rate = p.completion_rate == null ? "Unavailable" : formatObservation({ unit: "fraction" }, p.completion_rate);
    const days = p.completion_days_median == null ? "Unavailable" : `${Number(p.completion_days_median).toLocaleString("en-GB", { maximumFractionDigits: 0 })} days`;
    const statuses = p.status_counts.map(item => `<div class="outcome-row"><span>${escape(titleCase(item.status))}</span><strong>${item.n}</strong></div>`).join("");
    return `${eyebrow("Verified portfolio / transaction outcomes")}<div class="page-heading"><div><h1>Deal outcomes</h1><p>Completion status and timing from attested, QA-publishable transactions.</p></div><span class="heading-aside">${p.deal_count} VERIFIED DEAL${p.deal_count === 1 ? "" : "S"}</span></div>
      <div class="metric-grid outcome-metrics">${metric("Verified deals", p.deal_count, "QA-publishable sample")}${metric("Completion rate", rate, `n=${p.completion_n} verified deals`)}${metric("Median time to completion", days, `n=${p.completion_days_n} completed with dates`)}</div>
      <section class="panel outcome-panel"><div class="panel-head"><div><h3>Transaction status</h3><p>Counts use only the verified sample.</p></div></div><div class="analysis-body">${statuses || `<div class="empty-analysis"><strong>No verified outcomes yet</strong><p>The research ledger may contain draft cases, but they do not enter this portfolio view.</p></div>`}</div></section>`;
  }

  function qualityPage() {
    const deals = state.data.deals;
    const cards = deals.map(deal => {
      const blockers = deal.qa.flags.filter(flag => ["BLOCK_PUBLISH", "ERROR"].includes(flag.severity)).length;
      return `<a class="quality-record" href="#deal/${encodeURIComponent(deal.id)}"><span><strong>${escape(deal.name)}</strong><small>${escape(deal.id)} · ${escape(deal.origin)}</small></span><span>${badge(deal.review_status)}<small>${deal.sources.length} sources · ${deal.evidence_count} references · ${blockers} blockers</small></span>${icon("arrow")}</a>`;
    }).join("");
    return `${eyebrow("Research integrity / provenance")}<div class="page-heading"><div><h1>Data quality &amp; sources</h1><p>Review status, source coverage and publication blockers for every displayed record.</p></div><span class="heading-aside">${deals.length} RECORD${deals.length === 1 ? "" : "S"}</span></div>
      <div class="metric-grid outcome-metrics">${metric("Records shown", deals.length, "Validated research records")}${metric("Verified sample", state.data.summary.verified, "Attested and QA-publishable")}${metric("Provisional records", state.data.summary.draft + state.data.summary.reviewed, "Outside portfolio statistics")}</div>
      <section class="panel outcome-panel"><div class="panel-head"><div><h3>Record quality</h3><p>Open a case for its source ledger, definitions and QA flags.</p></div></div><div class="quality-records">${cards || `<div class="empty-analysis"><strong>No records available</strong><p>Add validated research to populate the ledger.</p></div>`}</div></section>`;
  }

  function sourcePills(fact, sources) {
    return fact?.sources?.length ? `<span class="source-pills">${fact.sources.map(id => {
      const source = sources.find(s => s.id === id);
      return source ? `<a href="${safeUrl(source.url)}" target="_blank" rel="noopener noreferrer" title="${escape(source.title)}">${escape(id)} ${icon("external")}</a>` : "";
    }).join("")}</span>` : "";
  }

  function factRow(label, value, detail, fact, sources) {
    return `<div class="fact-row"><span class="fact-label">${escape(label)}</span><span class="fact-main">${value ? `<strong>${escape(value)}</strong>` : `<span class="absence">Not recorded</span>`}${detail ? `<small>${escape(detail)}</small>` : ""}${sourcePills(fact, sources)}</span></div>`;
  }

  function casePage(deal) {
    const v = deal.values;
    const keyFlags = deal.qa.flags.filter(f => ["BLOCK_PUBLISH", "ERROR"].includes(f.severity));
    const sources = deal.sources;
    const offer = money(v.offer, true);
    const equity = money(v.equity), enterprise = money(v.enterprise);
    const flagText = keyFlags.length ? keyFlags.slice(0, 3).map(f => `<div class="blocker">${icon("info")}<span><strong>${escape(titleCase(f.code))}.</strong> ${escape(f.message)}</span></div>`).join("") : `<p class="quality-hint">No publication blocker returned by the current QA check.</p>`;
    const sourceList = sources.map(source => `<a class="source-link" href="${safeUrl(source.url)}" target="_blank" rel="noopener noreferrer"><span class="source-id">${escape(source.id)}</span><span><strong>${escape(source.title)}</strong><small>${escape(titleCase(source.type))} · ${date(source.date)}</small></span>${icon("external")}</a>`).join("");
    return `<div class="case-top"><a href="#research" class="back-link">${icon("arrow")} Back to ledger</a>${badge(deal.review_status)}</div>
      ${eyebrow(`Transaction record / ${deal.id}`)}
      <div class="case-intro"><div><h1>${escape(deal.name)}</h1><p class="case-subtitle">${escape(deal.bidder)} / ${escape(deal.target)} · Announced ${date(deal.announcement_date)}</p></div><div class="case-actions"><button class="ghost-button" id="download-record" type="button">${icon("download")} Download case summary</button></div></div>
      ${deal.review_status !== "VERIFIED" ? `<div class="draft-banner">${icon("info")}<span><strong>Provisional research record</strong>The terms below come from this research record. They have not received the owner’s manual source and calculation sign-off, and do not enter portfolio statistics.</span></div>` : !deal.qa.publishable ? `<div class="draft-banner">${icon("info")}<span><strong>Excluded from portfolio analysis</strong>The record has VERIFIED status, but its current QA result blocks publication.</span></div>` : `<div class="status-strip">${icon("info")}<span><strong>Verified record.</strong> This record has passed the project’s manual verification and QA gates.</span></div>`}
      <section class="case-flow" aria-label="Transaction relationship diagram"><div class="flow-header"><span>TRANSACTION STRUCTURE</span><span>${escape(deal.id)} / ${escape(deal.review_status)}</span></div><div class="flow-line"><div class="flow-entity"><small>BIDDER</small><strong>${escape(deal.bidder)}</strong></div><div class="flow-connector"><span>${escape(offer || "Offer terms")}</span></div><div class="flow-entity right"><small>TARGET</small><strong>${escape(deal.target)}</strong></div></div><div class="flow-caption"><span>ANNOUNCED <strong>${date(deal.announcement_date)}</strong></span><span>TRANSACTION <strong>${escape(titleCase(deal.transaction_status))}</strong></span><span>COMPLETION <strong>${date(deal.completion_date)}</strong></span></div></section>
      <div class="case-grid"><section class="panel"><div class="panel-head"><div><h3>Recorded terms</h3><p>Figures retain their reported definitions and source links.</p></div><span class="panel-kicker">${escape(deal.review_status)}</span></div><div class="facts-list">
        ${factRow("Selected offer", offer, v.offer?.definition || deal.selected_offer?.basis, v.offer, sources)}
        ${factRow("Equity value", equity, v.equity?.definition, v.equity, sources)}
        ${factRow("Enterprise value", enterprise, v.enterprise?.definition, v.enterprise, sources)}
        ${factRow("Sector", deal.sector, "Analyst classification in research record", null, sources)}
      </div></section><section class="panel"><div class="panel-head"><div><h3>Quality &amp; review</h3><p>Publication gate for this record</p></div></div><div class="quality-list"><div class="quality-stat"><span>Review status</span>${badge(deal.review_status)}</div><div class="quality-stat"><span>Record source</span><span>${escape(deal.origin)}</span></div><div class="quality-stat"><span>Source documents</span><strong>${sources.length}</strong></div><div class="quality-stat"><span>Evidence references</span><strong>${deal.evidence_count}</strong></div><div class="quality-stat"><span>Publication blockers</span><strong>${keyFlags.length}</strong></div>${flagText}${keyFlags.length > 3 ? `<p class="quality-hint">${keyFlags.length - 3} additional blocker${keyFlags.length - 3 === 1 ? "" : "s"} remain in the QA result.</p>` : ""}</div></section></div>
      <section class="panel source-section"><div class="panel-head"><div><h3>Source ledger</h3><p>Direct links stored with the research record. A link does not imply independent verification.</p></div><span class="panel-kicker">${sources.length} SOURCES</span></div><div class="source-list">${sourceList || `<p class="absence">No source documents recorded.</p>`}</div></section>`;
  }

  function methodology() {
    return `${eyebrow("Data provenance / publication policy")}
      <div class="method-intro"><h1>From source<br>to defensible insight.</h1><p>DealLens separates provisional research from verified portfolio analysis. This is the actual gating logic used by the local research engine.</p></div>
      <section class="method-flow"><div class="method-steps"><div class="method-step"><span class="method-node">1</span><span class="method-index">CAPTURE</span><h3>Research</h3><p>Terms, financial observations and source references enter a validated deal record.</p></div><div class="method-step"><span class="method-node">2</span><span class="method-index">CHALLENGE</span><h3>Review</h3><p>Calculations, definitions, evidence and reasonableness flags are checked. A draft is still excluded.</p></div><div class="method-step"><span class="method-node">3</span><span class="method-index">PUBLISH</span><h3>Verify</h3><p>A named human attests to the review; the record must pass QA before entering portfolio analysis.</p></div></div><div class="method-rule"></div><div class="method-criteria"><div><strong>Reported ≠ calculated</strong><p>Original source values remain distinct from derived results and assumptions.</p></div><div><strong>Unknown ≠ zero</strong><p>Missing figures stay empty. The interface never substitutes a numeric zero.</p></div><div><strong>Comparable basis required</strong><p>Currency, period and financial definitions remain attached to cohorts.</p></div></div></section>
      <div class="section-head"><div><h2>How to read this workspace</h2><p>Visible status labels govern how each number may be used.</p></div></div>
      <div class="definition-grid"><div class="definition-card"><span>01 / RESEARCH LEDGER</span><h3>Draft and reviewed cases</h3><p>These records can be inspected with their source links and review flags. They are working material and remain outside headline portfolio analytics.</p></div><div class="definition-card"><span>02 / PORTFOLIO LAYER</span><h3>Verified, publishable cases</h3><p>Only attested VERIFIED records that pass QA contribute to aggregate figures. Cohorts retain their currency and valuation basis.</p></div><div class="definition-card"><span>03 / FINANCIAL VALUES</span><h3>Reported definitions</h3><p>Offer, equity and enterprise values preserve the definitions in the research record. The case view links figures to their recorded sources.</p></div><div class="definition-card"><span>04 / RESEARCH WORKSPACE</span><h3>Read-only interface</h3><p>This screen presents research data without editing it. Manual verification, research edits and database imports remain explicit actions in the Python workflow.</p></div></div>`;
  }

  function navigate() {
    if (!state.data) return;
    const raw = location.hash.replace(/^#/, "") || "overview";
    const [page, encodedId] = raw.split("/");
    let id = null;
    try { id = decodeURIComponent(encodedId || ""); } catch { /* Invalid URL is handled below. */ }
    const deal = page === "deal" ? state.data.deals.find(item => item.id === id) : null;
    const knownPage = ["overview", "research", "valuation", "premiums", "financing", "synergies", "outcomes", "quality", "methodology"].includes(page) && !encodedId;
    const notFound = !deal && !knownPage;
    const name = deal ? "TRANSACTION RECORD" : notFound ? "NOT FOUND" : ({ overview: "OVERVIEW", research: "RESEARCH LEDGER", valuation: "VALUATION", premiums: "OFFER PREMIUMS", financing: "FINANCING & LEVERAGE", synergies: "SYNERGIES", outcomes: "DEAL OUTCOMES", quality: "DATA QUALITY", methodology: "METHODOLOGY" })[page];
    document.getElementById("breadcrumb").textContent = name;
    document.querySelectorAll("[data-nav]").forEach(link => {
      const active = link.dataset.nav === (deal ? "research" : page) && !notFound;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    app.innerHTML = deal ? casePage(deal) : notFound ? `<div class="error-state"><h1>Page not found</h1><p>That research page or deal ID is not in this dataset.</p><a class="back-link" href="#overview">${icon("arrow")} Return to overview</a></div>` : page === "research" ? research() : ["valuation", "premiums", "financing", "synergies"].includes(page) ? analysisPage(page) : page === "outcomes" ? outcomesPage() : page === "quality" ? qualityPage() : page === "methodology" ? methodology() : overview();
    if (page === "research") updateResearchResults();
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("menu-button").setAttribute("aria-expanded", "false");
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  app.addEventListener("input", (event) => {
    if (event.target.id === "research-search") { state.query = event.target.value; updateResearchResults(); }
  });
  app.addEventListener("click", (event) => {
    const filter = event.target.closest("[data-filter]");
    if (filter) {
      state.filter = filter.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach(button => { button.classList.toggle("active", button === filter); button.setAttribute("aria-pressed", String(button === filter)); });
      updateResearchResults();
    }
    if (event.target.closest("#download-record")) {
      const id = decodeURIComponent(location.hash.split("/")[1] || "");
      const deal = state.data.deals.find(item => item.id === id);
      if (deal) {
        const blob = new Blob([JSON.stringify(deal, null, 2)], { type: "application/json" });
        const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${deal.id}-case-summary.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      }
    }
  });
  document.getElementById("menu-button").addEventListener("click", (event) => {
    const open = document.getElementById("sidebar").classList.toggle("open");
    event.currentTarget.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", (event) => {
    if (window.innerWidth <= 850 && !event.target.closest("#sidebar,#menu-button")) {
      document.getElementById("sidebar").classList.remove("open");
      document.getElementById("menu-button").setAttribute("aria-expanded", "false");
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.getElementById("sidebar").classList.remove("open");
      document.getElementById("menu-button").setAttribute("aria-expanded", "false");
    }
  });
  window.addEventListener("hashchange", navigate);

  async function init() {
    const apiUrl = document.querySelector('meta[name="deallens-api"]')?.content;
    if (apiUrl && ["http:", "https:"].includes(location.protocol)) {
      try {
        const response = await fetch(apiUrl, { cache: "no-store" });
        if (!response.ok) throw new Error(`Data request failed (${response.status})`);
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        state.data = data;
        state.mode = "live";
      } catch (error) {
        app.innerHTML = `<div class="error-state"><h1>Live data unavailable</h1><p>${escape(error.message)}</p></div>`;
        return;
      }
    } else {
      state.data = window.DEALLENS_SNAPSHOT;
    }
    if (!state.data) {
      app.innerHTML = `<div class="error-state"><h2>Research data unavailable</h2><p>The published research snapshot is missing.</p></div>`;
      return;
    }
    const modeLabel = state.mode === "live" ? "LIVE RESEARCH DATA" : "PUBLISHED SNAPSHOT";
    document.getElementById("sidebar-mode").textContent = modeLabel;
    document.getElementById("footer-mode").textContent = modeLabel + (state.data.release_version ? ` · RELEASE ${state.data.release_version}` : "");
    document.getElementById("clock").textContent = modeLabel;
    navigate();
  }
  init();
})();

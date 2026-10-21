const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let allLinks = [];
let analyticsData = null;
let activeFilter = "all";
let analyticsDays = 7;
let toastTimer;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}
function shortHost(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}
function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}
function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
function showToast(message, type = "success") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.className = "toast", 3000);
}
async function api(url, options = {}) {
  const mutating = ["POST", "PATCH", "PUT", "DELETE"].includes((options.method || "GET").toUpperCase());
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(mutating ? { "X-CSRF-Token": csrf } : {}), ...(options.headers || {}) }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
async function loadDashboard() {
  try {
    const end = new Date();
    const start = new Date(); start.setDate(start.getDate() - (analyticsDays - 1));
    const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    const [links, analytics, me] = await Promise.all([api("/api/links"), api(`/api/analytics?start=${iso(start)}&end=${iso(end)}`), api("/api/auth/me")]);
    allLinks = links;
    analyticsData = analytics;
    renderStats(analytics);
    renderChart(analytics.daily || []);
    renderReferrers(analytics.referrers || []);
    renderLinks();
    $("#navLinkCount").textContent = links.length;
    $("#planUsage").textContent = `${links.length} links created`;
    $("#profileName").textContent = me.name;
    $("#profileEmail").textContent = me.email;
    $("#workspaceName").textContent = `${me.name}'s workspace`;
    $("#workspacePlan").textContent = `${me.plan.toUpperCase()} PLAN`;
    $("#planName").textContent = `${me.plan.toUpperCase()} PLAN`;
    await loadSettings();
  } catch (error) {
    showToast(`Could not load dashboard: ${error.message}`, "error");
    $("#linksTable").innerHTML = `<tr><td colspan="5" class="empty-state">Unable to load data. Is the backend running? ${escapeHtml(error.message)}</td></tr>`;
  }
}
function renderStats(data) {
  $("#totalClicks").textContent = formatNumber(data.total_clicks);
  $("#totalLinks").textContent = formatNumber(data.total_links);
  $("#todayClicks").textContent = formatNumber(data.today_clicks);
  $("#activeLinks").textContent = formatNumber(data.active_links);
  $("#chartTotal").textContent = formatNumber((data.daily || []).reduce((sum, item) => sum + item.count, 0));
  const uniqueNote = document.querySelector(".panel-bottom-note"); if (uniqueNote) uniqueNote.innerHTML = `<span class="tiny-check">✓</span> Approx. ${formatNumber(data.unique_visitors_estimate || 0)} unique visitors · estimated`;
  const chartCaption = document.querySelector("#chartTotal").nextElementSibling; if (chartCaption) chartCaption.textContent = ` clicks in the last ${analyticsDays} days`;
  $("#linkCountBadge").textContent = data.total_links;
}
function renderChart(daily) {
  const values = daily.map(item => Number(item.count) || 0);
  const max = Math.max(...values, 1);
  $("#chartBars").innerHTML = daily.map((item, index) => {
    const height = Math.max(3, (Number(item.count) / max) * 100);
    const date = new Date(`${item.day}T12:00:00`);
    const dayLabel = date.toLocaleDateString(undefined, { weekday: "short" });
    return `<div class="bar-column"><div class="bar-value">${formatNumber(item.count)}</div><div class="bar" style="height:${height}%" title="${escapeHtml(item.day)}: ${item.count} clicks"></div></div>`;
  }).join("");
  $("#chartLabels").innerHTML = daily.map(item => {
    const date = new Date(`${item.day}T12:00:00`);
    return `<span>${date.toLocaleDateString(undefined, { weekday: "short" })}</span>`;
  }).join("");
  const labels = $$("#chartCanvas .chart-gridlines i");
  labels.forEach((line, i) => { line.setAttribute("aria-hidden", "true"); });
}
function renderReferrers(referrers) {
  const total = referrers.reduce((sum, item) => sum + item.count, 0) || 1;
  const icons = ["G", "in", "↗", "✉", "•"];
  const classes = ["source-google", "source-linkedin", "source-social", "source-mail", "source-direct"];
  if (!referrers.length) {
    $("#sourceList").innerHTML = '<div class="empty-inline">No clicks yet. Share a link to start collecting analytics.</div>';
    return;
  }
  $("#sourceList").innerHTML = referrers.slice(0, 5).map((item, index) => {
    const pct = Math.round((item.count / total) * 100);
    return `<div class="source-row"><div class="source-main"><span class="source-icon ${classes[index % classes.length]}">${icons[index % icons.length]}</span><div class="source-name"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong><div class="source-progress"><span style="width:${pct}%"></span></div></div><div class="source-count"><strong>${formatNumber(item.count)}</strong><small>${pct}%</small></div></div></div>`;
  }).join("");
}
function renderLinks() {
  const query = $("#linkSearch").value.trim().toLowerCase();
  let filtered = allLinks.filter(link => {
    const matchesQuery = [link.title, link.original_url, link.short_url, link.code].some(value => String(value).toLowerCase().includes(query));
    const matchesFilter = activeFilter === "all" || (activeFilter === "active" ? link.is_active : !link.is_active);
    return matchesQuery && matchesFilter;
  });
  if (!filtered.length) {
    $("#linksTable").innerHTML = `<tr><td colspan="5"><div class="empty-state"><span>⌁</span><strong>No links found</strong><p>${allLinks.length ? "Try another search or filter." : "Create your first short link to get started."}</p></div></td></tr>`;
  } else {
    $("#linksTable").innerHTML = filtered.map(link => {
      const favicon = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(shortHost(link.original_url))}&sz=64`;
      return `<tr>
        <td><div class="link-cell"><img class="site-favicon" src="${favicon}" alt="" onerror="this.style.display='none'"><div class="link-info"><a class="short-link" href="/${encodeURIComponent(link.code)}" target="_blank" rel="noopener noreferrer">${escapeHtml(location.host + "/" + link.code)} <span>↗</span></a><span class="destination" title="${escapeHtml(link.original_url)}">${escapeHtml(link.title || shortHost(link.original_url))} · ${escapeHtml(shortHost(link.original_url))}</span></div></div></td>
        <td><strong class="click-count">${formatNumber(link.clicks)}</strong><span class="table-subtext">clicks</span></td>
        <td><span class="created-date">${formatDate(link.created_at)}</span></td>
        <td><span class="status ${link.is_active ? "status-active" : "status-paused"}"><i></i>${link.is_active ? "Active" : "Paused"}</span></td>
        <td><div class="row-actions"><button class="row-action" title="Copy short link" data-action="copy" data-id="${link.id}">▢</button><button class="row-action" title="View analytics" data-action="analytics" data-id="${link.id}">⌁</button><button class="row-action" title="${link.is_active ? "Pause" : "Activate"} link" data-action="toggle" data-id="${link.id}">${link.is_active ? "Ⅱ" : "▶"}</button><button class="row-action danger-action" title="Delete link" data-action="delete" data-id="${link.id}">×</button></div></td>
      </tr>`;
    }).join("");
  }
  $("#tableSummary").textContent = `Showing ${filtered.length} of ${allLinks.length} links`;
  $("#navLinkCount").textContent = allLinks.length;
  $("#linkCountBadge").textContent = allLinks.length;
}
async function createLink(event) {
  event.preventDefault();
  const button = $("#submitLink");
  const errorBox = $("#formError");
  errorBox.textContent = "";
  button.disabled = true;
  button.textContent = "Creating link…";
  try {
    const result = await api("/api/links", {
      method: "POST",
      body: JSON.stringify({
        original_url: $("#destination").value.trim(),
        title: $("#linkTitle").value.trim(),
        custom_code: $("#customAlias").value.trim()
      })
    });
    $("#createForm").reset();
    closeModal("createModal");
    await loadDashboard();
    showToast(`Short link created: ${result.short_url}`);
    try { await navigator.clipboard.writeText(result.short_url); showToast("Short link created and copied!"); } catch {}
  } catch (error) {
    errorBox.textContent = error.message;
  } finally {
    button.disabled = false;
    button.innerHTML = 'Create short link <span>→</span>';
  }
}
function openModal(id) {
  const modal = document.getElementById(id);
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  const first = modal.querySelector("input");
  if (first) setTimeout(() => first.focus(), 80);
}
function closeModal(id) {
  const modal = document.getElementById(id);
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  if (!$(".modal-backdrop.open")) document.body.classList.remove("modal-open");
}
async function handleTableAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const link = allLinks.find(item => item.id === Number(button.dataset.id));
  if (!link) return;
  const action = button.dataset.action;
  try {
    if (action === "copy") {
      await navigator.clipboard.writeText(link.short_url);
      showToast("Short link copied to clipboard.");
    } else if (action === "analytics") {
      await showLinkDetails(link);
    } else if (action === "toggle") {
      await api(`/api/links/${link.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !link.is_active }) });
      await loadDashboard();
      showToast(link.is_active ? "Link paused." : "Link activated.");
    } else if (action === "delete") {
      if (!confirm(`Delete "${link.title}"? Its click history will also be deleted.`)) return;
      await api(`/api/links/${link.id}`, { method: "DELETE" });
      await loadDashboard();
      showToast("Link deleted.");
    }
  } catch (error) {
    showToast(error.message || "Action failed.", "error");
  }
}
async function showLinkDetails(link) {
  const data = await api(`/api/links/${link.id}`);
  $("#detailTitle").textContent = data.link.title || "Link performance";
  $("#detailUrl").textContent = data.link.short_url;
  $("#detailClicks").textContent = formatNumber(data.link.clicks);
  const max = Math.max(...data.daily.map(x => x.count), 1);
  $("#detailBars").innerHTML = data.daily.map(item => {
    const date = new Date(`${item.day}T12:00:00`);
    const label = date.toLocaleDateString(undefined, { weekday: "short" });
    return `<div class="detail-bar-col"><span>${item.count}</span><div style="height:${Math.max(3, item.count / max * 100)}%"></div><small>${label}</small></div>`;
  }).join("");
  $("#detailRefs").innerHTML = data.referrers.length ? data.referrers.map(ref => `<div class="detail-ref"><span>${escapeHtml(ref.name)}</span><strong>${formatNumber(ref.count)}</strong></div>`).join("") : '<p class="empty-inline">No click events recorded yet.</p>';
  openModal("detailModal");
}
function exportCsv() {
  const rows = [["Title", "Short URL", "Destination URL", "Clicks", "Status", "Created"]];
  allLinks.forEach(link => rows.push([link.title, link.short_url, link.original_url, link.clicks, link.is_active ? "Active" : "Paused", link.created_at]));
  const csv = rows.map(row => row.map(value => `"${String(value ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = "linklytics-links.csv"; anchor.click();
  URL.revokeObjectURL(url);
  showToast("CSV export downloaded.");
}
function setupEvents() {
  $("#openCreate").addEventListener("click", () => openModal("createModal"));
  $("#createForm").addEventListener("submit", createLink);
  $("#linksTable").addEventListener("click", handleTableAction);
  $("#linkSearch").addEventListener("input", renderLinks);
  $("#refreshBtn").addEventListener("click", async () => { await loadDashboard(); showToast("Dashboard refreshed."); });
  $("#exportBtn").addEventListener("click", exportCsv);
  $("#baseUrl").textContent = `${location.host}/`;
  $("#filterBtn").addEventListener("click", () => {
    const choice = prompt("Filter links: type all, active, or paused", activeFilter);
    if (choice === null) return;
    const normalized = choice.trim().toLowerCase();
    if (!["all", "active", "paused"].includes(normalized)) { showToast("Enter all, active, or paused.", "error"); return; }
    activeFilter = normalized; renderLinks();
  });
  $("#rangeSelect").addEventListener("click", async () => {
    const choice = prompt("Chart range in days: enter 7, 30, or 90", String(analyticsDays));
    if (choice === null) return;
    const days = Number(choice);
    if (![7, 30, 90].includes(days)) { showToast("Choose 7, 30, or 90 days.", "error"); return; }
    analyticsDays = days; $("#rangeSelect").textContent = `Last ${days} days⌄`;
    await loadDashboard();
  });
  $("#upgradeBtn").addEventListener("click", () => { $("#settingsPanel").scrollIntoView({behavior:"smooth",block:"start"}); showToast("Review your plan and billing status in Settings."); });
  $("#billingBtn").addEventListener("click", async () => {
    try {
      const info = await api("/api/billing");
      if (info.plan !== "pro" && info.checkout_configured) {
        const startCheckout = confirm(`Upgrade to Linklytics Pro?\n\nLinks: ${info.links_used} / ${info.links_limit ?? "unlimited"}\nClicks this month: ${info.clicks_used} / ${info.clicks_limit ?? "unlimited"}\n\nYou'll continue to Stripe Checkout to review pricing and pay.`);
        if (!startCheckout) return;
        const checkout = await api("/api/billing/checkout", { method: "POST", body: JSON.stringify({}) });
        if (checkout.checkout_url) location.href = checkout.checkout_url;
        return;
      }
      alert(`Plan: ${info.plan.toUpperCase()}\nBilling status: ${info.billing_status}\nLinks: ${info.links_used}${info.links_limit ? ` / ${info.links_limit}` : " / unlimited"}\nClicks this month: ${info.clicks_used}${info.clicks_limit ? ` / ${info.clicks_limit}` : " / unlimited"}\n\n${info.message}`);
    } catch(e) { showToast(e.message,"error"); }
  });
  $("#domainForm").addEventListener("submit", async e => { e.preventDefault(); const domain=$("#domainInput").value.trim(); try { const item=await api("/api/domains",{method:"POST",body:JSON.stringify({domain})}); $("#domainInput").value=""; alert(`Domain added: ${item.domain}\n\nCreate a DNS TXT record named _linklytics.${item.domain} with this value:\n${item.verification_token}\n\n${item.instructions}`); await loadDomains(); } catch(err) { showToast(err.message,"error"); } });
  $("#logoutBtn").addEventListener("click", async () => { if(!confirm("Sign out of Linklytics?")) return; try { await fetch("/api/auth/logout",{method:"POST",headers:{"Content-Type":"application/json"}}); location.href="/"; } catch(e) { showToast("Could not sign out.","error"); } });
  $("#helpBtn").addEventListener("click", () => alert("Linklytics help\\n\\n1. Create a short link.\\n2. Open the short URL to record a click.\\n3. Review dashboard and link analytics.\\n\\nThis local MVP uses demo data on first launch."));
  ["privacyLink", "docsLink"].forEach(id => $("#" + id).addEventListener("click", e => { e.preventDefault(); showToast("Documentation page planned for a future version."); }));
  $$(".modal-close").forEach(button => button.addEventListener("click", () => closeModal(button.dataset.close)));
  $$(".modal-backdrop").forEach(backdrop => backdrop.addEventListener("click", e => { if (e.target === backdrop) closeModal(backdrop.id); }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") $$(".modal-backdrop.open").forEach(modal => closeModal(modal.id)); });
  $$(".nav-item").forEach(button => button.addEventListener("click", () => {
    $$(".nav-item").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    const section = button.dataset.section;
    $("#breadcrumbTitle").textContent = button.textContent.trim();
    if (section === "links") $("#linksPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    else if (section === "analytics") $(".chart-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    else if (section === "settings") $("#settingsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    else window.scrollTo({ top: 0, behavior: "smooth" });
    $("#sidebar").classList.remove("sidebar-open");
  }));
  $("#mobileMenu").addEventListener("click", () => $("#sidebar").classList.toggle("sidebar-open"));
}
async function loadSettings() {
  await Promise.all([loadBilling(), loadDomains()]);
}
async function loadBilling() {
  try {
    const b = await api("/api/billing");
    const linkLimit = b.links_limit == null ? "unlimited" : b.links_limit;
    const clickLimit = b.clicks_limit == null ? "unlimited" : b.clicks_limit.toLocaleString();
    $("#billingUsage").innerHTML = `<div class="detail-ref"><span>Current plan</span><strong>${escapeHtml(b.plan.toUpperCase())}</strong></div><div class="detail-ref"><span>Links created</span><strong>${formatNumber(b.links_used)} / ${linkLimit}</strong></div><div class="detail-ref"><span>Clicks this month</span><strong>${formatNumber(b.clicks_used)} / ${clickLimit}</strong></div>`;
  } catch(e) { $("#billingUsage").textContent = e.message; }
}
async function loadDomains() {
  try {
    const domains = await api("/api/domains");
    if (!domains.length) { $("#domainList").innerHTML = '<div class="empty-inline">No custom domains added yet.</div>'; return; }
    $("#domainList").innerHTML = domains.map(d => `<div class="detail-ref"><span><strong>${escapeHtml(d.domain)}</strong><small style="display:block;color:#888">${d.verified ? "Verified · active for short-link URLs" : `Pending DNS verification · TXT: ${escapeHtml(d.verification_token)}`}</small></span><span style="display:flex;gap:4px">${d.verified ? "" : `<button class="row-action" data-domain-verify="${d.id}" title="Verify DNS">✓</button>`}<button class="row-action danger-action" data-domain-delete="${d.id}" title="Remove domain">×</button></span></div>`).join("");
    $$("[data-domain-verify]").forEach(btn => btn.addEventListener("click", async()=>{try{await api(`/api/domains/${btn.dataset.domainVerify}/verify`,{method:"POST",body:JSON.stringify({})});await loadDomains();await loadDashboard();showToast("Domain verified.");}catch(e){showToast(e.message,"error");}}));
    $$("[data-domain-delete]").forEach(btn => btn.addEventListener("click", async()=>{if(!confirm("Remove this domain?"))return;try{await api(`/api/domains/${btn.dataset.domainDelete}`,{method:"DELETE"});await loadDomains();showToast("Domain removed.");}catch(e){showToast(e.message,"error");}}));
  } catch(e) { $("#domainList").textContent = e.message; }
}
document.addEventListener("DOMContentLoaded", () => { setupEvents(); loadDashboard(); });

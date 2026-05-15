// predictormaster ops dashboard — polling + DOM updates.
// All numeric formatting is locale-stable so the operator's screen
// looks the same regardless of system locale. Values that come back
// null/undefined render as "—" — never as "NaN" or "$0.00".

const POLL_MS_FAST = 2000;     // status, decisions, runner stdout
const POLL_MS_SLOW = 15000;    // balance (Polygon RPC), metrics aggregation
let LIVE_TOKEN = null;

const $ = (id) => document.getElementById(id);

const fmt = {
  usd(v, signed = false) {
    if (v === null || v === undefined || !Number.isFinite(v)) return "—";
    const abs = Math.abs(v).toLocaleString("en-US", {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
    const sign = signed ? (v >= 0 ? "+" : "−") : (v < 0 ? "−" : "");
    return `${sign}$${abs}`;
  },
  num(v, digits = 4) {
    if (v === null || v === undefined || !Number.isFinite(v)) return "—";
    return v.toLocaleString("en-US", {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
  },
  pct(v) {
    if (v === null || v === undefined || !Number.isFinite(v)) return "—";
    return (v * 100).toFixed(1) + "%";
  },
  addr(a) {
    if (!a) return "—";
    return a.slice(0, 6) + "…" + a.slice(-4);
  },
  time(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString("en-US", { hour12: false });
    } catch { return iso; }
  },
};

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

// ---- status ----
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    LIVE_TOKEN = s.live_confirmation_token;
    $("confirm-token").textContent = LIVE_TOKEN;

    const r = s.runner;
    const dot = $("status-dot");
    const txt = $("status-text");
    if (r.running) {
      dot.classList.remove("bg-ink-600", "bg-accent-red");
      dot.classList.add("bg-accent-green");
      const since = r.started_at_utc ? new Date(r.started_at_utc) : null;
      const uptime = since ? Math.floor((Date.now() - since.getTime()) / 1000) : 0;
      txt.textContent = `running · ${r.mode} · pid=${r.pid} · ${formatUptime(uptime)} · interval=${r.interval}s`;
      $("btn-stop").disabled = false;
      $("btn-start").disabled = true;
    } else {
      dot.classList.remove("bg-accent-green", "bg-accent-red");
      dot.classList.add("bg-ink-600");
      txt.textContent = "stopped";
      $("btn-stop").disabled = true;
      $("btn-start").disabled = false;
    }

    const ks = s.kill_switch;
    const ksPill = $("ks-pill");
    if (ks.armed) {
      ksPill.textContent = "kill switch: armed";
      ksPill.className = "px-2 py-1 rounded text-xs font-medium bg-accent-green/15 text-accent-green border border-accent-green/30";
    } else {
      ksPill.textContent = `kill switch: TRIPPED (${ks.tripped_reason || "unknown"})`;
      ksPill.className = "px-2 py-1 rounded text-xs font-medium bg-accent-red/15 text-accent-red border border-accent-red/30";
    }

    const credsPill = $("creds-pill");
    if (s.credentials_present) {
      credsPill.textContent = "creds: ok";
      credsPill.className = "px-2 py-1 rounded text-xs font-medium bg-accent-green/15 text-accent-green border border-accent-green/30";
    } else {
      credsPill.textContent = "creds: missing";
      credsPill.className = "px-2 py-1 rounded text-xs font-medium bg-accent-yellow/15 text-accent-yellow border border-accent-yellow/30";
    }
  } catch (e) {
    $("status-text").textContent = `status error: ${e.message}`;
  }
}

function formatUptime(sec) {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  const h = Math.floor(sec / 3600); const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}

// ---- balance ----
async function refreshBalance() {
  try {
    const b = await api("/api/balance");
    $("kpi-proxy-usdc").textContent = fmt.usd(b.proxy_usdc);
    $("kpi-proxy-addr").textContent = fmt.addr(b.proxy_address);
    $("kpi-eoa-matic").textContent = fmt.num(b.eoa_matic, 3);
  } catch (e) {
    console.warn("balance error", e);
  }
}

// ---- metrics ----
async function refreshMetrics() {
  try {
    const m = await api("/api/metrics");
    const agg = m.aggregate_paper_plus_live;
    $("kpi-pnl").textContent = fmt.usd(agg.total_pnl_usd, true);
    $("kpi-pnl-sub").textContent = `${agg.n_fills_with_pnl} fills · ${fmt.usd(agg.total_notional_usd)} notl`;
    $("kpi-sharpe").textContent = fmt.num(agg.per_bet_sharpe_ann, 2);
    $("kpi-winrate").textContent = fmt.pct(agg.win_rate);
    $("kpi-fills").textContent = `${agg.n_fills_with_pnl} fills · ${agg.n_decisions} decisions`;
    $("kpi-dd").textContent = fmt.usd(agg.max_drawdown_usd, true);
    paintPnLColor($("kpi-pnl"), agg.total_pnl_usd);

    paintMode("shadow", m.by_mode.shadow);
    paintMode("paper", m.by_mode.paper);
    paintMode("live", m.by_mode.live);

    // rejection reasons (across all modes)
    const allReasons = {};
    for (const mode of ["shadow", "paper", "live"]) {
      const bucket = m.by_mode[mode];
      if (!bucket) continue;
      for (const e of bucket.rejection_reasons || []) {
        allReasons[e.reason] = (allReasons[e.reason] || 0) + e.count;
      }
    }
    const sorted = Object.entries(allReasons).sort((a, b) => b[1] - a[1]).slice(0, 8);
    $("reject-list").innerHTML = sorted.length
      ? sorted.map(([r, n]) => `<div class="flex justify-between"><span class="text-ink-200">${escape(r)}</span><span class="num text-ink-400">${n}</span></div>`).join("")
      : `<div class="text-ink-600">No rejections yet.</div>`;
  } catch (e) {
    console.warn("metrics error", e);
  }
}

function paintPnLColor(el, v) {
  el.classList.remove("text-accent-green", "text-accent-red", "text-ink-50");
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) {
    el.classList.add("text-ink-50");
  } else if (v > 0) {
    el.classList.add("text-accent-green");
  } else {
    el.classList.add("text-accent-red");
  }
}

function paintMode(mode, b) {
  const el = $(`mode-${mode}`);
  if (!b || b.n_decisions === 0) {
    el.innerHTML = `<div class="text-ink-600 text-xs">no activity</div>`;
    return;
  }
  el.innerHTML = `
    <div class="flex justify-between"><span class="text-ink-400">decisions</span><span class="num">${b.n_decisions}</span></div>
    <div class="flex justify-between"><span class="text-ink-400">accepted</span><span class="num text-accent-green">${b.n_accepted}</span></div>
    <div class="flex justify-between"><span class="text-ink-400">rejected</span><span class="num text-accent-red">${b.n_rejected}</span></div>
    <div class="flex justify-between"><span class="text-ink-400">fills</span><span class="num">${b.n_fills_with_pnl}</span></div>
    <div class="flex justify-between"><span class="text-ink-400">pnl</span><span class="num ${b.total_pnl_usd > 0 ? "text-accent-green" : b.total_pnl_usd < 0 ? "text-accent-red" : ""}">${fmt.usd(b.total_pnl_usd, true)}</span></div>
    <div class="flex justify-between"><span class="text-ink-400">win rate</span><span class="num">${fmt.pct(b.win_rate)}</span></div>
    <div class="flex justify-between"><span class="text-ink-400">sharpe</span><span class="num">${fmt.num(b.per_bet_sharpe_ann, 2)}</span></div>
  `;
}

// ---- decisions ----
async function refreshDecisions() {
  try {
    const d = await api("/api/decisions?limit=50");
    $("decisions-meta").textContent = `${d.rows.length} of ${d.total} total`;
    const tbody = $("decisions-tbody");
    if (!d.rows.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center py-6 text-ink-600 text-xs">No decisions yet — start the runner.</td></tr>`;
      return;
    }
    tbody.innerHTML = d.rows.map((r) => {
      const status = r.accepted
        ? `<span class="text-accent-green">accepted</span>`
        : `<span class="text-accent-red" title="${escape(r.rejection_reason || "")}">rejected</span>`;
      const pnlCls = r.pnl_usd === null || r.pnl_usd === undefined
        ? "text-ink-600"
        : r.pnl_usd > 0 ? "text-accent-green" : r.pnl_usd < 0 ? "text-accent-red" : "";
      const modeCls = r.mode === "live" ? "text-accent-red"
        : r.mode === "paper" ? "text-accent-yellow"
        : "text-ink-400";
      return `<tr class="border-b border-surface-700/40">
        <td class="px-3 py-1.5 text-ink-400">${fmt.time(r.timestamp)}</td>
        <td class="px-3 py-1.5">${escape(r.alpha)}</td>
        <td class="px-3 py-1.5 ${modeCls}">${escape(r.mode)}</td>
        <td class="px-3 py-1.5">${escape(r.side)}</td>
        <td class="px-3 py-1.5 text-right">${fmt.num(r.size, 2)}</td>
        <td class="px-3 py-1.5 text-right">${fmt.num(r.price, 3)}</td>
        <td class="px-3 py-1.5 text-right">${fmt.usd(r.notional_usd)}</td>
        <td class="px-3 py-1.5 text-right ${pnlCls}">${r.pnl_usd === null || r.pnl_usd === undefined ? "—" : fmt.usd(r.pnl_usd, true)}</td>
        <td class="px-3 py-1.5">${status}</td>
      </tr>`;
    }).join("");
  } catch (e) {
    console.warn("decisions error", e);
  }
}

async function refreshStdout() {
  try {
    const s = await api("/api/runner-stdout?n=80");
    const pre = $("stdout-pre");
    pre.textContent = (s.lines || []).join("\n");
    pre.scrollTop = pre.scrollHeight;
    $("stdout-meta").textContent = `${s.lines.length} lines`;
  } catch (e) {
    console.warn("stdout error", e);
  }
}

function escape(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// ---- modal + actions ----
function openModal() {
  $("modal-error").classList.add("hidden");
  $("f-confirm").value = "";
  $("start-modal").classList.remove("hidden");
  updateLiveWarning();
}
function closeModal() { $("start-modal").classList.add("hidden"); }
function updateLiveWarning() {
  const isLive = $("f-mode").value === "live";
  $("live-warning").classList.toggle("hidden", !isLive);
}

async function doStart() {
  const body = {
    mode: $("f-mode").value,
    bankroll: parseFloat($("f-bankroll").value),
    max_stake: parseFloat($("f-max-stake").value),
    min_edge: parseFloat($("f-min-edge").value),
    interval: parseFloat($("f-interval").value),
    confirmation: $("f-confirm").value || null,
  };
  try {
    await api("/api/start", { method: "POST", body: JSON.stringify(body) });
    closeModal();
    await refreshAll();
  } catch (e) {
    const err = $("modal-error");
    err.classList.remove("hidden");
    err.textContent = e.message;
  }
}

async function doStop() {
  if (!confirm("Stop the runner? Any pending orders will be cancelled by the runtime, not by this button.")) return;
  try {
    await api("/api/stop", { method: "POST" });
    await refreshAll();
  } catch (e) {
    alert("stop failed: " + e.message);
  }
}

async function doKillSwitch() {
  const reason = prompt("Reason for tripping the kill switch:");
  if (!reason) return;
  try {
    await api("/api/kill-switch/trip", { method: "POST", body: JSON.stringify({ reason }) });
    await refreshStatus();
  } catch (e) {
    alert("kill-switch trip failed: " + e.message);
  }
}

// ---- wire-up + polling ----
function refreshAll() {
  return Promise.all([refreshStatus(), refreshBalance(), refreshMetrics(),
                       refreshDecisions(), refreshStdout()]);
}

document.addEventListener("DOMContentLoaded", () => {
  $("btn-start").addEventListener("click", openModal);
  $("modal-close").addEventListener("click", closeModal);
  $("modal-cancel").addEventListener("click", closeModal);
  $("modal-start").addEventListener("click", doStart);
  $("f-mode").addEventListener("change", updateLiveWarning);
  $("btn-stop").addEventListener("click", doStop);
  $("btn-killswitch").addEventListener("click", doKillSwitch);

  refreshAll();
  setInterval(refreshStatus, POLL_MS_FAST);
  setInterval(refreshDecisions, POLL_MS_FAST);
  setInterval(refreshStdout, POLL_MS_FAST);
  setInterval(refreshMetrics, POLL_MS_SLOW);
  setInterval(refreshBalance, POLL_MS_SLOW);
});

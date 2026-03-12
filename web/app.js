const STORAGE_KEYS = {
  householdId: "nivvi_household_id",
  apiToken: "nivvi_api_token",
};

const state = {
  householdId: localStorage.getItem(STORAGE_KEYS.householdId) || "primary_household",
  apiToken: localStorage.getItem(STORAGE_KEYS.apiToken) || "",
  dashboard: null,
  actions: [],
  ledger: null,
  rules: [],
  audit: [],
  auditIntegrity: null,
  chatMessages: [],
  chatIdentities: [],
  providerConnections: [],
  providerHealth: [],
};

const $ = (selector) => document.querySelector(selector);

init();

function init() {
  hydrateSettings();
  bindTabs();
  bindSettings();
  bindForms();
  refreshAll();
}

function hydrateSettings() {
  const householdInput = $("#householdId");
  const tokenInput = $("#apiToken");
  if (householdInput) householdInput.value = state.householdId;
  if (tokenInput) tokenInput.value = state.apiToken;
}

function bindTabs() {
  const tabbar = $("#tabbar");
  if (!tabbar) return;

  tabbar.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    const tab = target.dataset.tab;
    if (!tab) return;

    tabbar.querySelectorAll("button").forEach((button) => button.classList.remove("active"));
    target.classList.add("active");

    document.querySelectorAll(".panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === `panel-${tab}`);
    });
  });
}

function bindSettings() {
  const toggle = $("#settingsToggle");
  const panel = $("#settingsPanel");
  const form = $("#settingsForm");
  const clear = $("#clearTokenBtn");

  toggle?.addEventListener("click", () => panel?.classList.toggle("hidden"));

  clear?.addEventListener("click", () => {
    state.apiToken = "";
    localStorage.removeItem(STORAGE_KEYS.apiToken);
    const tokenInput = $("#apiToken");
    if (tokenInput) tokenInput.value = "";
    toast("API token cleared", "ok");
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    state.householdId = String(formData.get("householdId") || "").trim() || "primary_household";
    state.apiToken = String(formData.get("apiToken") || "").trim();

    localStorage.setItem(STORAGE_KEYS.householdId, state.householdId);
    if (state.apiToken) {
      localStorage.setItem(STORAGE_KEYS.apiToken, state.apiToken);
    } else {
      localStorage.removeItem(STORAGE_KEYS.apiToken);
    }

    await refreshAll();
    panel?.classList.add("hidden");
    toast("Settings saved", "ok");
  });
}

function bindForms() {
  $("#chatForm")?.addEventListener("submit", sendChatMessage);
  $("#channelLinkForm")?.addEventListener("submit", linkChannel);
  $("#actionDraftForm")?.addEventListener("submit", createActionDraft);
  $("#providerConnectForm")?.addEventListener("submit", connectProvider);
  $("#ruleForm")?.addEventListener("submit", saveRule);
  $("#syncAllBtn")?.addEventListener("click", syncAllDomains);
  $("#refreshAccountsBtn")?.addEventListener("click", refreshAll);
}

async function refreshAll() {
  const householdId = state.householdId;
  if (!householdId) return;

  try {
    await ensureHouseholdExists(householdId);
  } catch (error) {
    renderFatal(`Unable to access household: ${String(error.message || error)}`);
    return;
  }

  const responses = await Promise.allSettled([
    api("GET", `/v1/dashboard/today?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/actions?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/households/${encodeURIComponent(householdId)}/ledger`),
    api("GET", `/v1/rules?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/audit/events?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/audit/integrity?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/chat/messages?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/chat/identities?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/providers/connections?household_id=${encodeURIComponent(householdId)}`),
    api("GET", `/v1/providers/health?household_id=${encodeURIComponent(householdId)}`),
  ]);

  const failed = responses.find((item) => item.status === "rejected");
  if (failed && failed.status === "rejected") {
    renderFatal(String(failed.reason?.message || "Failed to refresh app state"));
    return;
  }

  state.dashboard = responses[0].value;
  state.actions = responses[1].value.items || [];
  state.ledger = responses[2].value.ledger || null;
  state.rules = responses[3].value.items || [];
  state.audit = responses[4].value.events || [];
  state.auditIntegrity = responses[5].value || null;
  state.chatMessages = responses[6].value.items || [];
  state.chatIdentities = responses[7].value.items || [];
  state.providerConnections = responses[8].value.items || [];
  state.providerHealth = responses[9].value.items || [];

  renderAll();
}

function renderAll() {
  renderStatus();
  renderToday();
  renderActions();
  renderAccounts();
  renderRules();
  renderAudit();
}

function renderStatus() {
  const counts = state.dashboard?.counts || {
    alerts: 0,
    pending_actions: 0,
    overdue_deadlines: 0,
    agent_interventions: 0,
  };

  $("#statAlerts").textContent = String(counts.alerts || 0);
  $("#statPending").textContent = String(counts.pending_actions || 0);
  $("#statInterventions").textContent = String(counts.agent_interventions || 0);
  $("#statOverdue").textContent = String(counts.overdue_deadlines || 0);
}

function renderToday() {
  const alerts = state.dashboard?.alerts || [];
  const interventions = state.dashboard?.agent_interventions || [];
  const recentMessages = state.chatMessages.slice(-6).reverse();

  if (!alerts.length) {
    $("#todayAlerts").innerHTML =
      '<article class="card"><h4>No active risk alerts</h4><p class="sub">Nivvi is monitoring your cash, deadlines, and shortfall windows.</p></article>';
  } else {
    $("#todayAlerts").innerHTML = alerts
      .map(
        (item) => `
          <article class="card">
            <h4>${escapeHtml(item.title || item.type || "Priority alert")}</h4>
            <p class="sub">${escapeHtml(item.type || "risk")}</p>
            <div class="meta">
              <span>${item.due_at ? `Due: ${formatDate(item.due_at)}` : ""}</span>
              <span>${item.date ? `Date: ${formatDate(item.date)}` : ""}</span>
              <span>${item.p10_balance !== undefined ? `p10 balance: €${Number(item.p10_balance).toFixed(2)}` : ""}</span>
            </div>
          </article>
        `
      )
      .join("");
  }

  if (!state.chatIdentities.length) {
    $("#channelList").innerHTML =
      '<article class="card"><h4>No linked channel</h4><p class="sub">Link WhatsApp or Telegram to receive proactive interventions.</p></article>';
  } else {
    $("#channelList").innerHTML = state.chatIdentities
      .map(
        (identity) => `
          <article class="card">
            <h4>${escapeHtml(titleCase(identity.channel))} linked</h4>
            <p class="sub">${escapeHtml(identity.user_handle)}</p>
            <div class="meta"><span>Linked: ${formatDate(identity.linked_at)}</span></div>
          </article>
        `
      )
      .join("");
  }

  const interventionCards = interventions
    .map(
      (item) => `
        <article class="card">
          <h4>${escapeHtml(formatInterventionKind(item.kind))}</h4>
          <p class="sub">${escapeHtml(item.text || "")}</p>
          <div class="meta">
            <span>${formatDate(item.created_at)}</span>
            <span>Action: ${escapeHtml(item.action_id || "n/a")}</span>
          </div>
        </article>
      `
    )
    .join("");

  const messageCards = recentMessages
    .map(
      (item) => `
        <article class="card">
          <h4>${escapeHtml(item.sender)} · ${escapeHtml(titleCase(item.channel))}</h4>
          <p class="sub">${escapeHtml(item.text)}</p>
          <div class="meta"><span>${formatDate(item.created_at)}</span></div>
        </article>
      `
    )
    .join("");

  const hasActivity = interventionCards.length > 0 || messageCards.length > 0;
  $("#todayInterventions").innerHTML = hasActivity
    ? `${interventionCards}${messageCards}`
    : '<article class="card"><h4>No recent interventions</h4><p class="sub">Nivvi will step in when something changes.</p></article>';
}

function renderActions() {
  if (!state.actions.length) {
    $("#actionsList").innerHTML =
      '<article class="card"><h4>No drafted actions</h4><p class="sub">Create a draft now, or wait for Nivvi to propose one automatically.</p></article>';
    return;
  }

  $("#actionsList").innerHTML = state.actions
    .map((action) => {
      const statusClass = action.status === "failed" ? "warn" : action.status === "dispatched" ? "ok" : "";
      return `
        <article class="card">
          <h4>${escapeHtml(titleCase(action.action_type))} · €${Number(action.amount || 0).toFixed(2)}</h4>
          <p class="sub">${escapeHtml(action.category || "money action")}</p>
          <div class="controls">
            <span class="pill ${statusClass}">${escapeHtml(titleCase(action.status))}</span>
          </div>
          <div class="meta">
            <span>ID: ${escapeHtml(action.id)}</span>
            <span>Risk score: ${Number(action.risk_score || 0).toFixed(2)}</span>
            <span>Due: ${action.due_at ? formatDate(action.due_at) : "n/a"}</span>
          </div>
          <div class="controls">
            <button class="ghost" data-action="preview" data-id="${action.id}" type="button">Preview</button>
            <button class="secondary" data-action="confirm" data-id="${action.id}" type="button">Confirm</button>
            <button data-action="authorize" data-id="${action.id}" type="button">Authorize</button>
            <button class="danger" data-action="reject" data-id="${action.id}" type="button">Reject</button>
            <button class="ghost" data-action="dispatch" data-id="${action.id}" type="button">Dispatch</button>
          </div>
        </article>
      `;
    })
    .join("");

  document.querySelectorAll("#actionsList button[data-action]").forEach((button) => {
    button.addEventListener("click", handleActionControlClick);
  });
}

function renderAccounts() {
  const accounts = state.ledger?.accounts || [];
  const connections = state.providerConnections || [];
  const healthByKey = new Map((state.providerHealth || []).map((item) => [`${item.provider_name}:${item.domain}`, item]));

  if (!accounts.length) {
    $("#accountsList").innerHTML =
      '<article class="card"><h4>No connected accounts yet</h4><p class="sub">Connect a provider and run sync to build your unified ledger.</p></article>';
  } else {
    $("#accountsList").innerHTML = accounts
      .map(
        (account) => `
          <article class="card">
            <h4>${escapeHtml(account.institution)} · ${escapeHtml(titleCase(account.account_type))}</h4>
            <p class="sub">${escapeHtml(account.currency)} ${Number(account.balance || 0).toFixed(2)}</p>
            <div class="meta">
              <span>Updated: ${formatDate(account.updated_at)}</span>
              <span>Account ID: ${escapeHtml(account.id)}</span>
            </div>
          </article>
        `
      )
      .join("");
  }

  if (!connections.length) {
    $("#connectionsList").innerHTML =
      '<article class="card"><h4>No provider rails connected</h4><p class="sub">Add aggregation and execution providers to activate full management.</p></article>';
    return;
  }

  $("#connectionsList").innerHTML = connections
    .map((connection) => {
      const health = healthByKey.get(`${connection.provider_name}:${connection.domain}`);
      return `
        <article class="card">
          <h4>${escapeHtml(connection.provider_name)} · ${escapeHtml(titleCase(connection.domain))}</h4>
          <p class="sub">${escapeHtml(titleCase(connection.status))}${connection.is_primary ? " · Primary" : ""}</p>
          <div class="meta">
            <span>Health: ${escapeHtml(titleCase(health?.status || "unknown"))}</span>
            <span>Checked: ${health?.checked_at ? formatDate(health.checked_at) : "n/a"}</span>
            <span>Credentials ref: ${escapeHtml(connection.credentials_ref || "n/a")}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderRules() {
  if (!state.rules.length) {
    $("#rulesList").innerHTML =
      '<article class="card"><h4>No safety rules configured</h4><p class="sub">Set execution limits before dispatching live actions.</p></article>';
    return;
  }

  $("#rulesList").innerHTML = state.rules
    .map(
      (rule) => `
        <article class="card">
          <h4>${escapeHtml(titleCase(rule.scope))} safety policy</h4>
          <p class="sub">Approval and anomaly controls are active.</p>
          <div class="meta">
            <span>Rule ID: ${escapeHtml(rule.rule_id)}</span>
            <span>Daily limit: ${rule.daily_amount_limit ?? "n/a"}</span>
            <span>Max single action: ${rule.max_single_action ?? "n/a"}</span>
            <span>Blocked categories: ${(rule.blocked_categories || []).join(", ") || "none"}</span>
            <span>Anomaly loop: ${rule.anomaly_detection_enabled ? "enabled" : "disabled"}</span>
            <span>Weekly planning: ${rule.weekly_planning_enabled ? "enabled" : "disabled"}</span>
          </div>
        </article>
      `
    )
    .join("");
}

function renderAudit() {
  const integrity = state.auditIntegrity;
  if (!integrity) {
    $("#auditIntegrity").innerHTML = "";
  } else {
    $("#auditIntegrity").innerHTML = `
      <article class="card">
        <h4>Audit integrity ${integrity.valid ? "verified" : "warning"}</h4>
        <p class="sub">Hash-chain status for this household stream.</p>
        <div class="controls"><span class="pill ${integrity.valid ? "ok" : "warn"}">${integrity.valid ? "Valid" : "Mismatch"}</span></div>
      </article>
    `;
  }

  if (!state.audit.length) {
    $("#auditList").innerHTML =
      '<article class="card"><h4>No audit events yet</h4><p class="sub">Recommendations and approvals will appear here.</p></article>';
    return;
  }

  $("#auditList").innerHTML = state.audit
    .slice(0, 40)
    .map(
      (event) => `
        <article class="card">
          <h4>${escapeHtml(event.event_type)}</h4>
          <p class="sub">${escapeHtml(event.entity_id)}</p>
          <div class="meta">
            <span>${formatDate(event.created_at)}</span>
            <span>${escapeHtml(JSON.stringify(event.details || {}))}</span>
          </div>
        </article>
      `
    )
    .join("");
}

async function sendChatMessage(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const message = String(formData.get("message") || "").trim();
  if (!message) {
    toast("Type a message before sending", "warn");
    return;
  }

  const linked = state.chatIdentities[0];
  const channel = linked?.channel || "whatsapp";
  const userId = linked?.user_handle || "companion_app_user";

  try {
    await api("POST", "/v1/chat/events", {
      household_id: state.householdId,
      channel,
      user_id: userId,
      message,
      metadata: { source: "companion_app_mobile" },
    });
    form.reset();
    await refreshAll();
    toast("Message sent", "ok");
  } catch (error) {
    toast(String(error.message || error), "warn");
  }
}

async function linkChannel(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const channel = String(formData.get("channel") || "whatsapp").toLowerCase();
  const userHandle = String(formData.get("userHandle") || "").trim();
  if (!userHandle) {
    toast("Enter a channel handle", "warn");
    return;
  }

  try {
    await api("POST", "/v1/chat/identities/link", {
      household_id: state.householdId,
      channel,
      user_handle: userHandle,
    });
    await refreshAll();
    event.currentTarget.reset();
    toast("Channel linked", "ok");
  } catch (error) {
    toast(String(error.message || error), "warn");
  }
}

async function createActionDraft(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const actionType = String(formData.get("actionType") || "transfer");
  const amount = Number(formData.get("amount") || 0);
  if (!amount || amount <= 0) {
    toast("Enter a valid amount", "warn");
    return;
  }

  try {
    await api("POST", "/v1/actions/proposals", {
      household_id: state.householdId,
      action_type: actionType,
      amount,
      currency: "EUR",
      due_at: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
      category: actionType === "transfer" ? "cash_optimization" : "goal_contribution",
      rationale: ["Drafted in companion app", "Two-step approval required"],
    });
    await refreshAll();
    toast("Action draft created", "ok");
  } catch (error) {
    toast(String(error.message || error), "warn");
  }
}

async function connectProvider(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const providerName = String(formData.get("providerName") || "").trim().toLowerCase();
  const domain = String(formData.get("domain") || "aggregation").toLowerCase();

  if (!providerName) {
    toast("Provider name is required", "warn");
    return;
  }

  try {
    await api("POST", "/v1/providers/connections", {
      household_id: state.householdId,
      provider_name: providerName,
      domain,
      is_primary: true,
      is_enabled: true,
      credentials_ref: null,
      metadata: {},
    });
    await refreshAll();
    toast("Provider connected", "ok");
  } catch (error) {
    toast(String(error.message || error), "warn");
  }
}

async function syncAllDomains() {
  try {
    await api("POST", `/v1/households/${encodeURIComponent(state.householdId)}/sync`, {
      domains: ["aggregation", "payments", "investing", "tax_submission"],
    });
    await refreshAll();
    toast("Household sync triggered", "ok");
  } catch (error) {
    toast(String(error.message || error), "warn");
  }
}

async function saveRule(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const blockedCategories = String(formData.get("blockedCategories") || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  try {
    await api("POST", "/v1/rules", {
      household_id: state.householdId,
      scope: "global",
      daily_amount_limit: Number(formData.get("dailyAmountLimit")) || null,
      max_single_action: Number(formData.get("maxSingleAction")) || null,
      blocked_categories: blockedCategories,
      blocked_action_types: [],
      require_approval_always: true,
      anomaly_detection_enabled: formData.get("anomalyDetectionEnabled") === "on",
      anomaly_expense_multiplier: 1.75,
      anomaly_income_multiplier: 2.0,
      anomaly_min_expense_amount: 150,
      anomaly_min_income_amount: 300,
      weekly_planning_enabled: formData.get("weeklyPlanningEnabled") === "on",
      weekly_drift_threshold_percent: 20,
      weekly_min_delta_amount: 50,
      weekly_cooldown_days: 6,
    });
    await refreshAll();
    toast("Safety rule saved", "ok");
  } catch (error) {
    toast(String(error.message || error), "warn");
  }
}

async function handleActionControlClick(event) {
  const button = event.currentTarget;
  const actionId = button.dataset.id;
  const action = button.dataset.action;

  try {
    if (action === "preview") {
      const preview = await api("GET", `/v1/actions/${actionId}/preview`);
      toast(
        `Projected balance: €${Number(preview.projected_balance_after || 0).toFixed(2)} | Fee impact: €${Number(
          preview.fee_impact || 0
        ).toFixed(2)}`,
        "ok"
      );
    }

    if (action === "confirm") {
      await api("POST", `/v1/actions/${actionId}/approve`, { step: "confirm" });
      toast("Action confirmed", "ok");
    }

    if (action === "authorize") {
      await api("POST", `/v1/actions/${actionId}/approve`, { step: "authorize" });
      toast("Action authorized", "ok");
    }

    if (action === "reject") {
      const reason = window.prompt("Reason for rejection (optional):", "Timing not right") || "";
      await api("POST", `/v1/actions/${actionId}/reject`, { reason });
      toast("Action rejected", "ok");
    }

    if (action === "dispatch") {
      await api("POST", `/v1/executions/${actionId}/dispatch`, {
        idempotency_key: `ui_${Date.now()}`,
      });
      toast("Dispatch submitted", "ok");
    }

    await refreshAll();
  } catch (error) {
    toast(String(error.message || error), "warn");
  }
}

async function ensureHouseholdExists(householdId) {
  const ledgerResponse = await fetch(`/v1/households/${encodeURIComponent(householdId)}/ledger`, {
    headers: buildHeaders(),
  });

  if (ledgerResponse.ok) {
    return;
  }

  if (ledgerResponse.status !== 404) {
    throw new Error(await extractErrorDetail(ledgerResponse));
  }

  const createResponse = await fetch("/v1/connect/accounts", {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify({
      household_id: householdId,
      household_name: "Nivvi Household",
      accounts: [],
    }),
  });

  if (!createResponse.ok) {
    throw new Error(await extractErrorDetail(createResponse));
  }
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: buildHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    throw new Error(await extractErrorDetail(response));
  }

  return response.json();
}

function buildHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (state.apiToken) {
    headers.Authorization = `Bearer ${state.apiToken}`;
  }
  return headers;
}

function renderFatal(message) {
  const html = `<article class="card"><h4>Unable to load app data</h4><p class="sub">${escapeHtml(message)}</p></article>`;
  ["#todayAlerts", "#todayInterventions", "#actionsList", "#accountsList", "#connectionsList", "#rulesList", "#auditList"].forEach(
    (selector) => {
      const el = $(selector);
      if (el) {
        el.innerHTML = html;
      }
    }
  );
}

function toast(message, tone = "ok") {
  const node = document.createElement("div");
  node.textContent = message;
  Object.assign(node.style, {
    position: "fixed",
    left: "50%",
    bottom: "96px",
    transform: "translateX(-50%)",
    background: tone === "warn" ? "#8a3040" : "#1f53d9",
    color: "#fff",
    borderRadius: "10px",
    padding: "10px 12px",
    fontSize: "13px",
    maxWidth: "92vw",
    zIndex: "120",
    boxShadow: "0 10px 24px rgba(16, 39, 68, 0.2)",
  });
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2200);
}

async function extractErrorDetail(response) {
  let detail = `${response.status} ${response.statusText}`;
  try {
    const errorBody = await response.json();
    detail = errorBody.detail || detail;
  } catch {
    // keep fallback detail
  }
  return detail;
}

function formatDate(value) {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatInterventionKind(kind) {
  if (kind === "expense_shock") return "Expense shock";
  if (kind === "income_shock") return "Income shock";
  if (kind === "weekly_plan_drift") return "Weekly plan drift";
  return kind || "Agent intervention";
}

function titleCase(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function escapeHtml(input) {
  return String(input)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

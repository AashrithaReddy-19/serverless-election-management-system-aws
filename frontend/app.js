// =====================================================================
// Serverless Election Management and Voting System - frontend logic
// Plain JavaScript. Talks to:
//   - Amazon Cognito (login)            -> cognito-idp REST endpoint
//   - API Gateway + Lambda (everything) -> APP_CONFIG.apiUrl
// =====================================================================
const CFG = window.APP_CONFIG;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function showMsg(el, text, type) { $(el).innerHTML = text ? `<div class="msg ${type || "ok"}">${esc(text)}</div>` : ""; }

// ---------------- Session (ID token from Cognito) ----------------
function saveToken(t) { try { sessionStorage.setItem("idToken", t); } catch (e) { window._idToken = t; } }
function getToken() { try { return sessionStorage.getItem("idToken") || window._idToken; } catch (e) { return window._idToken; } }
function clearToken() { try { sessionStorage.removeItem("idToken"); } catch (e) {} window._idToken = null; }

function decodeToken(t) {
  const p = t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(decodeURIComponent(escape(atob(p))));
}
// Used only to choose which dashboard to show. The backend re-checks the
// role from the verified token on every request, so this cannot be abused.
function roleFromToken(t) {
  const groups = decodeToken(t)["cognito:groups"] || [];
  return ["ADMIN", "CANDIDATE", "VOTER"].find((r) => groups.includes(r)) || null;
}
function tokenValid(t) { try { return decodeToken(t).exp * 1000 > Date.now() + 10000; } catch (e) { return false; } }

// ---------------- Cognito login ----------------
async function cognitoLogin(email, password) {
  const res = await fetch(`https://cognito-idp.${CFG.region}.amazonaws.com/`, {
    method: "POST",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth" },
    body: JSON.stringify({ AuthFlow: "USER_PASSWORD_AUTH", ClientId: CFG.clientId, AuthParameters: { USERNAME: email, PASSWORD: password } }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || "Login failed");
  if (!data.AuthenticationResult) throw new Error("Additional verification required (" + (data.ChallengeName || "challenge") + "). Ask the admin to set a permanent password.");
  return data.AuthenticationResult.IdToken;
}

// ---------------- API helper ----------------
async function api(path, method = "GET", body) {
  const headers = { "Content-Type": "application/json" };
  const t = getToken();
  if (t) headers.Authorization = "Bearer " + t;
  const res = await fetch(CFG.apiUrl + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (res.status === 401) { logout(); throw new Error("Session expired. Please login again."); }
  return { ok: res.ok, status: res.status, data };
}

// ---------------- View switching ----------------
const VIEWS = ["authView", "voterView", "candidateView", "adminView"];
function show(view) { VIEWS.forEach((v) => $(v).classList.toggle("hidden", v !== view)); }
function setStatus(el, s) { $(el).className = "status " + s; $(el).textContent = (s || "").replace("_", " "); }

function logout() { clearToken(); $("whoBox").classList.add("hidden"); show("authView"); }
$("logoutBtn").onclick = logout;

function route() {
  const t = getToken();
  if (!t || !tokenValid(t)) { logout(); return; }
  const role = roleFromToken(t);
  const claims = decodeToken(t);
  $("whoText").textContent = `${claims.name || claims.email} (${role || "no role"})`;
  $("whoBox").classList.remove("hidden");
  if (role === "VOTER") { show("voterView"); loadVoter(); }
  else if (role === "CANDIDATE") { show("candidateView"); loadCandidate(); }
  else if (role === "ADMIN") { show("adminView"); loadAdmin(); }
  else { logout(); showMsg("authMsg", "Your account has no role assigned.", "err"); }
}

// ---------------- Auth tabs ----------------
const FORMS = { tabLogin: "loginForm", tabVoter: "voterForm", tabCandidate: "candidateForm" };
Object.keys(FORMS).forEach((tab) => {
  $(tab).onclick = () => {
    Object.entries(FORMS).forEach(([t, f]) => { $(t).classList.toggle("active", t === tab); $(f).classList.toggle("hidden", t !== tab); });
    showMsg("authMsg", "");
  };
});

$("loginForm").onsubmit = async (e) => {
  e.preventDefault();
  showMsg("authMsg", "Logging in...", "warn");
  try {
    saveToken(await cognitoLogin($("loginEmail").value.trim().toLowerCase(), $("loginPassword").value));
    $("loginPassword").value = "";
    showMsg("authMsg", "");
    route();
  } catch (err) { showMsg("authMsg", err.message, "err"); }
};

async function register(body, formId) {
  showMsg("authMsg", "Registering...", "warn");
  const r = await api("/register", "POST", body);
  showMsg("authMsg", r.data.message || "Registration failed", r.ok ? "ok" : "err");
  if (r.ok) { $(formId).reset(); $("loginEmail").value = body.email; }
}
$("voterForm").onsubmit = (e) => {
  e.preventDefault();
  register({ role: "VOTER", name: $("vName").value, email: $("vEmail").value, voterId: $("vId").value, password: $("vPassword").value }, "voterForm");
};
$("candidateForm").onsubmit = (e) => {
  e.preventDefault();
  register({ role: "CANDIDATE", name: $("cName").value, email: $("cEmail").value, candidateId: $("cId").value,
    partyName: $("cParty").value, symbol: $("cSymbol").value, password: $("cPassword").value }, "candidateForm");
};

// =====================================================================
// VOTER DASHBOARD  (no results, no counts, no winner - by design)
// =====================================================================
let selectedCandidate = null;

async function loadVoter() {
  const r = await api("/candidates");
  if (!r.ok) { showMsg("voterNotice", r.data.message || "Could not load candidates", "err"); return; }
  const { me, election, candidates } = r.data;
  $("voterWelcome").textContent = `Welcome, ${me.name}`;
  $("voterIdText").textContent = me.voterId || "-";
  setStatus("voterStatus", election.status);
  selectedCandidate = null;

  let canVote = false;
  if (election.status === "NOT_STARTED") showMsg("voterNotice", "Election has not started yet.", "warn");
  else if (election.status === "ENDED") showMsg("voterNotice", "Election has ended.", "warn");
  else if (me.hasVoted) showMsg("voterNotice", "You have already voted in this election.", "ok");
  else { showMsg("voterNotice", "Select one candidate and click Cast Vote. Your vote cannot be changed.", "warn"); canVote = true; }

  $("candidateGrid").innerHTML = candidates.length ? candidates.map((c) => `
    <div class="cand" data-id="${esc(c.candidateId)}">
      <div class="sym">${esc((c.symbol || c.partyName || "?").slice(0, 3).toUpperCase())}</div>
      <div class="name">${esc(c.candidateName)}</div>
      <div class="meta">Party: ${esc(c.partyName)}</div>
      <div class="meta">Candidate ID: ${esc(c.candidateId)}</div>
      ${canVote ? `<div class="row"><button class="secondary" type="button">Vote</button></div>` : ""}
    </div>`).join("") : "<p>No candidates registered yet.</p>";

  document.querySelectorAll("#candidateGrid .cand").forEach((card) => {
    card.onclick = () => {
      if (!canVote) return;
      document.querySelectorAll("#candidateGrid .cand").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      selectedCandidate = card.dataset.id;
      $("castVoteBtn").disabled = false;
    };
  });
  $("castVoteBtn").disabled = true;
  $("castVoteBtn").classList.toggle("hidden", !canVote);
}

$("castVoteBtn").onclick = async () => {
  if (!selectedCandidate) return;
  $("castVoteBtn").disabled = true;
  const r = await api("/vote", "POST", { candidateId: selectedCandidate });
  showMsg("voteMsg", r.data.message || "Vote failed", r.ok ? "ok" : "err");
  await loadVoter();
};

// =====================================================================
// RESULTS RENDERING (admin + candidate only)
// =====================================================================
function renderResults(d, highlightId) {
  const max = Math.max(1, ...d.results.map((r) => r.votes));
  const winnerId = d.winner ? d.winner.candidateId : null;
  let html = `<h2>FINAL ELECTION RESULTS</h2>
    <p>Total votes cast: <b>${d.totalVotes}</b> &nbsp;|&nbsp; Registered voters: <b>${d.totalVoters}</b> &nbsp;|&nbsp; Turnout: <b>${d.turnoutPercent}%</b></p>`;
  html += d.results.map((r) => `
    <div class="result-row ${r.candidateId === winnerId ? "win" : ""}">
      <div class="info">
        <div><b>${esc(r.candidateName)}</b> ${r.candidateId === highlightId ? "(You)" : ""}</div>
        <div style="color:var(--muted);font-size:13px">Party: ${esc(r.partyName)} &nbsp;|&nbsp; ID: ${esc(r.candidateId)}</div>
        <div class="bar"><div style="width:${(r.votes / max) * 100}%"></div></div>
      </div>
      <div class="votes">${r.votes} vote${r.votes === 1 ? "" : "s"}</div>
    </div>`).join("");

  if (d.winner) {
    html += `<div class="winner">
      <div class="big">&#127942; CONGRATULATIONS!</div>
      <div class="line">Congratulations <b>${esc(d.winner.candidateName)}</b>, you have won the election with <b>${d.winner.votes}</b> votes.</div>
      <div class="sub">Party: ${esc(d.winner.partyName)} &nbsp;|&nbsp; Candidate ID: ${esc(d.winner.candidateId)} &nbsp;|&nbsp; Winning vote count: ${d.winner.votes}</div>
    </div>`;
  } else if (d.isTie) {
    const names = d.tiedCandidates.map((c) => c.candidateName);
    const list = names.length > 2 ? names.slice(0, -1).join(", ") + " and " + names.slice(-1) : names.join(" and ");
    html += `<div class="winner tie">
      <div class="big">Election Result: Tie</div>
      <div class="line">The election resulted in a tie between ${esc(list)}.</div>
      <div class="sub">${d.tiedCandidates.map((c) => `${esc(c.candidateName)}: ${c.votes}`).join(" &nbsp;|&nbsp; ")}</div>
    </div>`;
  } else {
    html += `<div class="winner tie"><div class="big">No votes were cast</div></div>`;
  }
  return html;
}

// =====================================================================
// CANDIDATE DASHBOARD
// =====================================================================
async function loadCandidate() {
  const r = await api("/candidates");
  if (!r.ok) { showMsg("cpMsg", r.data.message || "Could not load profile", "err"); return; }
  const { me, election } = r.data;
  $("cpName").textContent = me.name;
  $("cpParty").textContent = me.partyName;
  $("cpId").textContent = me.candidateId;
  setStatus("cpStatus", election.status);
  $("cpResults").classList.add("hidden");
  if (election.status !== "ENDED") { showMsg("cpMsg", "Results will be available after the election has ended.", "warn"); return; }
  const res = await api("/results");
  if (!res.ok) { showMsg("cpMsg", res.data.message, "err"); return; }
  showMsg("cpMsg", "");
  $("cpResults").innerHTML = renderResults(res.data, me.candidateId);
  $("cpResults").classList.remove("hidden");
}
$("cpRefresh").onclick = loadCandidate;

// =====================================================================
// ADMIN DASHBOARD
// =====================================================================
async function loadAdmin() {
  const r = await api("/admin/dashboard");
  if (!r.ok) { showMsg("adMsg", r.data.message || "Could not load dashboard", "err"); return; }
  const { election, stats, voters, candidates } = r.data;
  $("adName").textContent = election.electionName;
  setStatus("adStatus", election.status);
  $("stVoters").textContent = stats.totalVoters;
  $("stVotes").textContent = stats.totalVotes;
  $("stCands").textContent = stats.totalCandidates;
  $("stTurnout").textContent = stats.turnoutPercent + "%";
  $("startBtn").disabled = election.status !== "NOT_STARTED";
  $("endBtn").disabled = election.status !== "ACTIVE";
  $("resultsBtn").disabled = election.status !== "ENDED";
  $("declareBtn").disabled = election.status !== "ENDED";
  $("adCandTable").innerHTML = candidates.map((c) => `<tr><td>${esc(c.candidateId)}</td><td>${esc(c.candidateName)}</td><td>${esc(c.partyName)}</td><td>${esc(c.symbol)}</td><td>${esc(c.email)}</td></tr>`).join("") || `<tr><td colspan="5">No candidates yet</td></tr>`;
  $("adVoterTable").innerHTML = voters.map((v) => `<tr><td>${esc(v.voterId)}</td><td>${esc(v.name)}</td><td>${esc(v.email)}</td><td>${v.hasVoted ? "Yes" : "No"}</td></tr>`).join("") || `<tr><td colspan="4">No voters yet</td></tr>`;
  if (election.status !== "ENDED") $("adResults").classList.add("hidden");
}

async function setElection(status, confirmText) {
  if (confirmText && !confirm(confirmText)) return;
  const r = await api("/admin/election", "POST", { status });
  showMsg("adMsg", r.data.message || "Failed", r.ok ? "ok" : "err");
  await loadAdmin();
}
$("startBtn").onclick = () => setElection("ACTIVE", "Start the election now?");
$("endBtn").onclick = () => setElection("ENDED", "End the election? Voting will close.");
$("resetBtn").onclick = () => setElection("RESET", "Reset the election? All votes will be deleted (users are kept).");
$("adRefresh").onclick = loadAdmin;

async function showAdminResults(declare) {
  const r = declare ? await api("/results/declare", "POST", {}) : await api("/results");
  if (!r.ok) { showMsg("adMsg", r.data.message || "Results not available", "err"); return; }
  showMsg("adMsg", declare ? "Winner declared." : "");
  $("adResults").innerHTML = renderResults(r.data);
  $("adResults").classList.remove("hidden");
  $("adResults").scrollIntoView({ behavior: "smooth" });
}
$("resultsBtn").onclick = () => showAdminResults(false);
$("declareBtn").onclick = () => showAdminResults(true);

route();

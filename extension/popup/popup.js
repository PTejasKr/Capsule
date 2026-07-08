document.addEventListener("DOMContentLoaded", async () => {
  // Elements
  const stateLoading = document.getElementById("state-loading");
  const stateNoPr = document.getElementById("state-no-pr");
  const stateError = document.getElementById("state-error");
  const dashboardContent = document.getElementById("dashboard-content");
  
  const prNumberEl = document.getElementById("pr-number");
  const prRepoEl = document.getElementById("pr-repo");
  const prTitleEl = document.getElementById("pr-title");
  
  const workflowImpactBanner = document.getElementById("workflow-impact-banner");
  const workflowStatusTitle = document.getElementById("workflow-status-title");
  const workflowStatusDesc = document.getElementById("workflow-status-desc");
  
  const wfIconGreen = document.getElementById("wf-icon-green");
  const wfIconYellow = document.getElementById("wf-icon-yellow");
  const wfIconRed = document.getElementById("wf-icon-red");
  
  const aiSummaryText = document.getElementById("ai-summary-text");
  const confidenceBar = document.getElementById("confidence-bar");
  const confidenceText = document.getElementById("confidence-text");
  
  const changesCountEl = document.getElementById("changes-count");
  const changesList = document.getElementById("changes-list");
  
  const changelogVersionEl = document.getElementById("changelog-version");
  const changelogTextEl = document.getElementById("changelog-text");
  
  const btnRefresh = document.getElementById("btn-refresh");
  const btnSettings = document.getElementById("btn-settings");
  const btnRetry = document.getElementById("btn-retry");
  const btnCopyChangelog = document.getElementById("btn-copy-changelog");
  
  const btnToggleChanges = document.getElementById("btn-toggle-changes");
  const changesContainer = document.getElementById("changes-list-container");
  
  const btnToggleChangelog = document.getElementById("btn-toggle-changelog");
  const changelogContainer = document.getElementById("changelog-preview-container");

  // Admin Tools Elements (Current PR)
  const adminSummaryEdit = document.getElementById("admin-summary-edit");
  const btnRepair = document.getElementById("btn-repair");
  const btnCompare = document.getElementById("btn-compare");
  const compareResults = document.getElementById("compare-results");
  const btnApprove = document.getElementById("btn-approve");

  // Track state
  let currentRepo = "";
  let currentPrNumber = null;

  // Setup accordions for Current PR
  btnToggleChanges.addEventListener("click", () => {
    btnToggleChanges.classList.toggle("active");
    changesContainer.classList.toggle("hidden");
  });

  btnToggleChangelog.addEventListener("click", () => {
    btnToggleChangelog.classList.toggle("active");
    changelogContainer.classList.toggle("hidden");
  });

  // Settings redirect
  btnSettings.addEventListener("click", async () => {
    const optionsUrl = chrome.runtime.getURL("options/options.html");
    try {
      if (typeof chrome.runtime.openOptionsPage === "function") {
        await chrome.runtime.openOptionsPage();
      } else {
        chrome.tabs.create({ url: optionsUrl });
      }
    } catch (err) {
      console.error("Failed to open options page via API, falling back to tab:", err);
      chrome.tabs.create({ url: optionsUrl });
    }
  });

  btnRetry.addEventListener("click", loadPrAnalysis);
  btnRefresh.addEventListener("click", loadPrAnalysis);

  // Copy to clipboard
  btnCopyChangelog.addEventListener("click", () => {
    const text = changelogTextEl.textContent;
    navigator.clipboard.writeText(text).then(() => {
      const originalText = btnCopyChangelog.innerHTML;
      btnCopyChangelog.textContent = "Copied!";
      btnCopyChangelog.style.backgroundColor = "#238636";
      setTimeout(() => {
        btnCopyChangelog.innerHTML = originalText;
        btnCopyChangelog.style.backgroundColor = "";
      }, 2000);
    });
  });

  // Main logic
  async function loadPrAnalysis() {
    stateLoading.classList.remove("hidden");
    dashboardContent.classList.add("hidden");
    stateNoPr.classList.add("hidden");
    stateError.classList.add("hidden");

    // 1. Get current active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    
    let isGithubPR = false;
    let owner, repo, prNum;
    
    if (tab && tab.url) {
      const match = tab.url.match(/github\.com\/([^\/]+)\/([^\/]+)\/pull\/(\d+)/);
      if (match) {
        isGithubPR = true;
        owner = match[1];
        repo = match[2];
        prNum = parseInt(match[3], 10);
      }
    }

    if (!isGithubPR) {
      // If not on GitHub PR, switch to Dashboard
      document.getElementById("tab-dashboard").click();
      return;
    }

    // Switch to Current PR tab if it is a PR
    switchTab(document.getElementById("tab-pr"), document.getElementById("panel-pr"));
    
    currentRepo = `${owner}/${repo}`;
    currentPrNumber = prNum;

    prRepoEl.textContent = currentRepo;
    prNumberEl.textContent = `PR #${currentPrNumber}`;

    try {
      // 3. Fetch summary from backend
      const response = await chrome.runtime.sendMessage({
        type: "FETCH_SUMMARY",
        repo: currentRepo,
        prNumber: currentPrNumber
      });

      if (response.error) {
        throw new Error(response.error);
      }

      const summary = response.data;
      renderCurrentPR(summary);
      
      // 4. Fetch changelog preview
      const changelogResponse = await chrome.runtime.sendMessage({
        type: "FETCH_CHANGELOG",
        repo: currentRepo,
        prNumber: currentPrNumber
      });
      
      if (!changelogResponse.error) {
        const changelog = changelogResponse.data;
        changelogVersionEl.textContent = changelog.version;
        changelogTextEl.textContent = formatChangelogText(changelog);
      }

    } catch (err) {
      console.error(err);
      const errorMsg = document.getElementById("error-message");
      errorMsg.textContent = `Could not fetch analysis: ${err.message}. Ensure backend is running and configured correctly.`;
      showState(stateError);
    }
  }

  function showState(element) {
    stateLoading.classList.add("hidden");
    stateNoPr.classList.add("hidden");
    stateError.classList.add("hidden");
    dashboardContent.classList.add("hidden");
    element.classList.remove("hidden");
  }

  function renderCurrentPR(data) {
    showState(dashboardContent);

    prTitleEl.textContent = data.title || "Untitled Pull Request";
    aiSummaryText.textContent = data.summary || "No summary details available.";
    adminSummaryEdit.value = data.summary || "";
    
    const confidencePct = Math.round(data.confidence_score * 100);
    confidenceBar.style.width = `${confidencePct}%`;
    confidenceText.textContent = `${confidencePct}%`;

    const wf = data.workflow_impact || {};
    workflowImpactBanner.className = "impact-banner";
    wfIconGreen.classList.add("hidden");
    wfIconYellow.classList.add("hidden");
    wfIconRed.classList.add("hidden");

    if (wf.severity === "major") {
      workflowImpactBanner.classList.add("banner-major");
      workflowStatusTitle.textContent = "Major Workflow Change";
      workflowStatusDesc.textContent = wf.impact_description || "High severity impact detected.";
      wfIconRed.classList.remove("hidden");
    } else if (wf.severity === "minor") {
      workflowImpactBanner.classList.add("banner-minor");
      workflowStatusTitle.textContent = "Minor Workflow Change";
      workflowStatusDesc.textContent = wf.impact_description || "Low severity workflow impact detected.";
      wfIconYellow.classList.remove("hidden");
    } else {
      workflowImpactBanner.classList.add("banner-none");
      workflowStatusTitle.textContent = "No Workflow Impact";
      workflowStatusDesc.textContent = "No BRD business processes are modified by these changes.";
      wfIconGreen.classList.remove("hidden");
    }

    changesList.innerHTML = "";
    const changes = data.changes || [];
    changesCountEl.textContent = changes.length;

    if (changes.length === 0) {
      changesList.innerHTML = `<li class="change-desc" style="color: var(--text-muted)">No files analyzed.</li>`;
    } else {
      changes.forEach(c => {
        const li = document.createElement("li");
        li.className = "change-item";
        const changeTypeClass = `badge-${c.change_type.toLowerCase()}`;
        li.innerHTML = `
          <div class="change-header">
            <span class="change-file" title="${c.file}">${basename(c.file)}</span>
            <span class="change-badge ${changeTypeClass}">${c.change_type}</span>
          </div>
          <div class="change-desc">${c.description} <span style="color: var(--text-muted); font-size:10px;">(Lines: ${c.line_range})</span></div>
        `;
        changesList.appendChild(li);
      });
    }
  }

  function basename(path) {
    return path.split('/').pop();
  }

  function formatChangelogText(changelog) {
    let text = `## [${changelog.version}] - ${changelog.date}\n`;
    text += `### Technical Changes\n`;
    changelog.technical_changes.forEach(c => text += `- ${c}\n`);
    text += `\n### Workflow Changes\n`;
    if (changelog.workflow_changes.length > 0) {
      changelog.workflow_changes.forEach(w => text += `- ${w}\n`);
    } else {
      text += `- No workflow changes detected.\n`;
    }
    text += `\n### Lines Changed: +${changelog.lines_added} / -${changelog.lines_deleted}`;
    return text;
  }

  // --- TAB NAVIGATION SYSTEM ---
  const tabs = [
    { button: document.getElementById("tab-dashboard"), panel: document.getElementById("panel-dashboard"), onShow: loadDashboard },
    { button: document.getElementById("tab-pr"), panel: document.getElementById("panel-pr") },
    { button: document.getElementById("tab-weekly"), panel: document.getElementById("panel-weekly"), onShow: loadWeeklyChanges },
    { button: document.getElementById("tab-workflow"), panel: document.getElementById("panel-workflow"), onShow: loadCurrentBrdWorkflow }
  ];

  function switchTab(btn, pnl) {
    stateLoading.classList.add("hidden");
    stateNoPr.classList.add("hidden");
    stateError.classList.add("hidden");
    dashboardContent.classList.remove("hidden");

    tabs.forEach(t => {
      t.button.classList.remove("active");
      t.panel.classList.add("hidden");
    });
    btn.classList.add("active");
    pnl.classList.remove("hidden");
  }

  tabs.forEach(tab => {
    tab.button.addEventListener("click", () => {
      switchTab(tab.button, tab.panel);
      if (tab.onShow) tab.onShow();
    });
  });

  // --- DASHBOARD LOGIC ---
  async function loadDashboard() {
    showState(dashboardContent);
    const repoTabsEl = document.getElementById("repo-tabs");
    const prsContainerEl = document.getElementById("repo-prs-container");
    const loadingEl = document.getElementById("dashboard-loading");
    const emptyEl = document.getElementById("dashboard-empty");

    repoTabsEl.innerHTML = "";
    prsContainerEl.innerHTML = "";
    loadingEl.classList.remove("hidden");
    emptyEl.classList.add("hidden");

    try {
      const res = await fetchWithAuth("/api/pr/pending");
      if (!res.ok) throw new Error("Failed to fetch pending PRs");
      
      const pendingPrs = await res.json();
      loadingEl.classList.add("hidden");

      if (!pendingPrs || pendingPrs.length === 0) {
        emptyEl.classList.remove("hidden");
        return;
      }

      // Group by repo
      const repos = {};
      pendingPrs.forEach(pr => {
        if (!repos[pr.repo]) repos[pr.repo] = [];
        repos[pr.repo].push(pr);
      });

      let firstRepo = null;
      for (const repo in repos) {
        if (!firstRepo) firstRepo = repo;
        
        // Create tab
        const tab = document.createElement("div");
        tab.className = "repo-tab";
        tab.textContent = repo;
        tab.dataset.repo = repo;
        tab.addEventListener("click", () => selectRepoTab(repo, repos));
        repoTabsEl.appendChild(tab);
      }

      // Select first repo by default
      if (firstRepo) {
        selectRepoTab(firstRepo, repos);
      }

    } catch (e) {
      console.error(e);
      loadingEl.classList.add("hidden");
      emptyEl.classList.remove("hidden");
      emptyEl.innerHTML = `<p style="color:var(--accent-red)">Error: ${e.message}</p>`;
    }
  }

  function selectRepoTab(selectedRepo, allReposData) {
    // Update active tab style
    document.querySelectorAll(".repo-tab").forEach(t => {
      t.classList.toggle("active", t.dataset.repo === selectedRepo);
    });

    // Render PRs for this repo
    const container = document.getElementById("repo-prs-container");
    container.innerHTML = "";

    const prs = allReposData[selectedRepo] || [];
    prs.forEach(pr => {
      const card = document.createElement("div");
      card.className = "dashboard-card";
      
      const confidencePct = Math.round(pr.confidence_score * 100);
      
      card.innerHTML = `
        <div class="dashboard-card-header">
          <div class="dashboard-card-title">
            <span class="dashboard-pr-num">PR #${pr.pr_number}</span>
            <span class="dashboard-pr-title">${pr.title}</span>
          </div>
          <svg class="chevron-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
        <div class="dashboard-card-body hidden" style="border-top:1px solid rgba(255,255,255,0.1);">
          
          <div class="confidence-container" style="margin-bottom:8px;">
            <span class="confidence-label">Confidence:</span>
            <div class="confidence-bar-bg">
              <div class="confidence-bar-fill" style="width: ${confidencePct}%"></div>
            </div>
            <span style="font-size:11px;font-weight:bold;color:var(--text-bright);">${confidencePct}%</span>
          </div>

          <p style="font-size:12px; color:var(--text-main); margin-bottom:10px;">Edit Summary:</p>
          <textarea id="edit-${pr.pr_number}" class="input-field" rows="3" style="width:100%; box-sizing:border-box; background:rgba(0,0,0,0.4); color:#c9d1d9; padding:8px; border-radius:4px; border:1px solid rgba(255,255,255,0.1); font-size:12px; margin-bottom:8px;">${pr.summary}</textarea>
          
          <div style="display:flex; gap:6px; margin-bottom:8px;">
            <button class="btn btn-secondary dash-repair" data-pr="${pr.pr_number}" data-repo="${pr.repo}" style="flex:1; font-size:11px;">Save Edit</button>
            <button class="btn btn-secondary dash-compare" data-pr="${pr.pr_number}" data-repo="${pr.repo}" style="flex:1; font-size:11px;">Compare</button>
          </div>
          
          <div id="comp-res-${pr.pr_number}" class="hidden" style="margin-bottom:8px; padding:8px; background:rgba(0,0,0,0.3); border-radius:4px; font-size:11px;"></div>
          
          <div style="display:flex; gap:6px; margin-bottom:8px;">
            <button class="btn btn-primary dash-autorepair" data-pr="${pr.pr_number}" data-repo="${pr.repo}" style="flex:1; font-size:11px; background-color:var(--accent-blue);">Auto-Repair Code</button>
            <button class="btn btn-primary dash-approve" data-pr="${pr.pr_number}" data-repo="${pr.repo}" style="flex:1; font-size:11px; background-color:#238636;">Approve</button>
          </div>
          
          <button class="btn btn-secondary dash-reject" data-pr="${pr.pr_number}" data-repo="${pr.repo}" style="width:100%; font-size:11px; color:var(--accent-red); border-color:rgba(248,81,73,0.3);">Reject / Remove</button>
        </div>
      `;

      // Accordion toggle
      const header = card.querySelector(".dashboard-card-header");
      const body = card.querySelector(".dashboard-card-body");
      const chevron = card.querySelector(".chevron-icon");
      
      header.addEventListener("click", () => {
        card.classList.toggle("expanded");
        body.classList.toggle("hidden");
        chevron.style.transform = card.classList.contains("expanded") ? "rotate(180deg)" : "rotate(0deg)";
      });

      // Bind buttons
      card.querySelector(".dash-repair").addEventListener("click", (e) => handleDashRepair(e.target));
      card.querySelector(".dash-compare").addEventListener("click", (e) => handleDashCompare(e.target));
      card.querySelector(".dash-autorepair").addEventListener("click", (e) => handleDashAutoRepair(e.target));
      card.querySelector(".dash-approve").addEventListener("click", (e) => handleDashApprove(e.target));
      card.querySelector(".dash-reject").addEventListener("click", (e) => handleDashReject(e.target));

      container.appendChild(card);
    });
  }

  // Dashboard Button Handlers
  async function handleDashRepair(btn) {
    const prNum = btn.dataset.pr;
    const repo = btn.dataset.repo;
    const text = document.getElementById(`edit-${prNum}`).value.trim();
    
    btn.textContent = "...";
    try {
      const res = await fetchWithAuth(`/api/pr/${prNum}/repair?repo=${encodeURIComponent(repo)}`, {
        method: "POST",
        body: JSON.stringify({ edited_summary: text })
      });
      if (!res.ok) throw new Error(await res.text());
      btn.textContent = "Saved";
      setTimeout(() => btn.textContent = "Save Edit", 2000);
    } catch(e) { alert(e.message); btn.textContent = "Save Edit"; }
  }

  async function handleDashCompare(btn) {
    const prNum = btn.dataset.pr;
    const repo = btn.dataset.repo;
    const resDiv = document.getElementById(`comp-res-${prNum}`);
    
    btn.textContent = "...";
    resDiv.classList.add("hidden");
    
    try {
      const res = await fetchWithAuth(`/api/pr/${prNum}/compare?repo=${encodeURIComponent(repo)}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      btn.textContent = "Compare";
      
      resDiv.classList.remove("hidden");
      if (!data.differences_detected) {
        resDiv.innerHTML = "<strong style='color:var(--accent-green)'>No differences.</strong>";
      } else {
        resDiv.innerHTML = `<strong>Analysis:</strong> ${data.analysis || data.message}<br><strong>Recommendation:</strong> ${data.recommendation || ''}`;
      }
    } catch(e) { alert(e.message); btn.textContent = "Compare"; }
  }

  async function handleDashAutoRepair(btn) {
    const prNum = btn.dataset.pr;
    const repo = btn.dataset.repo;
    
    btn.textContent = "Repairing...";
    btn.disabled = true;
    try {
      const res = await fetchWithAuth(`/api/pr/${prNum}/auto-repair?repo=${encodeURIComponent(repo)}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      btn.textContent = "Repaired ✅";
      btn.style.backgroundColor = "var(--accent-green)";
    } catch(e) { 
      alert(e.message); 
      btn.textContent = "Auto-Repair Code"; 
      btn.disabled = false;
    }
  }

  async function handleDashApprove(btn) {
    const prNum = btn.dataset.pr;
    const repo = btn.dataset.repo;
    
    btn.textContent = "Approving...";
    btn.disabled = true;
    try {
      const res = await fetchWithAuth(`/api/pr/${prNum}/approve?repo=${encodeURIComponent(repo)}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      btn.textContent = "Approved ✅";
      btn.style.backgroundColor = "var(--accent-green)";
      setTimeout(() => loadDashboard(), 1500); // refresh list
    } catch(e) { 
      alert(e.message); 
      btn.textContent = "Approve"; 
      btn.disabled = false;
    }
  }

  async function handleDashReject(btn) {
    const prNum = btn.dataset.pr;
    const repo = btn.dataset.repo;
    
    if(!confirm(`Are you sure you want to reject and remove PR #${prNum} from pending?`)) return;
    
    btn.textContent = "Rejecting...";
    btn.disabled = true;
    try {
      const res = await fetchWithAuth(`/api/pr/${prNum}/reject?repo=${encodeURIComponent(repo)}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      
      // Remove card from UI
      btn.closest('.dashboard-card').remove();
    } catch(e) { 
      alert(e.message); 
      btn.textContent = "Reject / Remove"; 
      btn.disabled = false;
    }
  }

  // --- WEEKLY CHANGES ---
  async function loadWeeklyChanges() {
    const weeklyLoading = document.getElementById("weekly-loading");
    const weeklyEmpty = document.getElementById("weekly-empty");
    const weeklyList = document.getElementById("weekly-list");

    weeklyLoading.classList.remove("hidden");
    weeklyEmpty.classList.add("hidden");
    weeklyList.classList.add("hidden");
    weeklyList.innerHTML = "";

    try {
      const response = await chrome.runtime.sendMessage({ type: "FETCH_WEEK_CHANGES" });
      if (response.error) throw new Error(response.error);

      const summaries = response.data || [];
      weeklyLoading.classList.add("hidden");

      if (summaries.length === 0) {
        weeklyEmpty.classList.remove("hidden");
      } else {
        weeklyList.classList.remove("hidden");
        summaries.forEach(s => {
          const li = document.createElement("li");
          li.className = "change-item";
          li.style.borderLeft = "3px solid var(--accent-blue)";
          li.style.paddingLeft = "8px";
          li.style.marginBottom = "10px";
          li.innerHTML = `
            <div class="change-header">
              <span class="change-file" style="font-weight:600;">${s.repo} (PR #${s.pr_number})</span>
              <span class="change-badge badge-modified">${s.branch || 'main'}</span>
            </div>
            <div class="change-desc" style="font-weight:500; margin-top:4px;">${s.title}</div>
            <div class="change-desc" style="color:var(--text-muted); font-size:12px; margin-top:4px;">${s.summary}</div>
          `;
          weeklyList.appendChild(li);
        });
      }
    } catch (err) {
      console.error(err);
      weeklyLoading.classList.add("hidden");
      weeklyEmpty.classList.remove("hidden");
      weeklyEmpty.innerHTML = `<p style="color:var(--accent-red)">Error loading weekly changes: ${err.message}</p>`;
    }
  }

  // --- WORKFLOW PREFILL ---
  let brdWorkflowLoaded = false;
  async function loadCurrentBrdWorkflow() {
    if (brdWorkflowLoaded) return;
    const wfPromptInput = document.getElementById("wf-prompt-input");
    try {
      const res = await fetchWithAuth(`/api/profiles/1/brd/current`);
      if (res.ok) {
        const brd = await res.json();
        if (brd && brd.content) {
          const content = brd.content;
          const workflowSection = content.match(/workflow[\s\S]*?\n\n/) || content.substring(0, 300);
          wfPromptInput.value = Array.isArray(workflowSection) ? workflowSection[0].trim() : workflowSection.trim();
          brdWorkflowLoaded = true;
        }
      }
    } catch (err) { console.warn("Failed to pre-fill BRD workflow reference:", err); }
  }

  // --- WORKFLOW GENERATION ---
  const btnGenerateWf = document.getElementById("btn-generate-wf");
  const wfImageLoading = document.getElementById("wf-image-loading");
  const wfImageContainer = document.getElementById("wf-image-container");
  const wfGeneratedImg = document.getElementById("wf-generated-img");
  const wfPromptInput = document.getElementById("wf-prompt-input");

  btnGenerateWf.addEventListener("click", async () => {
    const text = wfPromptInput.value.trim();
    if (!text) return;
    btnGenerateWf.disabled = true;
    wfImageLoading.classList.remove("hidden");
    wfImageContainer.classList.add("hidden");
    try {
      const response = await chrome.runtime.sendMessage({ type: "GENERATE_WORKFLOW_IMAGE", workflowText: text });
      if (response.error) throw new Error(response.error);
      wfGeneratedImg.src = response.data;
      wfImageContainer.classList.remove("hidden");
    } catch (err) {
      alert("Failed to generate workflow diagram: " + err.message);
    } finally {
      wfImageLoading.classList.add("hidden");
      btnGenerateWf.disabled = false;
    }
  });

  // --- ADMIN ACTIONS (Current PR Tab) ---
  async function fetchWithAuth(url, options = {}) {
      const settings = await new Promise((resolve) => chrome.storage.local.get(["apiUrl", "backendUrl", "apiKey"], resolve));
      let apiUrl = settings.apiUrl || settings.backendUrl || "http://localhost:8000";
      if (apiUrl.includes("capsule-opal-nine.vercel.app")) {
          apiUrl = "http://localhost:8089";
      }
      return fetch(`${apiUrl}${url}`, {
        ...options,
        headers: {
          "X-API-Key": settings.apiKey || "dev-bypass",
          "Content-Type": "application/json",
          ...options.headers
        }
      });
  }
  
  btnRepair.addEventListener("click", async () => {
    if (!currentPrNumber) return;
    const editedSummary = adminSummaryEdit.value.trim();
    btnRepair.textContent = "Saving...";
    try {
      const res = await fetchWithAuth(`/api/pr/${currentPrNumber}/repair?repo=${encodeURIComponent(currentRepo)}`, {
        method: "POST",
        body: JSON.stringify({ edited_summary: editedSummary })
      });
      if (!res.ok) throw new Error(await res.text());
      btnRepair.textContent = "Saved!";
      setTimeout(() => btnRepair.textContent = "Save Edit", 2000);
      aiSummaryText.textContent = editedSummary;
    } catch (e) { alert(e.message); btnRepair.textContent = "Save Edit"; }
  });
  
  btnCompare.addEventListener("click", async () => {
    if (!currentPrNumber) return;
    btnCompare.textContent = "Comparing...";
    compareResults.classList.add("hidden");
    try {
      const res = await fetchWithAuth(`/api/pr/${currentPrNumber}/compare?repo=${encodeURIComponent(currentRepo)}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      btnCompare.textContent = "Compare";
      compareResults.classList.remove("hidden");
      if (!data.differences_detected) {
        compareResults.innerHTML = "<strong style='color:var(--accent-green)'>No significant differences detected.</strong>";
      } else {
        compareResults.innerHTML = `<div style="margin-bottom:5px;"><strong>Analysis:</strong> ${data.analysis || data.message || "Differences found."}</div>${data.recommendation ? `<div><strong>Recommendation:</strong> ${data.recommendation}</div>` : ""}`;
      }
    } catch (e) { alert(e.message); btnCompare.textContent = "Compare"; }
  });
  
  btnApprove.addEventListener("click", async () => {
    if (!currentPrNumber) return;
    btnApprove.textContent = "Approving & Pushing...";
    btnApprove.disabled = true;
    try {
      const res = await fetchWithAuth(`/api/pr/${currentPrNumber}/approve?repo=${encodeURIComponent(currentRepo)}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      btnApprove.textContent = "Approved & Pushed ✅";
      btnApprove.style.backgroundColor = "var(--accent-green)";
    } catch (e) { alert(e.message); btnApprove.textContent = "Approve & Push Changelog"; btnApprove.disabled = false; }
  });

  // Load immediately on open
  await loadPrAnalysis();
});

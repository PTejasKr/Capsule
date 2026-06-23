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

  // Track state
  let currentRepo = "";
  let currentPrNumber = null;

  // Setup accordions
  btnToggleChanges.addEventListener("click", () => {
    btnToggleChanges.classList.toggle("active");
    changesContainer.classList.toggle("hidden");
  });

  btnToggleChangelog.addEventListener("click", () => {
    btnToggleChangelog.classList.toggle("active");
    changelogContainer.classList.toggle("hidden");
  });

  // Settings redirect
  btnSettings.addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
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
    if (!tab || !tab.url) {
      showState(stateNoPr);
      return;
    }

    // 2. Parse GitHub PR URL format: https://github.com/owner/repo/pull/number
    const match = tab.url.match(/github\.com\/([^\/]+)\/([^\/]+)\/pull\/(\d+)/);
    if (!match) {
      showState(stateNoPr);
      return;
    }

    const owner = match[1];
    const repo = match[2];
    currentRepo = `${owner}/${repo}`;
    currentPrNumber = parseInt(match[3], 10);

    prRepoEl.textContent = currentRepo;
    prNumberEl.textContent = `PR #${currentPrNumber}`;

    try {
      // 3. Fetch summary from backend (via service-worker)
      const response = await chrome.runtime.sendMessage({
        type: "FETCH_SUMMARY",
        repo: currentRepo,
        prNumber: currentPrNumber
      });

      if (response.error) {
        throw new Error(response.error);
      }

      const summary = response.data;
      renderDashboard(summary);
      
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

  function renderDashboard(data) {
    showState(dashboardContent);

    // Title
    prTitleEl.textContent = data.title || "Untitled Pull Request";
    
    // AI Summary
    aiSummaryText.textContent = data.summary || "No summary details available.";
    
    // Confidence meter
    const confidencePct = Math.round(data.confidence_score * 100);
    confidenceBar.style.width = `${confidencePct}%`;
    confidenceText.textContent = `${confidencePct}%`;

    // Workflow impact
    const wf = data.workflow_impact || {};
    workflowImpactBanner.className = "impact-banner"; // reset
    
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

    // Detailed changes
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
    changelog.technical_changes.forEach(c => {
      text += `- ${c}\n`;
    });
    text += `\n### Workflow Changes\n`;
    if (changelog.workflow_changes.length > 0) {
      changelog.workflow_changes.forEach(w => {
        text += `- ${w}\n`;
      });
    } else {
      text += `- No workflow changes detected.\n`;
    }
    text += `\n### Lines Changed: +${changelog.lines_added} / -${changelog.lines_deleted}`;
    return text;
  }

  // --- TAB NAVIGATION SYSTEM ---
  const tabs = [
    { button: document.getElementById("tab-pr"), panel: document.getElementById("panel-pr") },
    { button: document.getElementById("tab-weekly"), panel: document.getElementById("panel-weekly"), onShow: loadWeeklyChanges },
    { button: document.getElementById("tab-workflow"), panel: document.getElementById("panel-workflow"), onShow: loadCurrentBrdWorkflow }
  ];

  tabs.forEach(tab => {
    tab.button.addEventListener("click", () => {
      tabs.forEach(t => {
        t.button.classList.remove("active");
        t.panel.classList.add("hidden");
      });
      tab.button.classList.add("active");
      tab.panel.classList.remove("hidden");
      if (tab.onShow) {
        tab.onShow();
      }
    });
  });

  // Load consolidated changes from past 1 week
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
      if (response.error) {
        throw new Error(response.error);
      }

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

  // Pre-fill workflow prompt with active BRD processes
  let brdWorkflowLoaded = false;
  async function loadCurrentBrdWorkflow() {
    if (brdWorkflowLoaded) return;
    
    const wfPromptInput = document.getElementById("wf-prompt-input");
    try {
      const settings = await new Promise((resolve) => {
        chrome.storage.local.get(["apiUrl", "apiKey"], resolve);
      });
      const apiUrl = settings.apiUrl || "http://localhost:8000";
      
      const res = await fetch(`${apiUrl}/api/brd/current`, {
        headers: { "X-API-Key": settings.apiKey || "" }
      });
      
      if (res.ok) {
        const brd = await res.json();
        if (brd && brd.content) {
          const content = brd.content;
          const workflowSection = content.match(/(?s)workflow.*?\n\n/) || content.substring(0, 300);
          wfPromptInput.value = Array.isArray(workflowSection) ? workflowSection[0].trim() : workflowSection.trim();
          brdWorkflowLoaded = true;
        }
      }
    } catch (err) {
      console.warn("Failed to pre-fill BRD workflow reference:", err);
    }
  }

  // Workers AI Image generation handler
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
      const response = await chrome.runtime.sendMessage({
        type: "GENERATE_WORKFLOW_IMAGE",
        workflowText: text
      });

      if (response.error) {
        throw new Error(response.error);
      }

      wfGeneratedImg.src = response.data;
      wfImageContainer.classList.remove("hidden");
    } catch (err) {
      console.error(err);
      alert("Failed to generate workflow diagram: " + err.message);
    } finally {
      wfImageLoading.classList.add("hidden");
      btnGenerateWf.disabled = false;
    }
  });

  // Load immediately on open
  await loadPrAnalysis();
});


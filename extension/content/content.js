(function() {
  // Check if we are on a GitHub PR page
  const prUrlRegex = /github\.com\/([^\/]+)\/([^\/]+)\/pull\/(\d+)/;
  const match = window.location.href.match(prUrlRegex);
  if (!match) return;

  const owner = match[1];
  const repo = match[2];
  const repoFullName = `${owner}/${repo}`;
  const prNumber = parseInt(match[3], 10);

  logger("Injected into PR Page. Initializing Capsule floating widget...");

  // Prevent multiple injections
  if (document.getElementById("capsule-root")) return;

  // Create Root Element
  const rootElement = document.createElement("div");
  rootElement.id = "capsule-root";
  document.body.appendChild(rootElement);

  // Attach Shadow DOM
  const shadow = rootElement.attachShadow({ mode: "closed" });

  // Stylesheet
  const style = document.createElement("style");
  style.textContent = `
    /* Floating Widget Button */
    .capsule-badge-btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background-color: #0d1117;
      border: 1px solid #30363d;
      color: #58a6ff;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
      z-index: 999999;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    .capsule-badge-btn:hover {
      transform: scale(1.08);
      border-color: #58a6ff;
      box-shadow: 0 0 12px rgba(88, 166, 255, 0.4);
    }

    .capsule-badge-btn svg {
      width: 22px;
      height: 22px;
    }

    /* Status Dot indicator */
    .status-dot {
      position: absolute;
      top: 2px;
      right: 2px;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background-color: transparent;
      border: 2px solid #0d1117;
    }

    .status-dot.dot-none { background-color: #3fb950; }
    .status-dot.dot-minor { background-color: #d29922; }
    .status-dot.dot-major { background-color: #f85149; }

    /* Side Panel */
    .capsule-side-panel {
      position: fixed;
      top: 0;
      right: -420px;
      width: 400px;
      height: 100vh;
      background-color: #0d1117;
      border-left: 1px solid #30363d;
      box-shadow: -4px 0 24px rgba(0, 0, 0, 0.5);
      z-index: 999998;
      display: flex;
      flex-direction: column;
      color: #c9d1d9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      transition: right 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .capsule-side-panel.open {
      right: 0;
    }

    /* Side Panel Header */
    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px;
      background-color: #161b22;
      border-bottom: 1px solid #30363d;
    }

    .panel-header h2 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
      color: #f0f6fc;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .close-btn {
      background: none;
      border: none;
      color: #8b949e;
      cursor: pointer;
      display: flex;
      align-items: center;
      padding: 4px;
      border-radius: 4px;
    }

    .close-btn:hover {
      color: #f0f6fc;
      background-color: rgba(255, 255, 255, 0.05);
    }

    /* Content Area */
    .panel-body {
      padding: 16px;
      overflow-y: auto;
      flex-grow: 1;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    /* Scrollbar */
    .panel-body::-webkit-scrollbar {
      width: 6px;
    }
    .panel-body::-webkit-scrollbar-track {
      background: #0d1117;
    }
    .panel-body::-webkit-scrollbar-thumb {
      background: #30363d;
      border-radius: 3px;
    }

    /* Banners */
    .impact-banner {
      padding: 12px;
      border-radius: 6px;
      border-left: 4px solid #30363d;
      font-size: 13px;
      line-height: 1.4;
    }
    .impact-none {
      background-color: rgba(63, 185, 80, 0.08);
      border-left-color: #3fb950;
    }
    .impact-minor {
      background-color: rgba(210, 153, 34, 0.08);
      border-left-color: #d29922;
    }
    .impact-major {
      background-color: rgba(248, 81, 73, 0.08);
      border-left-color: #f85149;
    }

    .impact-title {
      font-weight: 600;
      margin-bottom: 4px;
    }
    .impact-none .impact-title { color: #56d364; }
    .impact-minor .impact-title { color: #e3b341; }
    .impact-major .impact-title { color: #ff7b72; }

    /* Summary Card */
    .card {
      background-color: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 14px;
    }

    .card h3 {
      margin-top: 0;
      margin-bottom: 8px;
      font-size: 13px;
      text-transform: uppercase;
      color: #8b949e;
      letter-spacing: 0.5px;
    }

    .summary-text {
      font-size: 13px;
      line-height: 1.5;
      color: #c9d1d9;
    }

    /* Details Accordion */
    .section-title {
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 8px;
      color: #f0f6fc;
      border-bottom: 1px solid #30363d;
      padding-bottom: 4px;
    }

    .change-list {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .change-item {
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-size: 12px;
    }

    .change-meta {
      display: flex;
      justify-content: space-between;
    }

    .change-file {
      font-family: monospace;
      color: #58a6ff;
    }

    .change-type {
      font-size: 9px;
      font-weight: bold;
      text-transform: uppercase;
      padding: 1px 4px;
      border-radius: 3px;
    }
    .added { background-color: rgba(63, 185, 80, 0.15); color: #3fb950; }
    .modified { background-color: rgba(210, 153, 34, 0.15); color: #d29922; }
    .deleted { background-color: rgba(248, 81, 73, 0.15); color: #f85149; }

    /* Loading Skeletons */
    .skeleton {
      background-color: #30363d;
      height: 12px;
      border-radius: 4px;
      margin-bottom: 8px;
      animation: shimmer 1.5s infinite ease-in-out;
    }
    .skeleton-h { height: 18px; width: 60%; }
    .skeleton-p { width: 100%; }
    .skeleton-p2 { width: 85%; }
    
    @keyframes shimmer {
      0% { opacity: 0.4; }
      50% { opacity: 0.7; }
      100% { opacity: 0.4; }
    }

    .hidden { display: none !important; }
  `;
  shadow.appendChild(style);

  // 1. Create Badge Button
  const badgeBtn = document.createElement("button");
  badgeBtn.className = "capsule-badge-btn";
  badgeBtn.title = "View Capsule PR Analysis";
  badgeBtn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <path d="M12 8v8"/>
      <path d="M8 12h8"/>
    </svg>
    <div class="status-dot" id="capsule-dot"></div>
  `;
  shadow.appendChild(badgeBtn);

  // 2. Create Side Panel
  const sidePanel = document.createElement("div");
  sidePanel.className = "capsule-side-panel";
  sidePanel.innerHTML = `
    <div class="panel-header">
      <h2>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        Capsule PR Analysis
      </h2>
      <button class="close-btn" id="capsule-close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    
    <div class="panel-body">
      <!-- Loading state -->
      <div id="capsule-loading">
        <div class="skeleton skeleton-h"></div>
        <div style="margin-top: 20px;">
          <div class="skeleton skeleton-p"></div>
          <div class="skeleton skeleton-p2"></div>
        </div>
      </div>
      
      <!-- Loaded Data -->
      <div id="capsule-data" class="hidden">
        <div id="capsule-banner" class="impact-banner">
          <div class="impact-title" id="capsule-banner-title">No Workflow Impact</div>
          <div id="capsule-banner-desc">Analyzing database processes...</div>
        </div>
        
        <div class="card" style="margin-top: 14px;">
          <h3>AI Summary</h3>
          <div class="summary-text" id="capsule-summary">PR Summary loading...</div>
        </div>

        <div style="margin-top: 14px;">
          <div class="section-title">Workflow & Process Impact</div>
          <div id="capsule-workflows" style="font-size: 13px;">None</div>
        </div>

        <div style="margin-top: 14px;">
          <div class="section-title">Affected Files</div>
          <ul class="change-list" id="capsule-changes"></ul>
        </div>
      </div>

      <!-- Error State -->
      <div id="capsule-error" class="hidden" style="text-align: center; padding: 20px; color: #f85149;">
        ⚠️ Failed to fetch PR analysis. Make sure Capsule API is running and the PR is analyzed.
      </div>
    </div>
  `;
  shadow.appendChild(sidePanel);

  // Elements mapping inside Shadow DOM
  const closeBtn = shadow.getElementById("capsule-close");
  const loadingEl = shadow.getElementById("capsule-loading");
  const dataEl = shadow.getElementById("capsule-data");
  const errorEl = shadow.getElementById("capsule-error");
  const summaryEl = shadow.getElementById("capsule-summary");
  const bannerEl = shadow.getElementById("capsule-banner");
  const bannerTitleEl = shadow.getElementById("capsule-banner-title");
  const bannerDescEl = shadow.getElementById("capsule-banner-desc");
  const workflowsEl = shadow.getElementById("capsule-workflows");
  const changesEl = shadow.getElementById("capsule-changes");
  const statusDot = shadow.getElementById("capsule-dot");

  let summaryFetched = false;

  // Toggle Panel open/close
  badgeBtn.addEventListener("click", () => {
    sidePanel.classList.toggle("open");
    if (sidePanel.classList.contains("open") && !summaryFetched) {
      fetchAnalysis();
    }
  });

  closeBtn.addEventListener("click", () => {
    sidePanel.classList.remove("open");
  });

  // Background fetch
  async function fetchAnalysis() {
    loadingEl.classList.remove("hidden");
    dataEl.classList.add("hidden");
    errorEl.classList.add("hidden");

    try {
      const response = await chrome.runtime.sendMessage({
        type: "FETCH_SUMMARY",
        repo: repoFullName,
        prNumber: prNumber
      });

      if (response.error) {
        throw new Error(response.error);
      }

      const summary = response.data;
      
      // Render
      summaryEl.textContent = summary.summary;
      
      // Render impact
      const wf = summary.workflow_impact || {};
      bannerEl.className = "impact-banner"; // Reset
      statusDot.className = "status-dot";

      if (wf.severity === "major") {
        bannerEl.classList.add("impact-major");
        bannerTitleEl.textContent = "Major Workflow Change";
        bannerDescEl.textContent = wf.impact_description;
        statusDot.classList.add("dot-major");
        
        let wfDetails = `<p><strong>Affected Workflows:</strong> ${wf.affected_workflows.join(", ")}</p>`;
        if (wf.before_state || wf.after_state) {
          wfDetails += `<p style="margin-top:4px;"><strong>Transition:</strong> [${wf.before_state}] ➔ [${wf.after_state}]</p>`;
        }
        workflowsEl.innerHTML = wfDetails;
      } else if (wf.severity === "minor") {
        bannerEl.classList.add("impact-minor");
        bannerTitleEl.textContent = "Minor Workflow Change";
        bannerDescEl.textContent = wf.impact_description;
        statusDot.classList.add("dot-minor");
        workflowsEl.innerHTML = `<p><strong>Affected:</strong> ${wf.affected_workflows.join(", ")}</p>`;
      } else {
        bannerEl.classList.add("impact-none");
        bannerTitleEl.textContent = "No Workflow Impact";
        bannerDescEl.textContent = "Matches existing BRD. Zero process flows altered.";
        statusDot.classList.add("dot-none");
        workflowsEl.innerHTML = "<p style='color:#8b949e;'>No changes to existing business requirement flows.</p>";
      }

      // Render Changes
      changesEl.innerHTML = "";
      const changes = summary.changes || [];
      changes.forEach(c => {
        const li = document.createElement("li");
        li.className = "change-item";
        li.innerHTML = `
          <div class="change-meta">
            <span class="change-file">${c.file.split('/').pop()}</span>
            <span class="change-type ${c.change_type}">${c.change_type}</span>
          </div>
          <div style="color: #8b949e; margin-top:2px;">${c.description}</div>
        `;
        changesEl.appendChild(li);
      });

      loadingEl.classList.add("hidden");
      dataEl.classList.remove("hidden");
      summaryFetched = true;
    } catch (e) {
      console.error("Capsule analysis load error:", e);
      loadingEl.classList.add("hidden");
      errorEl.classList.remove("hidden");
    }
  }

  // Pre-fetch status dot to color indicator on load
  async function checkStatusDot() {
    try {
      const response = await chrome.runtime.sendMessage({
        type: "FETCH_SUMMARY",
        repo: repoFullName,
        prNumber: prNumber
      });
      if (response && response.data && response.data.workflow_impact) {
        const severity = response.data.workflow_impact.severity;
        statusDot.className = "status-dot";
        if (severity === "major") statusDot.classList.add("dot-major");
        else if (severity === "minor") statusDot.classList.add("dot-minor");
        else statusDot.classList.add("dot-none");
      }
    } catch (e) {
      // Slid silently
    }
  }

  // Delay a bit to not block initial page rendering
  setTimeout(checkStatusDot, 2000);

  function logger(msg) {
    console.log(`%c[Capsule] %c${msg}`, "color: #58a6ff; font-weight: bold;", "color: inherit;");
  }
})();

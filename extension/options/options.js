document.addEventListener("DOMContentLoaded", () => {
  // --- AUTH LOGIC ---
  const authOverlay = document.getElementById("auth-overlay");
  const appContent = document.getElementById("app-content");
  const inputLoginBackendUrl = document.getElementById("input-login-backend-url");
  const btnEnterDashboard = document.getElementById("btn-enter-dashboard");
  const authError = document.getElementById("auth-error");
  const btnGithubLogin = document.getElementById("btn-github-login");
  const btnBypassAuth = document.getElementById("btn-bypass-auth");

  // Load existing backend URL if any
  chrome.storage.local.get(["backendUrl", "apiKey"]).then(({ backendUrl, apiKey }) => {
    if (backendUrl) {
      inputLoginBackendUrl.value = backendUrl;
    }
    // If already authenticated, show the enter dashboard button immediately
    if (apiKey) {
      btnGithubLogin.style.display = "none";
      btnEnterDashboard.style.display = "block";
    }
  });

  btnEnterDashboard.addEventListener("click", () => {
    authOverlay.style.opacity = "0";
    setTimeout(() => {
      authOverlay.style.display = "none";
      appContent.style.display = "flex";
    }, 400);
  });

  if (btnBypassAuth) {
    btnBypassAuth.addEventListener("click", () => {
      const backendUrl = inputLoginBackendUrl.value.trim().replace(/\/$/, "");
      chrome.storage.local.set({ apiKey: "dev-bypass", apiUrl: backendUrl, backendUrl: backendUrl }, () => {
        authOverlay.style.opacity = "0";
        setTimeout(() => {
          authOverlay.style.display = "none";
          appContent.style.display = "flex";
        }, 400);
      });
    });
  }

  if (btnGithubLogin) {
    btnGithubLogin.addEventListener("click", async () => {
      btnGithubLogin.disabled = true;
      const originalText = btnGithubLogin.innerHTML;
      btnGithubLogin.innerHTML = 'Connecting...';
      authError.style.display = "none";
      
      try {
        const backendUrl = inputLoginBackendUrl.value.trim().replace(/\/$/, "");
        if (!backendUrl) throw new Error("Please enter a valid Backend URL");
        
        await chrome.storage.local.set({ backendUrl });
        
        // Fetch config
        const configRes = await fetch(`${backendUrl}/api/auth/extension/config`);
        if (!configRes.ok) throw new Error("Failed to fetch extension config");
        const config = await configRes.json();
        
        const clientId = config.github_client_id;
        const redirectUrl = chrome.identity.getRedirectURL();
        
        const authUrl = `https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUrl)}&scope=read:org`;
        
        chrome.identity.launchWebAuthFlow(
          { url: authUrl, interactive: true },
          async (redirectUri) => {
            if (chrome.runtime.lastError || !redirectUri) {
              btnGithubLogin.disabled = false;
              btnGithubLogin.innerHTML = originalText;
              authError.textContent = chrome.runtime.lastError?.message || "Auth flow cancelled";
              authError.style.display = "block";
              setTimeout(() => { authError.style.display = "none"; }, 5000);
              return;
            }
            
            const urlParams = new URLSearchParams(new URL(redirectUri).search);
            const code = urlParams.get("code");
            if (!code) {
              throw new Error("No OAuth code received");
            }
            
            btnGithubLogin.innerHTML = 'Verifying org...';
            
            // Send code to backend
            try {
              const verifyRes = await fetch(`${backendUrl}/api/auth/extension/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code })
              });
              
              const verifyData = await verifyRes.json();
              
              if (verifyRes.ok && verifyData.api_key) {
                await chrome.storage.local.set({ apiKey: verifyData.api_key, apiUrl: backendUrl, backendUrl: backendUrl });
                btnGithubLogin.style.display = "none";
                btnEnterDashboard.style.display = "block";
              } else {
                throw new Error(verifyData.detail || "Verification failed");
              }
            } catch (err) {
              authError.textContent = err.message || "Backend verification failed";
              authError.style.display = "block";
              btnGithubLogin.disabled = false;
              btnGithubLogin.innerHTML = originalText;
              setTimeout(() => { authError.style.display = "none"; }, 5000);
            }
          }
        );
      } catch (err) {
        authError.textContent = err.message || "Failed to initialize auth";
        authError.style.display = "block";
        btnGithubLogin.disabled = false;
        btnGithubLogin.innerHTML = originalText;
        setTimeout(() => { authError.style.display = "none"; }, 5000);
      }
    });
  }


  // --- TABS LOGIC ---
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      tabContents.forEach(c => c.classList.remove("active"));
      
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");

      // Auto-refresh profiles if switching to profiles or BRD tab
      if (btn.dataset.tab === "tab-profiles" || btn.dataset.tab === "tab-brd") {
        fetchProfiles();
      }
    });
  });

  // --- CONNECTION TAB ---
  const inputApiUrl = document.getElementById("input-api-url");
  const inputApiKey = document.getElementById("input-api-key");
  
  chrome.storage.local.get(["apiUrl", "apiKey"], (items) => {
    inputApiUrl.value = items.apiUrl || "https://capsule-opal-nine.vercel.app";
    inputApiKey.value = items.apiKey || "";
  });

  document.getElementById("btn-save-conn").addEventListener("click", () => {
    const url = inputApiUrl.value.trim().replace(/\/$/, "");
    const key = inputApiKey.value.trim();
    if (!url) {
      showStatus("status-conn", "Server API URL is required", "error");
      return;
    }
    chrome.storage.local.set({ apiUrl: url, apiKey: key }, () => {
      showStatus("status-conn", "Settings successfully saved!", "success");
    });
  });

  document.getElementById("btn-test-conn").addEventListener("click", async () => {
    const url = inputApiUrl.value.trim().replace(/\/$/, "");
    const key = inputApiKey.value.trim();
    if (!url) return showStatus("status-conn", "Provide a Server URL to test", "error");

    showStatus("status-conn", "Testing server connection...", "success");
    try {
      const response = await fetch(`${url}/api/health`, { method: "GET" });
      if (response.ok) {
        showStatus("status-conn", "Connection successful! Backend is online.", "success");
      } else {
        showStatus("status-conn", `Server responded with code ${response.status}`, "error");
      }
    } catch (e) {
      showStatus("status-conn", `Connection failed: ${e.message}`, "error");
    }
  });

  // --- API HELPER ---
  async function apiCall(endpoint, method = "GET", body = null) {
    const { apiUrl, apiKey } = await chrome.storage.local.get(["apiUrl", "apiKey"]);
    if (!apiUrl || !apiKey) throw new Error("API URL or Key not configured");

    const headers = { "x-api-key": apiKey };
    
    let options = { method, headers };
    
    // Check if body is FormData (for file uploads) or normal JSON
    if (body instanceof FormData) {
      options.body = body;
    } else if (body) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    const finalEndpoint = endpoint.startsWith("/api") ? endpoint : `/api${endpoint}`;
    const response = await fetch(`${apiUrl}${finalEndpoint}`, options);
    
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Server error: ${response.status}`);
    }
    return response.json();
  }

  // --- PROFILES FETCHING ---
  async function fetchProfiles() {
    try {
      const profiles = await apiCall("/profiles");
      populateDropdowns(profiles);
    } catch (e) {
      console.error("Failed to fetch profiles:", e);
    }
  }

  function populateDropdowns(profiles) {
    const dropdowns = document.querySelectorAll(".profile-dropdown");
    dropdowns.forEach(dd => {
      const currentVal = dd.value;
      dd.innerHTML = '<option value="">Select a Profile...</option>';
      profiles.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.name} (ID: ${p.id})`;
        dd.appendChild(opt);
      });
      if (currentVal) dd.value = currentVal;
    });
  }

  // --- CREATE PROFILE ---
  document.getElementById("btn-create-prof").addEventListener("click", async () => {
    const name = document.getElementById("prof-name").value.trim();
    const changelog = document.getElementById("prof-changelog").value.trim();
    const model = document.getElementById("prof-model").value.trim();
    const token = document.getElementById("prof-token").value.trim();

    if (!name || !changelog) return showStatus("status-create-prof", "Name and Changelog Repo required", "error");

    try {
      await apiCall("/profiles", "POST", {
        name, 
        changelog_repo: changelog, 
        ai_model: model, 
        github_token: token
      });
      showStatus("status-create-prof", "Profile created successfully!", "success");
      fetchProfiles();
      
      // Clear form
      document.getElementById("prof-name").value = "";
      document.getElementById("prof-changelog").value = "";
      document.getElementById("prof-token").value = "";
    } catch (e) {
      showStatus("status-create-prof", e.message, "error");
    }
  });

  // --- MAP REPOSITORY ---
  document.getElementById("btn-map-repo").addEventListener("click", async () => {
    const profId = document.getElementById("map-prof-select").value;
    const repo = document.getElementById("map-repo").value.trim();

    if (!profId || !repo) return showStatus("status-map", "Profile and Repo required", "error");

    try {
      await apiCall("/profiles/mappings", "POST", {
        profile_id: parseInt(profId),
        source_repo: repo
      });
      showStatus("status-map", "Repository mapped successfully!", "success");
      document.getElementById("map-repo").value = "";
    } catch (e) {
      showStatus("status-map", e.message, "error");
    }
  });

  // --- DEPLOY WEBHOOK ---
  document.getElementById("btn-deploy-webhook").addEventListener("click", async () => {
    const profId = document.getElementById("deploy-prof-select").value;
    const repo = document.getElementById("deploy-repo").value.trim();
    let url = document.getElementById("deploy-url").value.trim();

    if (!profId || !repo) return showStatus("status-deploy", "Profile and Repo required", "error");
    
    // Auto-generate URL if blank
    if (!url) {
      const { apiUrl } = await chrome.storage.local.get(["apiUrl"]);
      url = `${apiUrl}/webhooks/github?profile_id=${profId}`;
      document.getElementById("deploy-url").value = url;
    }

    showStatus("status-deploy", "Deploying webhook...", "success");

    try {
      const res = await apiCall("/profiles/mappings/deploy-webhook", "POST", {
        profile_id: parseInt(profId),
        source_repo: repo,
        webhook_url: url
      });
      showStatus("status-deploy", res.message || "Webhook deployed!", "success");
    } catch (e) {
      showStatus("status-deploy", e.message, "error");
    }
  });

  // --- BRD MANAGER ---
  const brdProfSelect = document.getElementById("brd-prof-select");
  
  brdProfSelect.addEventListener("change", fetchCurrentBRD);
  document.getElementById("btn-refresh-brd").addEventListener("click", fetchCurrentBRD);

  async function fetchCurrentBRD() {
    const profId = brdProfSelect.value;
    const infoBox = document.getElementById("current-brd-info");
    
    if (!profId) {
      infoBox.innerHTML = "Select a profile to view active BRD.";
      return;
    }

    infoBox.innerHTML = "Fetching...";
    try {
      const meta = await apiCall(`/profiles/${profId}/brd/current`);
      if (meta && meta.version && meta.version !== "v0.0.0") {
        infoBox.innerHTML = `
          <p><strong>Version:</strong> ${meta.version}</p>
          <p><strong>Uploaded:</strong> ${meta.uploaded_at}</p>
          <p><strong>Hash:</strong> ${meta.hash.substring(0, 12)}...</p>
        `;
      } else {
        infoBox.innerHTML = "<p>No BRD uploaded for this profile.</p>";
      }
    } catch (e) {
      infoBox.innerHTML = `<p style="color: #ff7b72;">Error: ${e.message}</p>`;
    }
  }

  document.getElementById("btn-upload-brd").addEventListener("click", async () => {
    const profId = brdProfSelect.value;
    const content = document.getElementById("brd-content").value.trim();
    const version = document.getElementById("brd-version").value.trim();

    if (!profId) return showStatus("status-brd", "Select a profile first", "error");
    if (!content) return showStatus("status-brd", "Content is required", "error");

    const formData = new FormData();
    formData.append("text_content", content);
    if (version) formData.append("version", version);

    showStatus("status-brd", "Uploading...", "success");

    try {
      await apiCall(`/profiles/${profId}/brd/upload`, "POST", formData);
      showStatus("status-brd", "BRD Uploaded Successfully!", "success");
      document.getElementById("brd-content").value = "";
      document.getElementById("brd-version").value = "";
      fetchCurrentBRD();
    } catch (e) {
      showStatus("status-brd", e.message, "error");
    }
  });

  // --- HISTORY TAB LOGIC ---
  const histProfSelect = document.getElementById("hist-prof-select");
  
  histProfSelect.addEventListener("change", fetchHistory);
  
  async function fetchHistory() {
    const profId = histProfSelect.value;
    if (!profId) {
      clearHistory();
      return;
    }
    
    try {
      const history = await apiCall(`/profiles/${profId}/pr-history`);
      renderHistory(history);
    } catch (e) {
      console.error("Failed to fetch history:", e);
    }
  }
  
  function clearHistory() {
    ["present-day", "past-day", "past-week", "past-month"].forEach(id => {
      document.querySelector(`#history-${id} .history-list`).innerHTML = "";
    });
  }
  
  function renderHistory(items) {
    clearHistory();
    const now = new Date();
    
    const groups = {
      presentDay: [],
      pastDay: [],
      pastWeek: [],
      pastMonth: []
    };
    
    items.forEach(item => {
      // Create a clean display element
      const el = document.createElement("div");
      el.style.padding = "12px";
      el.style.backgroundColor = "rgba(255, 255, 255, 0.4)";
      el.style.borderRadius = "8px";
      el.style.borderLeft = "4px solid var(--accent)";
      
      const analyzedAt = item.analyzed_at ? new Date(item.analyzed_at + "Z") : new Date(); // assuming UTC
      const repo = item.repo;
      const prNum = item.pr_number;
      const branch = item.branch || "main";
      
      el.innerHTML = `
        <div style="font-weight: 600; color: var(--foreground);">
          ${repo} <span style="color: var(--accent);">#${prNum}</span> (${branch})
        </div>
        <div style="font-size: 0.85rem; color: #555; margin-top: 4px;">
          ${item.title || "No Title"}
        </div>
        <div style="font-size: 0.75rem; color: #888; margin-top: 8px;">
          Analyzed: ${analyzedAt.toLocaleString()}
        </div>
      `;
      
      // Calculate diff in hours
      const diffHours = (now - analyzedAt) / (1000 * 60 * 60);
      
      if (diffHours < 24 && now.getDate() === analyzedAt.getDate()) {
        groups.presentDay.push(el);
      } else if (diffHours < 48) {
        groups.pastDay.push(el);
      } else if (diffHours < 24 * 7) {
        groups.pastWeek.push(el);
      } else {
        groups.pastMonth.push(el);
      }
    });
    
    // Append to DOM
    if (groups.presentDay.length) {
      groups.presentDay.forEach(el => document.querySelector("#history-present-day .history-list").appendChild(el));
    } else {
      document.querySelector("#history-present-day .history-list").innerHTML = "<div style='color: #888; font-size: 0.9rem;'>No items</div>";
    }
    
    if (groups.pastDay.length) {
      groups.pastDay.forEach(el => document.querySelector("#history-past-day .history-list").appendChild(el));
    } else {
      document.querySelector("#history-past-day .history-list").innerHTML = "<div style='color: #888; font-size: 0.9rem;'>No items</div>";
    }
    
    if (groups.pastWeek.length) {
      groups.pastWeek.forEach(el => document.querySelector("#history-past-week .history-list").appendChild(el));
    } else {
      document.querySelector("#history-past-week .history-list").innerHTML = "<div style='color: #888; font-size: 0.9rem;'>No items</div>";
    }
    
    if (groups.pastMonth.length) {
      groups.pastMonth.forEach(el => document.querySelector("#history-past-month .history-list").appendChild(el));
    } else {
      document.querySelector("#history-past-month .history-list").innerHTML = "<div style='color: #888; font-size: 0.9rem;'>No items</div>";
    }
  }

  // --- UTILS ---
  function showStatus(elementId, msg, type) {
    const el = document.getElementById(elementId);
    if (!el) return;
    
    el.textContent = msg;
    el.className = "status-message"; 
    
    if (type === "success") {
      el.classList.add("status-success");
    } else {
      el.classList.add("status-error");
    }
    
    el.style.display = "block";
    
    setTimeout(() => {
      el.style.display = "none";
    }, 4000);
  }
});

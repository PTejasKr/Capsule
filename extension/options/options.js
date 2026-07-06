document.addEventListener("DOMContentLoaded", () => {
  // --- AUTH LOGIC ---
  const authOverlay = document.getElementById("auth-overlay");
  const appContent = document.getElementById("app-content");
  const btnUnlock = document.getElementById("btn-unlock");
  const inputMasterPassword = document.getElementById("input-master-password");
  const authError = document.getElementById("auth-error");

  // Auth checks the stored API key — no hardcoded secrets.
  // On first use, a fallback passcode "capsule-admin" is accepted
  // so the user can reach settings to configure their real API key.
  const checkAuth = async () => {
    const entered = inputMasterPassword.value.trim();
    if (!entered) return;

    const { apiKey } = await chrome.storage.local.get(["apiKey"]);

    // If an API key is saved, it becomes the master passcode.
    // If none is saved yet, accept the default bootstrap password so
    // the admin can log in and configure the key for the first time.
    const validPasscode = apiKey || "capsule-admin";

    if (entered === validPasscode) {
      authOverlay.style.opacity = "0";
      setTimeout(() => {
        authOverlay.style.display = "none";
        appContent.style.display = "flex";
      }, 400);
    } else {
      authError.textContent = apiKey
        ? "Incorrect passcode. Use your configured API Key."
        : "Incorrect passcode. Default is 'capsule-admin'.";
      authError.style.display = "block";
      inputMasterPassword.value = "";
      setTimeout(() => { authError.style.display = "none"; }, 3000);
    }
  };

  btnUnlock.addEventListener("click", checkAuth);
  inputMasterPassword.addEventListener("keypress", (e) => {
    if (e.key === "Enter") checkAuth();
  });

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

    const response = await fetch(`${apiUrl}${endpoint}`, options);
    
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

// Default configurations
const DEFAULT_API_URL = "http://localhost:8089";
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

// Message listener
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "FETCH_SUMMARY") {
    handleFetchSummary(request.repo, request.prNumber)
      .then(data => sendResponse({ data }))
      .catch(err => sendResponse({ error: err.message }));
    return true; // Keep message channel open for asynchronous response
  }
  
  if (request.type === "FETCH_CHANGELOG") {
    handleFetchChangelog(request.repo, request.prNumber)
      .then(data => sendResponse({ data }))
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }

  if (request.type === "FETCH_WEEK_CHANGES") {
    handleFetchWeeklyChanges()
      .then(data => sendResponse({ data }))
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }

  if (request.type === "GENERATE_WORKFLOW_IMAGE") {
    handleGenerateWorkflowImage(request.workflowText)
      .then(data => sendResponse({ data }))
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }
});

// Helper to retrieve saved settings from storage
async function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["apiUrl", "apiKey"], (items) => {
      resolve({
        apiUrl: items.apiUrl || DEFAULT_API_URL,
        apiKey: items.apiKey || "dev-bypass"
      });
    });
  });
}

// Check cache for valid entries
async function getCache(key) {
  return new Promise((resolve) => {
    chrome.storage.local.get([key], (result) => {
      const entry = result[key];
      if (entry && (Date.now() - entry.timestamp) < CACHE_TTL_MS) {
        resolve(entry.data);
      } else {
        resolve(null);
      }
    });
  });
}

// Write to cache
async function setCache(key, data) {
  const entry = {
    data: data,
    timestamp: Date.now()
  };
  return new Promise((resolve) => {
    chrome.storage.local.set({ [key]: entry }, () => {
      resolve();
    });
  });
}

async function handleFetchSummary(repo, prNumber) {
  const cacheKey = `summary_cache_${repo}_${prNumber}`;
  
  // 1. Try Cache
  const cached = await getCache(cacheKey);
  if (cached) {
    console.log("Serving PR summary from cache:", cacheKey);
    return cached;
  }

  // 2. Load API settings
  const settings = await getSettings();
  if (!settings.apiKey) {
    throw new Error("Missing API Key. Open Extension Options to configure.");
  }

  // 3. Make fetch call
  const url = `${settings.apiUrl}/api/pr/${prNumber}/summary?repo=${encodeURIComponent(repo)}`;
  console.log("Fetching summary from API URL:", url);
  
  const res = await fetch(url, {
    method: "GET",
    headers: {
      "X-API-Key": settings.apiKey,
      "Accept": "application/json"
    }
  });

  if (res.status === 401) {
    throw new Error("Unauthorized access. Verify API Key settings.");
  }
  if (res.status === 404) {
    throw new Error("PR has not been analyzed yet. Run analysis via Jenkins or Github first.");
  }
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Server returned error (${res.status}): ${errorText || res.statusText}`);
  }

  const data = await res.json();
  
  // 4. Update Cache
  await setCache(cacheKey, data);
  
  // 5. Update Badge Color on Icon based on severity
  updateIconBadge(data.workflow_impact?.severity);

  return data;
}

async function handleFetchChangelog(repo, prNumber) {
  const cacheKey = `changelog_cache_${repo}_${prNumber}`;
  
  // 1. Try Cache
  const cached = await getCache(cacheKey);
  if (cached) {
    console.log("Serving changelog from cache:", cacheKey);
    return cached;
  }

  // 2. Load API settings
  const settings = await getSettings();
  if (!settings.apiKey) {
    throw new Error("Missing API Key. Open Extension Options to configure.");
  }

  // 3. Make fetch call
  const url = `${settings.apiUrl}/api/pr/${prNumber}/changelog-preview?repo=${encodeURIComponent(repo)}`;
  const res = await fetch(url, {
    method: "GET",
    headers: {
      "X-API-Key": settings.apiKey,
      "Accept": "application/json"
    }
  });

  if (res.status === 401) {
    throw new Error("Unauthorized access. Verify API Key settings.");
  }
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Server returned error (${res.status}): ${errorText || res.statusText}`);
  }

  const data = await res.json();
  
  // 4. Update Cache
  await setCache(cacheKey, data);
  
  return data;
}

async function handleFetchWeeklyChanges() {
  const settings = await getSettings();
  if (!settings.apiKey) {
    throw new Error("Missing API Key. Open Extension Options to configure.");
  }

  const url = `${settings.apiUrl}/api/changes/weekly`;
  console.log("Fetching weekly changes from backend:", url);
  
  const res = await fetch(url, {
    method: "GET",
    headers: {
      "X-API-Key": settings.apiKey,
      "Accept": "application/json"
    }
  });

  if (res.status === 401) {
    throw new Error("Unauthorized access. Verify API Key settings.");
  }
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Server returned error (${res.status}): ${errorText || res.statusText}`);
  }

  const data = await res.json();
  return data;
}

async function handleGenerateWorkflowImage(workflowText) {
  const settings = await getSettings();
  if (!settings.apiKey) {
    throw new Error("Missing API Key. Open Extension Options to configure.");
  }

  const url = `${settings.apiUrl}/api/workflow/diagram`;
  console.log("Generating workflow diagram from backend:", url);
  
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": settings.apiKey
    },
    body: JSON.stringify({ workflow_text: workflowText })
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Diagram generator returned error (${res.status}): ${errorText || res.statusText}`);
  }

  const data = await res.json();
  return data.image_url;
}

// Helper to update Extension Badge Color based on workflow change severity
function updateIconBadge(severity) {
  if (!chrome.action) return;

  if (severity === "major") {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#f85149" }); // Red
  } else if (severity === "minor") {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#d29922" }); // Yellow/Amber
  } else {
    chrome.action.setBadgeText({ text: "" }); // Clear badge
  }
}

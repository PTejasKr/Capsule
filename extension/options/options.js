document.addEventListener("DOMContentLoaded", () => {
  const inputApiUrl = document.getElementById("input-api-url");
  const inputApiKey = document.getElementById("input-api-key");
  const btnSave = document.getElementById("btn-save");
  const btnTest = document.getElementById("btn-test");
  const statusBox = document.getElementById("status-box");

  // Load currently saved settings
  chrome.storage.local.get(["apiUrl", "apiKey"], (items) => {
    inputApiUrl.value = items.apiUrl || "http://localhost:8000";
    inputApiKey.value = items.apiKey || "";
  });

  // Save click handler
  btnSave.addEventListener("click", () => {
    const url = inputApiUrl.value.trim().replace(/\/$/, ""); // Strip trailing slash
    const key = inputApiKey.value.trim();

    if (!url) {
      showStatus("Server API URL is required", "error");
      return;
    }

    chrome.storage.local.set({ apiUrl: url, apiKey: key }, () => {
      showStatus("Settings successfully saved!", "success");
    });
  });

  // Test Connection handler
  btnTest.addEventListener("click", async () => {
    const url = inputApiUrl.value.trim().replace(/\/$/, "");
    const key = inputApiKey.value.trim();

    if (!url) {
      showStatus("Provide a Server URL to test", "error");
      return;
    }

    showStatus("Testing server connection...", "success");

    try {
      const response = await fetch(`${url}/api/health`, {
        method: "GET",
        headers: {
          "Accept": "application/json"
        }
      });
      
      if (response.ok) {
        showStatus("Connection successful! Backend is online.", "success");
      } else {
        showStatus(`Server responded with code ${response.status}`, "error");
      }
    } catch (e) {
      showStatus(`Connection failed: Check if Server is running at ${url}`, "error");
    }
  });

  function showStatus(msg, type) {
    statusBox.textContent = msg;
    statusBox.className = "status-message"; // Reset
    
    if (type === "success") {
      statusBox.classList.add("status-success");
    } else {
      statusBox.classList.add("status-error");
    }
    
    statusBox.style.display = "block";
    
    setTimeout(() => {
      statusBox.style.display = "none";
    }, 4000);
  }
});

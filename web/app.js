const state = {
  devices: [],
  realDevices: [],
  artifacts: [],
  history: [],
  lastTroubleshooting: [],
  lastSystemDetails: {},
  audioContext: null,
};

const nodes = {
  statusPills: document.getElementById("status-pills"),
  deviceList: document.getElementById("device-list"),
  keyDeviceSelect: document.getElementById("key-device-select"),
  keyOutput: document.getElementById("key-output"),
  installDeviceSelect: document.getElementById("install-device-select"),
  artifactSelect: document.getElementById("artifact-select"),
  systemInfo: document.getElementById("system-info"),
  releaseResults: document.getElementById("release-results"),
  sourceInput: document.querySelector('#source-form input[name="source"]'),
  artifactList: document.getElementById("artifact-list"),
  installOutput: document.getElementById("install-output"),
  troubleshooting: document.getElementById("troubleshooting"),
  activityLog: document.getElementById("activity-log"),
  toast: document.getElementById("toast"),
  dropzone: document.getElementById("dropzone"),
  uploadInput: document.getElementById("upload-input"),
  pickFileButton: document.getElementById("pick-file-button"),
  confettiCanvas: document.getElementById("confetti-canvas"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });
  const rawText = await response.text();
  let payload = null;
  try {
    payload = rawText ? JSON.parse(rawText) : {};
  } catch {
    payload = {
      ok: false,
      message: rawText || `Unexpected ${response.status} response from the dashboard.`,
      troubleshooting: [
        {
          title: "The dashboard returned a non-JSON error",
          cause: "The frontend expected structured JSON, but the server returned plain text instead.",
          steps: [
            "Retry the action once after the page finishes reloading.",
            "If it happens again, look at the step log card and the terminal output together.",
            "Keep the raw error text visible before trying a different workaround.",
          ],
        },
      ],
      raw_text: rawText,
      stage: "server",
    };
  }
  if (!response.ok || payload.ok === false) {
    const error = new Error(payload.message || "Request failed.");
    error.payload = payload;
    throw error;
  }
  return payload;
}

function toast(message, tone = "info") {
  nodes.toast.textContent = message;
  nodes.toast.className = `toast show ${tone}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    nodes.toast.className = "toast";
  }, 3200);
}

function summarizeMessage(message, fallback = "Something glitched.") {
  if (!message) return fallback;
  const singleLine = String(message).split("\n").filter(Boolean)[0] || fallback;
  return singleLine.length > 150 ? `${singleLine.slice(0, 147)}...` : singleLine;
}

function html(strings, ...values) {
  return strings.reduce((acc, chunk, index) => acc + chunk + (values[index] ?? ""), "");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatBytes(value) {
  if (!value && value !== 0) return "unknown size";
  const units = ["B", "KB", "MB", "GB"];
  let index = 0;
  let size = value;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value) {
  return new Date(value).toLocaleString();
}

function isRealTv(device) {
  const host = device?.deviceinfo?.ip || device?.deviceinfo?.host;
  return !(device?.name === "emulator" || host === "127.0.0.1");
}

function setTroubleshooting(items = []) {
  state.lastTroubleshooting = items;
  if (!items.length) {
    nodes.troubleshooting.innerHTML = `<div class="trouble-card"><strong>Nothing yelling yet.</strong><p>When the CLI returns a recognizable error, the likely cause and recovery steps appear here.</p></div>`;
    return;
  }
  nodes.troubleshooting.innerHTML = items
    .map(
      (item) => html`
        <div class="trouble-card">
          <strong>${escapeHtml(item.title)}</strong>
          <p>${escapeHtml(item.cause)}</p>
          <ul>${item.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
        </div>
      `
    )
    .join("");
}

function fallbackTroubleshooting(message) {
  return [
    {
      title: "The dashboard hit an unexpected error",
      cause: message || "The server did not return a normal structured error payload.",
      steps: [
        "Retry once after the page settles.",
        "If the same error repeats, read the step log card directly below the action you triggered.",
        "Keep the exact message and avoid changing multiple things at once.",
      ],
    },
  ];
}

function renderStatus(cli) {
  const pills = [
    { label: `Python ${state.pythonVersion || "?"}`, tone: "ok" },
    { label: `Node ${cli?.node?.stdout || "missing"}`, tone: cli?.node?.returncode === 0 ? "ok" : "bad" },
    { label: `npm ${cli?.npm?.stdout || "missing"}`, tone: cli?.npm?.returncode === 0 ? "ok" : "bad" },
    { label: `webOS CLI ${cli?.ares?.stdout || "missing"}`, tone: cli?.ares?.returncode === 0 ? "ok" : "bad" },
    { label: `${state.realDevices.length} TV${state.realDevices.length === 1 ? "" : "s"}`, tone: state.realDevices.length ? "ok" : "warn" },
    { label: `${state.artifacts.length} package${state.artifacts.length === 1 ? "" : "s"}`, tone: state.artifacts.length ? "ok" : "warn" },
  ];
  nodes.statusPills.innerHTML = pills.map((pill) => `<span class="pill ${pill.tone}">${escapeHtml(pill.label)}</span>`).join("");
}

function renderDevices() {
  const deviceOptions = state.realDevices
    .map((device) => `<option value="${escapeHtml(device.name)}">${escapeHtml(device.name)}${device.default ? " (default)" : ""}</option>`)
    .join("");
  nodes.keyDeviceSelect.innerHTML = deviceOptions || `<option value="">No TV saved yet</option>`;
  nodes.installDeviceSelect.innerHTML = deviceOptions || `<option value="">No TV saved yet</option>`;

  if (!state.devices.length) {
    nodes.deviceList.innerHTML = `<div class="device-card"><strong>No TVs saved yet.</strong><p>Add your LG TV using its current IP address, port 9922, and username prisoner.</p></div>`;
    return;
  }

  nodes.deviceList.innerHTML = state.devices
    .map((device) => {
      const host = device.deviceinfo?.ip || device.deviceinfo?.host || "unknown";
      const port = device.deviceinfo?.port || "9922";
      const user = device.deviceinfo?.user || device.deviceinfo?.username || "prisoner";
      const desc = device.details?.description || "LG webOS TV";
      const keyName = device.details?.privatekey || "";
      const passphraseSaved = Boolean(device.details?.passphrase);
      return html`
        <div class="device-card">
          <strong>${escapeHtml(device.name)} ${device.default ? "⭐" : ""} ${isRealTv(device) ? "" : "🧪"}</strong>
          <div class="device-meta">
            <span>${escapeHtml(user)}@${escapeHtml(host)}:${escapeHtml(port)}</span>
            <span>${escapeHtml(desc)}</span>
          </div>
          ${
            isRealTv(device)
              ? html`
                  <div class="device-meta auth-meta">
                    <span class="${keyName ? "auth-ok" : "auth-missing"}">${escapeHtml(keyName ? `SSH key: ${keyName}` : "SSH key missing")}</span>
                    <span class="${passphraseSaved ? "auth-ok" : "auth-missing"}">${escapeHtml(passphraseSaved ? "Passphrase saved" : "Passphrase missing")}</span>
                  </div>
                `
              : ""
          }
          ${isRealTv(device) ? "" : `<p class="micro-note">Built-in emulator entry. It is useful for simulator work, not real LG TV sideloading.</p>`}
          <div class="device-actions">
            <button type="button" class="secondary" data-action="make-default" data-device="${escapeHtml(device.name)}">Make default</button>
            <button type="button" class="secondary" data-action="delete-device" data-device="${escapeHtml(device.name)}">Remove</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderArtifacts() {
  const options = state.artifacts
    .map((artifact) => {
      const labelParts = [artifact.filename];
      if (artifact.app_id) labelParts.push(artifact.app_id);
      return `<option value="${escapeHtml(artifact.id)}">${escapeHtml(labelParts.join(" • "))}</option>`;
    })
    .join("");
  nodes.artifactSelect.innerHTML = options || `<option value="">No package loaded yet</option>`;

  if (!state.artifacts.length) {
    nodes.artifactList.innerHTML = `<div class="artifact-card"><strong>No packages yet.</strong><p>Upload an .ipk, upload a zip that contains a webOS app, or resolve a GitHub release.</p></div>`;
    return;
  }

  nodes.artifactList.innerHTML = state.artifacts
    .map(
      (artifact) => html`
        <div class="artifact-card">
          <strong>${escapeHtml(artifact.filename)}</strong>
          <div class="artifact-meta">
            <span>${escapeHtml(artifact.app_id || "app id unknown")}</span>
            <span>${escapeHtml(artifact.version || "version ?")}</span>
            <span>${escapeHtml(formatBytes(artifact.size))}</span>
          </div>
          <p>${escapeHtml(artifact.source_label)}</p>
          ${
            artifact.warnings?.length
              ? `<p class="micro-note">${artifact.warnings.map((item) => escapeHtml(item)).join(" • ")}</p>`
              : ""
          }
        </div>
      `
    )
    .join("");
}

function renderHistory() {
  if (!state.history.length) {
    nodes.activityLog.innerHTML = `<div class="history-item"><strong>No moves yet.</strong><p>Your install, link, and download events show up here.</p></div>`;
    return;
  }

  nodes.activityLog.innerHTML = state.history
    .map(
      (entry) => html`
        <div class="history-item ${escapeHtml(entry.status)}">
          <strong>${escapeHtml(entry.title)}</strong>
          <p>${escapeHtml(entry.summary)}</p>
          <div class="artifact-meta">
            <span>${escapeHtml(formatDate(entry.created_at))}</span>
          </div>
        </div>
      `
    )
    .join("");
}

function renderSystemInfo(details = {}) {
  const entries = Object.entries(details);
  if (!entries.length) {
    nodes.systemInfo.innerHTML = `<div class="info-chip"><span>Waiting</span>Link a TV and the system details land here.</div>`;
    return;
  }

  nodes.systemInfo.innerHTML = entries
    .slice(0, 6)
    .map(
      ([key, value]) => html`
        <div class="info-chip">
          <span>${escapeHtml(key)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `
    )
    .join("");
}

function renderReleaseResults(resolved) {
  const assets = resolved?.assets || [];
  const advisoryCard = resolved?.advisory
    ? html`
        <div class="release-card release-advisory">
          <strong>What I found</strong>
          <p>${escapeHtml(resolved.advisory)}</p>
          ${
            resolved?.help_steps?.length
              ? `<ul class="note-list">${resolved.help_steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul>`
              : ""
          }
        </div>
      `
    : "";

  if (!assets.length) {
    nodes.releaseResults.innerHTML =
      advisoryCard ||
      `<div class="release-card"><strong>No .ipk assets.</strong><p>Try the specific LG/webOS client repo or a direct .ipk URL.</p></div>`;
    return;
  }

  nodes.releaseResults.innerHTML =
    advisoryCard +
    assets
      .map(
        (asset) => html`
        <div class="release-card">
          <strong>${escapeHtml(asset.name)}</strong>
          <div class="release-meta">
            <span>${escapeHtml(asset.repo || resolved.repo || resolved.owner || "release source")}</span>
            <span>${escapeHtml(asset.tag_name || resolved.tag_name || resolved.release_name || "latest release")}</span>
            <span>${escapeHtml(formatBytes(asset.size))}</span>
          </div>
          <button type="button" class="download-button" data-action="download-asset" data-url="${escapeHtml(asset.download_url)}">
            ⬇️ Download into dashboard
          </button>
        </div>
      `
      )
      .join("");
}

function renderInstallOutput(result) {
  renderStepFeed(
    nodes.installOutput,
    result?.steps,
    "No install run yet.",
    "Pick a TV and package, then install. Verified installs trigger confetti and a success sound.",
  );
}

function renderStepFeed(container, steps, emptyTitle, emptyBody) {
  if (!steps?.length) {
    container.innerHTML = `<div class="step-card"><strong>${escapeHtml(emptyTitle)}</strong><p>${escapeHtml(emptyBody)}</p></div>`;
    return;
  }

  container.innerHTML = steps
    .map(
      (step) => html`
        <div class="step-card ${step.ok ? "ok" : "bad"}">
          <strong>${escapeHtml(step.label)} ${step.ok ? "✅" : "⚠️"}</strong>
          <p>${escapeHtml(step.command || "webOS CLI step")}</p>
          <pre>${escapeHtml(step.combined || step.stdout || "No CLI output returned.")}</pre>
        </div>
      `
    )
    .join("");
}

async function refreshDashboard() {
  const payload = await api("/api/status");
  state.devices = payload.devices || [];
  state.realDevices = state.devices.filter(isRealTv);
  state.artifacts = payload.artifacts || [];
  state.history = payload.history || [];
  state.pythonVersion = payload.python_version;
  renderStatus(payload.cli);
  renderDevices();
  renderArtifacts();
  renderHistory();
  renderSystemInfo(state.lastSystemDetails);
  setTroubleshooting(state.lastTroubleshooting);
}

async function submitJson(path, body) {
  return api(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

async function onDeviceSubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    name: form.get("name"),
    host: form.get("host"),
    port: Number(form.get("port")),
    username: form.get("username"),
    description: form.get("description"),
    set_default: form.get("set_default") === "on",
  };
  try {
    await submitJson("/api/devices", payload);
    await refreshDashboard();
    toast("TV saved. Next move: hit Key Server on the TV and link the passphrase. 📺");
  } catch (error) {
    handleError(error);
  }
}

async function onKeySubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const deviceName = form.get("device_name");
  const passphrase = String(form.get("passphrase") || "").trim().toUpperCase();
  try {
    const payload = await submitJson(`/api/devices/${encodeURIComponent(deviceName)}/key`, { passphrase });
    state.lastSystemDetails = payload.system_details || {};
    renderSystemInfo(payload.system_details);
    renderStepFeed(
      nodes.keyOutput,
      payload.steps,
      "Waiting for a key link attempt.",
      "Run Step 2 and the key exchange log will appear here.",
    );
    setTroubleshooting([]);
    await refreshDashboard();
    toast("TV linked. The dashboard can talk to your LG now. ⚡", "success");
  } catch (error) {
    handleError(error);
    await refreshDashboard();
  }
}

async function onSourceSubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await resolveSourceValue(form.get("source"));
}

async function resolveSourceValue(source) {
  try {
    const payload = await submitJson("/api/sources/resolve", { source });
    renderReleaseResults(payload.resolved);
    setTroubleshooting([]);
    if (payload.resolved.assets?.length) {
      toast("Installable assets found. Pick one and pull it into the dashboard. 🛰️", "success");
    } else {
      toast(payload.resolved.advisory || "No .ipk asset was found. Read the explanation card.", "warn");
    }
  } catch (error) {
    handleError(error);
  }
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source_label", file.name);
  const payload = await api("/api/artifacts/upload", {
    method: "POST",
    body: formData,
  });
  state.artifacts = payload.artifacts || [];
  renderArtifacts();
  renderStatus({
    node: { returncode: 0, stdout: "" },
    npm: { returncode: 0, stdout: "" },
    ares: { returncode: 0, stdout: "" },
  });
  await refreshDashboard();
  toast("Package loaded into the install lane. 📦");
}

async function onInstallSubmit(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const payload = await submitJson("/api/install", {
      device_name: form.get("device_name"),
      artifact_id: form.get("artifact_id"),
      launch_after_install: form.get("launch_after_install") === "on",
    });
    renderInstallOutput(payload);
    setTroubleshooting(payload.troubleshooting || []);
    await refreshDashboard();
    if (payload.verified) {
      celebrate();
      toast(`Verified on ${payload.device_name}. TV time. 🎉`, "success");
    } else {
      toast("Install ran, but verification could not fully confirm the app id. Check the troubleshooting lane.", "warn");
    }
  } catch (error) {
    handleError(error);
  }
}

function handleError(error) {
  const payload = error.payload || {};
  setTroubleshooting(payload.troubleshooting?.length ? payload.troubleshooting : fallbackTroubleshooting(payload.message || error.message));
  if (payload.stage === "key-link") {
    renderStepFeed(
      nodes.keyOutput,
      payload.steps,
      "Waiting for a key link attempt.",
      "Run Step 2 and the key exchange log will appear here.",
    );
  }
  if (payload.command || payload.stdout || payload.stderr) {
    renderInstallOutput({
      steps: [
        {
          label: "CLI error",
          ok: false,
          command: payload.command || "webOS CLI",
          combined: payload.message || payload.stderr || payload.stdout,
        },
      ],
    });
  } else if (payload.steps?.length) {
    renderInstallOutput({ steps: payload.steps });
  }
  toast(summarizeMessage(payload.message || error.message, "Something glitched. Check troubleshooting."), "bad");
}

async function handleActionClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const { action } = button.dataset;

  try {
    if (action === "download-asset") {
      await submitJson("/api/sources/download", { url: button.dataset.url });
      await refreshDashboard();
      toast("Release asset downloaded into the package rack. ⬇️");
      return;
    }

    if (action === "preset-source") {
      nodes.sourceInput.value = button.dataset.source;
      await resolveSourceValue(button.dataset.source);
      return;
    }

    if (action === "focus-source") {
      nodes.sourceInput.focus();
      nodes.sourceInput.select();
      toast("Paste any GitHub repo, release page, org page, or direct .ipk URL here. ✍️");
      return;
    }

    if (action === "make-default") {
      await submitJson("/api/devices/default", { name: button.dataset.device });
      await refreshDashboard();
      toast("Default TV updated. ⭐");
      return;
    }

    if (action === "delete-device") {
      await api(`/api/devices/${encodeURIComponent(button.dataset.device)}`, { method: "DELETE" });
      await refreshDashboard();
      toast("TV removed from the device list.");
    }
  } catch (error) {
    handleError(error);
  }
}

function initDropzone() {
  ["dragenter", "dragover"].forEach((name) => {
    nodes.dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      nodes.dropzone.classList.add("dragging");
    });
  });

  ["dragleave", "drop"].forEach((name) => {
    nodes.dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      nodes.dropzone.classList.remove("dragging");
    });
  });

  nodes.dropzone.addEventListener("drop", async (event) => {
    const [file] = event.dataTransfer.files;
    if (!file) return;
    try {
      await uploadFile(file);
    } catch (error) {
      handleError(error);
    }
  });

  nodes.pickFileButton.addEventListener("click", () => nodes.uploadInput.click());
  nodes.uploadInput.addEventListener("change", async (event) => {
    const [file] = event.target.files;
    if (!file) return;
    try {
      await uploadFile(file);
    } catch (error) {
      handleError(error);
    } finally {
      event.target.value = "";
    }
  });
}

function celebrate() {
  playSuccessSound();
  burstConfetti();
}

function playSuccessSound() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  state.audioContext = state.audioContext || new AudioContextClass();
  const ctx = state.audioContext;
  const now = ctx.currentTime;
  [523.25, 659.25, 783.99].forEach((frequency, index) => {
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = "triangle";
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.14, now + 0.02 + index * 0.06);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.25 + index * 0.06);
    oscillator.connect(gain).connect(ctx.destination);
    oscillator.start(now + index * 0.06);
    oscillator.stop(now + 0.32 + index * 0.06);
  });
}

function burstConfetti() {
  const canvas = nodes.confettiCanvas;
  const context = canvas.getContext("2d");
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  const colors = ["#57f6ff", "#ff445f", "#c4ff3d", "#ffb347", "#ffffff"];
  const particles = Array.from({ length: 180 }, () => ({
    x: window.innerWidth * (0.3 + Math.random() * 0.4),
    y: window.innerHeight * 0.2,
    vx: (Math.random() - 0.5) * 8,
    vy: Math.random() * -8 - 2,
    size: Math.random() * 8 + 4,
    color: colors[Math.floor(Math.random() * colors.length)],
    life: 1,
    tilt: (Math.random() - 0.5) * 10,
  }));

  function frame() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    let alive = 0;
    particles.forEach((particle) => {
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.vy += 0.18;
      particle.life -= 0.012;
      if (particle.life <= 0) return;
      alive += 1;
      context.globalAlpha = particle.life;
      context.fillStyle = particle.color;
      context.fillRect(particle.x, particle.y, particle.size, particle.size * 0.6 + particle.tilt);
    });
    context.globalAlpha = 1;
    if (alive > 0) requestAnimationFrame(frame);
    else context.clearRect(0, 0, canvas.width, canvas.height);
  }

  requestAnimationFrame(frame);
}

function bindForms() {
  document.getElementById("device-form").addEventListener("submit", onDeviceSubmit);
  document.getElementById("key-form").addEventListener("submit", onKeySubmit);
  document.getElementById("source-form").addEventListener("submit", onSourceSubmit);
  document.getElementById("install-form").addEventListener("submit", onInstallSubmit);
  document.body.addEventListener("click", handleActionClick);
}

window.addEventListener("resize", () => {
  nodes.confettiCanvas.width = window.innerWidth;
  nodes.confettiCanvas.height = window.innerHeight;
});

bindForms();
initDropzone();
refreshDashboard().catch(handleError);

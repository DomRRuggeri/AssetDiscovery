const state = {
    assets: [],
    filteredAssets: [],
    sortKey: "Hostname",
    sortDirection: "asc"
};

const SNAPSHOT_URL = "../output/asset-snapshot.json";

const elements = {
    fileInput: document.getElementById("fileInput"),
    assetTableBody: document.getElementById("assetTableBody"),
    tableMeta: document.getElementById("tableMeta"),
    statusFilter: document.getElementById("statusFilter"),
    environmentFilter: document.getElementById("environmentFilter"),
    searchInput: document.getElementById("searchInput"),
    exportButton: document.getElementById("exportButton"),
    sortButtons: document.querySelectorAll(".sort-button"),
    metricAssets: document.getElementById("metricAssets"),
    metricHostname: document.getElementById("metricHostname"),
    metricOwner: document.getElementById("metricOwner"),
    metricActive: document.getElementById("metricActive")
};

elements.fileInput.addEventListener("change", async (event) => {
    const [file] = event.target.files;
    if (!file) {
        return;
    }

    const text = await file.text();
    try {
        const assets = JSON.parse(text);
        loadAssets(assets, file.name);
    }
    catch (error) {
        window.alert("The selected file is not valid JSON.");
        console.error(error);
    }
});

elements.searchInput.addEventListener("input", applyFilters);
elements.statusFilter.addEventListener("change", applyFilters);
elements.environmentFilter.addEventListener("change", applyFilters);
elements.exportButton.addEventListener("click", exportFilteredCsv);
elements.sortButtons.forEach((button) => {
    button.addEventListener("click", () => {
        const sortKey = button.dataset.sortKey;
        if (state.sortKey === sortKey) {
            state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
        }
        else {
            state.sortKey = sortKey;
            state.sortDirection = "asc";
        }

        updateSortButtons();
        applyFilters();
    });
});

loadDefaultSnapshot();
updateSortButtons();

function loadAssets(rawAssets, sourceLabel) {
    const normalized = Array.isArray(rawAssets) ? rawAssets.map(normalizeAsset) : [];
    state.assets = normalized;
    elements.searchInput.value = "";
    elements.statusFilter.value = "";
    elements.environmentFilter.value = "";
    populateFilters(normalized);
    applyFilters();
    elements.tableMeta.textContent = `${normalized.length} assets loaded from ${sourceLabel}.`;
}

function normalizeAsset(asset) {
    return {
        AssetId: asset.AssetId ?? "",
        Hostname: asset.Hostname ?? "",
        IpAddress: asset.IpAddress ?? "",
        MacAddress: asset.MacAddress ?? "",
        MacVendor: asset.MacVendor ?? "",
        Source: asset.Source ?? "",
        AzureVerified: Boolean(asset.AzureVerified),
        Status: asset.Status ?? "active",
        LastSeen: asset.LastSeen ?? "",
        FirstSeen: asset.FirstSeen ?? "",
        OperatingSystem: asset.OperatingSystem ?? "",
        Owner: asset.Owner ?? "",
        Environment: asset.Environment ?? "",
        Notes: asset.Notes ?? ""
    };
}

function populateFilters(assets) {
    const statuses = [...new Set(assets.map((asset) => asset.Status).filter(Boolean))].sort();
    const environments = [...new Set(assets.map((asset) => asset.Environment).filter(Boolean))].sort();

    elements.statusFilter.innerHTML = '<option value="">All statuses</option>';
    elements.environmentFilter.innerHTML = '<option value="">All environments</option>';

    for (const status of statuses) {
        const option = document.createElement("option");
        option.value = status;
        option.textContent = status;
        elements.statusFilter.appendChild(option);
    }

    for (const environment of environments) {
        const option = document.createElement("option");
        option.value = environment;
        option.textContent = environment;
        elements.environmentFilter.appendChild(option);
    }
}

function applyFilters() {
    const search = elements.searchInput.value.trim().toLowerCase();
    const status = elements.statusFilter.value;
    const environment = elements.environmentFilter.value;

    state.filteredAssets = state.assets.filter((asset) => {
        if (status && asset.Status !== status) {
            return false;
        }
        if (environment && asset.Environment !== environment) {
            return false;
        }

        if (!search) {
            return true;
        }

        const haystack = [
            asset.Hostname,
            asset.IpAddress,
            asset.MacAddress,
            asset.MacVendor,
            asset.Owner,
            asset.Environment,
            asset.Status,
            asset.Source,
            asset.AssetId,
            asset.OperatingSystem,
            asset.Notes
        ].join(" ").toLowerCase();

        return haystack.includes(search);
    });

    state.filteredAssets.sort(compareAssets);
    updateMetrics(state.filteredAssets);
    renderTable(state.filteredAssets);
    elements.exportButton.disabled = state.filteredAssets.length === 0;
}

function updateMetrics(assets) {
    elements.metricAssets.textContent = assets.length.toString();
    elements.metricHostname.textContent = assets.filter((asset) => asset.Hostname).length.toString();
    elements.metricOwner.textContent = assets.filter((asset) => asset.Owner).length.toString();
    elements.metricActive.textContent = assets.filter((asset) => (asset.Status || "").toLowerCase() === "active").length.toString();
}

function renderTable(assets) {
    elements.assetTableBody.innerHTML = "";

    if (assets.length === 0) {
        const row = document.createElement("tr");
        row.innerHTML = '<td colspan="10" class="empty-state">No assets match the current filters.</td>';
        elements.assetTableBody.appendChild(row);
        return;
    }

    for (const asset of assets) {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>${formatText(asset.Hostname)}</td>
            <td class="mono">${formatText(asset.IpAddress)}</td>
            <td class="mono">${formatText(asset.MacAddress)}</td>
            <td>${formatText(asset.MacVendor)}</td>
            <td>${formatText(asset.Owner)}</td>
            <td>${formatText(asset.Environment)}</td>
            <td>${formatVerification(asset.AzureVerified)}</td>
            <td><span class="pill">${formatText(asset.Status)}</span></td>
            <td>${formatDate(asset.LastSeen)}</td>
            <td class="mono">${formatText(asset.AssetId)}</td>
        `;
        row.addEventListener("click", () => {
            const url = new URL("./detail.html", window.location.href);
            url.searchParams.set("asset", asset.AssetId);
            window.location.href = url.toString();
        });
        elements.assetTableBody.appendChild(row);
    }
}

function formatText(value) {
    if (!value) {
        return '<span class="muted">n/a</span>';
    }

    return escapeHtml(String(value));
}

function formatDate(value) {
    if (!value) {
        return '<span class="muted">n/a</span>';
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return escapeHtml(String(value));
    }

    return escapeHtml(parsed.toLocaleString());
}

function formatVerification(value) {
    const checked = value ? "checked" : "";
    const label = value ? "Verified" : "Not Verified";
    return `<span class="checkbox-cell"><input type="checkbox" disabled ${checked}><span>${escapeHtml(label)}</span></span>`;
}

function exportFilteredCsv() {
    if (state.filteredAssets.length === 0) {
        return;
    }

    const headers = ["Hostname", "IpAddress", "MacAddress", "MacVendor", "Owner", "Environment", "Status", "LastSeen", "AssetId"];
    const rows = state.filteredAssets.map((asset) => headers.map((header) => csvEscape(asset[header])));
    const csv = [headers.join(","), ...rows.map((row) => row.join(","))].join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "filtered-assets.csv";
    link.click();
    URL.revokeObjectURL(url);
}

async function loadDefaultSnapshot() {
    try {
        const response = await fetch(SNAPSHOT_URL, { cache: "no-store" });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const assets = await response.json();
        loadAssets(assets, "asset-snapshot.json");
    }
    catch (error) {
        elements.tableMeta.textContent = "Auto-load unavailable. Use Load Local JSON if needed.";
        elements.assetTableBody.innerHTML = '<tr><td colspan="9" class="empty-state">Auto-load failed. Use Load Local JSON to open asset-snapshot.json.</td></tr>';
        console.error(error);
    }
}

function compareAssets(left, right) {
    const direction = state.sortDirection === "asc" ? 1 : -1;
    const leftValue = normalizeSortValue(left[state.sortKey], state.sortKey);
    const rightValue = normalizeSortValue(right[state.sortKey], state.sortKey);

    if (leftValue < rightValue) {
        return -1 * direction;
    }
    if (leftValue > rightValue) {
        return 1 * direction;
    }

    return String(left.AssetId || "").localeCompare(String(right.AssetId || "")) * direction;
}

function normalizeSortValue(value, key) {
    if (key === "AzureVerified") {
        return value ? 1 : 0;
    }

    if (!value) {
        return key === "LastSeen" ? 0 : "";
    }

    if (key === "LastSeen") {
        const timestamp = new Date(value).getTime();
        return Number.isNaN(timestamp) ? 0 : timestamp;
    }

    return String(value).toLowerCase();
}

function updateSortButtons() {
    elements.sortButtons.forEach((button) => {
        const isActive = button.dataset.sortKey === state.sortKey;
        button.dataset.active = isActive ? "true" : "false";
        button.dataset.direction = isActive ? state.sortDirection : "";
    });
}

function csvEscape(value) {
    const text = String(value ?? "");
    if (text.includes(",") || text.includes('"') || text.includes("\n")) {
        return `"${text.replaceAll('"', '""')}"`;
    }

    return text;
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

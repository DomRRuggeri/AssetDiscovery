const SNAPSHOT_URL = "../output/asset-snapshot.json";

const elements = {
    detailTitle: document.getElementById("detailTitle"),
    detailMeta: document.getElementById("detailMeta"),
    assetDetailGrid: document.getElementById("assetDetailGrid")
};

loadAssetDetail();

async function loadAssetDetail() {
    const assetId = new URLSearchParams(window.location.search).get("asset");
    if (!assetId) {
        elements.detailTitle.textContent = "Asset Not Specified";
        elements.detailMeta.textContent = "No asset ID was provided in the page URL.";
        elements.assetDetailGrid.innerHTML = '<div class="detail-empty">Return to the asset list and select a row.</div>';
        return;
    }

    try {
        const response = await fetch(SNAPSHOT_URL, { cache: "no-store" });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const assets = await response.json();
        const asset = Array.isArray(assets) ? assets.find((item) => item.AssetId === assetId) : null;
        if (!asset) {
            elements.detailTitle.textContent = "Asset Not Found";
            elements.detailMeta.textContent = `No asset with ID ${assetId} exists in the current snapshot.`;
            elements.assetDetailGrid.innerHTML = '<div class="detail-empty">Refresh the snapshot or return to the asset list.</div>';
            return;
        }

        renderAsset(asset);
    }
    catch (error) {
        elements.detailTitle.textContent = "Load Failed";
        elements.detailMeta.textContent = "The asset snapshot could not be loaded.";
        elements.assetDetailGrid.innerHTML = '<div class="detail-empty">Start the viewer with Start-Viewer.ps1 so the page can fetch the snapshot.</div>';
        console.error(error);
    }
}

function renderAsset(asset) {
    const title = asset.Hostname || asset.IpAddress || asset.AssetId;
    elements.detailTitle.textContent = title;
    elements.detailMeta.textContent = `Asset ID ${asset.AssetId}`;
    elements.assetDetailGrid.innerHTML = "";

    const fields = [
        ["Hostname", asset.Hostname],
        ["IP Address", asset.IpAddress],
        ["MAC Address", asset.MacAddress],
        ["MAC Vendor", asset.MacVendor],
        ["Owner", asset.Owner],
        ["Environment", asset.Environment],
        ["Azure Verified", asset.AzureVerified ? "Yes" : "No"],
        ["Status", asset.Status],
        ["Operating System", asset.OperatingSystem],
        ["Source", asset.Source],
        ["First Seen", formatDateValue(asset.FirstSeen)],
        ["Last Seen", formatDateValue(asset.LastSeen)],
        ["Asset ID", asset.AssetId],
        ["Notes", asset.Notes]
    ];

    for (const [label, value] of fields) {
        const card = document.createElement("article");
        card.className = "detail-card";
        card.innerHTML = `
            <span class="detail-label">${escapeHtml(label)}</span>
            <strong class="${label.includes('ID') || label.includes('IP') || label.includes('MAC') ? 'mono detail-value' : 'detail-value'}">${formatPlainText(value)}</strong>
        `;
        elements.assetDetailGrid.appendChild(card);
    }
}

function formatDateValue(value) {
    if (!value) {
        return "n/a";
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return String(value);
    }

    return parsed.toLocaleString();
}

function formatPlainText(value) {
    if (!value) {
        return '<span class="muted">n/a</span>';
    }

    return escapeHtml(String(value));
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

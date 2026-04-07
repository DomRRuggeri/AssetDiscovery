const README_URL = "../README.md";

const elements = {
    readmeStatus: document.getElementById("readmeStatus"),
    readmeContent: document.getElementById("readmeContent")
};

loadReadme();

async function loadReadme() {
    try {
        const response = await fetch(README_URL, { cache: "no-store" });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const markdown = await response.text();
        renderMarkdown(markdown);
        elements.readmeStatus.textContent = "README loaded from the project root.";
    }
    catch (error) {
        elements.readmeStatus.textContent = "Unable to load README.md from the project root.";
        elements.readmeContent.innerHTML = `<pre class="code-block">${escapeHtml(String(error))}</pre>`;
        console.error(error);
    }
}

function renderMarkdown(markdown) {
    const lines = markdown.replace(/\r\n/g, "\n").split("\n");
    const html = [];
    let paragraph = [];
    let listItems = [];
    let codeLines = [];
    let inCodeBlock = false;

    const flushParagraph = () => {
        if (paragraph.length === 0) {
            return;
        }

        html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
        paragraph = [];
    };

    const flushList = () => {
        if (listItems.length === 0) {
            return;
        }

        html.push(`<ul>${listItems.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
        listItems = [];
    };

    const flushCode = () => {
        if (codeLines.length === 0) {
            return;
        }

        html.push(`<pre class="code-block"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
    };

    for (const line of lines) {
        if (line.startsWith("```")) {
            flushParagraph();
            flushList();
            if (inCodeBlock) {
                flushCode();
                inCodeBlock = false;
            }
            else {
                inCodeBlock = true;
            }
            continue;
        }

        if (inCodeBlock) {
            codeLines.push(line);
            continue;
        }

        if (!line.trim()) {
            flushParagraph();
            flushList();
            continue;
        }

        const headingMatch = line.match(/^(#{1,3})\s+(.*)$/);
        if (headingMatch) {
            flushParagraph();
            flushList();
            const level = Math.min(headingMatch[1].length + 1, 4);
            html.push(`<h${level}>${renderInline(headingMatch[2])}</h${level}>`);
            continue;
        }

        const listMatch = line.match(/^\-\s+(.*)$/);
        if (listMatch) {
            flushParagraph();
            listItems.push(listMatch[1]);
            continue;
        }

        paragraph.push(line.trim());
    }

    flushParagraph();
    flushList();
    flushCode();

    elements.readmeContent.innerHTML = html.join("");
}

function renderInline(text) {
    let value = escapeHtml(text);
    value = value.replace(/`([^`]+)`/g, "<code>$1</code>");
    return value;
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

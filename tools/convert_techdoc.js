const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
        ShadingType, PageNumber, PageBreak } = require("docx");

const md = fs.readFileSync("docs/TECHNICAL.md", "utf-8");

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };
const headerShading = { fill: "2E75B6", type: ShadingType.CLEAR };

function headerCell(text, width) {
    return new TableCell({
        borders, width: { size: width, type: WidthType.DXA }, margins: cellMargins,
        shading: headerShading,
        children: [new Paragraph({ children: [new TextRun({ text, bold: true, font: "Arial", size: 20, color: "FFFFFF" })] })]
    });
}
function cell(text, width) {
    return new TableCell({
        borders, width: { size: width, type: WidthType.DXA }, margins: cellMargins,
        children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 20 })] })]
    });
}

function parseInline(text) {
    if (!text) return [new TextRun({ text: "", font: "Arial", size: 20 })];
    const runs = [];
    // Process bold **text**, code `code`
    const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);
    for (const part of parts) {
        if (part.startsWith("**") && part.endsWith("**")) {
            runs.push(new TextRun({ text: part.slice(2, -2), bold: true, font: "Arial", size: 20 }));
        } else if (part.startsWith("`") && part.endsWith("`")) {
            runs.push(new TextRun({ text: part.slice(1, -1), font: "Consolas", size: 19 }));
        } else {
            runs.push(new TextRun({ text: part, font: "Arial", size: 20 }));
        }
    }
    return runs;
}

const children = [];
const lines = md.split("\n");
let i = 0;
let inCodeBlock = false;
let codeLines = [];
let inTable = false;
let tableRows = [];
let tableColWidths = [];

while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.startsWith("```")) {
        if (inCodeBlock) {
            for (const cl of codeLines) {
                children.push(new Paragraph({
                    spacing: { before: 0, after: 0 },
                    children: [new TextRun({ text: cl || " ", font: "Consolas", size: 17 })]
                }));
            }
            children.push(new Paragraph({ spacing: { before: 0, after: 120 }, children: [] }));
            codeLines = [];
            inCodeBlock = false;
        } else {
            inCodeBlock = true;
        }
        i++; continue;
    }
    if (inCodeBlock) { codeLines.push(line); i++; continue; }

    // Separator
    if (line === "---") {
        children.push(new Paragraph({ children: [new PageBreak()] }));
        i++; continue;
    }

    // Table
    if (line.startsWith("|") && line.endsWith("|")) {
        const cells = line.split("|").slice(1, -1).map(c => c.trim());
        if (cells.every(c => /^[-:]+$/.test(c) || c === "")) { i++; continue; } // separator row
        if (!inTable) {
            tableRows = [];
            inTable = true;
            tableColWidths = cells.map(() => Math.floor(9360 / cells.length));
        }
        tableRows.push(cells);
        i++; continue;
    }
    if (inTable) {
        // Build table
        const headerCells = tableRows[0].map((c, idx) => headerCell(c, tableColWidths[idx]));
        const dataRows = tableRows.slice(1).map(row =>
            new TableRow({ children: row.map((c, idx) => cell(c, tableColWidths[idx])) })
        );
        children.push(new Table({
            width: { size: 9360, type: WidthType.DXA },
            columnWidths: tableColWidths,
            rows: [new TableRow({ children: headerCells }), ...dataRows],
        }));
        children.push(new Paragraph({ spacing: { before: 120, after: 120 }, children: [] }));
        inTable = false;
        tableRows = [];
        continue;
    }

    // Headings
    if (line.startsWith("## ")) {
        children.push(new Paragraph({
            heading: HeadingLevel.HEADING_2,
            spacing: { before: 240, after: 120 },
            children: [new TextRun({ text: line.slice(3), font: "Arial", size: 28, bold: true })]
        }));
    } else if (line.startsWith("### ")) {
        children.push(new Paragraph({
            heading: HeadingLevel.HEADING_3,
            spacing: { before: 180, after: 100 },
            children: [new TextRun({ text: line.slice(4), font: "Arial", size: 24, bold: true })]
        }));
    } else if (line.startsWith("# ")) {
        children.push(new Paragraph({
            heading: HeadingLevel.HEADING_1,
            spacing: { before: 360, after: 200 },
            children: [new TextRun({ text: line.slice(2), font: "Arial", size: 36, bold: true })]
        }));
    } else if (line.startsWith("- ")) {
        // List item
        children.push(new Paragraph({
            spacing: { before: 40, after: 40 },
            indent: { left: 360, hanging: 180 },
            children: [
                new TextRun({ text: "• ", font: "Arial", size: 20 }),
                ...parseInline(line.slice(2))
            ]
        }));
    } else if (line.trim() === "") {
        children.push(new Paragraph({ spacing: { before: 60, after: 60 }, children: [] }));
    } else {
        children.push(new Paragraph({
            spacing: { before: 40, after: 40 },
            children: parseInline(line)
        }));
    }
    i++;
}

// Handle unclosed table at end of file
if (inTable && tableRows.length > 0) {
    const headerCells = tableRows[0].map((c, idx) => headerCell(c, tableColWidths[idx]));
    const dataRows = tableRows.slice(1).map(row =>
        new TableRow({ children: row.map((c, idx) => cell(c, tableColWidths[idx])) })
    );
    children.push(new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: tableColWidths,
        rows: [new TableRow({ children: headerCells }), ...dataRows],
    }));
}

const doc = new Document({
    styles: {
        default: { document: { run: { font: "Arial", size: 20 } } },
        paragraphStyles: [
            { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 36, bold: true, font: "Arial" },
                paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
            { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 28, bold: true, font: "Arial" },
                paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
            { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 24, bold: true, font: "Arial" },
                paragraph: { spacing: { before: 180, after: 100 }, outlineLevel: 2 } },
        ]
    },
    sections: [{
        properties: {
            page: {
                size: { width: 11906, height: 16838 },
                margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
            }
        },
        headers: {
            default: new Header({ children: [new Paragraph({
                alignment: AlignmentType.RIGHT,
                children: [new TextRun({ text: "TradingAgents-AShare 技术文档", font: "Arial", size: 18, color: "888888" })]
            })] })
        },
        footers: {
            default: new Footer({ children: [new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({ text: "Page ", font: "Arial", size: 18 }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18 })]
            })] })
        },
        children,
    }],
});

Packer.toBuffer(doc).then(buf => {
    const out = "docs/TECHNICAL_v2.docx";
    fs.writeFileSync(out, buf);
    console.log("Done: " + out + " (" + (buf.length / 1024).toFixed(0) + " KB)");
});

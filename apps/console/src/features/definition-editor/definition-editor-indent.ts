interface DraftBodyIndentationEdit {
    readonly body: string;
    readonly selectionEnd: number;
    readonly selectionStart: number;
}

interface DraftBodyIndentationInput {
    readonly body: string;
    readonly selectionEnd: number;
    readonly selectionStart: number;
    readonly shouldOutdent: boolean;
}

const DRAFT_BODY_INDENT = "  ";

export function applyDraftBodyIndentation({
    body,
    selectionEnd,
    selectionStart,
    shouldOutdent,
}: DraftBodyIndentationInput): DraftBodyIndentationEdit {
    if (selectionStart === selectionEnd) {
        return shouldOutdent
            ? outdentDraftBodyLine(body, selectionStart)
            : insertDraftBodyIndent(body, selectionStart);
    }

    return shouldOutdent
        ? outdentDraftBodySelection({ body, selectionEnd, selectionStart })
        : indentDraftBodySelection({ body, selectionEnd, selectionStart });
}

function insertDraftBodyIndent(body: string, selectionStart: number): DraftBodyIndentationEdit {
    return {
        body: `${body.slice(0, selectionStart)}${DRAFT_BODY_INDENT}${body.slice(selectionStart)}`,
        selectionEnd: selectionStart + DRAFT_BODY_INDENT.length,
        selectionStart: selectionStart + DRAFT_BODY_INDENT.length,
    };
}

function lineStartForOffset(body: string, offset: number): number {
    return body.lastIndexOf("\n", Math.max(offset - 1, 0)) + 1;
}

function selectedLineRange({
    body,
    selectionEnd,
    selectionStart,
}: {
    readonly body: string;
    readonly selectionEnd: number;
    readonly selectionStart: number;
}): { readonly end: number; readonly start: number } {
    const start = lineStartForOffset(body, selectionStart);
    const adjustedSelectionEnd =
        selectionEnd > selectionStart && body.charAt(selectionEnd - 1) === "\n"
            ? selectionEnd - 1
            : selectionEnd;
    const nextLineBreak = body.indexOf("\n", adjustedSelectionEnd);
    return {
        end: nextLineBreak === -1 ? body.length : nextLineBreak,
        start,
    };
}

function indentDraftBodySelection({
    body,
    selectionEnd,
    selectionStart,
}: {
    readonly body: string;
    readonly selectionEnd: number;
    readonly selectionStart: number;
}): DraftBodyIndentationEdit {
    const range = selectedLineRange({ body, selectionEnd, selectionStart });
    const selectedBlock = body.slice(range.start, range.end);
    const lineCount = selectedBlock.length === 0 ? 1 : selectedBlock.split("\n").length;
    const indentedBlock = selectedBlock
        .split("\n")
        .map((line) => `${DRAFT_BODY_INDENT}${line}`)
        .join("\n");

    return {
        body: `${body.slice(0, range.start)}${indentedBlock}${body.slice(range.end)}`,
        selectionEnd: selectionEnd + DRAFT_BODY_INDENT.length * lineCount,
        selectionStart:
            selectionStart === range.start
                ? selectionStart
                : selectionStart + DRAFT_BODY_INDENT.length,
    };
}

function outdentDraftBodyLine(body: string, selectionStart: number): DraftBodyIndentationEdit {
    const lineStart = lineStartForOffset(body, selectionStart);
    const removableWidth = draftBodyOutdentWidth(body, lineStart);
    if (removableWidth === 0) {
        return { body, selectionEnd: selectionStart, selectionStart };
    }

    const nextSelectionStart = Math.max(selectionStart - removableWidth, lineStart);
    return {
        body: `${body.slice(0, lineStart)}${body.slice(lineStart + removableWidth)}`,
        selectionEnd: nextSelectionStart,
        selectionStart: nextSelectionStart,
    };
}

function outdentDraftBodySelection({
    body,
    selectionEnd,
    selectionStart,
}: {
    readonly body: string;
    readonly selectionEnd: number;
    readonly selectionStart: number;
}): DraftBodyIndentationEdit {
    const range = selectedLineRange({ body, selectionEnd, selectionStart });
    const lines = body.slice(range.start, range.end).split("\n");
    let removedBeforeStart = 0;
    let removedTotal = 0;
    let runningOffset = range.start;
    const outdentedLines = lines.map((line) => {
        const removableWidth = draftBodyOutdentWidth(line, 0);
        if (removableWidth > 0) {
            if (runningOffset < selectionStart) {
                removedBeforeStart += removableWidth;
            }
            removedTotal += removableWidth;
        }
        runningOffset += line.length + 1;
        return line.slice(removableWidth);
    });

    return {
        body: `${body.slice(0, range.start)}${outdentedLines.join("\n")}${body.slice(range.end)}`,
        selectionEnd: Math.max(selectionEnd - removedTotal, range.start),
        selectionStart: Math.max(selectionStart - removedBeforeStart, range.start),
    };
}

function draftBodyOutdentWidth(body: string, offset: number): number {
    if (body.startsWith(DRAFT_BODY_INDENT, offset)) {
        return DRAFT_BODY_INDENT.length;
    }

    if (body.charAt(offset) === "\t") {
        return 1;
    }

    return body.charAt(offset) === " " ? 1 : 0;
}

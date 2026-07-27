import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Allowlist for model-authored prose. Every field rendered through this
 * component was written by a provider, so the schema stays deliberately narrow:
 * text, emphasis, lists, links, tables, and code. No images, no raw HTML, no
 * attributes beyond what the elements below need.
 */
const SCHEMA = {
    ...defaultSchema,
    tagNames: [
        "p",
        "br",
        "strong",
        "em",
        "del",
        "a",
        "ul",
        "ol",
        "li",
        "code",
        "pre",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "hr",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    ],
    attributes: {
        a: ["href", "title"],
        th: ["align"],
        td: ["align"],
    },
    protocols: {
        ...defaultSchema.protocols,
        href: ["http", "https", "mailto"],
    },
};

export interface ProseProps {
    /** Markdown authored by a provider. Never trusted as HTML. */
    readonly children: string | null | undefined;
    readonly className?: string;
}

/**
 * Renders model-authored markdown. Result summaries, Result details, Member
 * updates, Activity summaries, plan text, and Operator messages all carry
 * markdown, so they all render through here rather than as raw strings.
 */
export function Prose({ children, className = "" }: ProseProps) {
    const source = children?.trim() ?? "";
    if (source === "") {
        return null;
    }
    return (
        <div className={`prose ${className}`.trim()}>
            <Markdown
                components={{
                    a: ({ children: linkChildren, href }) => (
                        <a
                            href={href}
                            rel="noreferrer noopener"
                            target="_blank"
                        >
                            {linkChildren}
                        </a>
                    ),
                }}
                rehypePlugins={[[rehypeSanitize, SCHEMA]]}
                remarkPlugins={[remarkGfm]}
            >
                {source}
            </Markdown>
        </div>
    );
}

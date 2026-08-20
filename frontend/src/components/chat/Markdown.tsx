import { Children, cloneElement, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CitationPill } from "@/components/chat/CitationPill";
import { CodeBlock } from "@/components/chat/CodeBlock";
import type { Source } from "@/types";

/**
 * Sentinel appended to a partial answer so the blinking caret lands inline at
 * the very end of the streamed text, whatever block it happens to end in.
 */
export const CARET_TOKEN = "⟦caret⟧";

const TOKEN_RE = /\[(\d+)\]|⟦caret⟧/g;

/** Flattens a react-markdown subtree back to its plain text. */
function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return extractText(node.props.children);
  return "";
}

/** Pulls "sql" out of the `language-sql` class react-markdown puts on <code>. */
function codeLanguage(node: ReactNode): string | undefined {
  const child = Children.toArray(node)[0];
  if (!isValidElement<{ className?: string }>(child)) return undefined;
  return child.props.className?.match(/language-(\w+)/)?.[1];
}

/**
 * Answers arrive as markdown with citations written inline as [1], [2], …
 * react-markdown hands those to us as plain text, so each text node is split
 * on the marker and the marker replaced with a clickable pill.
 */
function Caret() {
  return (
    <span
      aria-hidden
      className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[0.18em] rounded-full bg-hbl-green animate-caret"
    />
  );
}

function withTokens(
  children: ReactNode,
  renderPill: (index: number, key: string) => ReactNode,
): ReactNode {
  return Children.map(children, (child, childIdx) => {
    if (typeof child === "string") {
      const parts: ReactNode[] = [];
      let cursor = 0;
      let match: RegExpExecArray | null;
      TOKEN_RE.lastIndex = 0;

      while ((match = TOKEN_RE.exec(child)) !== null) {
        if (match.index > cursor) parts.push(child.slice(cursor, match.index));
        parts.push(
          match[1] === undefined ? (
            <Caret key={`caret-${childIdx}-${match.index}`} />
          ) : (
            renderPill(Number(match[1]), `${childIdx}-${match.index}`)
          ),
        );
        cursor = match.index + match[0].length;
      }

      if (parts.length === 0) return child;
      if (cursor < child.length) parts.push(child.slice(cursor));
      return <>{parts}</>;
    }

    // Recurse into inline elements such as <strong> and <em>.
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return cloneElement(child, undefined, withTokens(child.props.children, renderPill));
    }

    return child;
  });
}

export function Markdown({
  content,
  sources,
  activeSourceId,
  onCitationClick,
}: {
  content: string;
  sources: Source[];
  activeSourceId?: string | null;
  onCitationClick: (source: Source) => void;
}) {
  const byIndex = new Map(sources.map((s) => [s.index, s]));

  const renderPill = (index: number, key: string) => {
    const source = byIndex.get(index);
    if (!source) return `[${index}]`;
    return (
      <CitationPill
        key={key}
        index={index}
        title={`${source.title} — p.${source.page}`}
        active={activeSourceId === source.id}
        onClick={() => onCitationClick(source)}
      />
    );
  };

  const cite = (children: ReactNode) => withTokens(children, renderPill);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => (
          <h3 className="mb-2 mt-6 text-lg font-semibold leading-7 tracking-[-0.01em] text-hbl-primary first:mt-0">
            {cite(children)}
          </h3>
        ),
        h2: ({ children }) => (
          <h3 className="mb-2 mt-6 text-lg font-semibold leading-7 tracking-[-0.01em] text-hbl-primary first:mt-0">
            {cite(children)}
          </h3>
        ),
        h3: ({ children }) => (
          <h3 className="mb-2 mt-6 text-[17px] font-semibold leading-6 tracking-[-0.01em] text-hbl-primary first:mt-0">
            {cite(children)}
          </h3>
        ),
        h4: ({ children }) => (
          <h4 className="mb-2 mt-5 text-[15px] font-semibold leading-6 text-hbl-primary first:mt-0">
            {cite(children)}
          </h4>
        ),
        p: ({ children }) => (
          <p className="mb-4 text-[15px] leading-7 text-hbl-primary last:mb-0">{cite(children)}</p>
        ),
        ul: ({ children }) => (
          <ul className="mb-4 flex list-disc flex-col gap-2 pl-5 marker:text-hbl-tertiary last:mb-0">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-4 flex list-decimal flex-col gap-2 pl-5 marker:text-hbl-tertiary last:mb-0">
            {children}
          </ol>
        ),
        li: ({ children }) => (
          <li className="text-[15px] leading-7 text-hbl-primary">{cite(children)}</li>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-hbl-primary">{children}</strong>
        ),
        em: ({ children }) => <em className="italic">{children}</em>,
        a: ({ children, href }) => (
          <a href={href} className="text-hbl-green underline underline-offset-2 hover:opacity-80">
            {children}
          </a>
        ),
        blockquote: ({ children }) => (
          <blockquote className="mb-4 border-l-2 border-hbl-green/50 pl-4 text-[15px] italic leading-7 text-hbl-secondary">
            {children}
          </blockquote>
        ),
        hr: () => <hr className="my-6 border-border" />,
        code: ({ children }) => (
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[13px] text-hbl-primary">
            {children}
          </code>
        ),
        // `pre` owns the block-code case so the copy button has the raw text.
        pre: ({ children }) => {
          const language = codeLanguage(children);
          return <CodeBlock code={extractText(children).replace(/\n$/, "")} language={language} />;
        },
        /* Policy documents are full of tables. Rules are kept to horizontal
           dividers only — a full grid turns a comparison table into noise. */
        table: ({ children }) => (
          <div className="hbl-scroll mb-4 overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead>{children}</thead>,
        th: ({ children }) => (
          <th className="whitespace-nowrap border-b border-border pb-2 pr-6 text-[12px] font-medium text-hbl-secondary last:pr-0">
            {cite(children)}
          </th>
        ),
        td: ({ children }) => (
          <td className="border-b border-border/60 py-2.5 pr-6 align-top text-[14px] leading-6 text-hbl-primary last:pr-0">
            {cite(children)}
          </td>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

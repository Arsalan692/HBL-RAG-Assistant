import { ArrowUpRight, Plus } from "lucide-react";
import { HblMark } from "@/components/common/HblMark";
import type { DocumentSummary } from "@/lib/api";
import { cn } from "@/lib/utils";
import { primaryButtonCls } from "@/lib/variants";

/**
 * Openers built from the documents that are actually indexed.
 *
 * The previous list was written for the design mockup and included "What's the
 * FED rate on remittances?" — nothing in this corpus answers that, so the one
 * suggestion a new reader is most likely to click would have returned a
 * refusal and taught them the product does not work.
 *
 * These name a real document and ask an open question about it, which is the
 * only thing that can be promised without knowing what is inside. The largest
 * documents come first: more passages means more chance of a useful answer.
 */
function openers(documents: DocumentSummary[]): string[] {
  const seen = new Set<string>();
  return [...documents]
    .sort((a, b) => b.chunks - a.chunks)
    .filter((doc) => {
      // One per policy family — two editions of the same policy would
      // otherwise take two of the four slots.
      const key = doc.policyFamily || doc.id;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 4)
    .map((doc) => `What does the ${doc.title} cover?`);
}

export function EmptyState({
  onPick,
  documents,
  onOpenDocuments,
}: {
  onPick: (prompt: string) => void;
  /** null while the library is still loading, or if it could not be reached. */
  documents: DocumentSummary[] | null;
  onOpenDocuments: () => void;
}) {
  const suggestions = documents ? openers(documents) : [];
  const empty = documents !== null && documents.length === 0;

  return (
    <div className="flex min-h-full flex-col items-center justify-center px-6 py-16">
      <HblMark height={40} className="mb-7" />

      <h2 className="mb-2 text-center text-[28px] font-semibold leading-9 tracking-[-0.01em] text-hbl-primary">
        {empty ? "No documents yet" : "How can I help you today?"}
      </h2>
      <p className="mb-9 max-w-md text-center text-[15px] leading-6 text-hbl-secondary">
        {empty
          ? "Add a PDF and the assistant will be able to answer from it. Until then there is nothing for it to read."
          : "Ask anything about HBL policies, SOPs or compliance circulars. Every answer is grounded in the source document."}
      </p>

      {empty ? (
        <button type="button" onClick={onOpenDocuments} className={cn(primaryButtonCls(), "gap-1.5")}>
          <Plus size={16} />
          Add PDFs
        </button>
      ) : (
        <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onPick(s)}
              className={cn(
                "group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4 text-left",
                "shadow-[var(--hbl-shadow)] transition-all",
                "hover:-translate-y-px hover:border-hbl-green/45 hover:bg-accent/40",
              )}
            >
              <span className="text-sm leading-5 text-hbl-primary">{s}</span>
              <ArrowUpRight
                size={15}
                className="mt-0.5 shrink-0 text-hbl-tertiary transition-colors group-hover:text-hbl-green"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

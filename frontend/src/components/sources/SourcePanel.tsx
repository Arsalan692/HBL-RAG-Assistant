import { useEffect, useState } from "react";
import { Check, Copy, ExternalLink, FileText, X } from "lucide-react";
import { IconButton } from "@/components/common/IconButton";
import { cn } from "@/lib/utils";
import type { Source } from "@/types";

/**
 * One metadata row, or nothing.
 *
 * Not every document states every field — the corpus has no "department" at
 * all, and only two policies carry a circular number. The API returns an empty
 * string rather than inventing something plausible, so an empty row here means
 * "the document does not say", and printing a blank value would look like a
 * bug rather than an absence.
 */
function MetaRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className="shrink-0 text-[11px] uppercase tracking-[0.06em] text-hbl-tertiary">
        {label}
      </dt>
      <dd className="min-w-0 text-right text-[13px] font-medium leading-5 text-hbl-primary">
        {value}
      </dd>
    </div>
  );
}

export function SourcePanel({ source, onClose }: { source: Source; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  // Esc closes the panel, matching every other dismissible surface here.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function copyExcerpt() {
    try {
      await navigator.clipboard.writeText(source.excerpt);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard is unavailable over plain http on some hosts; fail quietly.
    }
  }

  return (
    <aside
      className="flex h-full w-[360px] shrink-0 animate-panel-in flex-col border-l border-border bg-sidebar"
      aria-label="Source document"
    >
      {/* Header */}
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
        <FileText size={15} className="shrink-0 text-hbl-green" />
        <h2 className="min-w-0 flex-1 truncate text-[13px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
          Source {source.index}
        </h2>
        <IconButton label="Close source panel" size="sm" onClick={onClose}>
          <X size={16} />
        </IconButton>
      </div>

      <div className="hbl-scroll min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <h3 className="text-[15px] font-semibold leading-6 tracking-[-0.01em] text-hbl-primary">
          {source.title}
        </h3>
        <p className="mt-0.5 text-xs leading-5 text-hbl-secondary">{source.section}</p>

        {/* Document preview.
            Phase 07 replaces this text rendering with the real rasterised page
            image, keeping the same highlight treatment over the chunk bounds. */}
        <div
          className={cn(
            "mt-4 rounded-xl border border-border bg-card p-4",
            "shadow-[var(--hbl-shadow)]",
          )}
        >
          <div className="mb-3 flex items-center justify-between border-b border-border pb-2">
            <span className="text-[10px] uppercase tracking-[0.06em] text-hbl-tertiary">
              Page {source.page}
            </span>
            <span className="text-[10px] font-medium tabular-nums text-hbl-green">
              {Math.round(source.relevance * 100)}% match
            </span>
          </div>

          <div className="space-y-2.5 text-[12.5px] leading-[22px]">
            {source.contextBefore && (
              <p className="text-hbl-tertiary">{source.contextBefore}</p>
            )}

            <p
              className={cn(
                "rounded-md border-l-2 px-2.5 py-2 text-hbl-primary",
                "bg-[var(--hbl-highlight)] border-l-[var(--hbl-highlight-edge)]",
              )}
            >
              {source.excerpt}
            </p>

            {source.contextAfter && <p className="text-hbl-tertiary">{source.contextAfter}</p>}
          </div>
        </div>

        {/* Metadata */}
        <dl className="mt-5 divide-y divide-border rounded-xl border border-border bg-card px-3.5 py-1">
          <MetaRow label="Document" value={source.title} />
          <MetaRow label="Department" value={source.department} />
          <MetaRow label="Effective" value={source.effectiveDate} />
          <MetaRow label="Version" value={source.version} />
          <MetaRow label="Page" value={String(source.page)} />
        </dl>
      </div>

      {/* Actions */}
      <div className="flex shrink-0 gap-2 border-t border-border p-3">
        <button
          type="button"
          className={cn(
            "flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-hbl-solid px-3 py-2",
            "text-[13px] font-medium text-hbl-on-solid outline-none",
            "transition-all duration-180 ease-spring hover:bg-hbl-solid-hover active:scale-97",
            "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
          )}
        >
          <ExternalLink size={14} />
          Open full document
        </button>
        <button
          type="button"
          onClick={copyExcerpt}
          className={cn(
            "flex items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2",
            "text-[13px] font-medium text-hbl-primary transition-colors",
            "hover:bg-black/3 dark:hover:bg-white/5",
          )}
        >
          {copied ? <Check size={14} className="text-hbl-green" /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy excerpt"}
        </button>
      </div>
    </aside>
  );
}

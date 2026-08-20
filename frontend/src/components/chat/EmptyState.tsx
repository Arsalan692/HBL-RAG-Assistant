import { ArrowUpRight } from "lucide-react";
import { HblMark } from "@/components/common/HblMark";
import { SUGGESTIONS } from "@/data/mock";
import { cn } from "@/lib/utils";

export function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-6 py-16">
      <HblMark height={40} className="mb-7" />

      <h2 className="mb-2 text-center text-[28px] font-semibold leading-9 tracking-[-0.01em] text-hbl-primary">
        How can I help you today?
      </h2>
      <p className="mb-9 max-w-md text-center text-[15px] leading-6 text-hbl-secondary">
        Ask anything about HBL policies, SOPs or compliance circulars. Every answer is grounded in
        the source document.
      </p>

      <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
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
    </div>
  );
}

import { cn } from "@/lib/utils";

function Bar({ className }: { className?: string }) {
  return <div className={cn("hbl-shimmer h-2.5 rounded-full bg-muted", className)} />;
}

/** Placeholder source cards, shown while retrieval is still running. */
export function SourceSkeletons({ count = 4 }: { count?: number }) {
  return (
    <section className="mt-5" aria-hidden>
      <div className="mb-2 h-2.5 w-20 rounded-full bg-muted" />
      <div className="hbl-scroll-none -mx-1 flex gap-2.5 overflow-hidden px-1 pb-1">
        {Array.from({ length: count }).map((_, i) => (
          <div
            key={i}
            className="flex w-[248px] shrink-0 items-start gap-2.5 rounded-xl border border-border bg-card p-3"
          >
            <div className="hbl-shimmer h-8 w-8 shrink-0 rounded-lg bg-muted" />
            <div className="flex min-w-0 flex-1 flex-col gap-2 pt-0.5">
              <Bar className="w-[85%]" />
              <Bar className="w-[60%]" />
              <div className="mt-1 flex items-center gap-1.5">
                <div className="hbl-shimmer h-1 w-12 rounded-full bg-muted" />
                <Bar className="h-2 w-12" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

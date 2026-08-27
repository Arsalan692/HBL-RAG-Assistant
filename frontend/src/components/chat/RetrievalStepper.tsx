import { Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export type RetrievalStep = "searching" | "reading" | "composing" | "done";

const ORDER: Exclude<RetrievalStep, "done">[] = ["searching", "reading", "composing"];

/**
 * Shown above an answer while it is being produced, so the wait is legible
 * rather than a blank pause. On a CPU-only machine that wait is minutes, which
 * makes this the only thing telling a reader the system is alive.
 *
 * The counts arrive with the backend's `sources` event, and that event lands
 * *after* searching is already underway — so during the first step there is
 * genuinely nothing to count yet. A bare "Searching" is honest; "Searching 0
 * documents" reads like a system that found nothing.
 */
export function RetrievalStepper({
  step,
  documentCount,
  sourceCount,
}: {
  step: RetrievalStep;
  documentCount: number;
  sourceCount: number;
}) {
  const labels: Record<Exclude<RetrievalStep, "done">, string> = {
    searching: documentCount > 0 ? `Searched ${documentCount.toLocaleString()} documents` : "Searching",
    reading: sourceCount > 0 ? `Reading ${sourceCount} sources` : "Reading",
    composing: "Composing",
  };

  const activeIndex = step === "done" ? ORDER.length : ORDER.indexOf(step);

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-1 gap-y-2">
      {ORDER.map((s, i) => {
        const complete = i < activeIndex;
        const active = i === activeIndex;

        return (
          <div key={s} className="flex items-center gap-1">
            <div
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full py-1 pl-1.5 pr-2.5",
                "text-xs font-medium transition-colors duration-220 ease-spring",
                complete && "bg-accent text-accent-foreground",
                active && "bg-accent text-accent-foreground",
                !complete && !active && "text-hbl-tertiary",
              )}
            >
              <span
                className={cn(
                  "flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
                  complete && "bg-hbl-solid text-hbl-on-solid",
                  active && "text-hbl-green",
                  !complete && !active && "border border-current",
                )}
              >
                {complete && <Check size={10} strokeWidth={3} />}
                {active && <Loader2 size={12} className="animate-spin" />}
              </span>
              {labels[s]}
            </div>

            {i < ORDER.length - 1 && (
              <span aria-hidden className="px-0.5 text-xs text-hbl-tertiary">
                →
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

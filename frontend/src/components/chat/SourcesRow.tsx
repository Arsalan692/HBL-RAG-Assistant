import { FileText } from "lucide-react";
import { sourceCardCls, type ForcedState } from "@/lib/variants";
import type { Source } from "@/types";

export function SourceCard({
  source,
  active = false,
  onClick,
  state,
}: {
  source: Source;
  active?: boolean;
  onClick?: () => void;
  /** Forces an appearance for the states reference page. */
  state?: ForcedState;
}) {
  return (
    <button type="button" onClick={onClick} className={sourceCardCls(active, state)}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent">
        <FileText size={15} className="text-accent-foreground" />
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium leading-[18px] text-hbl-primary">
          {source.title}
        </p>
        <p className="truncate text-[11px] leading-4 text-hbl-tertiary">
          Page {source.page} · {source.section}
        </p>
        <div className="mt-1.5 flex items-center gap-1.5">
          <div className="h-1 w-12 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-hbl-green"
              style={{ width: `${Math.round(source.relevance * 100)}%` }}
            />
          </div>
          <span className="text-[10px] font-medium tabular-nums text-hbl-tertiary">
            {Math.round(source.relevance * 100)}% match
          </span>
        </div>
      </div>
    </button>
  );
}

export function SourcesRow({
  sources,
  activeSourceId,
  onSelect,
}: {
  sources: Source[];
  activeSourceId?: string | null;
  onSelect: (source: Source) => void;
}) {
  return (
    <section className="mt-5">
      <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
        Sources · {sources.length}
      </h4>
      <div className="hbl-scroll-none -mx-1 flex snap-x gap-2.5 overflow-x-auto px-1 pb-1">
        {sources.map((s) => (
          <SourceCard
            key={s.id}
            source={s}
            active={activeSourceId === s.id}
            onClick={() => onSelect(s)}
          />
        ))}
      </div>
    </section>
  );
}

import { citationPillCls, type ForcedState } from "@/lib/variants";

/**
 * The small numbered marker that appears inline inside an answer.
 * Clicking it opens the source panel on that document.
 */
export function CitationPill({
  index,
  active = false,
  onClick,
  title,
  state,
}: {
  index: number;
  active?: boolean;
  onClick?: () => void;
  title?: string;
  /** Forces an appearance for the states reference page. */
  state?: ForcedState;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title ? `Source ${index}: ${title}` : `Source ${index}`}
      className={citationPillCls(active, state)}
    >
      {index}
    </button>
  );
}

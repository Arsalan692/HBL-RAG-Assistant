/**
 * Shared shapes for the chat surface.
 *
 * These mirror what the FastAPI backend will return from Phase 06 onward, so
 * swapping mock data for real responses should not change any component.
 */

export interface Source {
  /** Stable id, used to open the source panel. */
  id: string;
  /** The number shown in the inline citation pill: [1], [2], … */
  index: number;
  /** Document title as it appears in the library. */
  title: string;
  /** Section breadcrumb inside the document, e.g. "4.2 Customer Due Diligence". */
  section: string;
  page: number;
  /** Reranker score, 0–1. Rendered as a percentage. */
  relevance: number;
  department: string;
  effectiveDate: string;
  version: string;
  /**
   * True when a newer edition of the same policy is also indexed.
   *
   * Retrieval keeps superseded passages on purpose — where two editions
   * differ, that difference is usually the answer — so the interface has to
   * say which is which. The model has repeatedly cited one of these without
   * mentioning it was replaced, which is why this is shown rather than trusted
   * to the answer text.
   */
  superseded?: boolean;

  /** The retrieved chunk itself — highlighted in the source panel. */
  excerpt: string;
  /** Surrounding page text, shown unhighlighted for context. */
  contextBefore?: string;
  contextAfter?: string;
}

export interface UserMessage {
  id: string;
  role: "user";
  content: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  /** Markdown. Inline citations are written as [1], [2], … */
  content: string;
  sources: Source[];
}

export type Message = UserMessage | AssistantMessage;

export interface ChatSummary {
  id: string;
  title: string;
  pinned?: boolean;
  /** Which heading the row sits under in the sidebar. */
  group: "Today" | "Yesterday" | "Previous 7 days";
}

/** Which citation is currently open in the source panel. */
export interface ActiveCitation {
  messageId: string;
  sourceId: string;
}

/**
 * The backend, over HTTP.
 *
 * `/chat` is a POST that answers with Server-Sent Events, which rules out
 * `EventSource` — that only does GET. So the body is read as a stream and the
 * frames are parsed here. It is about thirty lines, and it keeps the question
 * in a JSON body rather than a query string, which matters: questions are
 * about confidential policy and query strings end up in logs.
 *
 * Frames arrive in a fixed order the UI depends on:
 *
 *     step(searching) → step(reading) → sources → step(composing) → delta* → done
 *
 * Sources before any text is the load-bearing part. Citation pills resolve at
 * render time, so a delta containing `[2]` that arrives before source 2 exists
 * would render as a number pointing at nothing.
 */

import type { Source } from "@/types";

const BASE = (import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export type Step = "searching" | "reading" | "composing";

/** What the backend reports about the answer once it has finished. */
export interface AnswerAudit {
  refused: boolean;
  /** Citation numbers the model produced that no passage backed. */
  invented: number[];
  /** Cited passages that came from a superseded edition of a policy. */
  superseded: number[];
  /** Passages the answer never used. */
  unused: number[];
  seconds: number;
}

export interface ChatHandlers {
  onStep: (step: Step) => void;
  onSources: (sources: Source[], documentCount: number) => void;
  onDelta: (text: string) => void;
  onDone: (audit: AnswerAudit) => void;
  onError: (message: string) => void;
}

export interface DocumentSummary {
  id: string;
  title: string;
  year: number | null;
  policyFamily: string;
  circular: string;
  pages: number;
  chunks: number;
  status: string;
  error: string;
  hasOtherVintage: boolean;
}

/**
 * Ask a question and receive the answer as it is written.
 *
 * Resolves when the stream ends. `signal` aborts it — the backend notices the
 * disconnect between events and stops, rather than holding a model busy for
 * another several minutes on an answer nobody is reading.
 */
export async function askQuestion(
  question: string,
  handlers: ChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) return;
    handlers.onError(
      `Could not reach the assistant at ${BASE}. Is the backend running? Start it with \`hbl serve\`.`,
    );
    return;
  }

  if (!response.ok || !response.body) {
    handlers.onError(`The assistant returned ${response.status} ${response.statusText}.`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // A frame ends at a blank line. Anything after the last one is a
      // partial frame and stays in the buffer for the next read.
      let split = buffer.indexOf("\n\n");
      while (split !== -1) {
        dispatch(buffer.slice(0, split), handlers);
        buffer = buffer.slice(split + 2);
        split = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    if (!signal?.aborted) {
      handlers.onError("The connection to the assistant was interrupted.");
    }
  } finally {
    reader.cancel().catch(() => undefined);
  }
}

function dispatch(frame: string, handlers: ChatHandlers): void {
  let event = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data = line.slice(6);
  }
  if (!event || !data) return;

  let payload: any;
  try {
    payload = JSON.parse(data);
  } catch {
    return;
  }

  switch (event) {
    case "step":
      handlers.onStep(payload.step as Step);
      break;
    case "sources":
      handlers.onSources(payload.sources as Source[], payload.documentCount ?? 0);
      break;
    case "delta":
      handlers.onDelta(payload.text ?? "");
      break;
    case "done":
      handlers.onDone(payload as AnswerAudit);
      break;
    case "error":
      handlers.onError(payload.message ?? "The assistant failed while answering.");
      break;
  }
}

/** An upload on its way to being answerable. */
export interface IngestJob {
  id: string;
  filename: string;
  state: "queued" | "extracting" | "chunking" | "indexing" | "ready" | "failed" | "duplicate";
  /** Human-readable form of `state`, worded by the backend so it says one thing. */
  label: string;
  pagesDone: number;
  pagesTotal: number;
  chunks: number;
  docId: string;
  error: string;
  duplicateOf: string;
  done: boolean;
  seconds: number;
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const response = await fetch(`${BASE}/documents`);
  if (!response.ok) throw new Error(`documents: ${response.status}`);
  return (await response.json()) as DocumentSummary[];
}

export async function listJobs(): Promise<IngestJob[]> {
  const response = await fetch(`${BASE}/documents/jobs`);
  if (!response.ok) throw new Error(`jobs: ${response.status}`);
  return (await response.json()) as IngestJob[];
}

/**
 * Send a PDF to be indexed.
 *
 * Returns as soon as the file is stored, not when it is searchable — reading a
 * scanned policy takes minutes. Watch `listJobs` for the rest.
 *
 * Refusals come back as a readable message rather than an exception, because
 * every one of them is something the person can act on: wrong file type, too
 * large, or a name already in the library.
 */
export async function uploadDocument(file: File): Promise<{ job?: IngestJob; error?: string }> {
  const body = new FormData();
  body.append("file", file);

  let response: Response;
  try {
    response = await fetch(`${BASE}/documents`, { method: "POST", body });
  } catch {
    return { error: `Could not reach the assistant at ${BASE}.` };
  }

  if (!response.ok) {
    let detail = `${file.name} was refused (${response.status}).`;
    try {
      const payload = await response.json();
      if (payload?.detail) detail = `${file.name}: ${payload.detail}`;
    } catch {
      /* keep the status-based message */
    }
    return { error: detail };
  }

  return { job: (await response.json()) as IngestJob };
}

export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(`${BASE}/documents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`delete: ${response.status}`);
}

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, FileText, Loader2, Plus, Trash2, X } from "lucide-react";
import { IconButton } from "@/components/common/IconButton";
import {
  deleteDocument,
  listDocuments,
  listJobs,
  uploadDocument,
  type DocumentSummary,
  type IngestJob,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { primaryButtonCls } from "@/lib/variants";

/**
 * How often the ingest jobs are re-fetched while any are running.
 *
 * An ingest reports once a page, and a page takes the vision model about
 * fourteen seconds — so polling faster than this only produces identical
 * answers, and polling much slower makes a working system look frozen.
 */
const POLL_MS = 3000;

/**
 * The document library: what the assistant can answer from, and the only place
 * that set changes.
 *
 * The relationship worth making obvious is that this list *is* the assistant's
 * knowledge. Nothing outside it is used, and removing something here removes it
 * from every future answer — so deletion says what it destroys rather than
 * asking a bare "are you sure?".
 */
export function DocumentsModal({ onClose }: { onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [jobs, setJobs] = useState<IngestJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState<DocumentSummary | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [docs, running] = await Promise.all([listDocuments(), listJobs()]);
      setDocuments(docs);
      setJobs(running);
      setError("");
    } catch {
      setError("Could not reach the assistant. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll only while something is actually ingesting. A library at rest does
  // not need re-fetching every three seconds.
  const active = jobs.some((job) => !job.done);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, refresh]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") (confirming ? setConfirming(null) : onClose());
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, confirming]);

  async function onFiles(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    for (const file of Array.from(files)) {
      const result = await uploadDocument(file);
      if (result.error) setError(result.error);
    }
    setBusy(false);
    if (fileRef.current) fileRef.current.value = "";
    void refresh();
  }

  async function confirmDelete() {
    if (!confirming) return;
    setBusy(true);
    try {
      await deleteDocument(confirming.id);
      setConfirming(null);
      await refresh();
    } catch {
      setError(`Could not remove ${confirming.title}.`);
    } finally {
      setBusy(false);
    }
  }

  const running = jobs.filter((job) => !job.done);
  const recent = jobs.filter((job) => job.done && job.state !== "ready").slice(0, 3);

  return (
    <div
      className="fixed inset-0 z-50 flex animate-overlay-in items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (!panelRef.current?.contains(e.target as Node)) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Document library"
        className={cn(
          "flex max-h-[82vh] w-full max-w-[640px] animate-modal-in flex-col overflow-hidden rounded-2xl",
          "border border-border bg-popover shadow-[0_24px_64px_rgba(0,0,0,0.22)]",
        )}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-hbl-primary">Documents</h2>
            <p className="mt-0.5 text-[12.5px] leading-5 text-hbl-tertiary">
              The assistant answers only from these. Adding one makes it searchable; removing
              one takes it out of every future answer.
            </p>
          </div>
          <IconButton label="Close" onClick={onClose}>
            <X size={17} />
          </IconButton>
        </header>

        <div className="hbl-scroll min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <div className="mb-3 flex items-start gap-2 rounded-lg border border-[var(--hbl-danger-border,#E4B4B0)] bg-[var(--hbl-danger-bg,#FBEFEE)] px-3 py-2.5 text-[12.5px] text-[var(--hbl-danger,#93312C)] dark:bg-[#2E1A1A] dark:text-[#E4908C]">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {running.length > 0 && (
            <section className="mb-4">
              <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
                Being added
              </h3>
              <ul className="flex flex-col gap-2">
                {running.map((job) => (
                  <li
                    key={job.id}
                    className="rounded-xl border border-border bg-card px-3.5 py-3"
                  >
                    <div className="flex items-center gap-2.5">
                      <Loader2 size={14} className="shrink-0 animate-spin text-hbl-green" />
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-hbl-primary">
                        {job.filename}
                      </span>
                      <span className="shrink-0 text-[12px] tabular-nums text-hbl-tertiary">
                        {job.pagesTotal > 0
                          ? `${job.pagesDone} / ${job.pagesTotal} pages`
                          : job.label}
                      </span>
                    </div>
                    {job.pagesTotal > 0 && (
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-accent">
                        <div
                          className="h-full rounded-full bg-hbl-green transition-[width] duration-500 ease-spring"
                          style={{
                            width: `${Math.round((job.pagesDone / job.pagesTotal) * 100)}%`,
                          }}
                        />
                      </div>
                    )}
                    <p className="mt-1.5 text-[11.5px] text-hbl-tertiary">
                      {job.label}. Scanned pages are read one at a time — a long document takes
                      several minutes.
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {recent.length > 0 && (
            <section className="mb-4">
              <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
                Not added
              </h3>
              <ul className="flex flex-col gap-2">
                {recent.map((job) => (
                  <li
                    key={job.id}
                    className="rounded-xl border border-border bg-card px-3.5 py-2.5 text-[12.5px]"
                  >
                    <span className="font-medium text-hbl-primary">{job.filename}</span>
                    <span className="text-hbl-tertiary">
                      {" — "}
                      {job.state === "duplicate"
                        ? `already in the library as ${job.duplicateOf}`
                        : job.error || "failed"}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
            In the library · {documents.length}
          </h3>

          {loading ? (
            <p className="py-6 text-center text-[13px] text-hbl-tertiary">Loading…</p>
          ) : documents.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-[13px] text-hbl-tertiary">
              Nothing indexed yet. Add a PDF and the assistant will be able to answer from it.
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="group flex items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-2.5"
                >
                  <FileText size={15} className="shrink-0 text-hbl-tertiary" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-hbl-primary">
                      {doc.title}
                    </p>
                    <p className="mt-0.5 truncate text-[11.5px] text-hbl-tertiary">
                      {[
                        doc.year ? String(doc.year) : null,
                        doc.circular || null,
                        `${doc.chunks} passages`,
                        doc.hasOtherVintage ? "another edition also indexed" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setConfirming(doc)}
                    aria-label={`Remove ${doc.title}`}
                    className={cn(
                      "shrink-0 rounded-lg p-1.5 text-hbl-tertiary outline-none",
                      "transition-all duration-180 ease-spring",
                      "hover:bg-accent hover:text-[#93312C] dark:hover:text-[#E4908C]",
                      "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
                    )}
                  >
                    <Trash2 size={15} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-border px-5 py-3.5">
          <p className="text-[11.5px] text-hbl-tertiary">PDF only, up to 80 MB.</p>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            className="sr-only"
            onChange={(e) => void onFiles(e.target.files)}
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            className={cn(primaryButtonCls(), "gap-1.5 disabled:opacity-60")}
          >
            <Plus size={15} />
            Add PDFs
          </button>
        </footer>
      </div>

      {confirming && (
        <div
          className="absolute inset-0 z-10 flex animate-overlay-in items-center justify-center bg-black/40 p-4"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label={`Remove ${confirming.title}`}
            className="w-full max-w-[420px] animate-modal-in rounded-2xl border border-border bg-popover p-5 shadow-[0_24px_64px_rgba(0,0,0,0.22)]"
          >
            <h3 className="text-[14px] font-semibold text-hbl-primary">
              Remove {confirming.title}?
            </h3>
            {/* Says what is destroyed rather than asking a bare "are you sure?".
                This deletes the PDF as well, and on this machine it may be the
                only copy. */}
            <p className="mt-2 text-[12.5px] leading-5 text-hbl-tertiary">
              This deletes its {confirming.chunks} passages, its search entries and the PDF
              itself. The assistant will no longer be able to answer from it, and past answers
              that cited it will not resolve.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirming(null)}
                className={cn(
                  "rounded-lg border border-border px-3 py-1.5 text-[13px] text-hbl-secondary outline-none",
                  "transition-all duration-180 ease-spring hover:bg-accent",
                  "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
                )}
              >
                Keep it
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void confirmDelete()}
                className={cn(
                  "rounded-lg bg-[#93312C] px-3 py-1.5 text-[13px] font-medium text-white outline-none",
                  "transition-all duration-180 ease-spring hover:bg-[#7C2925] active:scale-97",
                  "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)] disabled:opacity-60",
                )}
              >
                {busy ? "Removing…" : "Remove"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

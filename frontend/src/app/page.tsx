"use client";

import Image from "next/image";
import React, { useEffect, useMemo, useRef, useState } from "react";

type InputType = "url" | "text";
type Mode = "Short" | "Balanced" | "Detailed";

type Citation = { snippet: string; chunkIndex?: number | null };
type Bullet = { id: string; text: string; citations: Citation[] };
type Topic = { id: string; title: string; bullets: Bullet[] };
type DerivePayload =
  | { inputType: "url"; mode: Mode; url: string; text?: never }
  | { inputType: "text"; mode: Mode; text: string; url?: never };

type JobStatus = "queued" | "running" | "failed" | "done" | "notes_saved";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const navy = "bg-[#0f1729]";
const card =
  "rounded-2xl border border-white/70 bg-white/85 shadow-xl shadow-slate-900/[0.07] ring-1 ring-slate-900/[0.04] backdrop-blur-sm";

function deepCloneTopics(topics: Topic[]): Topic[] {
  return JSON.parse(JSON.stringify(topics)) as Topic[];
}

function SegmentedToggle<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { id: T; label: string }[];
}) {
  return (
    <div className="inline-flex rounded-xl bg-slate-100/90 p-1 ring-1 ring-slate-200/70">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-all ${value === o.id
              ? `${navy} text-white shadow-md`
              : "text-slate-600 hover:bg-white/70 hover:text-slate-900"
            }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function Home() {
  const [inputType, setInputType] = useState<InputType>("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [mode, setMode] = useState<Mode>("Balanced");

  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<JobStatus>("queued");
  const [progress, setProgress] = useState(0);
  const [editedTopics, setEditedTopics] = useState<Topic[]>([]);
  const [coverageNote, setCoverageNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pollingRef = useRef<number | null>(null);

  const canSubmit = useMemo(() => {
    if (inputType === "url") return url.trim().length > 0;
    return text.trim().length > 0;
  }, [inputType, url, text]);

  const busy = !!jobId && (status === "running" || status === "queued");

  useEffect(() => {
    return () => {
      if (pollingRef.current) window.clearInterval(pollingRef.current);
    };
  }, []);

  async function startDerive() {
    setError(null);
    setEditedTopics([]);
    setCoverageNote(null);

    const payload: DerivePayload =
      inputType === "url"
        ? { inputType: "url", mode, url }
        : { inputType: "text", mode, text };

    try {
      const res = await fetch(`${API_BASE}/derive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Request failed: ${res.status}`);
      }
      const data = (await res.json()) as { job_id: string };
      setJobId(data.job_id);
      setStatus("queued");
      setProgress(0);

      if (pollingRef.current) window.clearInterval(pollingRef.current);
      pollingRef.current = window.setInterval(async () => {
        if (!data.job_id) return;
        const r = await fetch(`${API_BASE}/jobs/${data.job_id}`);
        if (!r.ok) return;
        const jd = await r.json();
        setStatus(jd.status);
        setProgress(jd.progress ?? 0);

        if (jd.status === "done" || jd.status === "notes_saved") {
          const jt = jd.topics ?? [];
          setEditedTopics(deepCloneTopics(jt));
          setCoverageNote(jd.coverageNote ?? null);
          if (pollingRef.current) window.clearInterval(pollingRef.current);
        } else if (jd.status === "failed") {
          setError(jd.error ?? "Derivation failed.");
          if (pollingRef.current) window.clearInterval(pollingRef.current);
        }
      }, 1500);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not start derivation.";
      setError(msg);
    }
  }

  function updateTopicTitle(topicIndex: number, value: string) {
    setEditedTopics((prev) => {
      const next = deepCloneTopics(prev);
      next[topicIndex].title = value;
      return next;
    });
  }

  function updateBulletText(topicIndex: number, bulletIndex: number, value: string) {
    setEditedTopics((prev) => {
      const next = deepCloneTopics(prev);
      next[topicIndex].bullets[bulletIndex].text = value;
      return next;
    });
  }

  async function saveEdits() {
    if (!jobId) return;

    const res = await fetch(`${API_BASE}/jobs/${jobId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topics: editedTopics }),
    });
    if (!res.ok) {
      const msg = await res.text();
      throw new Error(msg || `Save failed: ${res.status}`);
    }
    return res.json();
  }

  async function downloadWord() {
    if (!jobId) return;
    setError(null);

    try {
      await saveEdits();
      const res = await fetch(`${API_BASE}/jobs/${jobId}/download`);
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Download failed: ${res.status}`);
      }
      const blob = await res.blob();
      const urlObj = window.URL.createObjectURL(blob);

      const a = document.createElement("a");
      a.href = urlObj;
      a.download = `LexiNote-${jobId}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(urlObj);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Something went wrong.";
      setError(msg);
    }
  }

  function renderProgress() {
    const steps = [
      { at: 0, label: "Queued" },
      { at: 10, label: "Fetching & extracting" },
      { at: 40, label: "Deriving topics" },
      { at: 80, label: "Polishing notes" },
    ];
    const current = steps.reduce((acc, s) => (progress >= s.at ? s.label : acc), steps[0].label);
    return (
      <div className={`${card} p-6`}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-blue-600/90">
              Processing
            </p>
            <p className="mt-1 text-lg font-semibold text-slate-900">{current}</p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold tabular-nums text-slate-700">
            {progress}%
          </span>
        </div>
        <div className="mt-5 h-2.5 w-full overflow-hidden rounded-full bg-slate-200/90">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-600 to-indigo-600 transition-[width] duration-500 ease-out"
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      </div>
    );
  }

  const inputClass =
    "mt-2 w-full rounded-xl border border-slate-200/90 bg-white px-4 py-3 text-sm text-slate-900 shadow-inner shadow-slate-900/[0.02] outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-500/25";

  return (
    <div className="flex min-h-screen flex-col">
      <header
        className={`${navy} relative overflow-hidden border-b border-white/10 text-white shadow-md shadow-slate-900/20`}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              "radial-gradient(ellipse 80% 120% at 100% 0%, rgba(59,130,246,0.35), transparent 50%)",
          }}
        />
        <div className="relative mx-auto flex max-w-6xl items-center gap-4 px-4 py-2.5 sm:px-6 sm:py-3">
          <Image
            src="/LexiNote-Photoroom.png"
            alt="LexiNote"
            width={960}
            height={240}
            className="h-14 w-auto max-w-[min(92vw,520px)] object-contain object-left sm:h-16 md:h-[4.5rem] md:max-w-[580px]"
            sizes="(max-width: 768px) 92vw, 580px"
            priority
          />
        </div>
      </header>

      <main className="flex flex-1 flex-col">
        <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-8 sm:py-10">
          <div className="mb-8 rounded-2xl border border-slate-200/80 bg-white/70 px-5 py-6 shadow-sm shadow-slate-900/5 sm:px-7 sm:py-7">
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-950 sm:text-3xl">
              Create your notes
            </h1>
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-slate-800 sm:text-[1.05rem] sm:leading-[1.65rem]">
              Choose a source, pick depth, then derive structured notes with grounded source snippets.
            </p>
          </div>

          <div className="grid gap-8 lg:grid-cols-2 lg:gap-10">
            {/* Input column */}
            <section className={`${card} p-6 sm:p-8`}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-700">
                Source
              </h2>
              <div className="mt-4">
                <SegmentedToggle
                  value={inputType}
                  onChange={setInputType}
                  options={[
                    { id: "url", label: "Article URL" },
                    { id: "text", label: "Paste text" },
                  ]}
                />
              </div>

              <div className="mt-8">
                <h2 className="text-xs font-bold uppercase tracking-widest text-slate-700">
                  Output depth
                </h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(["Short", "Balanced", "Detailed"] as Mode[]).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setMode(m)}
                      className={`rounded-full border px-4 py-2 text-sm font-medium transition-all ${mode === m
                          ? "border-blue-600/40 bg-blue-50 text-blue-900 shadow-sm ring-1 ring-blue-600/20"
                          : "border-transparent bg-slate-100/80 text-slate-600 hover:bg-slate-200/80 hover:text-slate-900"
                        }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-8">
                {inputType === "url" ? (
                  <>
                    <label className="text-sm font-medium text-slate-700">Article URL</label>
                    <input
                      className={inputClass}
                      placeholder="https://example.com/your-article"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      autoComplete="url"
                    />
                  </>
                ) : (
                  <>
                    <label className="text-sm font-medium text-slate-700">Full text</label>
                    <textarea
                      className={`${inputClass} min-h-[220px] resize-y leading-relaxed`}
                      placeholder="Paste the full article or chapter here…"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                    />
                  </>
                )}
              </div>

              <div className="mt-8">
                <button
                  disabled={!canSubmit || busy}
                  type="button"
                  onClick={() => void startDerive()}
                  className={`w-full rounded-xl bg-gradient-to-r from-[#0f1729] via-[#152a45] to-[#1e3a5f] py-3.5 text-sm font-semibold text-white shadow-lg shadow-slate-900/20 transition enabled:hover:brightness-110 enabled:active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-45`}
                >
                  {busy ? "Deriving…" : "Derive LexiNotes"}
                </button>
              </div>

              <p className="mt-4 text-xs leading-relaxed text-slate-600">
                Refreshing clears your session.
              </p>
            </section>

            {/* Output column */}
            <section className={`${card} flex flex-col p-6 sm:p-8`}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-700">
                Notes & export
              </h2>

              <div className="mt-5 flex min-h-[280px] flex-1 flex-col">
                {error ? (
                  <div className="rounded-xl border border-red-200/80 bg-gradient-to-br from-red-50 to-orange-50/50 p-4 text-sm leading-relaxed text-red-900 shadow-sm">
                    {error}
                  </div>
                ) : null}

                {!jobId ? (
                  <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200/90 bg-slate-50/50 px-6 py-12 text-center">
                    <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-md ring-1 ring-slate-200/80">
                      <svg
                        className="h-7 w-7 text-blue-600"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={1.5}
                        aria-hidden
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                        />
                      </svg>
                    </div>
                    <p className="text-base font-medium text-slate-800">Ready when you are</p>
                    <p className="mt-2 max-w-sm text-sm leading-relaxed text-slate-600">
                      Add a URL or paste text on the left, then run Derive LexiNotes. Your topic cards and
                      Word file will appear here.
                    </p>
                  </div>
                ) : status === "queued" || status === "running" ? (
                  renderProgress()
                ) : status === "failed" ? (
                  <div className="rounded-xl border border-amber-200/90 bg-amber-50/80 p-5 text-sm text-amber-950">
                    <p className="font-semibold">Derivation didn’t finish</p>
                    <p className="mt-2 text-amber-900/90">
                      Try another URL, paste the text instead, or check your backend logs / Gemini model
                      settings.
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-6">
                    {coverageNote ? (
                      <div className="rounded-xl border border-blue-100 bg-blue-50/60 px-4 py-3 text-sm leading-relaxed text-blue-950">
                        {coverageNote}
                      </div>
                    ) : null}

                    <div>
                      <p className="text-sm font-semibold text-slate-800">Topics</p>
                      <p className="mt-1 text-xs text-slate-600">
                        Edit titles and bullets; snippets stay for traceability.
                      </p>
                    </div>

                    <div className="flex max-h-[min(60vh,520px)] flex-col gap-4 overflow-y-auto pr-1">
                      {editedTopics.map((topic, ti) => (
                        <article
                          key={topic.id}
                          className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm ring-1 ring-slate-900/[0.02]"
                        >
                          <div className="border-l-4 border-blue-500 pl-3">
                            <input
                              className="w-full border-0 bg-transparent text-base font-semibold text-slate-900 outline-none ring-0 placeholder:text-slate-400 focus:ring-0"
                              value={topic.title}
                              onChange={(e) => updateTopicTitle(ti, e.target.value)}
                            />
                          </div>
                          <div className="mt-4 flex flex-col gap-3">
                            {topic.bullets.map((b, bi) => (
                              <div
                                key={b.id}
                                className="rounded-lg bg-slate-50/90 p-3 ring-1 ring-slate-200/60"
                              >
                                <textarea
                                  className="min-h-[4.5rem] w-full resize-y rounded-lg border border-slate-200/80 bg-white px-3 py-2 text-sm leading-relaxed text-slate-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20"
                                  value={b.text}
                                  onChange={(e) => updateBulletText(ti, bi, e.target.value)}
                                />
                                {b.citations?.length ? (
                                  <p className="mt-2 border-t border-slate-200/80 pt-2 text-xs leading-relaxed text-slate-600">
                                    <span className="font-medium text-slate-600">Source: </span>
                                    <span className="font-mono text-[11px] text-slate-700">
                                      {b.citations[0]?.snippet}
                                    </span>
                                  </p>
                                ) : (
                                  <p className="mt-2 text-xs text-slate-400">No verified snippet for this bullet.</p>
                                )}
                              </div>
                            ))}
                          </div>
                        </article>
                      ))}
                    </div>

                    <div className="mt-2 flex flex-col gap-3 border-t border-slate-200/80 pt-6 sm:flex-row sm:items-center sm:justify-between">
                      <p className="text-xs leading-relaxed text-slate-600">
                        Download saves your latest edits as a formatted .docx.
                      </p>
                      <button
                        type="button"
                        onClick={() => void downloadWord()}
                        className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-md shadow-blue-900/15 transition hover:brightness-105 active:scale-[0.99]"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
                          />
                        </svg>
                        Download Word
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>
      </main>

      <footer className="border-t border-slate-200/90 bg-white/80 py-7 text-center text-sm font-medium text-slate-800 backdrop-blur-sm">
        LexiNote — structured notes from long reads.
      </footer>
    </div>
  );
}

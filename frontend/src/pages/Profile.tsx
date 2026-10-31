import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type Me } from "../api";
import { Card, buttonClass, inputClass } from "../components";
import { useMe } from "../session";

export default function ProfilePage() {
  const me = useMe();
  if (!me.data) return null;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {!me.data.resume && (
        <p className="rounded-md bg-violet-50 px-4 py-3 text-sm text-violet-900 dark:bg-violet-950/50 dark:text-violet-200">
          Welcome! Add your resume below and the agent will rank jobs for you within a few
          minutes.
        </p>
      )}
      <ResumeCard me={me.data} />
      <DetailsCard me={me.data} />
      <DeleteCard />
    </div>
  );
}

function ResumeCard({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [agreed, setAgreed] = useState(me.consented);
  const upload = useMutation({
    mutationFn: async (file: File) => {
      if (!me.consented) await api.consent();
      return api.uploadResume(file);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(["me"], updated);
      queryClient.invalidateQueries({ queryKey: ["summary"] });
    },
  });
  const resume = me.resume;
  // While the worker is still ranking a new resume, check back every 15 seconds.
  const waiting = !!resume && !resume.ranked;
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => queryClient.invalidateQueries({ queryKey: ["me"] }), 15000);
    return () => clearInterval(timer);
  }, [waiting, queryClient]);

  return (
    <Card title="Resume">
      {resume ? (
        <div className="mb-4 text-sm">
          <div className="font-medium">{resume.filename}</div>
          <div className="text-stone-500">
            Uploaded {new Date(resume.uploaded_at).toLocaleDateString()} ·{" "}
            {resume.ranked
              ? "jobs ranked for this resume"
              : "ranking jobs for this resume, usually within a few minutes"}
          </div>
        </div>
      ) : (
        <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">
          A text-based PDF, up to 5 MB. Uploading a new one replaces the current resume.
        </p>
      )}

      {!me.consented && (
        <label className="mb-3 flex gap-2 text-sm">
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5" />
          <span>
            I agree that my resume's text is sent to AI model providers (via OpenRouter) to rank
            jobs and write briefs for me. Free models may keep prompts. My name, email and phone
            number are never sent.
          </span>
        </label>
      )}
      <input
        ref={fileInput}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        aria-label="Resume PDF"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) upload.mutate(file);
          e.target.value = "";
        }}
      />
      <button
        onClick={() => fileInput.current?.click()}
        disabled={(!me.consented && !agreed) || upload.isPending}
        className={buttonClass}
      >
        {upload.isPending ? "Uploading…" : resume ? "Replace resume" : "Upload resume (PDF)"}
      </button>
      {upload.isError && <p className="mt-2 text-sm text-red-600">{upload.error.message}</p>}
    </Card>
  );
}

function DetailsCard({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(me.name);
  const [about, setAbout] = useState(me.about);
  const [minSalary, setMinSalary] = useState(me.min_salary_usd?.toString() ?? "");
  useEffect(() => {
    setName(me.name);
    setAbout(me.about);
    setMinSalary(me.min_salary_usd?.toString() ?? "");
  }, [me.name, me.about, me.min_salary_usd]);

  const save = useMutation({
    mutationFn: () =>
      api.updateMe({ name, about, min_salary_usd: minSalary ? Number(minSalary) : null }),
    onSuccess: (updated) => queryClient.setQueryData(["me"], updated),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <Card title="Your details">
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} className={`${inputClass} w-full`} />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Minimum salary, in US dollars (USD) per year</span>
          <div className="flex items-center gap-2">
            <span className="text-stone-500">$</span>
            <input
              type="number"
              inputMode="numeric"
              min={0}
              step={1000}
              placeholder="e.g. 60000"
              aria-label="Minimum salary in US dollars per year"
              value={minSalary}
              onChange={(e) => setMinSalary(e.target.value)}
              className={`${inputClass} w-40`}
            />
            <span className="text-stone-500">USD / year</span>
          </div>
          <span className="mt-1 block text-xs text-stone-500">
            Enter the amount in <b>US dollars</b>, not rupees (₹50 lakh ≈ $57,000). The AI only ranks
            jobs paying at least this, plus jobs that don't state a salary. Leave empty for no
            minimum.
          </span>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Note for the AI (optional)</span>
          <textarea
            rows={3}
            maxLength={2000}
            placeholder="e.g. Pivoting from test automation to AI engineering; open to mid-level titles; not interested in management."
            value={about}
            onChange={(e) => setAbout(e.target.value)}
            className={`${inputClass} w-full`}
          />
        </label>
        <div className="flex items-center gap-3">
          <button type="submit" disabled={save.isPending} className={buttonClass}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {save.isSuccess && <span className="text-sm text-emerald-600">Saved</span>}
          {save.isError && <span className="text-sm text-red-600">{save.error.message}</span>}
        </div>
        <p className="text-xs text-stone-500">Signed in as {me.email}</p>
      </form>
    </Card>
  );
}

function DeleteCard() {
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: api.deleteMe,
    onSuccess: () => window.location.assign("/"),
  });
  return (
    <Card title="Delete account">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Permanently deletes your account, resume, rankings, briefs and tracker. This cannot be
        undone.
      </p>
      {confirming ? (
        <div className="flex items-center gap-3">
          <button
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            {remove.isPending ? "Deleting…" : "Yes, delete everything"}
          </button>
          <button onClick={() => setConfirming(false)} className="text-sm text-stone-500 underline">
            Cancel
          </button>
        </div>
      ) : (
        <button onClick={() => setConfirming(true)} className="text-sm text-red-600 underline">
          Delete my account
        </button>
      )}
    </Card>
  );
}

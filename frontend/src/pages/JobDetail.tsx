import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type ApplicationStatus, type Brief, type JobDetail } from "../api";
import { LabelControls } from "../LabelControls";
import { useMe } from "../session";
import {
  Card,
  STATUSES,
  ScoreBar,
  TierBadge,
  buttonClass,
  inputClass,
  remoteLabel,
  salaryLabel,
  timeAgo,
} from "../components";

const EXTRA_LABELS: Record<string, string> = {
  one_liner: "One-liner",
  team_size: "Team size",
  visa: "Visa",
  min_experience: "Min. experience",
  equity: "Equity",
  hiring_manager: "Hiring manager",
  job_type: "Job type",
  commitment: "Commitment",
  employment_type: "Employment",
};

export default function JobDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const me = useMe();
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api.job(id) });

  if (job.isPending) return <p className="text-sm text-stone-500">Loading…</p>;
  if (job.isError) return <p className="text-sm text-red-600">{job.error.message}</p>;
  const data = job.data;

  return (
    <div className="space-y-4">
      <button onClick={() => navigate(-1)} className="text-sm text-stone-500 hover:underline">
        ← Back
      </button>

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <TierBadge tier={data.tier} />
          <ScoreBar score={data.fit_score} />
          {!data.ranked && <span className="text-xs text-stone-500">Not ranked yet</span>}
        </div>
        <h1 className="text-xl font-semibold">{data.title}</h1>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          {data.company_website ? (
            <a href={data.company_website} target="_blank" rel="noreferrer" className="underline">
              {data.company}
            </a>
          ) : (
            data.company
          )}
          {data.yc_batch && ` (YC ${data.yc_batch})`} · {remoteLabel(data)}
          {data.location && ` (${data.location})`} · {salaryLabel(data)}
          {data.posted_at && ` · posted ${timeAgo(data.posted_at)}`} · via {data.source}
        </p>
        {data.filter_reason && (
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
            Filtered out: {data.filter_reason}
          </p>
        )}
        <a href={data.url} target="_blank" rel="noreferrer" className={`${buttonClass} inline-block`}>
          Open job posting ↗
        </a>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {data.brief && <BriefCard brief={data.brief} model={data.brief_model} />}
          {(data.reasons.length > 0 || data.gaps.length > 0) && <FitCard job={data} />}
          <DescriptionCard description={data.description} />
        </div>
        <div className="space-y-4">
          <TrackerCard job={data} />
          {me.data?.is_admin && (
            <Card title="Eval label">
              <LabelControls jobId={data.id} label={data.label} />
              <p className="mt-2 text-xs text-stone-500">
                Your own judgement of this job, used to measure ranking quality on the Evals
                page.
              </p>
            </Card>
          )}
          <CompanyCard job={data} />
        </div>
      </div>
    </div>
  );
}

function List({ items, marker }: { items: string[]; marker: string }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2">
          <span className="shrink-0 text-stone-400">{marker}</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function BriefCard({ brief, model }: { brief: Brief; model: string | null }) {
  return (
    <Card title="Research brief" className="border-violet-200 dark:border-violet-900">
      <div className="space-y-4 text-sm">
        {brief.company_summary && <p>{brief.company_summary}</p>}
        {brief.lead_project && (
          <div className="rounded-md bg-violet-50 p-3 dark:bg-violet-950/40">
            <div className="text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">
              Lead with
            </div>
            <div className="font-medium">{brief.lead_project}</div>
            {brief.why_lead_project && (
              <p className="mt-1 text-stone-600 dark:text-stone-400">{brief.why_lead_project}</p>
            )}
          </div>
        )}
        {brief.talking_points && brief.talking_points.length > 0 && (
          <div>
            <h3 className="mb-1.5 font-medium">Talking points</h3>
            <List items={brief.talking_points} marker="•" />
          </div>
        )}
        {brief.verify_before_reaching_out && brief.verify_before_reaching_out.length > 0 && (
          <div>
            <h3 className="mb-1.5 font-medium">Verify before reaching out</h3>
            <List items={brief.verify_before_reaching_out} marker="☐" />
          </div>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-stone-600 dark:text-stone-400">
          <dt>Stage</dt>
          <dd>{brief.stage_and_funding || "Not stated"}</dd>
          <dt>People</dt>
          <dd>
            {brief.people && brief.people.length > 0
              ? brief.people.map((p) => (p.role ? `${p.name} (${p.role})` : p.name)).join(", ")
              : "None named in the posting"}
          </dd>
        </dl>
        <p className="text-xs text-stone-400">
          Written by {model} from the posting only. Write your message yourself.
        </p>
      </div>
    </Card>
  );
}

function FitCard({ job }: { job: JobDetail }) {
  return (
    <Card title="Fit assessment">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="mb-1.5 text-sm font-medium text-emerald-700 dark:text-emerald-400">Why it fits</h3>
          <List items={job.reasons} marker="+" />
        </div>
        <div>
          <h3 className="mb-1.5 text-sm font-medium text-amber-700 dark:text-amber-400">Gaps</h3>
          {job.gaps.length > 0 ? (
            <List items={job.gaps} marker="−" />
          ) : (
            <p className="text-sm text-stone-500">None noted</p>
          )}
        </div>
      </div>
      <p className="mt-3 text-xs text-stone-400">
        {job.model && `Ranked by ${job.model}`}
        {job.similarity !== null && ` · resume similarity ${job.similarity.toFixed(2)}`}
      </p>
    </Card>
  );
}

function DescriptionCard({ description }: { description: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Card title="Job description">
      <div
        className={`whitespace-pre-line text-sm text-stone-700 dark:text-stone-300 ${
          open ? "" : "max-h-64 overflow-hidden"
        }`}
      >
        {description || "No description."}
      </div>
      {description.length > 800 && (
        <button onClick={() => setOpen(!open)} className="mt-2 text-sm text-stone-500 underline">
          {open ? "Show less" : "Show full description"}
        </button>
      )}
    </Card>
  );
}

function TrackerCard({ job }: { job: JobDetail }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ApplicationStatus>(job.status ?? "new");
  const [notes, setNotes] = useState(job.notes);
  useEffect(() => {
    setStatus(job.status ?? "new");
    setNotes(job.notes);
  }, [job.id, job.status, job.notes]);

  const save = useMutation({
    mutationFn: () => api.updateApplication(job.id, status, notes),
    onSuccess: (updated) => {
      queryClient.setQueryData(["job", job.id], updated);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["summary"] });
    },
  });
  const dirty = status !== (job.status ?? "new") || notes !== job.notes;

  return (
    <Card title="Tracker">
      <div className="space-y-3">
        <select
          aria-label="Application status"
          value={status}
          onChange={(e) => setStatus(e.target.value as ApplicationStatus)}
          className={`${inputClass} w-full`}
        >
          {STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <textarea
          aria-label="Notes"
          placeholder="Notes: who you contacted, when, next step…"
          rows={5}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className={`${inputClass} w-full`}
        />
        <div className="flex items-center gap-3">
          <button
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
            className={buttonClass}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {save.isSuccess && !dirty && <span className="text-sm text-emerald-600">Saved</span>}
          {save.isError && <span className="text-sm text-red-600">{save.error.message}</span>}
        </div>
      </div>
    </Card>
  );
}

function CompanyCard({ job }: { job: JobDetail }) {
  const extras = Object.entries(EXTRA_LABELS).filter(([key]) => job.extra[key]);
  const founders = (job.extra.founders as { name: string; title?: string; linkedin?: string }[]) ?? [];
  if (!job.company_description && extras.length === 0 && founders.length === 0) return null;
  return (
    <Card title="Company">
      <div className="space-y-3 text-sm">
        {job.company_description && (
          <p className="line-clamp-6 text-stone-700 dark:text-stone-300">{job.company_description}</p>
        )}
        {extras.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {extras.map(([key, label]) => (
              <div key={key} className="contents">
                <dt className="text-stone-500">{label}</dt>
                <dd>{String(job.extra[key])}</dd>
              </div>
            ))}
          </dl>
        )}
        {founders.length > 0 && (
          <div>
            <div className="mb-1 text-stone-500">Founders</div>
            <ul className="space-y-0.5">
              {founders.map((f) => (
                <li key={f.name}>
                  {f.linkedin ? (
                    <a href={f.linkedin} target="_blank" rel="noreferrer" className="underline">
                      {f.name}
                    </a>
                  ) : (
                    f.name
                  )}
                  {f.title && <span className="text-stone-500"> · {f.title}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

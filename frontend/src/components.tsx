import type { ReactNode } from "react";
import type { ApplicationStatus, JobItem } from "./api";

export const STATUSES: { value: ApplicationStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "shortlisted", label: "Shortlisted" },
  { value: "applied", label: "Applied" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer" },
  { value: "rejected", label: "Rejected" },
  { value: "archived", label: "Archived" },
];

const TIER_STYLES: Record<number, string> = {
  1: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300",
  2: "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-300",
  3: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300",
};

export function TierBadge({ tier }: { tier: number | null }) {
  const style = tier
    ? TIER_STYLES[tier]
    : "bg-stone-200 text-stone-600 dark:bg-stone-800 dark:text-stone-400";
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-semibold ${style}`}>
      {tier ? `Tier ${tier}` : "No tier"}
    </span>
  );
}

export function ScoreBar({ score }: { score: number | null }) {
  if (score === null) return <span className="text-xs text-stone-400">—</span>;
  const color = score >= 75 ? "bg-emerald-500" : score >= 50 ? "bg-sky-500" : "bg-stone-400";
  return (
    <span className="inline-flex items-center gap-2" title={`Fit score ${score}/100`}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
        <span className={`block h-full ${color}`} style={{ width: `${score}%` }} />
      </span>
      <span className="w-6 text-xs tabular-nums text-stone-600 dark:text-stone-400">{score}</span>
    </span>
  );
}

const REMOTE_LABELS: Record<string, string> = {
  remote_india: "Remote · India",
  remote_global: "Remote · Worldwide",
  remote_unspecified: "Remote · region unclear",
  remote_restricted: "Remote · other regions",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Unknown",
};

export function remoteLabel(job: Pick<JobItem, "remote_type">): string {
  return REMOTE_LABELS[job.remote_type] ?? job.remote_type;
}

const usdK = (value: number) => `$${Math.round(value / 1000)}k`;

/** Annual salary in US dollars, e.g. "$120k–$150k / yr". */
export function salaryLabel(job: Pick<JobItem, "salary_min_usd" | "salary_max_usd">): string {
  if (!job.salary_max_usd) return "Salary unknown";
  const low = job.salary_min_usd ?? job.salary_max_usd;
  return low === job.salary_max_usd
    ? `${usdK(job.salary_max_usd)} / yr`
    : `${usdK(low)}–${usdK(job.salary_max_usd)} / yr`;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  return `${Math.floor(days / 30)} mo ago`;
}

export function Card({ title, children, className = "" }: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900 ${className}`}
    >
      {title && (
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-stone-500">
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-stone-300 p-8 text-center text-sm text-stone-500 dark:border-stone-700">
      {children}
    </div>
  );
}

export const inputClass =
  "rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-stone-500 focus:ring-2 focus:ring-stone-200 dark:border-stone-700 dark:bg-stone-900 dark:focus:ring-stone-800";

export const buttonClass =
  "rounded-md bg-stone-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-stone-300";

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type ApplicationStatus } from "../api";
import { Empty, STATUSES, TierBadge, salaryLabel } from "../components";

const COLUMNS: ApplicationStatus[] = ["shortlisted", "applied", "interviewing", "offer", "rejected"];

export default function TrackerPage() {
  const jobs = useQuery({ queryKey: ["jobs", "tracked"], queryFn: () => api.jobs({ view: "tracked" }) });

  if (jobs.isPending) return <p className="text-sm text-stone-500">Loading…</p>;
  if (jobs.isError) return <p className="text-sm text-red-600">{jobs.error.message}</p>;
  if (jobs.data.length === 0) {
    return (
      <Empty>
        No tracked jobs yet. Open a job and set its status to Shortlisted or Applied.
      </Empty>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
      {COLUMNS.map((column) => {
        const items = jobs.data.filter((job) => job.status === column);
        const label = STATUSES.find((s) => s.value === column)!.label;
        return (
          <section key={column} className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              {label} <span className="text-stone-400">({items.length})</span>
            </h2>
            {items.map((job) => (
              <Link
                key={job.id}
                to={`/jobs/${job.id}`}
                className="block rounded-lg border border-stone-200 bg-white p-3 hover:border-stone-400 dark:border-stone-800 dark:bg-stone-900 dark:hover:border-stone-600"
              >
                <div className="mb-1">
                  <TierBadge tier={job.tier} />
                </div>
                <div className="text-sm font-medium">{job.title}</div>
                <div className="text-xs text-stone-500">
                  {job.company} · {salaryLabel(job)}
                </div>
              </Link>
            ))}
          </section>
        );
      })}
    </div>
  );
}

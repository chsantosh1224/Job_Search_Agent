import type { Run } from "../api";
import { Card, Empty } from "../components";
import { RunNowButton, useSummary } from "../RunNow";

const STATUS_STYLES: Record<string, string> = {
  success: "text-emerald-700 dark:text-emerald-400",
  partial: "text-amber-700 dark:text-amber-400",
  failed: "text-red-700 dark:text-red-400",
  running: "text-sky-700 dark:text-sky-400",
  queued: "text-sky-700 dark:text-sky-400",
  skipped: "text-stone-500",
};

export default function RunsPage() {
  const summary = useSummary();
  if (summary.isPending) return <p className="text-sm text-stone-500">Loading…</p>;
  if (summary.isError) return <p className="text-sm text-red-600">{summary.error.message}</p>;
  const data = summary.data;

  const stats = [
    { label: "Jobs stored", value: data.jobs_total },
    { label: "Passed filters", value: data.jobs_passed },
    { label: "Ranked into a tier", value: Object.values(data.tiers).reduce((a, b) => a + b, 0) },
    { label: "Research briefs", value: data.briefs },
  ];

  return (
    <div className="space-y-4">
      <RunNowButton />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <div className="text-2xl font-semibold tabular-nums">{s.value}</div>
            <div className="text-sm text-stone-500">{s.label}</div>
          </Card>
        ))}
      </div>
      <p className="text-sm text-stone-500">Active resume: {data.resume ?? "none (run jobagent ingest-resume)"}</p>

      <Card title="Recent runs">
        {data.runs.length === 0 ? (
          <Empty>No runs yet.</Empty>
        ) : (
          <ul className="divide-y divide-stone-200 dark:divide-stone-800">
            {data.runs.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function RunRow({ run }: { run: Run }) {
  const started = new Date(run.started_at);
  const minutes = run.finished_at
    ? Math.max(1, Math.round((new Date(run.finished_at).getTime() - started.getTime()) / 60_000))
    : null;
  return (
    <li className="py-3 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="font-medium">#{run.id}</span>
        <span className={`font-medium ${STATUS_STYLES[run.status] ?? ""}`}>{run.status}</span>
        <span className="text-stone-500">
          {started.toLocaleString()} · {run.trigger}
          {minutes && ` · ${minutes} min`}
        </span>
      </div>
      <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500">
        {flattenStats(run.stats).map(([source, value]) => (
            <div key={source}>
              <dt className="inline font-medium text-stone-700 dark:text-stone-300">{source}: </dt>
              <dd className="inline">{describe(value)}</dd>
            </div>
          ))}
      </dl>
      {Array.isArray(run.stats.errors) && run.stats.errors.length > 0 && (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
          {run.stats.errors.length} error(s): {String(run.stats.errors[0]).slice(0, 160)}
        </p>
      )}
    </li>
  );
}

/** Full pipeline runs nest per-source stats under "fetch"; show those sources inline. */
function flattenStats(stats: Record<string, unknown>): [string, unknown][] {
  return Object.entries(stats).flatMap(([key, value]): [string, unknown][] => {
    if (key === "errors") return [];
    if (key === "fetch" && value && typeof value === "object") {
      return Object.entries(value as Record<string, unknown>);
    }
    return [[key, value]];
  });
}

function describe(value: unknown): string {
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k} ${v}`)
      .join(", ");
  }
  return String(value);
}

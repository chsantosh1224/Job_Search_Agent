import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type JobFilters, type JobItem, type Region, type View } from "../api";
import {
  Empty,
  ScoreBar,
  STATUSES,
  TierBadge,
  buttonClass,
  inputClass,
  remoteLabel,
  salaryLabel,
  timeAgo,
} from "../components";
import { useSummary } from "../RunNow";
import { useMe } from "../session";

const VIEWS: { value: View; label: string; hint: string }[] = [
  { value: "matches", label: "Matches", hint: "Ranked into a tier, best first" },
  { value: "other", label: "Not ranked / no fit", hint: "Passed filters; awaiting ranking or not a fit" },
  { value: "tracked", label: "Tracked", hint: "Jobs you have moved past New" },
  { value: "filtered", label: "Filtered out", hint: "Failed a hard filter or the India check" },
];

const REGIONS: { value: Region; label: string }[] = [
  { value: "worldwide", label: "Worldwide remote" },
  { value: "india", label: "India remote" },
  { value: "unspecified", label: "Remote, region not stated" },
];

const number = (value: string | null) => (value ? Number(value) : null);

export default function JobsPage() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const filters: JobFilters = {
    view: (params.get("view") as View) || "matches",
    tier: number(params.get("tier")),
    q: params.get("q") ?? "",
    salaryMinUsd: number(params.get("min")),
    salaryMaxUsd: number(params.get("max")),
    includeUnknownSalary: params.get("unknown") !== "0",
    regions: (params.getAll("region") as Region[]).filter((r) =>
      REGIONS.some((x) => x.value === r)),
  };

  const jobs = useQuery({ queryKey: ["jobs", filters], queryFn: () => api.jobs(filters) });
  const summary = useSummary();

  const update = (changes: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key);
      for (const v of Array.isArray(value) ? value : value ? [value] : []) next.append(key, v);
    }
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-4">
      {me.data && !me.data.resume && (
        <p className="rounded-md bg-violet-50 px-4 py-3 text-sm text-violet-900 dark:bg-violet-950/50 dark:text-violet-200">
          Add your resume on the <Link to="/profile" className="font-medium underline">Profile</Link>{" "}
          page to get jobs ranked for you.
        </p>
      )}
      {me.data?.resume && !me.data.resume.ranked && (
        <p className="rounded-md bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:bg-sky-950/50 dark:text-sky-200">
          Ranking jobs for your resume. Matches appear here within a few minutes.
        </p>
      )}
      {summary.data && (
        <p className="text-sm text-stone-500">
          {summary.data.jobs_passed} remote jobs · your matches: Tier 1{" "}
          {summary.data.tiers["1"] ?? 0} · Tier 2 {summary.data.tiers["2"] ?? 0} · Tier 3{" "}
          {summary.data.tiers["3"] ?? 0} · {summary.data.briefs} briefs
        </p>
      )}

      <div className="flex flex-wrap gap-1 rounded-lg bg-stone-200/60 p-1 dark:bg-stone-800/60">
        {VIEWS.map((v) => (
          <button
            key={v.value}
            title={v.hint}
            onClick={() => update({ view: v.value === "matches" ? null : v.value, tier: null })}
            className={`rounded-md px-3 py-1 text-sm ${
              filters.view === v.value
                ? "bg-white font-medium shadow-sm dark:bg-stone-900"
                : "text-stone-600 dark:text-stone-400"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {filters.view !== "filtered" && <FilterBar filters={filters} update={update} />}

      {jobs.isPending && <p className="text-sm text-stone-500">Loading…</p>}
      {jobs.isError && <p className="text-sm text-red-600">{jobs.error.message}</p>}
      {jobs.data && jobs.data.length === 0 && (
        <Empty>
          {filters.view === "matches"
            ? "No ranked jobs match these filters yet."
            : "Nothing here with these filters."}
        </Empty>
      )}
      {jobs.data && jobs.data.length > 0 && (
        <ul className="divide-y divide-stone-200 overflow-hidden rounded-lg border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
          {jobs.data.map((job) => (
            <JobRow key={job.id} job={job} view={filters.view} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FilterBar({ filters, update }: {
  filters: JobFilters;
  update: (changes: Record<string, string | string[] | null>) => void;
}) {
  const [search, setSearch] = useState(filters.q ?? "");
  const [min, setMin] = useState(filters.salaryMinUsd?.toString() ?? "");
  const [max, setMax] = useState(filters.salaryMaxUsd?.toString() ?? "");
  const selected = filters.regions?.length ? filters.regions : REGIONS.map((r) => r.value);

  const apply = (event: FormEvent) => {
    event.preventDefault();
    update({ q: search.trim() || null, min: min || null, max: max || null });
  };
  const toggleRegion = (region: Region) => {
    const next = selected.includes(region)
      ? selected.filter((r) => r !== region)
      : [...selected, region];
    // All (or none) selected means no region filter.
    update({ region: next.length === REGIONS.length || next.length === 0 ? null : next });
  };

  return (
    <form
      onSubmit={apply}
      className="space-y-3 rounded-lg border border-stone-200 bg-white p-3 dark:border-stone-800 dark:bg-stone-900"
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-stone-500">Search</span>
          <input
            type="search"
            placeholder="Title or description"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`${inputClass} w-56`}
          />
        </label>
        <fieldset className="text-sm">
          <legend className="mb-1 text-xs font-medium text-stone-500">
            Salary, US dollars (USD) per year
          </legend>
          <div className="flex items-center gap-1.5">
            <span className="text-stone-500">$</span>
            <input
              type="number"
              min={0}
              step={5000}
              placeholder="Min USD"
              aria-label="Minimum salary in USD per year"
              value={min}
              onChange={(e) => setMin(e.target.value)}
              className={`${inputClass} w-28`}
            />
            <span className="text-stone-500">to $</span>
            <input
              type="number"
              min={0}
              step={5000}
              placeholder="Max USD"
              aria-label="Maximum salary in USD per year"
              value={max}
              onChange={(e) => setMax(e.target.value)}
              className={`${inputClass} w-28`}
            />
          </div>
        </fieldset>
        {filters.view === "matches" && (
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-stone-500">Tier</span>
            <select
              value={filters.tier ?? ""}
              onChange={(e) => update({ tier: e.target.value || null })}
              className={inputClass}
            >
              <option value="">All tiers</option>
              <option value="1">Tier 1</option>
              <option value="2">Tier 2</option>
              <option value="3">Tier 3</option>
            </select>
          </label>
        )}
        <button type="submit" className={buttonClass}>
          Apply
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={filters.includeUnknownSalary !== false}
            onChange={(e) => update({ unknown: e.target.checked ? null : "0" })}
          />
          Include jobs with unknown salary
        </label>
        <span className="text-stone-300 dark:text-stone-700">|</span>
        {REGIONS.map((region) => (
          <label key={region.value} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={selected.includes(region.value)}
              onChange={() => toggleRegion(region.value)}
            />
            {region.label}
          </label>
        ))}
      </div>
    </form>
  );
}

function JobRow({ job, view }: { job: JobItem; view: View }) {
  const status = STATUSES.find((s) => s.value === job.status);
  return (
    <li>
      <Link
        to={`/jobs/${job.id}`}
        className="flex flex-col gap-2 px-4 py-3 hover:bg-stone-50 sm:flex-row sm:items-center sm:gap-4 dark:hover:bg-stone-800/50"
      >
        <div className="flex shrink-0 items-center gap-3 sm:w-40">
          <TierBadge tier={job.tier} />
          <ScoreBar score={job.fit_score} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{job.title}</div>
          <div className="truncate text-sm text-stone-500">
            {job.company ?? "Unknown company"} · {remoteLabel(job)} · {salaryLabel(job)}
          </div>
          {view === "filtered" && job.filter_reason && (
            <div className="mt-0.5 truncate text-xs text-stone-500">{job.filter_reason}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs text-stone-500">
          {job.has_brief && (
            <span className="rounded bg-violet-100 px-1.5 py-0.5 font-medium text-violet-800 dark:bg-violet-900/50 dark:text-violet-300">
              Brief
            </span>
          )}
          {status && status.value !== "new" && (
            <span className="rounded bg-stone-100 px-1.5 py-0.5 font-medium dark:bg-stone-800">
              {status.label}
            </span>
          )}
          <span className="w-20 text-right">{timeAgo(job.posted_at)}</span>
        </div>
      </Link>
    </li>
  );
}

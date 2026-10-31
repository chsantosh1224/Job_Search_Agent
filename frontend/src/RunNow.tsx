import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { buttonClass } from "./components";

const ACTIVE = ["queued", "running"];

/** Summary query that refreshes every 5 s while a run is queued or running. */
export function useSummary() {
  return useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => ACTIVE.includes(run.status)) ? 5000 : false,
  });
}

export function RunNowButton() {
  const queryClient = useQueryClient();
  const summary = useSummary();
  const active = summary.data?.runs.find((run) => ACTIVE.includes(run.status));
  const runNow = useMutation({
    mutationFn: api.runNow,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["summary"] }),
  });

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => runNow.mutate()}
        disabled={!!active || runNow.isPending}
        className={buttonClass}
      >
        {active ? (active.status === "queued" ? "Run queued…" : "Running…") : "Run now"}
      </button>
      <span className="text-xs text-stone-500">
        {active
          ? `Run #${active.id} ${active.status}. Takes 10–30 min; you can leave this page.`
          : "Fetches new jobs, ranks them and emails the digest." +
            (summary.data ? ` Also runs daily at ${summary.data.daily_run_time_ist} IST.` : "")}
      </span>
      {runNow.isError && <span className="text-sm text-red-600">{runNow.error.message}</span>}
    </div>
  );
}

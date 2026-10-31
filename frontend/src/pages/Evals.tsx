import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type BriefEvalDetail, type EvalRunSummary, type RankingMetrics } from "../api";
import { Card, Empty, buttonClass } from "../components";
import { LabelControls } from "../LabelControls";

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const num = (v: number | null | undefined, digits = 2) => (v == null ? "—" : v.toFixed(digits));

export default function EvalsPage() {
  const evals = useQuery({ queryKey: ["evals"], queryFn: api.evals });
  if (evals.isPending) return <p className="text-sm text-stone-500">Loading…</p>;
  if (evals.isError) return <p className="text-sm text-red-600">{evals.error.message}</p>;
  const { ranking, label_goal, latest_briefs, history } = evals.data;

  return (
    <div className="space-y-4">
      <LabelProgress labeled={ranking.labeled} goal={label_goal} good={ranking.labeled_good} />
      <div className="grid gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <RankingCard metrics={ranking} />
          <BriefsCard run={latest_briefs} />
        </div>
        <div className="space-y-4 lg:col-span-2">
          <LabelQueue />
          <HistoryCard history={history} />
        </div>
      </div>
    </div>
  );
}

function LabelProgress({ labeled, goal, good }: { labeled: number; goal: number; good: number }) {
  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="font-semibold">Evaluation set</h1>
        <span className="text-sm text-stone-500">
          {labeled} / {goal} labeled · {good} good fit · {labeled - good} not a fit
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
        <div
          className="h-full bg-violet-500"
          style={{ width: `${Math.min(100, (labeled / goal) * 100)}%` }}
        />
      </div>
      <p className="mt-2 text-sm text-stone-500">
        Label jobs as you would judge them yourself. The queue hides the AI's tier and score so
        your labels stay an independent answer key. Aim for a mix of good and bad fits.
      </p>
    </Card>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div title={hint}>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-stone-500">{label}</div>
    </div>
  );
}

function RankingCard({ metrics: m }: { metrics: RankingMetrics }) {
  const queryClient = useQueryClient();
  const snapshot = useMutation({
    mutationFn: api.snapshotRankingEval,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["evals"] }),
  });
  const enough = m.evaluated >= 5 && m.labeled_good > 0 && m.labeled_good < m.labeled;

  return (
    <Card title="Ranking quality">
      {!enough && (
        <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
          Needs at least 5 ranked labels including both good and bad fits for meaningful numbers.
        </p>
      )}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Precision" value={pct(m.precision)} hint="Of jobs the AI called good, share you also called good" />
        <Stat label="Recall" value={pct(m.recall)} hint="Of jobs you called good, share the AI found" />
        <Stat label="Precision @ 5" value={pct(m.precision_at_5)} hint="Good fits among the AI's top 5 by score" />
        <Stat label="Tier accuracy" value={pct(m.tier_accuracy)} hint="Exact tier match on jobs you labeled good with a tier" />
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div className="rounded-md bg-stone-50 p-3 dark:bg-stone-800/50">
          <div className="text-xs font-semibold uppercase tracking-wide text-stone-500">
            Separating good from bad (AUC)
          </div>
          <div className="mt-1 flex items-baseline gap-4 text-sm">
            <span>
              LLM fit score <b className="tabular-nums">{num(m.auc_llm)}</b>
            </span>
            <span className="text-stone-500">
              Embeddings only <b className="tabular-nums">{num(m.auc_similarity)}</b>
            </span>
          </div>
          <p className="mt-1 text-xs text-stone-500">
            1.0 = perfect, 0.5 = coin flip. The gap shows what the LLM adds over vector search.
          </p>
        </div>
        <div className="rounded-md bg-stone-50 p-3 text-sm dark:bg-stone-800/50">
          <div className="text-xs font-semibold uppercase tracking-wide text-stone-500">
            Confusion (good = tier and score ≥ {m.threshold})
          </div>
          <div className="mt-1 grid grid-cols-2 gap-x-4 tabular-nums">
            <span>Agreed good: {m.confusion.tp}</span>
            <span>False alarms: {m.confusion.fp}</span>
            <span>Missed: {m.confusion.fn}</span>
            <span>Agreed bad: {m.confusion.tn}</span>
          </div>
        </div>
      </div>
      {m.not_ranked_yet > 0 && (
        <p className="mt-3 text-sm text-stone-500">
          {m.not_ranked_yet} labeled job(s) have no LLM ranking yet (the daily run skipped them).
          Rank them with <code>jobagent eval --rank-labeled {m.not_ranked_yet}</code>.
        </p>
      )}
      {m.mistakes.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1.5 text-sm font-medium">Disagreements</h3>
          <ul className="space-y-1 text-sm">
            {m.mistakes.map((mistake) => (
              <li key={mistake.job_id} className="flex gap-2">
                <span className="w-28 shrink-0 text-stone-500">{mistake.kind}</span>
                <Link to={`/jobs/${mistake.job_id}`} className="truncate underline">
                  {mistake.title}
                </Link>
                <span className="shrink-0 text-stone-500">
                  AI: {mistake.tier ? `T${mistake.tier}` : "no tier"} · {mistake.fit_score ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <button onClick={() => snapshot.mutate()} disabled={snapshot.isPending} className={`${buttonClass} mt-4`}>
        Save snapshot
      </button>
      <span className="ml-3 text-xs text-stone-500">Keeps today's numbers in the history.</span>
    </Card>
  );
}

function BriefsCard({ run }: { run: EvalRunSummary | null }) {
  if (!run) {
    return (
      <Card title="Brief quality">
        <Empty>
          No brief evaluation yet. Run <code>jobagent eval --briefs 5</code> to have a second model
          fact-check the latest briefs.
        </Empty>
      </Card>
    );
  }
  const m = run.metrics as Record<string, number | null>;
  return (
    <Card title={`Brief quality · ${new Date(run.created_at).toLocaleDateString()}`}>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Faithfulness" value={pct(m.faithfulness)} hint="Claims supported by the source (RAGAS definition)" />
        <Stat label="Specificity" value={`${num(m.specificity, 1)} / 5`} hint="Concrete links between candidate work and company needs" />
        <Stat label="Usefulness" value={`${num(m.usefulness, 1)} / 5`} hint="How much it helps write a personal message" />
        <Stat label="Briefs judged" value={String(m.briefs_judged ?? 0)} hint="Most recent briefs checked" />
      </div>
      <ul className="mt-4 divide-y divide-stone-200 dark:divide-stone-800">
        {(run.details ?? []).map((d) => (
          <BriefRow key={d.job_id} detail={d} />
        ))}
      </ul>
    </Card>
  );
}

function BriefRow({ detail: d }: { detail: BriefEvalDetail }) {
  return (
    <li className="py-3 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <Link to={`/jobs/${d.job_id}`} className="font-medium underline">
          {d.title}
        </Link>
        <span className="text-stone-500">{d.company}</span>
        <span className="ml-auto tabular-nums">
          {pct(d.faithfulness)} of {d.claims} claims supported
        </span>
      </div>
      {d.comment && <p className="mt-1 text-stone-600 dark:text-stone-400">{d.comment}</p>}
      {d.unsupported.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-amber-800 dark:text-amber-300">
          {d.unsupported.map((claim, i) => (
            <li key={i}>⚠ Unsupported: {claim}</li>
          ))}
        </ul>
      )}
      {d.people_not_in_source.length > 0 && (
        <p className="mt-1 text-red-700 dark:text-red-400">
          Names not in the source: {d.people_not_in_source.join(", ")}
        </p>
      )}
      {!d.lead_project_in_resume && (
        <p className="mt-1 text-red-700 dark:text-red-400">Lead project not found in the resume</p>
      )}
      <p className="mt-1 text-xs text-stone-400">
        Written by {d.writer_model} · judged by {d.judge_model}
      </p>
    </li>
  );
}

function LabelQueue() {
  const queue = useQuery({ queryKey: ["label-queue"], queryFn: api.labelQueue });
  return (
    <Card title="Label next">
      {queue.isPending && <p className="text-sm text-stone-500">Loading…</p>}
      {queue.data && queue.data.length === 0 && (
        <Empty>Everything is labeled. New jobs arrive with the next run.</Empty>
      )}
      <ul className="space-y-4">
        {queue.data?.slice(0, 5).map((job) => (
          <li key={job.id} className="space-y-1.5 border-b border-stone-200 pb-4 last:border-0 dark:border-stone-800">
            <div className="font-medium">{job.title}</div>
            <div className="text-sm text-stone-500">
              {job.company} · {job.location ?? "Location not stated"}
              {job.salary_max_lpa ? ` · up to ₹${job.salary_max_lpa} LPA` : ""}
            </div>
            <p className="line-clamp-4 text-sm text-stone-600 dark:text-stone-400">{job.snippet}</p>
            <a href={job.url} target="_blank" rel="noreferrer" className="text-sm underline">
              Read full posting ↗
            </a>
            <LabelControls jobId={job.id} label={null} quick />
          </li>
        ))}
      </ul>
    </Card>
  );
}

function HistoryCard({ history }: { history: EvalRunSummary[] }) {
  if (history.length === 0) return null;
  return (
    <Card title="History">
      <ul className="space-y-1 text-sm">
        {history.map((run) => {
          const m = run.metrics as Record<string, number | null>;
          return (
            <li key={run.id} className="flex justify-between gap-2">
              <span className="text-stone-500">{new Date(run.created_at).toLocaleDateString()}</span>
              <span>
                {run.kind === "ranking"
                  ? `Ranking · P ${pct(m.precision)} · R ${pct(m.recall)} · AUC ${num(m.auc_llm)}`
                  : `Briefs · faithfulness ${pct(m.faithfulness)}`}
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

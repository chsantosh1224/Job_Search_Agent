import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Label } from "./api";
import { inputClass } from "./components";

const choice =
  "rounded-md border px-3 py-1 text-sm font-medium disabled:opacity-50 border-stone-300 dark:border-stone-700";
const selectedGood =
  "border-emerald-600 bg-emerald-600 text-white dark:border-emerald-500 dark:bg-emerald-600";
const selectedBad = "border-stone-700 bg-stone-700 text-white dark:border-stone-300 dark:bg-stone-300 dark:text-stone-900";

/** Label a job for the eval set: good fit (with the tier it deserves) or not a fit.
 *
 * `quick` (the label queue) offers the tier in the same click, because a labeled job leaves
 * the queue immediately and there is no second chance to pick it.
 */
export function LabelControls({ jobId, label, quick = false }: {
  jobId: number;
  label: Label | null;
  quick?: boolean;
}) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: async (next: Label | null): Promise<void> => {
      if (next) await api.setLabel(jobId, next);
      else await api.deleteLabel(jobId);
    },
    onSuccess: () => {
      for (const key of [["evals"], ["label-queue"], ["job", jobId]]) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
  const set = (is_good_fit: boolean, expected_tier: number | null = null) =>
    save.mutate({ is_good_fit, expected_tier, notes: label?.notes ?? "" });

  if (quick) {
    return (
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Your label">
        <span className="text-xs text-stone-500">Good fit:</span>
        {[1, 2, 3].map((tier) => (
          <button key={tier} onClick={() => set(true, tier)} disabled={save.isPending} className={choice}>
            Tier {tier}
          </button>
        ))}
        <button onClick={() => set(false)} disabled={save.isPending} className={choice}>
          Not a fit
        </button>
        {save.isError && <span className="text-sm text-red-600">{save.error.message}</span>}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        onClick={() => set(true, label?.expected_tier ?? null)}
        disabled={save.isPending}
        aria-pressed={label?.is_good_fit === true}
        className={`${choice} ${label?.is_good_fit === true ? selectedGood : ""}`}
      >
        Good fit
      </button>
      <button
        onClick={() => set(false)}
        disabled={save.isPending}
        aria-pressed={label?.is_good_fit === false}
        className={`${choice} ${label?.is_good_fit === false ? selectedBad : ""}`}
      >
        Not a fit
      </button>
      {label?.is_good_fit && (
        <select
          aria-label="Expected tier"
          value={label.expected_tier ?? ""}
          onChange={(e) => set(true, e.target.value ? Number(e.target.value) : null)}
          className={inputClass}
        >
          <option value="">Tier?</option>
          <option value="1">Tier 1</option>
          <option value="2">Tier 2</option>
          <option value="3">Tier 3</option>
        </select>
      )}
      {label && (
        <button
          onClick={() => save.mutate(null)}
          disabled={save.isPending}
          className="text-xs text-stone-500 underline"
        >
          Clear
        </button>
      )}
      {save.isError && <span className="text-sm text-red-600">{save.error.message}</span>}
    </div>
  );
}

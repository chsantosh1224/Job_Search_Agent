import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AdminUser } from "../api";
import { Card, timeAgo } from "../components";
import { useMe } from "../session";

export default function AdminPage() {
  const overview = useQuery({ queryKey: ["admin-users"], queryFn: api.adminUsers });
  if (overview.isPending) return <p className="text-sm text-stone-500">Loading…</p>;
  if (overview.isError) return <p className="text-sm text-red-600">{overview.error.message}</p>;
  const data = overview.data;
  const used = Math.min(100, (data.calls_today / data.daily_cap) * 100);

  return (
    <div className="space-y-4">
      <Card title="AI usage today">
        <div className="flex items-baseline justify-between text-sm">
          <span>
            <b className="tabular-nums">{data.calls_today}</b> of {data.daily_cap} LLM calls
          </span>
          <span className="text-stone-500">
            Per user per day: {data.user_rank_limit} ranked jobs, {data.user_brief_limit} briefs
          </span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
          <div
            className={`h-full ${used > 90 ? "bg-red-500" : used > 70 ? "bg-amber-500" : "bg-emerald-500"}`}
            style={{ width: `${used}%` }}
          />
        </div>
      </Card>

      <Card title={`Users (${data.users.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-stone-500">
              <tr>
                <th className="py-2 pr-3 font-medium">User</th>
                <th className="py-2 pr-3 font-medium">Joined</th>
                <th className="py-2 pr-3 font-medium">Last sign-in</th>
                <th className="py-2 pr-3 font-medium">Resume</th>
                <th className="py-2 pr-3 font-medium">Matches</th>
                <th className="py-2 pr-3 font-medium">Today</th>
                <th className="py-2 font-medium">Access</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-200 dark:divide-stone-800">
              {data.users.map((user) => (
                <UserRow key={user.id} user={user} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function UserRow({ user }: { user: AdminUser }) {
  const queryClient = useQueryClient();
  const me = useMe();
  const toggle = useMutation({
    mutationFn: () => api.setUserActive(user.id, !user.is_active),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });
  const isMe = me.data?.id === user.id;

  return (
    <tr className={user.is_active ? "" : "text-stone-400"}>
      <td className="py-2 pr-3">
        <div className="font-medium">
          {user.name || user.email.split("@")[0]}
          {user.is_admin && (
            <span className="ml-2 rounded bg-violet-100 px-1.5 py-0.5 text-xs text-violet-800 dark:bg-violet-900/50 dark:text-violet-300">
              admin
            </span>
          )}
        </div>
        <div className="text-xs text-stone-500">{user.email}</div>
      </td>
      <td className="py-2 pr-3 text-stone-500">{timeAgo(user.created_at)}</td>
      <td className="py-2 pr-3 text-stone-500">
        {user.last_login_at ? timeAgo(user.last_login_at) : "never"}
      </td>
      <td className="py-2 pr-3">{user.has_resume ? "Yes" : "—"}</td>
      <td className="py-2 pr-3 tabular-nums">{user.matches}</td>
      <td className="py-2 pr-3 tabular-nums text-stone-500">
        {user.calls_today} calls · {user.ranked_today} ranked · {user.briefs_today} briefs
      </td>
      <td className="py-2">
        {isMe ? (
          <span className="text-xs text-stone-500">you</span>
        ) : (
          <button
            onClick={() => toggle.mutate()}
            disabled={toggle.isPending}
            className={`text-sm underline ${user.is_active ? "text-red-600" : "text-emerald-600"}`}
          >
            {user.is_active ? "Disable" : "Enable"}
          </button>
        )}
      </td>
    </tr>
  );
}

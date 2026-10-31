import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useSearchParams, type Location } from "react-router-dom";
import { api, googleLoginUrl } from "../api";
import { buttonClass, inputClass } from "../components";

const ERRORS: Record<string, string> = {
  cancelled: "Sign-in was cancelled.",
  expired: "The sign-in took too long. Please try again.",
  state: "The sign-in could not be verified. Please try again.",
  google: "Google sign-in failed. Please try again.",
  unverified: "Your Google account's email is not verified.",
  disabled: "This account has been disabled.",
};

export default function LoginPage() {
  const [params] = useSearchParams();
  const from = (useLocation().state as { from?: Location } | null)?.from;
  const next = from ? `${from.pathname}${from.search}` : undefined;
  const config = useQuery({ queryKey: ["auth-config"], queryFn: api.authConfig });
  const error = params.get("error");

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-5">
        <div>
          <h1 className="text-lg font-semibold">Sign in to Job Search Agent</h1>
          <p className="text-sm text-stone-500">
            New here? Signing in creates your account; then add your resume.
          </p>
        </div>
        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {ERRORS[error] ?? "Sign-in failed."}
          </p>
        )}
        {config.data?.google ? (
          <a
            href={googleLoginUrl(next)}
            className="flex w-full items-center justify-center gap-3 rounded-md border border-stone-300 bg-white px-4 py-2.5 text-sm font-medium text-stone-800 hover:bg-stone-50 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100 dark:hover:bg-stone-800"
          >
            <GoogleMark />
            Continue with Google
          </a>
        ) : (
          config.isSuccess && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
              Google sign-in is not set up on this server yet.
            </p>
          )
        )}
        {config.data?.dev_login && <DevLogin />}
        <p className="text-xs text-stone-500">
          Your resume is used to rank jobs for you. Its text (never your name, email or phone) is
          sent to AI model providers to do this.
        </p>
        <Link to="/" className="block text-center text-sm text-stone-500 hover:underline">
          ← Back to home
        </Link>
      </div>
    </div>
  );
}

/** Local development only: the server enables it with DEV_LOGIN and only for localhost. */
function DevLogin() {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const login = useMutation({
    mutationFn: () => api.devLogin(email),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-2 rounded-md border border-dashed border-stone-300 p-3 dark:border-stone-700">
      <div className="text-xs font-semibold uppercase tracking-wide text-stone-500">
        Dev sign-in (local only)
      </div>
      <input
        type="email"
        placeholder="any@email.test"
        aria-label="Email for dev sign-in"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className={`${inputClass} w-full`}
      />
      {login.isError && <p className="text-sm text-red-600">{login.error.message}</p>}
      <button type="submit" disabled={!email || login.isPending} className={`${buttonClass} w-full`}>
        Sign in
      </button>
    </form>
  );
}

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.1 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

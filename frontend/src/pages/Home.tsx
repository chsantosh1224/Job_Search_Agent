import { Link } from "react-router-dom";
import { buttonClass } from "../components";

// Public page: describes the tool in general terms only. Nothing personal (name, resume,
// jobs) appears here; all of that stays behind the login.

const STEPS = [
  {
    title: "Find",
    text: "Collects remote roles every day from the YC job board, Hacker News “Who is hiring?”, RemoteOK, Remotive and startup career pages on Greenhouse, Lever and Ashby.",
  },
  {
    title: "Filter",
    text: "Keeps AI engineering, agent automation, automation and AI QA / evals roles that are remote, open to candidates in India and match your salary range (in USD).",
  },
  {
    title: "Rank",
    text: "Compares each job with your resume, then an LLM sorts the best matches into three tiers with a fit score, reasons and gaps.",
  },
  {
    title: "Brief",
    text: "Prepares a research brief for the top jobs: what the company does, who to contact, which project to lead with and what to verify.",
  },
];

export default function HomePage({ loggedIn }: { loggedIn: boolean }) {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center px-4 py-4">
        <span className="font-semibold">Job Search Agent</span>
        <Link to={loggedIn ? "/jobs" : "/login"} className={`${buttonClass} ml-auto`}>
          {loggedIn ? "Open dashboard" : "Sign in"}
        </Link>
      </header>

      <main className="mx-auto max-w-5xl px-4">
        <section className="py-12 sm:py-20">
          <p className="mb-3 text-sm font-medium text-violet-700 dark:text-violet-400">
            Personal job search assistant
          </p>
          <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-5xl">
            Finds remote startup jobs worth applying to, and explains why.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-stone-600 dark:text-stone-400">
            An agent that searches funded startups for remote AI and automation roles, ranks them
            against your resume, and prepares the research needed to write a short, personal
            message to the team.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <Link
              to={loggedIn ? "/jobs" : "/login"}
              className={`${buttonClass} px-5 py-2.5 text-base`}
            >
              {loggedIn ? "Open dashboard" : "Sign in"}
            </Link>
            <span className="text-sm text-stone-500">Sign in with Google · add your resume · get ranked matches</span>
          </div>
        </section>

        <section className="border-t border-stone-200 py-12 dark:border-stone-800">
          <h2 className="mb-6 text-xs font-semibold uppercase tracking-wide text-stone-500">
            How it works
          </h2>
          <ol className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((step, i) => (
              <li key={step.title}>
                <div className="mb-2 flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-stone-900 text-xs font-semibold text-white dark:bg-stone-100 dark:text-stone-900">
                    {i + 1}
                  </span>
                  <h3 className="font-medium">{step.title}</h3>
                </div>
                <p className="text-sm text-stone-600 dark:text-stone-400">{step.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="grid gap-6 border-t border-stone-200 py-12 sm:grid-cols-2 dark:border-stone-800">
          <div>
            <h2 className="mb-2 font-medium">What it does</h2>
            <ul className="space-y-1.5 text-sm text-stone-600 dark:text-stone-400">
              <li>• Runs daily and sends an email digest of the best new matches</li>
              <li>• Tracks applications from shortlisted to offer</li>
              <li>• Measures its own ranking quality against hand-labeled examples</li>
            </ul>
          </div>
          <div>
            <h2 className="mb-2 font-medium">What it never does</h2>
            <ul className="space-y-1.5 text-sm text-stone-600 dark:text-stone-400">
              <li>• Apply to jobs or send messages on anyone’s behalf</li>
              <li>• Write outreach messages; those stay personal</li>
              <li>• Scrape sites whose terms forbid it, such as LinkedIn</li>
            </ul>
          </div>
        </section>
      </main>

      <footer className="mx-auto max-w-5xl border-t border-stone-200 px-4 py-6 text-xs text-stone-500 dark:border-stone-800">
        Built with LangGraph, RAG and LLM evaluation · FastAPI · React
      </footer>
    </div>
  );
}

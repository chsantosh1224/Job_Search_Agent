import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  type Location,
} from "react-router-dom";
import { api, type Me } from "./api";
import AdminPage from "./pages/Admin";
import EvalsPage from "./pages/Evals";
import HomePage from "./pages/Home";
import JobDetailPage from "./pages/JobDetail";
import JobsPage from "./pages/Jobs";
import LoginPage from "./pages/Login";
import ProfilePage from "./pages/Profile";
import RunsPage from "./pages/Runs";
import TrackerPage from "./pages/Tracker";
import { useMe } from "./session";

const NAV = [
  { to: "/jobs", label: "Jobs", admin: false },
  { to: "/tracker", label: "Tracker", admin: false },
  { to: "/profile", label: "Profile", admin: false },
  { to: "/runs", label: "Runs", admin: true },
  { to: "/evals", label: "Evals", admin: true },
  { to: "/admin", label: "Admin", admin: true },
];

export default function App() {
  const me = useMe();
  const location = useLocation();

  if (me.isPending) return null;

  if (!me.isSuccess) {
    return (
      <Routes>
        <Route path="/" element={<HomePage loggedIn={false} />} />
        <Route path="/login" element={<LoginPage />} />
        {/* Deep links (e.g. /jobs/12) go to sign-in, then back to where they pointed. */}
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location }} />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<HomePage loggedIn />} />
      <Route path="/login" element={<AfterLogin me={me.data} />} />
      <Route path="*" element={<Dashboard me={me.data} />} />
    </Routes>
  );
}

/** /login once signed in: back to where the user was headed; new users start on Profile. */
function AfterLogin({ me }: { me: Me }) {
  const from = (useLocation().state as { from?: Location } | null)?.from;
  const fallback = me.resume ? "/jobs" : "/profile";
  return <Navigate to={from ? `${from.pathname}${from.search}` : fallback} replace />;
}

function Dashboard({ me }: { me: Me }) {
  const logout = async () => {
    await api.logout();
    window.location.assign("/"); // full reload drops all cached data
  };

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link to="/" className="font-semibold">
            Job Search Agent
          </Link>
          <nav className="flex flex-wrap gap-1">
            {NAV.filter((item) => !item.admin || me.is_admin).map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-md px-2.5 py-1 text-sm ${
                    isActive
                      ? "bg-stone-100 font-medium dark:bg-stone-800"
                      : "text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="hidden text-stone-500 sm:inline">{me.email}</span>
            <button
              onClick={logout}
              className="text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/tracker" element={<TrackerPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          {me.is_admin && <Route path="/runs" element={<RunsPage />} />}
          {me.is_admin && <Route path="/evals" element={<EvalsPage />} />}
          {me.is_admin && <Route path="/admin" element={<AdminPage />} />}
          <Route path="*" element={<Navigate to="/jobs" replace />} />
        </Routes>
      </main>
    </div>
  );
}

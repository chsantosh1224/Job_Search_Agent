# Deploying to Lightsail (jobs.aicruit.in)

The stack runs in Docker next to the invoice agent: Postgres, the API/dashboard (on
`127.0.0.1:8010`), a worker for the daily run and per-user ranking, and a one-shot migration
step. Caddy, which already serves `invoice.aicruit.in`, adds HTTPS for `jobs.aicruit.in`.
Anyone can sign up with Google; see [docs/MULTI_USER.md](docs/MULTI_USER.md) for how users,
limits and admin rights work.

Commands below assume an Ubuntu Lightsail instance with user `ubuntu`; adjust paths if not.

## 1. DNS (GoDaddy)

Add an **A record**: name `jobs`, value = the instance's **static IP** (the same IP
`invoice.aicruit.in` points to), TTL 1 hour. Check it before continuing:

```bash
dig +short jobs.aicruit.in
```

## 2. Get the code and create settings

```bash
cd ~
git clone https://github.com/chsantosh1224/job-search-agent.git
cd job-search-agent
bash deploy/server-setup.sh
```

This adds a 2 GB swap file if there is none and creates `.env.prod` with a generated database
password and session secret. You fill in the rest in the next step.

## 3. Google sign-in

In the [Google Cloud console](https://console.cloud.google.com/):

1. Create a project (e.g. "Job Search Agent").
2. **APIs & Services → OAuth consent screen**: user type **External**; app name, support email,
   and the authorized domain `aicruit.in`. Scopes: `openid`, `email`, `profile` only.
   Then **Publish app** so anyone can sign in (these basic scopes need no Google review).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**: type
   **Web application**, authorized redirect URI
   `https://jobs.aicruit.in/api/auth/google/callback`.

Put the client ID and secret, your admin email and your OpenRouter key in `.env.prod`:

```bash
nano .env.prod
```

```
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
ADMIN_EMAILS=you@gmail.com
OPENROUTER_API_KEY=...
```

## 4. Start it

```bash
bash deploy/deploy.sh
```

It pulls, builds, runs database migrations, starts everything and waits for the health check.

## 5. Sign in and add your resume

After Caddy (next step) is set up, open https://jobs.aicruit.in, sign in with Google using the
admin email, and upload your resume on the **Profile** page. Set your minimum salary there in
**USD**. Ranking for your resume starts within a minute; the first run also downloads the
embedding model (~130 MB) into a cached volume.

## 6. Caddy

Find out how Caddy runs:

```bash
systemctl is-active caddy; docker ps --format '{{.Names}}  {{.Image}}' | grep -i caddy
```

- **Caddy on the host** (`active`): add the block from `deploy/Caddyfile.snippet` to
  `/etc/caddy/Caddyfile`, then `sudo systemctl reload caddy`.
- **Caddy in Docker**: follow the note at the bottom of the snippet (proxy to `172.17.0.1:8010`
  and bind the API port to that address), add the block to the mounted Caddyfile, then
  `docker exec <caddy-container> caddy reload --config /etc/caddy/Caddyfile`.

Lightsail's firewall already allows 80/443 for the invoice agent. Do **not** open 8010.

Open https://jobs.aicruit.in, log in, go to **Runs** and click **Run now**. The first run
fetches everything (about 20–30 minutes) and then ranks with the LLM. After that it runs daily
at 05:00 IST.

## 7. Nightly backups

```bash
chmod +x deploy/backup.sh
(crontab -l 2>/dev/null; echo "30 3 * * * $HOME/job-search-agent/deploy/backup.sh >> $HOME/jobagent-backup.log 2>&1") | crontab -
```

Keeps the last 14 compressed dumps in `~/jobagent-backups`.

## Updating

```bash
cd ~/job-search-agent && bash deploy/deploy.sh
```

## Checking on it

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file .env.prod ps
docker compose -f deploy/docker-compose.prod.yml --env-file .env.prod logs -f worker
docker stats --no-stream        # memory per container; the worker peaks during the daily run
```

## Email digest (later)

1. In Resend, add the domain `jobs.aicruit.in` and add the DNS records it shows at GoDaddy.
2. Once verified, set `RESEND_API_KEY` and `DIGEST_TO` in `.env.prod`, then `bash deploy/deploy.sh`.

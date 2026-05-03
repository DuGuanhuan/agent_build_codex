# VPS Deployment: Docker Compose + Caddy

This deployment runs the demo as three containers:

```text
Internet -> Caddy :443 -> Next.js frontend :3000 -> Python backend :8000
```

The browser only talks to the Next.js app. Next.js route handlers proxy API calls to the backend over Docker's private network at `http://backend:8000`.

## What You Need

1. A VPS with a public IPv4 address.
2. A domain or subdomain, for example `agent.example.com`.
3. DNS `A` record pointing that domain to the VPS IP.
4. Docker and Docker Compose installed on the VPS.
5. Real provider API keys for the models you want to enable.

If you need the Wanqing internal model, the VPS must be able to reach the company internal endpoint. A normal public VPS probably cannot access `wanqing.internal`.

## Server Setup

On a fresh Ubuntu VPS:

```bash
bash deploy/bootstrap_ubuntu.sh
```

Log out and back in so your user can run `docker` without `sudo`.

## Deploy

Clone the repo:

```bash
git clone https://github.com/DuGuanhuan/agent_build_codex.git
cd agent_build_codex
git checkout codex/nextjs-agent-frontend
```

Create production environment variables:

```bash
cp .env.production.example .env.production
nano .env.production
```

At minimum set:

```bash
APP_DOMAIN=agent.example.com
ZAI_API_KEY=...
DEEPSEEK_API_KEY=...
```

Start the stack:

```bash
docker compose up -d --build
```

Or use the Makefile wrapper:

```bash
make deploy-up
```

Check status:

```bash
docker compose ps
docker compose logs -f
```

Caddy will request and renew HTTPS certificates automatically once DNS points to the VPS and ports `80`/`443` are reachable.

## Update Deployment

```bash
git pull
docker compose up -d --build
docker image prune -f
```

Or:

```bash
bash deploy/update.sh
```

## Useful Operations

Restart everything:

```bash
docker compose restart
```

Restart only the backend:

```bash
docker compose restart backend
```

Read backend logs:

```bash
docker compose logs -f backend
```

Read frontend logs:

```bash
docker compose logs -f frontend
```

Stop the stack:

```bash
docker compose down
```

## Security Notes

This stack keeps model API keys on the backend container and never exposes them to the browser.

Before sharing the link widely, add at least one of:

```text
- Caddy basic auth
- App-level demo password
- Real Supabase/Auth login
```

The current tool system can read files inside the deployed container workspace. Do not mount your VPS home directory into the backend container unless you intentionally want the agent to access it.

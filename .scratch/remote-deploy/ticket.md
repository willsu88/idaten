---
title: Remote deploys while away from the server for 2 weeks
labels: [research, needs-grilling]
status: open
created: 2026-08-15
blocked-by: []
---

# Remote deploys while away from the server

Research into how to keep the server Mac serving and deploy new versions remotely from a laptop for 2 weeks.
All claims cite primary sources fetched 2026-08-15.

## What exists today (grounding)

- `start.sh` is both the test gate and the deploy path (ADR 0001, `docs/adr/0001-start-sh-is-the-test-gate.md`): backend pytest + frontend vitest run on the server host, then `docker compose up -d --build`.
- Both images are built locally: `docker-compose.yml` uses `build: ./backend` and `build: ./frontend` with no `image:` keys, so nothing is pulled from a registry today.
- The app is already exposed through a Cloudflare named tunnel run by the host `cloudflared` binary (`start.sh` `named` mode), so a Cloudflare account and `cloudflared` are already set up.
- `start.sh` already runs `caffeinate -dims` to prevent idle sleep.
- `.scratch/ci-test-workflow/ticket.md` already proposes a tests-only GitHub Actions workflow, with the open question of whether backend tests are hermetic.
- `backend/pytest.ini` excludes evals by default (`addopts = -m "not eval"`), so a plain `pytest` run in CI is free and does not call a model.

## The zero-migration baseline

Before any CI/CD machinery: if the laptop can SSH to the server, `git pull && ./start.sh` over SSH is exactly today's deploy, tests and all, run remotely.
This requires only the remote-access piece (below) and changes nothing about ADR 0001.
Everything else in this ticket is optional improvement on top of that, and the recommendation section weighs it accordingly.

## Option 1: build in GitHub Actions, push to ghcr.io, server pulls

### CI build side

- GitHub Actions is free and unlimited for public repositories on standard GitHub-hosted runners: "GitHub Actions usage is free for self-hosted runners and for public repositories that use standard GitHub-hosted runners" (https://docs.github.com/en/billing/managing-billing-for-your-products/about-billing-for-github-actions).
- The server is Apple Silicon, so images must be linux/arm64.
  GitHub now offers hosted arm64 Linux runners (`ubuntu-24.04-arm`, `ubuntu-22.04-arm`, `ubuntu-26.04-arm` in public preview), free on public repos, so no QEMU cross-build is needed (https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
- Pushing to ghcr.io from a workflow uses the built-in `GITHUB_TOKEN`; the package auto-links to the repo and the `org.opencontainers.image.source` label is the recommended way to establish that link (https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
- Pulling a private ghcr.io image from the server needs `docker login ghcr.io` with a PAT that has the `read:packages` scope (same URL).
  If the packages are public (viable for a public-facing repo), no pull auth is needed at all.
- Migration work in the compose file: add `image: ghcr.io/<owner>/idaten-backend:<tag>` (and frontend) keys; the deploy command on the server becomes `docker compose pull && docker compose up -d` instead of `up -d --build`.
  The frontend build arg `BACKEND_URL` bakes into the image at build time, so it moves into the CI build step.

### Pull side, candidate mechanisms

#### Watchtower

- The original `containrrr/watchtower` was archived on 2025-12-17 and is read-only; its README says "This project is no longer maintained" and it never recommended itself for production (https://github.com/containrrr/watchtower).
- There is an actively maintained fork, `nicholas-fedor/watchtower`: not archived, last push 2026-08-14, latest release v1.20.3 on 2026-08-05, ~4.3k stars (https://github.com/nicholas-fedor/watchtower).
- The fork keeps label-based scoping: with `--label-enable`, only containers labeled `com.centurylinklabs.watchtower.enable=true` are monitored (https://watchtower.nickfedor.com/v1.20.3/configuration/container-selection/).
- The fork supports private-registry auth via `REPO_USER`/`REPO_PASS` env vars or a mounted Docker `config.json` selected with `DOCKER_CONFIG` (https://github.com/nicholas-fedor/watchtower/blob/main/docs/configuration/registry-and-authentication/index.md).
- Caveat: Watchtower recreates containers itself, outside compose; `docker compose up` afterwards can fight it if the compose file changed.
  It updates on image change only, so compose-file changes (env vars, ports, new services) still need a manual `compose up` on the server.

#### GitHub Actions self-hosted runner on the server (rejected)

- macOS self-hosted runners are supported (macOS 11+, arm64 supported) (https://docs.github.com/en/actions/reference/runners/self-hosted-runners).
- But GitHub's hardening guide is unambiguous: "Self-hosted runners should almost never be used for public repositories on GitHub, because any user can open pull requests against the repository and compromise the environment" (https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions).
- This repo is public-facing, and the runner would sit on the machine holding the live DB and Garmin OAuth tokens.
  Fork PRs need approval before running by default, but the blast radius of a mistake is the production data, so this option is out.

#### Other pull-side tools

- Cron/launchd on the server running `docker compose pull && docker compose up -d` every N minutes: zero new software, fully inside compose semantics, but polls blindly and gives no feedback to the laptop.
- Diun: notification-only; it "helps you keep track of container image updates" and notifies (webhook, ntfy, Slack, etc.) but never updates containers; active, v4.33.0 2026-05-30 (https://crazymax.dev/diun/, https://github.com/crazy-max/diun).
  Pairs with a script: Diun fires a script/webhook, the script runs `compose pull && up -d`.
- Shepherd: Docker Swarm services only, so not applicable to this compose stack; last release v1.8.1 2025-11-11 (https://github.com/containrrr/shepherd).
- Komodo: a core web server plus small stateless "Periphery" agents; defines compose stacks "in the UI, on the host, or in a git repo with auto-deploy on push", i.e. GitHub-webhook-driven deploys; active, v2.3.2 2026-08-11, ~12k stars (https://komo.do/docs/intro, https://github.com/moghtech/komodo).
  Real capability, but it is a whole management plane (its own DB, auth, agent) for a one-server one-app setup, and the Periphery agent targets Linux hosts; running core+agent on macOS Docker is uncharted.
- Dockge: a compose-stack web UI by the Uptime Kuma author; last release 1.5.0 2025-03-30, last push 2026-04-25, so drifting toward dormant (https://github.com/louislam/dockge).
- Portainer stack webhooks: hitting the webhook URL redeploys the stack with the latest image, but "This functionality is only available in Portainer Business Edition" (https://docs.portainer.io/user/docker/stacks/webhooks).
  CE does have per-container webhooks, but the stack-level redeploy that matches this use case is paywalled.

## Option 2: local Kubernetes - honest assessment

- k3s runs on Linux only ("K3s is expected to work on most modern Linux systems"), so on macOS it needs a Linux VM anyway (https://docs.k3s.io/installation/requirements).
- Docker Desktop ships an optional single-node (kubeadm) or multi-node (kind) cluster running inside Docker Desktop, so it inherits Docker Desktop's session lifecycle (https://docs.docker.com/desktop/features/kubernetes/).
- OrbStack ships "a lightweight single-node Kubernetes cluster optimized for development" (https://docs.orbstack.dev/kubernetes/).
- minikube is explicitly a learn/dev-focused local Kubernetes (https://minikube.sigs.k8s.io/docs/).
- Verdict: every macOS option is a dev-oriented cluster inside a VM on top of the same single machine.
  Kubernetes would buy declarative deploys and image-pull automation, but at the cost of translating the compose file to manifests, learning/operating a control plane, and the SQLite volume + Garmin token dir still living on the one node.
  For a single-node, single-user app, the operational surface grows far more than the capability does.
  Not worth it; even the archived Watchtower README's "use k3s instead" advice assumes Linux hosts (https://github.com/containrrr/watchtower).

## Option 3 wrinkle: the test gate must move to CI

Registry-based deploys mean the artifact is built before it reaches the server, so the server-side pytest/vitest gate no longer guards what actually ships.
Conceptually the migration is:

- Amend ADR 0001: the gate moves from "start.sh on the host" to "CI must be green before the image is pushed" - the workflow runs pytest + vitest and only builds/pushes images on success, so a red test never produces a pullable image.
  This is a bigger amendment than the one `.scratch/ci-test-workflow` already contemplates (that ticket keeps CI as hygiene, not the gate).
- Resolve that ticket's open question first: backend tests must be hermetic (no live SQLite, no Garmin credentials, no running stack) or split with a marker so CI runs only the hermetic set.
- Evals stay out of CI by default (`pytest.ini` already excludes `-m eval`), so CI stays free; paid eval runs remain a manual/local step.
- `start.sh` splits into build-time and run-time concerns: the test gate and `--build` leave; caffeinate, `compose pull && up -d`, and the tunnel stay in a server-side deploy script.
- The gate then tests the commit, not the working tree, which closes the "forgot to git add" hole ADR 0001 explicitly documents as invisible today.
- What is lost: `SKIP_TESTS=1` hotfixes become "push a commit and wait for CI + build" unless a manual-dispatch fast path is kept; and the gate no longer runs in the exact deploy environment.

## Remote access from the laptop

### Tailscale

- Tailscale on macOS comes in three variants: Standalone (recommended), Mac App Store, and open-source `tailscaled` CLI; only `tailscaled` can run before login as a daemon and only `tailscaled` "can be a Tailscale SSH server", and Tailscale recommends `tailscaled` "only ... for unattended installs managed by experienced macOS system administrators" (https://tailscale.com/kb/1065/macos-variants).
- Tailscale SSH server therefore does not work with the normal macOS app; the practical macOS pattern is the Standalone app for the tailnet plus macOS's built-in Remote Login (OpenSSH) for the SSH layer (https://tailscale.com/kb/1193/tailscale-ssh).
- Connecting as a client works from any platform (same URL), so the laptop side is trivial.
- Caveat: the Standalone/App Store variants require a logged-in user, which ties into the unattended-Mac section below - but that constraint already exists for Docker Desktop.

### Plain SSH

- macOS Remote Login (System Settings sharing) is a stock OpenSSH server; combined with Tailscale it needs no port forwarding at all.
- Raw internet-exposed SSH port-forwarding on a home router is strictly worse than either Tailscale or cloudflared and is not recommended.

### cloudflared SSH

- Cloudflare documents four ways to SSH over a tunnel: client-side `cloudflared` (ProxyCommand, "works with just cloudflared on both ends"), Access for Infrastructure with short-lived certs, self-managed SSH keys, and a browser-rendered terminal that needs no client at all (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/use-cases/ssh/).
- Attractive here because `cloudflared` and the Cloudflare account already exist for the app tunnel; adding an SSH ingress hostname to the existing named tunnel is incremental config.

### Unattended-macOS caveats

- Docker Desktop's autostart is the setting "Start Docker Desktop when you sign in to your computer" - it runs inside a user login session, not as a system service (https://docs.docker.com/desktop/settings-and-maintenance/settings/).
  So after a power failure or reboot, containers do not come back until a user session exists.
- Automatic login closes that gap: System Settings -> Users & Groups -> "Automatically log in as", but it is unavailable when FileVault is on, when an MDM profile prohibits it, or when the account logs in with an Apple Account password, and it lets anyone with physical access in by restarting (https://support.apple.com/en-us/102316).
  Decide explicitly whether disabling FileVault on the server is acceptable given the health data on disk.
- Colima is the headless alternative: a CLI-only container runtime ("container runtimes on macOS with minimal setup") that is docker-CLI compatible; its FAQ documents autostart via `brew services start colima` (foreground mode via `--foreground` since v0.5.6) (https://github.com/abiosoft/colima, https://colima.run/docs/faq/).
  Actively maintained: last push 2026-08-13, v0.10.3 released 2026-06-04 (https://github.com/abiosoft/colima).
  Note `brew services` still installs per-user launchd agents by default, so a login session at some point is still involved unless run as root/system; and switching runtimes mid-trip is exactly the kind of change not to make the week before leaving.
- Power: `caffeinate -dims` from `start.sh` already prevents idle sleep while it runs; additionally set System Settings to never sleep on power and enable "Start up automatically after a power failure" so the box returns after an outage (verify the setting exists on this hardware; then auto-login + Docker Desktop autostart completes the chain).

## Comparison and recommendation

| Approach | New moving parts | Deploy latency | Gate location | Risk |
| --- | --- | --- | --- | --- |
| SSH in, `git pull && ./start.sh` | remote access only | ~2 min tests + build on server | unchanged (ADR 0001) | lowest |
| CI build -> ghcr -> cron/Diun-script pull | CI workflow, compose `image:` keys, pull script | CI build + poll interval | must move to CI | medium |
| CI build -> ghcr -> Watchtower fork | same + Watchtower container | CI build + poll interval | must move to CI | medium, third-party updater |
| Komodo / Portainer / Dockge | a management plane | varies | must move to CI | high for one app; Portainer stack webhooks are paid |
| Self-hosted runner on server | runner on prod box | fast | stays local-ish | rejected: GitHub warns against runners on public repos |
| Local Kubernetes | VM + control plane + manifest rewrite | high | must move to CI | highest, no matching benefit |

Recommendation for the 2-week window: do the smallest thing that works.

1. Set up remote access now: Tailscale Standalone on both machines plus macOS Remote Login, or an SSH ingress on the existing named cloudflared tunnel.
   Both are primary-source-supported on macOS; Tailscale is less config since the tunnel already serves the app.
2. Harden the unattended Mac: never-sleep on AC, start-after-power-failure, and decide the FileVault vs auto-login trade-off; keep Docker Desktop's "start when you sign in" enabled.
3. Deploy over SSH with `git pull && ./start.sh`, unchanged.
   This keeps ADR 0001 intact and adds zero new failure modes while away.

Registry-based CI/CD (Actions arm64 build -> ghcr -> pull) is the right long-term direction if deploys should survive the server being the only builder, but it forces the ADR 0001 amendment and the test-hermeticity work first.
Treat it as its own ticket after `.scratch/ci-test-workflow` ships and the hermeticity question is answered, not as something to stand up remotely mid-trip.
If it is built later, the pull side should be either a dumb server-side poll script or the `nicholas-fedor/watchtower` fork with `--label-enable` - the original Watchtower is archived and must not be used.

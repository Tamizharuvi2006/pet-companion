# Bella Phase 2F — GitHub-to-Railway Release Preflight

**Review date:** 2026-11-15

**Project:** `D:\final year project\backend`

**Decision:** **PREPARED FOR OWNER AUTHORIZATION — STOPPED BEFORE STAGING, COMMIT, AND PUSH.**

This is a GitHub-to-Railway preflight. Railway is expected to build the Dockerfile on its infrastructure. A local Docker installation/build is not required and was not attempted. No Railway settings or deployment were accessed or changed; no paid provider calls or hardware actions were performed.

## Repository and manifest review

- The local branch is `main`, tracking `origin/main`; local `HEAD` and `origin/main` were both `f3fb0e5` during this audit. The configured Git remote host is GitHub.
- The Phase 2E proposed manifest contains **107 paths** and matched the 107 current non-ignored worktree paths exactly before this report was added. No paths were staged.
- The Phase 2F report is the sole additional proposed source path. The prospective commit is therefore the exact 107 Phase 2E paths in `BELLA_PHASE2E_RELEASE_CANDIDATE.md` plus this document (**108 paths total**), subject to the owner's final review.
- No `.env`, `.venv`, `.pio`, `managed_components`, `artifacts/phase2e` binaries/archive, generated PPM snapshots, or cache paths are in that manifest. `.gitignore` excludes local artifacts; `.dockerignore` excludes `.env`, firmware and artifacts from the Railway Docker context.
- The two ESP-IDF `dependencies.lock` files are included as dependency pins; downloaded `managed_components` vendor trees are excluded. They are not interchangeable.
- A credential-pattern scan of the proposed text/source files found **zero matches** for provider/API-key patterns or private-key blocks. Secret values were not read or printed. The local `.env` remains ignored; only the documented template files belong in source control.
- All 107 files are present for review and the tested source paths passed; this is not a claim that every change has been independently approved by the owner. Nothing has been staged, committed, or pushed.

## Railway compatibility and safety checks

| Item | Local evidence | Result / limit |
|---|---|---|
| Python version | Dockerfile is `python:3.12-slim`; local project venv reports Python 3.12.13 | **Verified statically and locally** |
| Railway port binding | Docker command uses `0.0.0.0` and `${PORT:-8000}` | **Verified statically**; Railway supplies `PORT` |
| Worker count | Docker command uses `--workers 1` | **Verified statically** |
| Healthcheck | Docker healthcheck targets `/health`; service route is present | **Verified statically/tests** |
| Startup Whisper work | Dockerfile defaults `WHISPER_PRELOAD_ENABLED=false` and `WHISPER_INTERIM_ENABLED=false` | **Verified**; startup avoids local model downloads/interim CPU inference unless Railway Variables override these values |
| Normal voice mode | App defaults both one-shot test modes off; `.env.example` sets both false; local settings report `voice_test_mode=disabled` | **Verified locally**; no provider request was made |
| Browser authentication | Public mode requires `BELLA_ACCESS_PASSWORD`, `BELLA_SESSION_SECRET`, and exact HTTPS `BELLA_ALLOWED_ORIGINS`; session cookie is HttpOnly/Secure/SameSite=Strict | **Code and tests verified**; actual Railway values/domain not inspected |
| Device tokens | `BELLA_DEVICE_TOKENS` maps device IDs to tokens; device checks use constant-time comparison and authenticated WebSocket/HTTP paths | **Code and tests verified**; token values were not read |
| Camera exposure | Camera defaults disabled; public camera transport requires HTTPS and a configured dedicated token | **Code and tests verified**; leave disabled until route is approved |
| Replica count | Process-local registry, rate limits, and commands require one active replica | **Documented requirement**; Railway topology cannot be observed locally |
| GitHub/Railway connection | Local `origin` is on GitHub and current branch tracks `origin/main` | The Railway-linked branch/autodeploy setting **still needs dashboard confirmation** |

Important precedence note: the checked-in `.env.example` has local development preload/interim values enabled. It is not copied into the Docker context (`.env` is excluded); the production Dockerfile defaults both settings off. Railway Variables can override image defaults, so verify that these two variables are absent or explicitly false in the Railway service before deployment. No Railway variable values were inspected here.

## Test results

- Full suite, including browser, security, device simulation and native C++ checks: **100 passed, 42 warnings, 64.60 s** on the final run. Tests use fakes/local generated audio; no paid provider calls were made.
- One earlier full-suite attempt had 99 passes and one infrastructure failure when WSL failed to translate a temporary path during a native C++ test. A WSL smoke check succeeded; the focused expression/native suite then passed **10 tests**, and the subsequent full run passed all 100. No source change was made for that transient WSL startup failure.
- Python compilation under the Python 3.12 project venv: **passed**.
- `git diff --check`: **passed**; Git printed expected LF/CRLF conversion notices, not whitespace errors.
- No Docker command/build was run, as requested. This does not block a GitHub-triggered Railway build; only Railway's actual build log can establish hosted build success.

## Proposed commit and push plan — not executed

Before release, confirm in Railway that the service is connected to `origin/main` and that autodeploy behavior is understood. A push may start a production deployment.

After explicit owner authorization only:

1. Stage exactly the 107 paths enumerated under “Proposed source commit manifest” in `BELLA_PHASE2E_RELEASE_CANDIDATE.md`, plus `docs/BELLA_PHASE2F_GITHUB_RAILWAY_RELEASE.md`. Do not stage `.` or any other path.
2. Review `git diff --cached --check`, `git diff --cached --stat`, and `git diff --cached --name-only`; confirm the staged list contains only those 108 paths. Re-run the approved tests if the staged tree differs from this reviewed tree.
3. Suggested commit subject: `Prepare Bella Phase 2E GitHub/Railway release`.
4. Push the reviewed commit to `origin main` (`git push origin main`) only after confirming `main` is the Railway-connected deployment branch.
5. If authorized and access is available, observe the GitHub-triggered Railway build; verify deployed commit SHA, build result, `/health`, browser login/authenticated features, worker/replica settings, and the Whisper variable overrides. Do not run voice/chat requests or flash hardware.

No commit, push, staging, deployment, paid request, secret change, or hardware operation occurred during this preflight. Railway deployment status, service variables, actual build logs, health, and topology require owner/dashboard access after authorization.

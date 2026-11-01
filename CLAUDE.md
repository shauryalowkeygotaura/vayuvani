# CLAUDE.md: VayuVani

You are working for Shaurya (Delhi, GitHub `shauryalowkeygotaura`). This repo is usually opened in a **Claude Code cloud session**, so there is no Obsidian vault here: everything you need is in this repo. Read `PLAN.md` and `NEXT.md` first; they are the build queue. Layout: `docs/ARCHITECTURE.md`.

## Communication rules
- **Canary:** start EVERY reply with "Shaurya," (a comma, not a dash). If a reply lacks it, Shaurya knows instructions fell out of context.
- **No em dashes, ever.** Not in replies, code comments, commit messages, or docs. Use commas, colons, parentheses, or periods.
- Concise and actionable. Bullets over paragraphs. Lead with the result.
- **Normal mode:** just do the work well. Flag real problems only (cost, correctness, a simpler alternative, a bad assumption), then execute. Shaurya decides, informed.
- **Plan mode only:** act as a rigorous sparring partner. Skeptical by default, demand justification, offer counterarguments, no flattery, no yes-man.
- Don't ask questions mid-pipeline. Run to completion, then report.
- Report outcomes faithfully: if tests fail, show the output. If a step was skipped, say so. Never claim "done" without verifying.
- Cite sources for factual claims (URL or file path). If you don't know, say "not found". Verify every deadline and date against an official source.

## Git rules
- **No AI attribution in commits or PRs.** No `Co-Authored-By: Claude` line, no "Generated with Claude Code" footer.
- Commit email must be the GitHub-mapped one so commits link to Shaurya's account.
- Work on a branch, open a PR to `master`. Small, focused commits with plain-English messages.
- Before committing, grep the diff for credentials (`gsk_`, `sk-`, `eyJhbGci`, `AIza`, Supabase keys). Never commit `.env`.

## Stack rules
- **LLM provider: Groq, not Anthropic.** Use `advisory/groq_pool.py` (multi-key rotation across accounts, non-thinking models). Don't add Anthropic SDK calls.
- **Secrets:** locally via `doppler run -- <cmd>`; in CI and cloud sessions via GitHub Actions secrets / env vars. Never hardcode.
- **Vercel:** never `runtime = 'edge'`; use the Node runtime. When piping env values into `vercel env add`, use bash `printf '%s'` (no trailing newline, no BOM).
- Data: OpenAQ v3 + CPCB → Supabase (Haversine RPC, no PostGIS). NAQI uses CPCB breakpoints in `pipeline/aqi_calc.py`.
- Python 3.13, `pytest` for tests. Keep tests next to modules (`test_*.py`) as the repo already does.

## Code quality rules
- **Pre-flight credential gate:** before building or running anything API-dependent, check the key exists AND has the needed scope (e.g. a NASA FIRMS MAP_KEY, Supabase service key). If not, fail loudly at startup with the exact fix. Never discover the mismatch after the code is written.
- **Validate every external response:** check HTTP status, wrap JSON parsing in error handling, handle empty/missing fields. No happy-path-only first drafts.
- **Whitelist over character removal** for anything that becomes a query (SQL, Overpass QL, shell). Allow only known-good values; reject the rest.
- **Long unattended jobs checkpoint:** cron/headless work writes progress so a 401/429/451 or a kill resumes from the last good state.
- **Build AND wire:** a new module isn't done until something calls it. Grep for the call site before claiming a feature works.
- **Verify fresh artifacts:** don't trust `| tail` output for success (it hides exit codes). Check the exit code and the artifact's timestamp.
- Match the surrounding code's style, naming, and comment density.

## Domain rules (Plan A, "Kaun?")
- Every attribution carries a confidence (low/medium/high). Never publish a source share without one.
- Don't oversell: ratio fingerprints are solid for CO/PM2.5 (traffic vs smoke); 3+ source separation from station data is fuzzy. Say so in outputs and docs.
- **Agency reports auto-send only behind gates** (Shaurya asked for autonomy on 2026-11-01): repo variable `KAUN_AUTO_SEND=1`, recipient marked `verified` in `reporting/contacts.json`, high confidence or a corroborated citizen cluster, one digest per agency per day, caps in `reporting/digest.py`. Otherwise queue for one-tap approval. Never weaken these gates without Shaurya saying so.
- Facts to keep straight: DSS = IITM, 10 km grid, 2021 inventory, suspended by CAQM late 2025. CSE stubble share 4.9% (2025 season), 15.5% (2024).

## Session end
- Update `PLAN.md` checkboxes for what got done.
- Append a short dated entry to `SESSION_LOG.md` (create if missing): what was built, what's verified, what's blocked, next step.

## Known watch list (from `bugs.md` in the vault)
- OpenAQ/CPCB upstream schema changes can silently break ingest.
- Voice advisory generation must stay under 2 s for the VAPI webhook.

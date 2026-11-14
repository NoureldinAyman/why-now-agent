# Why-Now Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the agent in `design.md` in full: daily job ad reading, judging, fact-checked briefs, human decisions, a self-improving loop with an honest score, Langfuse tracing, a daily run on AWS, and public pages, runnable by anyone who clones the repo.

**Architecture:** Plain Python. Fixed steps are normal code, and AI is used only where judgement is needed. All outside services sit behind small swappable parts (job sources, page reader, AI models, store, tracing), so tests and the sample run need no network or keys. Code lives in the repo, and everything a run produces lives in a separate workspace.

**Tech Stack:** Python 3.13, uv, pytest, ruff, pyright, pydantic, httpx, typer, PyYAML, FastAPI with Jinja2, `anthropic`, `typesafe-sdk` (optional), `langfuse` (optional), boto3, AWS CDK in Python, Docker.

**Spec:** `design.md`. Executors read it first, along with `GLOSSARY.md`. Use the glossary's words in code and text.

## Global Constraints

- **Repo:** `NoureldinAyman/why-now-agent`, public, MIT licence. Description: "An agent that reads public job ads, judges each company against a written profile, and writes a fact-checked brief for a person to approve. It improves its own rules overnight and keeps a change only if its score rises."
- **Commit identity (this repo only):** name `NourEldin Ayman`, email `97467977+NoureldinAyman@users.noreply.github.com`. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Before any create or push:** `gh api user --jq .login` must print `NoureldinAyman`.
- **Nothing a run produces is ever committed.** Real job ads, evidence packs, test cases, marks, decisions, rules files and scores stay in the workspace.
- **The `private/` folder is never committed.** No public file, commit message or instruction file may refer to its contents or to why anything is private.
- **No code, test or setting may name a product.** Example profiles are plain files that can be deleted without breaking anything.
- **Every number from "Every number, and why" in `design.md` is a setting,** never fixed in code. Any new number gets a setting and a line in that table saying what it protects and where it came from.
- **Never send an email or message to anyone.** The job sources' endpoints for submitting applications are never called.
- **LinkedIn is never read,** for search or for pages.
- **Only real, measured numbers in anything public.** Estimates stay out of public text.
- **Public text is plain and modest, with no em dashes.** The README describes the project, not who did which part.
- **The owner enters all keys and card details.** No agent types them anywhere. Secrets come from the environment, or from Parameter Store on AWS.
- **Live calls cost money.** Anything marked `live` runs only on purpose and counts against the budget.

## Review Focus

Failure modes `design.md` implies but doesn't spell out. Each has a test in the task named.

1. **A job source is down for a whole day.** Every board fails at once. Expected: the run reports an outage and no board moves towards being set aside (Task 5).
2. **The reviewer goes away for two weeks.** Expected: undecided companies stay on the short list at no new cost, the list never grows past its limit, and no new research is paid for while it is full (Task 20).
3. **A model returns bad output:** a missing question, a probability outside 0 to 1, or a refusal. Expected: one retry, then the company is recorded as failed. It is never silently counted as a no in a score (Task 16, Task 18).
4. **A real quote looks different from the saved page:** curly quotes, non-breaking spaces or dash styles. Expected: the fact check accepts it, and a changed word still fails (Task 19).
5. **The browser sends the same form twice, or an ad contains HTML or script.** Expected: one record only, and ad text shows as plain text and never runs (Task 13).

## Decisions This Plan Adds

These fill gaps in `design.md` and follow its intent. Add each to the design's table or text when its task lands.

- **Undecided companies carry over.** They stay on the short list until decided, count towards its limit, and are not researched again. Research stops for the day when the list is full.
- **Answers are saved per question.** A saved answer is keyed by evidence pack, question text and model, so a try only pays for a new or edited question. This also makes check pile runs repeatable.
- **The fact check also ignores typographic differences,** using Unicode normalisation and treating curly quotes and dash styles as plain ones. Words must still match.
- **Language and country filters** use the job source's own fields. An ad with no language field is kept.
- **Fixed monthly costs.** AWS and Langfuse have no per-call meter, so the owner sets an expected monthly figure that counts towards the $70 limit.

## Revision of 8 Nov 2026

`design.md` was revised on 8 Nov 2026, after 22 tickets were built. This section overrides any task below where they disagree. Read the design's "Revision of 8 Nov 2026" first. Ticket numbers here are GitHub ticket titles; the plan's own task numbers are given in brackets where they differ.

### What changes in work already built

- **Score.** `ScoreResult.f05` becomes `ScoreResult.f` plus `beta`. `score(rows, beta)` takes `settings.score_beta`, default 1. `choose_cutoff` and `decide_keep` use `.f`.
- **Saved answers.** `workspace/judge.py` `_answer_key` and `pipeline/quick_look.py` `_key` include effort and a prompt version. The cut-off key becomes per model and effort. No old answers are moved: the workspace holds no real marks yet.
- **Piles.** `testset/piles.py` `split_piles`, `PilesFrozen` and `refresh_check_pile` are replaced by a pile decided at pick time. `yes_share`, `pick_repeats` and the repeat page stay.
- **Marking page.** It shows a card built from the pack, takes one-tap answers and accepts a reason chip in place of text (`form_error` changes to match).

### Task R1 (ticket 41): F1 score

**Files:** modify `evaluation/score.py`, `pipeline/judge.py`, `improve/keep.py`, `settings.py`, `examples/settings.example.toml`. Tests: `tests/evaluation/test_score.py`, `tests/improve/test_keep.py`, `tests/pipeline/test_judge.py`.

```python
class ScoreResult(BaseModel):
    tp: int; fp: int; fn: int; tn: int; n: int
    precision: float; recall: float; f: float; beta: float
def score(rows: list[tuple[bool, bool]], beta: float) -> ScoreResult: ...
```

Tests: worked examples for beta 1 done by hand; beta 0.5 still gives the old numbers; saying no to everything scores 0; `decide_keep` compares `.f`; refusing two results with different beta in one keep decision.

### Task R2 (ticket 42): Effort per job, and versioned saved answers

**Files:** modify `settings.py`, `ai/__init__.py`, `ai/claude.py`, `workspace/judge.py`, `workspace/quick_look.py`, `pipeline/quick_look.py`, `pipeline/judge.py`, `tracing.py`. Tests alongside.

- Settings: `quick_look_effort = "low"`, `research_effort = "medium"`, `judge_effort = "medium"`, `writer_effort = "medium"`, `proposer_effort = "high"`. Each a line in the design's numbers table (already added).
- `ClaudeCaller` sends `output_config={"effort": ...}` for its job. Check the current `anthropic` documentation with the claude-api skill first.
- Each system prompt gets a constant version, such as `ANSWER_PROMPT_VERSION = 1`. A model's `answer_key` is `f"{model}@{effort}#p{prompt_version}"` (Jev has no effort: `f"{model}#p{prompt_version}"`). Saved answers and cut-offs use it.
- Traces record effort and prompt version per model.

Tests: the request carries the job's effort; changing the effort or the prompt version asks again; the same values reuse the saved answer; a cut-off saved for one effort is not used for another.

### Task R3 (ticket 43): Piles fill as companies are marked

**Files:** modify `testset/piles.py`, `testset/picking.py`, `workspace/cases.py`, `workspace/piles.py`, `domain.py` (`CaseRecord.pile`), `cli/piles.py`. Tests: `tests/testset/test_piles.py`.

```python
def pile_for(seed: int, company_key: str, settings: Settings) -> Literal["practice", "check", "final"]: ...
def pile_report(workspace: Workspace) -> PileReport: ...  # per pile: cases, marked, yes, no, can't tell
def loop_ready(report: PileReport, settings: Settings) -> bool: ...  # check yes >= floor_yes_per_pile
```

- `pile_for` hashes the seed and key, and maps the result to piles in the ratio `practice_size : check_size : final_size`. The pile is stored on the case when it is picked.
- `why-now piles --profile P` prints the report. `split-piles` is removed.
- Remove the frozen flag. Keep `yes-share`, `repeat-marks` and `agreement`.

Tests: the same seed and key always give the same pile; over 10,000 keys the shares match the ratio within 2 points; the pile does not depend on marks, marking order or can't-tell answers; a company is in one pile only; `loop_ready` is false below the floor.

### Task R4 (ticket 44): Prepare and quick marking

**Files:** modify `testset/packs.py`, `cli/testset.py`, `web/routes_marking.py`, `web/routes_repeat.py`, templates, `domain.py` (`Mark.chips`, `Mark.seen_on_list`), `settings.py` (`prepare_batch = 20`, `reason_chips`). Tests alongside.

```python
def prepare(ctx: RunContext, profile: Profile, n: int, seed: int) -> BuildResult: ...  # pick n, decide piles, research each
def card(case: CaseRecord, pack: EvidencePack) -> Card: ...  # built by code from the pack only
```

- `why-now prepare --profile P --n 20` and a "Prepare" button on the marking page (on one's own computer).
- The card: company name, relevant job titles with counts, open jobs, newest ad date, the first 400 characters of the first non-ad source in the pack. The full pack opens below it.
- One-tap yes, no, can't tell. A reason is one or more chips or a sentence; at least one is required. The chips are a setting with generic defaults (recruitment agency, competitor, not hiring the right people, too big, too small, good timing).
- A mark records `seen_on_list` when the company was on a short list or more list before it was marked.
- The repeat page uses the same card, and the marking page shows a nudge when a repeat round is possible.

Tests: the card shows nothing outside the pack and no agent answer; a chip alone is a valid reason; nothing at all is refused; `seen_on_list` is set for a listed company; prepare stops cleanly at the budget and reruns pay for nothing twice.

### Task R5 (ticket 45, owner builds with Claude): Draft a profile

**Files:** create `src/why_now/drafting.py`, `cli/profile.py`; modify `profile.py`, `domain.py` (`quick_look_questions` optional, `Profile.version`). Tests alongside.

```python
def draft_profile(description: str, writer: Writer) -> Profile: ...
def quick_look_questions(profile: Profile) -> list[FitQuestion]: ...  # the profile's, or required ones plus one built from who uses the product
def preview(workspace: Workspace, profile: Profile) -> Preview: ...  # search on the last saved read, no paid calls
```

- `why-now draft-profile --out PATH` asks for a description, drafts, and writes YAML that `load_profile` accepts. The draft must name no product in code, and its questions follow the existing rules (one condition each).
- A profile's version is a hash of what it says. Scores record it. After the first mark, the web form warns that saving starts a new version.

Tests: a scripted writer's draft loads; a missing quick look list gives the derived one; preview makes no paid call; editing the profile changes its version.

### Task R6 (ticket 46): Control pages

**Files:** modify `web/app.py`, create `web/routes_control.py`, templates; modify `settings.py` (a description for every setting). Tests alongside.

- "Run now" (on one's own computer only) starts `why-now daily` as a separate process on the last saved read or a sample, and the page shows whether it is running and its last result.
- A setup status page from `check_setup`.
- A read-only settings page showing each setting, its value and its reason. A test fails if a setting has no description.
- A profile form over `draft_profile` and `preview`.
- "Improve now" appears once the improvement run exists.

Tests: run now is refused on AWS; the settings page lists every setting with a description; the pages escape every value and need the login.

### Changes to existing tickets

- **Ticket 15, owner:** draft the profile with R5, accept it, then prepare and mark the first 40. Blocked by R4 and R5.
- **Ticket 16, owner:** keep marking in sittings until `loop_ready`. The repeat round is optional.
- **Ticket 20 [Task 18], owner builds with Claude:** `compare_judges` compares only Jev and Sonnet at `judge_effort`. Add `consistency(run, answerer, packs, asks=5)`, which asks without saved answers and reports the spread per question. Fixed answer levels are tried only if the spread is large, and kept only if it falls. `short_list_precision(workspace)` is reported apart from pile scores. `PileResult` records pile size, beta, profile version and model keys. `check_version` is removed. Tuning reads the practice pile only.
- **Ticket 24 [Task 21]:** decisions use the same reason chips. The page shows short-list precision with its count, apart from scores.
- **Ticket 29 [Task 24], owner builds with Claude:** the proposer also reads reasons for correct yeses from the practice pile and daily decisions. `tries_per_run = 3`. After `tries_per_check_pile` tries, wait for `check_growth_for_more_tries = 25` new check companies. Not ready until `loop_ready`. `improve --profile P` is "Improve now". No `refresh-check` command, and no frozen flag.
- **New ticket 47, owner:** hands-on with what exists (sample run, a small real read, the marking page, a small paid daily run).
- **New ticket 48, owner:** build the whole AWS setup by hand, guided, and run the app on it. Ticket 32 then writes it as code, and ticket 33 deploys from the code and deletes the hand-made parts.
- **Ticket 38 [Task 30]:** one small label always visible at the top, modern design, using the project's design skill.
- **Ticket 39 [Task 31]:** the README describes the web path for non-coders: enter keys once, then use the browser.

### Update of 13 Nov 2026: fewer tickets, simpler builds

The open tickets were merged from 20 into 8. Every feature stays. Each ticket is built in the simplest way that still keeps the score honest, because this is a learning project and not a production system. Where this section is simpler than a task above, this section wins.

| Ticket | Who | Now also covers | Simplest build |
|---|---|---|---|
| 15: Mark test cases | Owner | 16, 25, 37, 47 | No code. Marking in sittings until the loop is ready, daily decisions along the way, then about 50 for the second profile |
| 20: Evaluation, judge comparison and first numbers | Owner with Claude | 21 | One module, `evaluation/evaluate.py`, holding `evaluate_pile`, `baselines`, `compare_judges`, `consistency` and `open_final_pile`. Fixed answer levels only if the consistency check shows a large spread. The code can be built before marks exist. The live step waits for the check pile |
| 29: Improvement run and first real tries | Owner with Claude | 27, 30 | One plain loop in `improve/run.py` and one proposer call per try. Mistakes are worked out fresh each run, and tried ones are recorded by rules version. `night-run` is the daily run followed by `improve` for each daily profile. The live hidden instruction run is part of the first real tries |
| 46: Control pages and profile drafting | Agent | 45 | The profile page is a text box holding the profile file, checked by `load_profile`, with a "Draft from description" button (one structured call) and a preview with no paid calls. No field-by-field form. The settings page is generated from each setting's description. "Improve now" shows once `why-now improve` exists |
| 32: AWS setup as code and deploy | Owner with Claude | 33 | One CDK stack in Python, public network only, no NAT gateway, matching the hand-made setup from ticket 48. The scheduled task runs `why-now daily` until `night-run` exists. After the owner's yes: deploy, check sign-in and one scheduled run, then delete the hand-made parts |
| 34: Public results and score page | Agent | 35 | One page without login in the same web app, reading one public results document. Approving or declining a rule is one button on the review page. Turning public results on needs the owner's yes |
| 38: Simulation page | Agent | | One static page with its invented data built in. No backend, no AI calls, no scores |
| 39: Second profile, README, fresh clone and final numbers | Agent | 36, 40 | The second profile is an example file only, and its rough score uses the existing evaluate commands. The final pile opening for publishing needs the owner's yes |

Steps that cost money, deploy, or delete anything stop and ask the owner first, with the cost or what will change.

### Update of 14 Nov 2026: ticket 15, marking

Ticket 15 is built in two parts. First a small pull request with the code below. Then marking sittings, which change only the workspace.

**Settings:** `practice_size`, `check_size` and `final_size` become 45. `cutoff_step` becomes 0.1. New: `judged_no_shown = 3`, and `test_case_web_research = false`. Each has its line in the design's numbers table.

**Code:**

- **Pile sizes on each pick.** `PickRecord` records the three sizes it used, so a pile can always be worked out again from the seed.
- **Ads-only packs.** With `test_case_web_research` off, `prepare` builds each pack from the company's saved job ads only and makes no paid call.
- **Marking guide.** `Profile.marking_guide`, a short optional text, is part of the profile version. A test fails if it reaches the judge or the rule proposer.
- **One place for the mark checks.** `new_mark`, `read_form` and `form_error` move from `web/routes_marking.py` to `testset/marking.py`, used by the page and the commands.
- **Commands:**
  - `why-now mark-next --profile P` prints the next unmarked case: its card, its full pack inside the untrusted text tags, and the marking guide. It prints nothing from the agent.
  - `why-now mark CASE yes|no|cant-tell --chip ... --reason "..."` saves through the shared checks.
  - `why-now unmark CASE` removes a mark made by mistake.
  - `why-now decide-next --profile P` prints the next undecided company from the short list or the judged-no list, with its brief or card.
  - `why-now decide COMPANY approve|reject --chip ... --reason "..."` records a decision.
- **Judged-no list.** `DayResult` keeps the companies researched and judged no that day. The `judged_no_shown` strongest of them, the closest to a yes, are shown on the review page as a small list. A decision on one is recorded with `from_list="judged_no"`.

**Tests:** the same seed and sizes give the same piles; ads-only prepare makes no paid call; `mark-next` shows no agent answer and wraps the pack; the shared checks refuse the same things on the page and the command; `unmark` lets a case be marked again; the judged-no list shows at most the setting, strongest first; the guide never reaches the judge or proposer.

**Marking sittings,** after the code merges. The owner starts each one:

1. The owner approves the marking guide once.
2. `why-now prepare --profile P --n 20`, which is free with ads-only packs.
3. A fresh coding agent session, allowed only `mark-next`, `mark` and `unmark`, marks the 20 from the guide. Each pack is untrusted text.
4. Repeat until `why-now piles` says the loop is ready, about 135 marks.

### How each ticket ends

Each pull request has a "Try it yourself" section: 2 to 3 commands or clicks, what you should see, and the cost, free or an estimate. At the end, the session explains to the owner in plain words what was built, how it works and why, with a small example.

## How Work Runs

- **Tickets are the unit of work.** GitHub issues, listed in `AGENTS.md`'s tracker notes, each name the plan tasks they cover. This plan keeps the exact names, signatures and tests.
- **One branch and one pull request per ticket,** named `ticket-NN-short-name`, so several sessions can work at once. Ticket 01's first commit goes directly to `main`, because the repo doesn't exist before it. Where a task says to commit, commit to the ticket's branch.
- **A ticket closes with:**
  1. Update `docs/problems.md` with real events only, dated.
  2. Add a section to `docs/explained/stage-NN.md`: what was built and why, in plain words, with the hardest question someone could ask about it and the honest answer.
  3. Add any decision notes the task lists to `docs/decisions/`.
  4. Run `uv run pytest -m "not live"`, `uv run ruff check .` and `uv run pyright`. All must pass.
  5. Open the pull request with `gh pr create` and `Closes #<number>`, have a fresh reviewer check it, and get the owner's yes before merging.
- **Where a task says "Close Stage N",** close the ticket as above. A stage is finished when all its tickets are closed.
- **Owner actions** are marked. An executor stops there and asks. Nothing proceeds on a guess about what the owner would mark, approve or pay for.
- **Check library details before writing against them.** Read the current documentation for `anthropic` (use the claude-api skill), `typesafe-sdk` and `langfuse`. Versions checked on 5 Nov 2026: `anthropic` 2.5.0, `typesafe-sdk` 0.7.5, `langfuse` 5.1.0.

## File Structure

```
src/why_now/
  settings.py        all settings, loaded from one file plus the environment
  domain.py          shared data shapes
  profile.py         load and validate a profile
  store/             Store protocol, LocalStore, AwsStore
  workspace/         typed reads and writes over a Store, one file per area
  sources/           JobSource protocol, polite client, Greenhouse, Lever, boards, Common Crawl
  ai/                Answerer, Writer and ResearchModel protocols, Claude and Jev versions, budget meter
  tracing.py         Tracer protocol, local log, Langfuse, unit counter
  pipeline/          read, search, find_new, quick_look, reader, research, judge, brief, fact_check, day
  testset/           picking, packs, marks, piles, repeat marking
  evaluation/        score, evaluate, baselines, comparison, final pile log
  improve/           mistakes, proposer, screen, keep rule, run
  results.py         public results
  web/               FastAPI app, auth, routes, templates, simulation page
  sample/            invented job ads, pages and scripted models
  cli/               the `why-now` command, one file per area, registered from one place
examples/            example profiles, small board list, settings.example.toml
infra/               AWS CDK app and Dockerfile
tests/               mirrors src, plus repo-level checks
docs/                decisions/, explained/, problems.md, how-we-work.md, superpowers/plans/
```

Shared shapes in `domain.py` are all pydantic models. Tasks 3 and later name them, so Task 3 is the source of truth.

The `cli` and `workspace` packages are split by area so that sessions working at once rarely edit the same file. Where a task says "Modify `cli.py`" or "Modify `workspace.py`", or says `Workspace` adds a method, add it in that area's file: the method still reads as `workspace.save_mark(...)` to callers.

---

## Stage 1: Repo and accounts

### Task 1: Repo, local checks and first commit

**Files:**
- Create: `.gitignore`, `LICENSE`, `README.md`, `pyproject.toml`, `AGENTS.md`, `CLAUDE.md`, `docs/problems.md`, `docs/how-we-work.md`, `.github/workflows/ci.yml`, `src/why_now/__init__.py`, `tests/test_smoke.py`
- Create outside Git: `private/local-checks/` (hooks and installer), `~/.config/why-now-agent/private-words.txt`

**Interfaces:** Produces the repo, `uv run` environment and CI that everything else uses.

- [ ] **Step 1: Start Git and ignore private files before anything else**

`git init -b main`, then set the commit identity with `git config` (repo level, no `--global`). Write `.gitignore` covering `private/`, `workspace/`, `.env`, `/settings.toml`, `.venv/`, `__pycache__/`, `cdk.out/`.

Run: `git check-ignore private/anything.md`. Expected: prints the path.

- [ ] **Step 2: Install local checks**

Install gitleaks with `winget install gitleaks`. Write hooks into `private/local-checks/` with an installer that copies them to `.git/hooks/`:
- `pre-commit`: runs `gitleaks protect --staged`, and fails if the staged diff contains a word from the private words file (case-insensitive).
- `commit-msg`: applies the same word check to the message.
- `pre-push`: fails unless `gh api user --jq .login` prints `NoureldinAyman`.

Owner action: confirm the private words list. It stays outside the repo.

- [ ] **Step 3: Prove the checks work**

Stage a temporary file containing a listed word and try to commit. Expected: commit refused. Stage a fake key in the shape of an AWS access key and try again. Expected: refused. Remove both.

- [ ] **Step 4: Set up the Python project and a smoke test**

`pyproject.toml` declares Python 3.13, the package under `src/`, a `why-now` script, the `live` pytest marker, ruff and pyright settings, and extras `jev`, `langfuse`, `aws`, `infra`. Core dependencies: pydantic, httpx, typer, pyyaml, fastapi, jinja2, uvicorn, anthropic.

```python
def test_package_imports():
    import why_now
    assert why_now.__name__ == "why_now"
```

Run: `uv sync --all-extras && uv run pytest -v`. Expected: 1 passed.

- [ ] **Step 5: Write CI and project docs**

CI runs on every push and pull request: `uv sync`, `ruff check`, `pyright`, `pytest -m "not live"`, and the gitleaks action. `AGENTS.md` holds the working rules from "How Work Runs" and the public Global Constraints. `CLAUDE.md` points to it. `docs/how-we-work.md` explains how work is planned, built and reviewed. Copy the glossary rule into `AGENTS.md`: use its words.

- [ ] **Step 6: First commit**

Stage `design.md`, `GLOSSARY.md`, this plan and the files above. Run `git status` and check that nothing from `private/` is listed. Commit: `chore: start the project`.

- [ ] **Step 7: Create the public repo**

Run `gh api user --jq .login`. Expected: `NoureldinAyman`. Then `gh repo create NoureldinAyman/why-now-agent --public --description "<description from Global Constraints>" --source . --push`, with `git config credential.helper "!gh auth git-credential"` set at repo level.

Run: `gh run list --limit 1`. Expected: the CI run passes.

### Task 2: Owner accounts

- [ ] **Step 1: Owner action.** Check which of these exist under personal accounts, and create what's missing: Claude API (separate from a Claude subscription), Jev (TypeSafe), Langfuse. AWS waits until Stage 9. Set a spending limit with each provider. Never use an employer's account or device.
- [ ] **Step 2: Owner action.** Put keys in a local `.env` (ignored by Git).
- [ ] **Step 3: Record in `docs/problems.md`** anything that went wrong, including whether Jev access is available. Close Stage 1.

---

## Stage 2: Read job ads

### Task 3: Settings, shared shapes, store and workspace

**Files:**
- Create: `src/why_now/settings.py`, `domain.py`, `store/__init__.py`, `store/local.py`, `workspace/__init__.py`, `cli/__init__.py`, `examples/settings.example.toml`
- Test: `tests/test_settings.py`, `tests/store/test_local.py`, `tests/test_workspace.py`, `tests/conftest.py`

**Interfaces (produces):**

```python
# settings.py
class Settings(BaseModel):  # defaults below, all overridable
    deployment: Literal["local", "aws"] = "local"
    workspace_path: Path = Path("workspace")
    daily_profiles: list[Path] = []
    board_lists: dict[str, Path] = {}
    public_results_enabled: bool = False
    short_list_size: int = 10
    hide_days: int = 90
    new_ad_days: int = 14
    research_per_day: int = 12
    research_steps: int = 5
    newest_ads_read: int = 5
    keep_min_gain: int = 2
    tries_per_check_pile: int = 50
    practice_size: int = 150; check_size: int = 75; final_size: int = 75
    pilot_size: int = 40; marking_ceiling: int = 500; remark_size: int = 30
    remark_after_days: int = 7
    target_yes_per_pile: int = 25; floor_yes_per_pile: int = 15
    request_delay_seconds: float = 1.0; outage_share: float = 0.9
    dead_after_days: int = 7; retry_dead_after_days: int = 30
    budget_limit_usd: float = 70; budget_warning_usd: float = 50
    loop_budget_usd: float = 25; fixed_monthly_costs_usd: float = 0
    langfuse_thin_at_units: int = 40_000
    quick_look_pass: float = 0.3; required_pass: float = 0.5
    max_page_bytes: int = 2_000_000; page_timeout_seconds: float = 15
    max_ad_chars: int = 20_000; max_pack_chars: int = 60_000
    brief_max_chars: int = 1_200
    screen_max_copied_words: int = 8; screen_max_why_words: int = 20
    research_model: str = "claude-sonnet-5-5"
    writer_model: str = "claude-sonnet-5-5"
    quick_look_model: str = "jev-1.14.0"  # falls back to claude-haiku-5-5 without a Jev key
    judge_model: str = "claude-sonnet-5-5"
    prices: dict[str, ModelPrice]  # per million tokens, plus per-search cost

def load_settings(path: Path | None = None) -> Settings: ...

# domain.py
class JobAd(BaseModel):
    source: str; board: str; ad_id: str; company_name: str; title: str
    location: str; country: str | None; language: str | None
    text: str; url: str; published_at: datetime; first_seen: date
class Company(BaseModel):
    key: str; name: str; ads: list[JobAd]; total_open_jobs: int
class FitQuestion(BaseModel):
    id: str; text: str; kind: Literal["required", "supporting"] = "supporting"
    direction: Literal["for", "against"] = "for"
    yes_means: str | None = None; no_means: str | None = None
class LearnedQuestion(FitQuestion):
    why: str
class RulesFile(BaseModel):
    profile_id: str; version: int = 0; questions: list[LearnedQuestion] = []
class Profile(BaseModel):
    id: str; product_name: str; product_description: str; users: str
    search_words: list[str]; countries: list[str] = []; languages: list[str] = []
    quick_look_questions: list[FitQuestion]; fit_questions: list[FitQuestion]
    why_now: str; public: bool = False
class Source(BaseModel):
    id: str; kind: Literal["job_ad", "page"]; url: str; text: str; fetched_at: datetime
class EvidencePack(BaseModel):
    pack_id: str; profile_id: str; company_key: str; company_name: str
    created_at: datetime; sources: list[Source]
    relevant_ad_count: int; total_open_jobs: int; research_steps: int
class Answer(BaseModel):
    question_id: str; probability: float; model: str
class Verdict(BaseModel):
    yes: bool; strength: float; answers: list[Answer]
class Claim(BaseModel):
    text: str; quote: str; source_id: str
class Brief(BaseModel):
    company_key: str; why_now: Claim; claims: list[Claim]
class Decision(BaseModel):
    profile_id: str; company_key: str; approved: bool; reason: str
    decided_at: datetime; from_list: Literal["short", "more"]
class Mark(BaseModel):
    case_id: str; answer: Literal["yes", "no", "cant_tell"]; reason: str
    marked_at: datetime; round: Literal["first", "repeat"] = "first"
class CaseRecord(BaseModel):
    case_id: str; profile_id: str; company_key: str; pack_id: str; seed: int
    pile: Literal["practice", "check", "final", "unsplit"] | None = None
    check_version: int | None = None

# store/__init__.py
class Store(Protocol):
    def put(self, collection: str, key: str, doc: dict) -> None: ...
    def get(self, collection: str, key: str) -> dict | None: ...
    def list(self, collection: str, prefix: str = "") -> Iterator[tuple[str, dict]]: ...
    def delete(self, collection: str, key: str) -> None: ...

# workspace.py
class Workspace:
    def __init__(self, store: Store, profile_id: str | None = None): ...
```

`Workspace` gains typed methods in later tasks. Each task lists the ones it adds, in a mixin file for its area, composed in `workspace/__init__.py`. All are thin reads and writes over `Store`, and pydantic models are saved with `model_dump(mode="json")`. `cli/__init__.py` holds the typer app and imports one module per area, so a new command only touches its own file.

- [ ] **Step 1: Write failing tests**

```python
def test_defaults_match_the_design(tmp_path):
    s = load_settings(None)
    assert (s.short_list_size, s.hide_days, s.new_ad_days) == (10, 90, 14)
    assert (s.budget_limit_usd, s.budget_warning_usd) == (70, 50)
    assert s.public_results_enabled is False

def test_settings_file_overrides_defaults(tmp_path):
    f = tmp_path / "s.toml"; f.write_text("short_list_size = 20")
    assert load_settings(f).short_list_size == 20

def test_store_round_trip_and_prefix(tmp_path):
    s = LocalStore(tmp_path)
    s.put("ads", "gh/acme", {"a": 1}); s.put("ads", "lv/beta", {"a": 2})
    assert s.get("ads", "gh/acme") == {"a": 1}
    assert [k for k, _ in s.list("ads", "gh/")] == ["gh/acme"]
    assert s.get("ads", "missing") is None

def test_store_refuses_keys_that_leave_the_folder(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).put("ads", "../../evil", {})

def test_interrupted_write_leaves_old_value(tmp_path, monkeypatch):
    s = LocalStore(tmp_path); s.put("c", "k", {"v": 1})
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError))
    with pytest.raises(OSError):
        s.put("c", "k", {"v": 2})
    assert s.get("c", "k") == {"v": 1}
```

`tests/conftest.py` provides `store` (a `LocalStore` on `tmp_path`), `settings`, and `make_profile(**overrides)`, which builds a throwaway profile with a random product name.

- [ ] **Step 2: Run `uv run pytest tests/test_settings.py tests/store tests/test_workspace.py -v`.** Expected: FAIL on import.
- [ ] **Step 3: Implement.** `LocalStore` keeps one JSON file per document and writes through a temporary file then `os.replace`. `load_settings` reads TOML and allows `WHY_NOW_`-prefixed environment overrides. `examples/settings.example.toml` lists every setting with a one-line comment.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add settings, store and workspace`

### Task 4: Profiles and job source adapters

The search reads words from the profile, so the loader lands here, one stage earlier than the design's order. Drafting the example profile stays in Stage 3.

**Files:**
- Create: `src/why_now/profile.py`, `sources/__init__.py`, `sources/polite.py`, `sources/greenhouse.py`, `sources/lever.py`, `sample/__init__.py`, `sample/data.py`
- Test: `tests/test_profile.py`, `tests/sources/test_polite.py`, `tests/sources/test_greenhouse.py`, `tests/sources/test_lever.py`

**Interfaces (produces):**

```python
class ProfileError(Exception): ...
def load_profile(path: Path) -> Profile: ...

class JobSource(Protocol):
    name: str
    def fetch_ads(self, board: str, today: date) -> list[JobAd]: ...  # raises BoardFailed
class BoardFailed(Exception): ...

class PoliteClient:
    def __init__(self, http: httpx.Client, delay_seconds: float, sleep=time.sleep, clock=time.monotonic,
                 *, attempts: int, max_retry_wait_seconds: float): ...  # both from settings
    def get_json(self, url: str) -> Any: ...

class GreenhouseSource: name = "greenhouse"  # GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
class LeverSource: name = "lever"            # GET https://api.lever.co/v0/postings/{board}?mode=json
```

Real response fields, checked on 5 Nov 2026:
- **Greenhouse:** `id`, `title`, `company_name`, `location.name`, `language`, `first_published`, `absolute_url`, and `content`, which is HTML with its tags escaped, so unescape it before stripping tags.
- **Lever:** `id`, `text`, `country`, `categories.location`, `createdAt` (milliseconds), `hostedUrl`, `descriptionPlain`, `lists[].text`, `lists[].content` (HTML), `additionalPlain`. Lever has no company name field, so tidy the board name for display.

- [ ] **Step 1: Write failing tests**

Keep short recorded responses, cut down and with invented text, in `tests/sources/fixtures/`.

```python
def test_greenhouse_maps_a_job(fake_http):
    ad = GreenhouseSource(client(fake_http)).fetch_ads("acme", date(2026, 11, 5))[0]
    assert ad.title == "Sales Development Representative"
    assert ad.company_name == "Acme"; assert ad.language == "en"
    assert ad.published_at == datetime.fromisoformat("2026-10-30T10:00:00-04:00")
    assert "<" not in ad.text and "&lt;" not in ad.text
    assert ad.url.startswith("https://")

def test_lever_maps_a_job_and_joins_its_text(fake_http):
    ad = LeverSource(client(fake_http)).fetch_ads("acme", date(2026, 11, 5))[0]
    assert ad.country == "SG"
    assert "What We Require" in ad.text and "<li>" not in ad.text

def test_polite_client_waits_between_requests():
    sleeps = []; c = PoliteClient(ok_http(), 1.0, sleep=sleeps.append, clock=fixed_clock)
    c.get_json("u1"); c.get_json("u2")
    assert sleeps == [1.0]

def test_polite_client_obeys_retry_after_then_gives_up():
    sleeps = []; c = PoliteClient(always_429(retry_after=7), 1.0, sleep=sleeps.append, clock=fixed_clock)
    with pytest.raises(BoardFailed):
        c.get_json("u")
    assert 7 in sleeps

def test_never_calls_anything_but_get():
    http = RecordingHttp(); GreenhouseSource(client(http)).fetch_ads("acme", date(2026, 11, 5))
    assert {r.method for r in http.requests} == {"GET"}

def test_missing_board_raises_board_failed(fake_http_404): ...
def test_missing_first_published_falls_back_to_updated_at(fake_http): ...  # 12 of 2,873 sampled jobs had none

def test_incomplete_profile_names_the_missing_field(tmp_path):
    p = tmp_path / "p.yaml"; p.write_text("id: x")
    with pytest.raises(ProfileError, match="search_words"):
        load_profile(p)

def test_profile_is_private_by_default(profile_file):
    assert load_profile(profile_file).public is False
```

- [ ] **Step 2: Run `uv run pytest tests/test_profile.py tests/sources -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** The client sends a `User-Agent` of `why-now-agent (+https://github.com/NoureldinAyman/why-now-agent)`. It waits on 429 and 503, honouring `Retry-After`, up to 3 attempts. Strip HTML with the standard library's `html.parser`, keeping line breaks. `sample/data.py` holds a small invented `SampleSource` used by tests and the sample run.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add profiles and job source adapters`

### Task 5: Board lists and the read step

**Files:**
- Create: `src/why_now/sources/boards.py`, `pipeline/__init__.py`, `pipeline/read.py`, `examples/boards.example.json`
- Modify: `src/why_now/workspace.py`
- Test: `tests/sources/test_boards.py`, `tests/pipeline/test_read.py`

**Interfaces:**
- Consumes: `JobSource`, `Workspace`, `Settings`
- Produces:

```python
class BoardList:
    def __init__(self, workspace: Workspace, source: str, names: list[str], settings: Settings): ...
    def to_read(self, today: date) -> list[str]: ...  # skips set-aside boards unless due for a retry
    def record_results(self, today: date, ok: list[str], failed: list[str]) -> None: ...
    def health(self, board: str) -> BoardHealth: ...  # failing_days, set_aside_on, last_retry

class ReadResult(BaseModel):
    ads: list[JobAd]; new_ad_count: int
    failed_boards: dict[str, list[str]]; outage_sources: list[str]
    open_job_counts: dict[str, int]  # company key to total open jobs

def read_all(sources: list[JobSource], boards: dict[str, BoardList], workspace: Workspace,
             today: date, on_progress=None, *, outage_share: float) -> ReadResult: ...
```

`Workspace` adds `load_board_ads(source, board)`, `save_board_ads(source, board, ads)` and `board_health(source)`, `save_board_health(source, doc)`.

- [ ] **Step 1: Write failing tests**

```python
def test_first_seen_is_kept_across_reads(workspace, today): ...  # read twice, first_seen stays the first date
def test_ad_list_is_only_written_when_it_changed(counting_store, today):
    read_all([source_with_one_ad], boards, wk(counting_store), today)
    writes = counting_store.puts("board_ads")
    read_all([source_with_one_ad], boards, wk(counting_store), today + timedelta(days=1))
    assert counting_store.puts("board_ads") == writes

def test_one_failing_board_does_not_stop_the_read(today):
    r = read_all([source(ok=["a"], fail=["b"])], boards(["a", "b"]), workspace, today)
    assert r.failed_boards == {"s": ["b"]}; assert r.ads

def test_board_is_set_aside_after_seven_failing_days_and_retried_monthly(workspace, today):
    b = BoardList(workspace, "s", ["a", "b"])
    for i in range(7):
        b.record_results(today + timedelta(days=i), ok=["a"], failed=["b"])
    assert b.to_read(today + timedelta(days=8)) == ["a"]
    assert "b" in b.to_read(today + timedelta(days=37))

def test_whole_source_outage_is_reported_and_no_board_is_punished(workspace, today):
    # Review Focus 1
    r = read_all([source(ok=[], fail=["a", "b"])], boards(["a", "b"]), workspace, today)
    assert r.outage_sources == ["s"]
    assert BoardList(workspace, "s", ["a", "b"]).health("a").failing_days == 0
```

- [ ] **Step 2: Run `uv run pytest tests/sources/test_boards.py tests/pipeline/test_read.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Each source runs in its own thread, so sources read side by side while each stays polite. An outage means every board in a source failed, or a setting `outage_share` (0.9, starting guess) of them did. Each document is written only if its content changed, because AWS charges per write.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add board lists and the read step`

### Task 6: Search and grouping

**Files:**
- Create: `src/why_now/pipeline/search.py`
- Test: `tests/pipeline/test_search.py`

**Interfaces:** Consumes `JobAd`, `Profile`. Produces:

```python
def company_key(board: str) -> str: ...  # lowercase, letters and digits only
def search_ads(ads: list[JobAd], profile: Profile, open_job_counts: dict[str, int]) -> list[Company]: ...
```

- [ ] **Step 1: Write failing tests**

```python
def test_matches_whole_words_in_titles_only(make_profile):
    p = make_profile(search_words=["sales", "sdr"])
    assert titles(search_ads([ad("Sales Manager"), ad("Wholesale Buyer"), ad("Engineer", text="sales")], p, {})) == ["Sales Manager"]

def test_five_ads_become_one_company(make_profile):
    assert len(search_ads([ad("Sales Rep", location=c) for c in "ABCDE"], make_profile(search_words=["sales"]), {})) == 1

def test_same_name_on_two_sources_is_one_company(make_profile):
    ads = [ad("Sales", board="Acme-Inc", source="greenhouse"), ad("Sales", board="acmeinc", source="lever")]
    assert len(search_ads(ads, make_profile(search_words=["sales"]), {})) == 1

def test_country_and_language_filters_use_source_fields(make_profile): ...
def test_ad_with_no_language_is_kept(make_profile): ...
def test_total_open_jobs_counts_all_ads_not_only_matches(make_profile): ...
def test_search_words_can_be_multi_word_and_any_case(make_profile): ...
```

- [ ] **Step 2: Run `uv run pytest tests/pipeline/test_search.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Compile one word-boundary regular expression from `search_words`.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add search and grouping by company`

### Task 7: Build a careers page list, and prove reading works

**Files:**
- Create: `src/why_now/sources/commoncrawl.py`, `cli/sources.py`
- Test: `tests/sources/test_commoncrawl.py`, `tests/test_cli.py`

**Interfaces:** Produces:

```python
def board_from_url(url: str, source: str) -> str | None: ...
def build_board_list(source: str, http: httpx.Client, existing: list[str]) -> list[str]: ...
```

CLI commands added: `why-now build-list --source greenhouse|lever --out PATH`, `why-now read --sample N`.

Hosts to query: `job-boards.greenhouse.io/*` and `boards.greenhouse.io/*` for Greenhouse, `jobs.lever.co/*` for Lever. Latest index from `https://index.commoncrawl.org/collinfo.json`, then `{id}-index?url=HOST&output=json&fl=url&page=N`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("url,expected", [
    ("https://job-boards.greenhouse.io/0x/jobs/7302322002", "0x"),
    ("https://job-boards.greenhouse.io/0verwatch?error=true", "0verwatch"),
    ("https://job-boards.greenhouse.io/", None),
    ("https://jobs.lever.co/acme/1234-abcd", "acme"),
])
def test_board_from_url(url, expected): ...

def test_build_list_merges_and_dedupes(fake_index): ...
def test_build_list_retries_on_timeouts_then_reports_failure(fake_index_504): ...
```

- [ ] **Step 2: Run `uv run pytest tests/sources/test_commoncrawl.py tests/test_cli.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement,** one page at a time with a pause between requests.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Answer the Common Crawl question.** Read `https://commoncrawl.org/terms-of-use` in full and record what it allows in `docs/decisions/`. Run `build-list` for both sources for real. If Lever keeps failing, record that and leave Lever to supplied lists, as the design allows.
- [ ] **Step 6: Live check.** Owner action: point `board_lists` at the owner's private list. Run `uv run why-now read --sample 50`. Expected: a summary of boards read, failed and ads saved, and nothing written inside the repo (`git status` is clean).
- [ ] **Step 7: Commit:** `feat: add careers page list command`. Decision note: why job sources, and why not LinkedIn or Ashby. Close Stage 2.

---

## Stage 3: Profiles

### Task 8: Example profile and setup check

**Files:**
- Create: `examples/profiles/` (one file for the main example), `src/why_now/setup_check.py`
- Modify: `src/why_now/cli.py`
- Test: `tests/test_setup_check.py`, `tests/test_repo_rules.py`

**Interfaces:** Produces `check_setup(settings, env) -> list[SetupItem]`, where `SetupItem` has `name`, `status` (`ok`, `missing`, `optional`) and `how_to_fix`. CLI: `why-now check-setup`.

- [ ] **Step 1: Write failing tests**

```python
def test_no_keys_still_allows_the_sample_run(settings):
    items = {i.name: i for i in check_setup(settings, env={})}
    assert items["sample run"].status == "ok"
    assert items["Claude API key"].status == "missing"
    assert items["Jev key"].status == "optional"
    assert items["Langfuse keys"].status == "optional"

def test_setup_check_never_prints_key_values(settings, capsys):
    run_cli(["check-setup"], env={"ANTHROPIC_API_KEY": "secret-value"})
    assert "secret-value" not in capsys.readouterr().out

def test_no_product_name_appears_in_code():
    names = [load_profile(p).product_name for p in Path("examples/profiles").glob("*.yaml")]
    for path in tracked_files("src", "tests", "infra"):
        text = path.read_text(errors="ignore").lower()
        assert not any(n.lower() in text for n in names), path

def test_no_run_data_is_tracked():
    assert not [f for f in tracked_files() if f.startswith(("workspace/", "private/"))]

def test_deleting_examples_breaks_nothing(tmp_path): ...  # copy src and tests without examples/, run the suite's core
```

- [ ] **Step 2: Run `uv run pytest tests/test_setup_check.py tests/test_repo_rules.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Draft the main example profile from the design: the invented practice tool for new sales hires. Keep required questions to true deal-breakers, such as a recruitment agency hiring for clients, or a competitor. Use a neutral, invented product name. Write each question with an exact condition, because Jev's documentation says it reads literally.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Owner action.** The owner reads and edits the profile. It isn't locked yet.
- [ ] **Step 6: Commit:** `feat: add the example profile and setup check`. Close Stage 3.

---

## Stage 4: Test cases

### Task 9: AI parts, budget meter and tracing

**Files:**
- Create: `src/why_now/ai/__init__.py`, `ai/budget.py`, `ai/claude.py`, `ai/jev.py`, `tracing.py`, `sample/models.py`
- Test: `tests/ai/test_budget.py`, `tests/ai/test_claude.py`, `tests/test_tracing.py`

**Interfaces (produces):**

```python
class BudgetExceeded(Exception): ...
class BudgetStatus(BaseModel):
    month: str; spent_usd: float; by_category: dict[str, float]
    warning: bool; stopped: bool; loop_stopped: bool
class Meter:
    def __init__(self, store: Store, settings: Settings, clock: Callable[[], datetime]): ...
    def ensure(self, category: str) -> None: ...  # raises BudgetExceeded
    def charge(self, category: str, usd: float, detail: str) -> None: ...
    def status(self) -> BudgetStatus: ...

class Answerer(Protocol):
    model: str
    def answer(self, state: str, questions: list[FitQuestion], category: str) -> list[Answer]: ...
class Writer(Protocol):
    def structured(self, *, system: str, untrusted: str, schema: type[BaseModel], category: str) -> BaseModel: ...
class ResearchStep(BaseModel):
    read_urls: list[str]; searches_used: int; done: bool
class ResearchModel(Protocol):
    def step(self, conversation: list[dict], category: str) -> ResearchStep: ...

@dataclass
class Models:
    quick_look: Answerer; judge: Answerer; writer: Writer; research: ResearchModel
def build_models(settings: Settings, meter: Meter, tracer: Tracer, env: Mapping[str, str]) -> Models: ...
def scripted_models(script: Script) -> Models: ...  # in sample/models.py, no network or keys

class Tracer(Protocol):
    def trace(self, name: str, *, profile_id: str, rules_version: int | None,
              models: dict[str, str], detail: Literal["full", "light"] = "full") -> ContextManager[TraceHandle]: ...
class TraceHandle(Protocol):
    def step(self, name: str, input: Any, output: Any) -> None: ...
    def score(self, name: str, value: float) -> None: ...
class LocalLogTracer: ...   # one JSON line per event in the workspace
class LangfuseTracer: ...   # optional extra
class UnitCounter: ...      # counts units per month, tells tracers to thin near the setting
```

- [ ] **Step 1: Write failing tests**

```python
def test_paid_calls_stop_at_the_limit(store, settings, clock):
    m = Meter(store, settings, clock); m.charge("research", 70.0, "x")
    with pytest.raises(BudgetExceeded):
        m.ensure("research")

def test_warning_at_fifty(store, settings, clock):
    m = Meter(store, settings, clock); m.charge("research", 50.0, "x")
    assert m.status().warning and not m.status().stopped

def test_fixed_costs_count_towards_the_limit(store, settings, clock):
    m = Meter(store, settings.model_copy(update={"fixed_monthly_costs_usd": 69.5}), clock)
    m.charge("research", 1.0, "x")
    assert m.status().stopped

def test_loop_has_its_own_share(store, settings, clock):
    m = Meter(store, settings, clock); m.charge("loop", 25.0, "x")
    with pytest.raises(BudgetExceeded):
        m.ensure("loop")
    m.ensure("research")  # research money is still available

def test_a_new_month_starts_at_zero(store, settings): ...
def test_claude_answerer_charges_by_real_token_use(fake_anthropic, meter): ...
def test_claude_answerer_uses_a_locked_model_and_marks_text_untrusted(fake_anthropic): ...
def test_jev_answerer_refuses_the_latest_alias(settings): ...
def test_model_output_outside_zero_to_one_is_rejected(fake_anthropic): ...  # Review Focus 3
def test_tracer_thins_company_traces_but_not_tries_near_the_limit(store, settings): ...
def test_trace_records_profile_rules_version_and_models(store, settings): ...
```

- [ ] **Step 2: Run `uv run pytest tests/ai tests/test_tracing.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** `ClaudeAnswerer` forces one tool call whose input is a list of answers, one per question, and wraps untrusted text in clearly labelled tags. The Jev version sends each question as a Noul, whose answer is the probability of yes. Bad output raises `BadModelOutput` straight away, and callers decide on a retry (Task 16). Check current library documentation first. Langfuse Cloud is optional, and only installed through the extra.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add AI parts, budget meter and tracing`

### Task 10: Page reader

**Files:**
- Create: `src/why_now/pipeline/reader.py`
- Test: `tests/pipeline/test_reader.py`

**Interfaces:** Produces:

```python
class PageRefused(Exception): ...  # .reason names the rule
class PageReader:
    def __init__(self, http: httpx.Client, settings: Settings, resolve=socket.getaddrinfo, clock=...): ...
    def read(self, url: str) -> Source: ...

def remove_contacts(text: str) -> str: ...
```

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("url", ["https://www.linkedin.com/company/x", "https://uk.linkedin.com/x", "https://lnkd.in/x"])
def test_refuses_linkedin(url, reader): ...

@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "::1", "fd00::1"])
def test_refuses_private_addresses(ip, reader_resolving_to): ...

def test_refuses_a_redirect_into_a_private_address(reader_with_redirect): ...
def test_refuses_non_http_schemes(reader): ...  # file://, ftp://
def test_follows_robots_rules(reader_with_robots_disallow): ...
def test_refuses_pdf_and_images(reader_with_content_type): ...
def test_stops_at_the_size_limit(reader_with_big_page): ...
def test_returns_plain_text_with_contacts_removed(reader):
    s = reader.read("https://acme.test/about")
    assert "<" not in s.text; assert "jo@acme.test" not in s.text; assert "+20 100 000 0000" not in s.text

def test_remove_contacts_keeps_normal_numbers():
    assert remove_contacts("Founded 2019, 250 staff") == "Founded 2019, 250 staff"
```

- [ ] **Step 2: Run `uv run pytest tests/pipeline/test_reader.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Follow redirects by hand, and check every hop's resolved address with the `ipaddress` module before connecting. Stream the body and stop at the byte limit. Use `urllib.robotparser`.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the safe page reader`

### Task 11: Research and evidence packs

**Files:**
- Create: `src/why_now/pipeline/research.py`
- Test: `tests/pipeline/test_research.py`

**Interfaces:** Consumes `ResearchModel`, `PageReader`, `Company`, `Profile`, `Tracer`. Produces:

```python
def research_company(company: Company, profile: Profile, model: ResearchModel, reader: PageReader,
                     settings: Settings, tracer: Tracer, *, category: str, now: datetime) -> EvidencePack: ...
```

- [ ] **Step 1: Write failing tests**

```python
def test_pack_starts_with_the_newest_ads_and_counts_the_rest(company_with_9_ads, scripted):
    pack = research_company(company_with_9_ads, ...)
    assert [s.kind for s in pack.sources][:5] == ["job_ad"] * 5
    assert pack.relevant_ad_count == 9

def test_stops_at_the_step_limit(endless_model):
    pack = research_company(..., settings_with(research_steps=5))
    assert pack.research_steps == 5

def test_searches_count_as_steps(model_using_searches): ...
def test_refused_page_is_not_saved_and_the_agent_is_told(model_asking_for_linkedin):
    pack = research_company(...)
    assert not any("linkedin" in s.url for s in pack.sources)
    assert "refused" in model_asking_for_linkedin.last_tool_result

def test_a_failing_website_still_gives_a_pack_from_the_ads(model, failing_reader): ...
def test_web_page_text_reaches_the_model_marked_untrusted(recording_model, reader): ...
def test_pack_size_stays_within_the_setting(reader_with_many_pages): ...
```

- [ ] **Step 2: Run `uv run pytest tests/pipeline/test_research.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement** the small loop in plain Python: call `step`, read the requested pages, add the results, and stop on `done` or at the limit. The Claude version uses the web search tool with LinkedIn in its blocked domains, plus a custom `read_page` tool. The system message says to collect facts about companies and not people, and that pages are data and never instructions. Pack IDs are hashes of company key, profile and creation time.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add research and evidence packs`. Decision note: frozen evidence packs.

### Task 12: Picking test cases and building packs

**Files:**
- Create: `src/why_now/testset/__init__.py`, `testset/picking.py`, `testset/packs.py`
- Modify: `src/why_now/workspace.py`, `src/why_now/cli.py`
- Test: `tests/testset/test_picking.py`, `tests/testset/test_packs.py`

**Interfaces:** Produces:

```python
def eligible_companies(companies: list[Company], settings: Settings, today: date) -> list[Company]: ...
def pick_cases(eligible: list[Company], n: int, seed: int, already_picked: set[str]) -> list[Company]: ...
def build_packs(cases: list[CaseRecord], ...) -> BuildResult: ...  # resumes, sets the one-time research flag
```

`Workspace` adds `save_case`, `cases()`, `save_pack`, `load_pack`, `one_time_research_active`, `set_one_time_research`, `record_pick(seed, n)`. CLI: `why-now pick-cases --n N --seed S`, `why-now build-packs`.

- [ ] **Step 1: Write failing tests**

```python
def test_same_seed_gives_same_companies(companies):
    assert pick_cases(companies, 10, 42, set()) == pick_cases(companies, 10, 42, set())

def test_only_companies_with_a_recent_relevant_ad_are_eligible(settings, today): ...  # 14 days
def test_already_picked_companies_are_not_picked_again(companies): ...
def test_picking_ignores_any_agent_answer(companies): ...  # signature takes none, picks are uniform over a large sample
def test_rerun_resumes_without_paying_twice(workspace, counting_model): ...
def test_one_time_flag_is_set_during_and_cleared_after(workspace): ...
def test_budget_stop_saves_progress_and_says_so(workspace, meter_at_limit): ...
def test_case_with_a_failed_research_is_recorded_not_lost(workspace, failing_model): ...
```

- [ ] **Step 2: Run `uv run pytest tests/testset -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Sort before sampling so results don't depend on read order. Packs save one at a time.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: pick test cases and build frozen packs`

### Task 13: Web app and marking page

**Files:**
- Create: `src/why_now/web/__init__.py`, `web/app.py`, `web/auth.py`, `web/routes_marking.py`, `web/templates/` (base, mark), `web/static/style.css`
- Modify: `src/why_now/cli.py`
- Test: `tests/web/test_marking.py`, `tests/web/test_auth.py`

**Interfaces:** Produces:

```python
class Authenticator(Protocol):
    def current_user(self, request: Request) -> str | None: ...
class LocalAuth: ...  # only for local use; refuses non-loopback clients
def create_app(ctx: AppContext, auth: Authenticator) -> FastAPI: ...

@dataclass
class AppContext:
    settings: Settings; store: Store; profiles: dict[str, Profile]; meter: Meter; clock: Callable[[], datetime]
```

`Workspace` adds `save_mark(mark) -> bool` (False if that case and round already exists), `marks(round)`. CLI: `why-now serve` binds to `127.0.0.1`.

Routes: `GET /mark` shows the next unmarked case. `POST /mark/{case_id}` saves. `GET /mark/progress`.

- [ ] **Step 1: Write failing tests**

```python
def test_marking_page_shows_the_pack_and_no_agent_answer(client, case_with_saved_answers):
    html = client.get("/mark").text
    assert "We are hiring sales staff" in html
    for leak in ("strength", "probability", "0.87", "quick look"):
        assert leak not in html.lower()

def test_saving_moves_to_the_next_case(client, two_cases): ...
def test_reason_is_required(client, case):
    assert client.post(f"/mark/{case.case_id}", data={"answer": "yes", "reason": ""}).status_code == 422

def test_cant_tell_is_saved_and_does_not_count_as_marked_yes_or_no(client, case): ...
def test_same_form_twice_saves_one_mark(client, case):  # Review Focus 5
    for _ in range(2):
        client.post(f"/mark/{case.case_id}", data=form)
    assert len(list(workspace.marks("first"))) == 1

def test_html_in_an_ad_shows_as_text(client, case_with_script):  # Review Focus 5
    html = client.get("/mark").text
    assert "<script>alert" not in html; assert "&lt;script&gt;" in html

def test_marking_resumes_after_restart(store): ...
def test_posting_without_the_form_token_is_refused(client, case): ...
def test_local_auth_refuses_other_machines(): ...
def test_app_refuses_local_auth_when_deployed_on_aws(settings_aws):
    with pytest.raises(ValueError):
        create_app(ctx(settings_aws), LocalAuth())
```

- [ ] **Step 2: Run `uv run pytest tests/web -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Server-rendered pages with Jinja2 autoescape on. Use a per-session form token. Keep the reason box a plain text box. Make it readable at phone width.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the marking page`

### Task 14: Repeat marking and piles

**Files:**
- Create: `src/why_now/testset/piles.py`, `testset/repeat.py`, `web/routes_repeat.py`
- Modify: `src/why_now/cli.py`
- Test: `tests/testset/test_piles.py`, `tests/testset/test_repeat.py`

**Interfaces:** Produces:

```python
class PileReport(BaseModel):
    counts: dict[str, int]; yes_counts: dict[str, int]; short_piles: list[str]; yes_share: float
def yes_share(marks: list[Mark]) -> float: ...
def assign_piles(cases: list[CaseRecord], marks: dict[str, Mark], seed: int, settings: Settings) -> tuple[list[CaseRecord], PileReport]: ...
def refresh_check_pile(workspace: Workspace, new_cases: list[CaseRecord]) -> int: ...  # returns the new check_version
def pick_repeats(marks: list[Mark], n: int, seed: int, today: date, after_days: int) -> list[str]: ...
def agreement(first: list[Mark], repeat: list[Mark]) -> float: ...
```

CLI: `why-now yes-share`, `why-now split-piles --seed S`, `why-now repeat-marks --seed S`, `why-now agreement`.

- [ ] **Step 1: Write failing tests**

```python
def test_no_company_in_two_piles_and_seed_fixes_the_split(cases, marks, settings):
    a, _ = assign_piles(cases, marks, 7, settings); b, _ = assign_piles(cases, marks, 7, settings)
    assert a == b; assert len({c.company_key for c in a}) == len(a)

def test_sizes_are_150_75_75_and_yes_answers_are_spread_evenly(cases_300, marks, settings):
    _, r = assign_piles(cases_300, marks, 7, settings)
    assert r.counts == {"practice": 150, "check": 75, "final": 75}
    assert abs(r.yes_counts["check"] - r.yes_counts["final"]) <= 1

def test_cant_tell_is_left_out_of_every_pile(cases, marks_with_cant_tell, settings): ...
def test_short_piles_are_reported(cases, mostly_no_marks, settings):
    _, r = assign_piles(cases, mostly_no_marks, 7, settings)
    assert "check" in r.short_piles

def test_splitting_is_refused_once_the_loop_has_started(workspace, settings): ...
def test_refresh_moves_old_check_cases_to_practice_and_bumps_the_version(workspace): ...
def test_repeats_wait_a_week(marks_marked_today, today):
    assert pick_repeats(marks_marked_today, 30, 1, today, 7) == []

def test_repeat_page_hides_the_first_answer(client, repeat_case): ...
def test_agreement_ignores_cant_tell(): ...
```

- [ ] **Step 2: Run `uv run pytest tests/testset/test_piles.py tests/testset/test_repeat.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Shuffle yes and no answers separately, then deal them out in proportion to pile sizes.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add piles and repeat marking`. Decision note: three piles.

### Task 15: Owner marking gate

No new code. Each step is real use, and problems found go in `docs/problems.md`.

- [ ] **Step 1: Pick and pack 40.** `why-now pick-cases --n 40`, then `why-now build-packs`. This spends real money, so show the expected cost and get the owner's yes first.
- [ ] **Step 2: Owner action: mark the 40** at `why-now serve`, then run `why-now yes-share`. A share of about 1 in 3 means carry on.
- [ ] **Step 3: If the share is low,** narrow the profile's search words with the owner, and start again with a new random sample.
- [ ] **Step 4: Owner action: lock the profile.** Save its hash with the test set. Later commands refuse to run if the hash differs, unless the owner marks the affected companies again.
- [ ] **Step 5: Pick and pack about 300,** stopping at the marking ceiling of 500 if yes answers stay short.
- [ ] **Step 6: Owner action: mark them,** then a week later the 30 repeats. Run `why-now agreement`.
- [ ] **Step 7: Split:** `why-now split-piles`. If a pile is short of 25 yes answers, mark more up to the ceiling. If it's still short, lower the aim to 15 with the owner and record that the numbers are rougher.
- [ ] **Step 8: Close Stage 4.**

---

## Stage 5: Quick look, judge and score

### Task 16: Score, quick look and judge

**Files:**
- Create: `src/why_now/evaluation/__init__.py`, `evaluation/score.py`, `pipeline/quick_look.py`, `pipeline/judge.py`
- Test: `tests/evaluation/test_score.py`, `tests/pipeline/test_quick_look.py`, `tests/pipeline/test_judge.py`

**Interfaces:** Produces:

```python
class ScoreResult(BaseModel):
    tp: int; fp: int; fn: int; tn: int; n: int; correct: int
    precision: float; recall: float; f05: float
def score(rows: list[tuple[bool, bool]]) -> ScoreResult: ...  # (agent_yes, reviewer_yes)

class QuickResult(BaseModel):
    company_key: str; passed: bool; order: float; answers: list[Answer]; failed: bool = False
def quick_look(companies: list[Company], profile: Profile, answerer: Answerer, settings: Settings,
               workspace: Workspace, tracer: Tracer) -> list[QuickResult]: ...

class CompanyFailed(Exception): ...
def answer_questions(pack: EvidencePack, questions: list[FitQuestion], answerer: Answerer,
                     workspace: Workspace, category: str) -> list[Answer]: ...  # reuses saved answers
def combine(questions: list[FitQuestion], answers: list[Answer], cutoff: float, settings: Settings) -> Verdict: ...
def all_questions(profile: Profile, rules: RulesFile) -> list[FitQuestion]: ...
def choose_cutoff(rows: list[tuple[list[Answer], bool]], questions: list[FitQuestion], settings: Settings) -> float: ...
```

`Workspace` adds `saved_answer(pack_id, question_text, model)`, `save_answer(...)`, `load_rules()`, `save_rules(...)`, `save_cutoff(...)`, `cutoff()`.

- [ ] **Step 1: Write failing tests**

```python
def test_f05_worked_example():
    r = score([(True, True)] * 6 + [(True, False)] * 2 + [(False, True)] * 4 + [(False, False)] * 8)
    assert r.precision == 0.75; assert r.recall == 0.6
    assert r.f05 == pytest.approx(1.25 * 0.75 * 0.6 / (0.25 * 0.75 + 0.6))
    assert r.correct == 14; assert r.n == 20

def test_saying_no_to_everything_scores_zero():
    assert score([(False, True), (False, False)]).f05 == 0

def test_failed_required_question_is_always_a_no(questions):
    v = combine(questions, answers(required=0.2, supporting=0.99), 0.5, settings)
    assert v.yes is False

def test_supporting_answer_can_move_a_company_to_yes(questions): ...
def test_against_question_counts_the_other_way(): ...
def test_no_supporting_questions_means_required_decides(): ...
def test_saved_answers_are_reused_so_only_a_new_question_is_paid_for(workspace, counting_answerer):
    answer_questions(pack, [q1, q2], counting_answerer, workspace, "judge")
    answer_questions(pack, [q1, q2, q3], counting_answerer, workspace, "judge")
    assert counting_answerer.asked == [["q1", "q2"], ["q3"]]

def test_editing_a_question_asks_again(workspace, counting_answerer): ...
def test_changing_the_model_asks_again(workspace, counting_answerer): ...
def test_cutoff_uses_the_given_rows_and_picks_the_best_score(): ...
def test_missing_answer_gets_a_retry_then_raises_company_failed(flaky_answerer):  # Review Focus 3
    with pytest.raises(CompanyFailed):
        answer_questions(pack, [q1], flaky_answerer, workspace, "judge")
    assert flaky_answerer.calls == 2

def test_quick_look_passes_generously_and_orders_strongest_first(companies, answerer): ...
def test_quick_look_answers_are_saved_per_model(workspace, counting_answerer): ...
def test_quick_look_failure_is_marked_failed_not_dropped(failing_answerer): ...
def test_long_ads_are_cut_before_the_model_sees_them(recording_answerer, company_with_huge_ad): ...
```

- [ ] **Step 2: Run `uv run pytest tests/evaluation/test_score.py tests/pipeline/test_quick_look.py tests/pipeline/test_judge.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Strength is the mean of `p` for "for" questions and `1 - p` for "against" questions. With no supporting questions it is 1. Choose the cut-off from a grid of 0.05 steps, taking the lowest value on a tie. Questions go to Jev as separate items, and the state stays small, because its documentation warns that irrelevant text costs accuracy.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add score, quick look and judge`. Decision note: F0.5, and required against supporting questions.

### Task 17: Langfuse tracing in practice

**Files:**
- Modify: `src/why_now/tracing.py`
- Test: `tests/test_tracing_langfuse.py` (marked `live`), plus a unit test with a fake Langfuse client

- [ ] **Step 1: Write the failing fake-client test.** One trace maps to the right names. Steps and scores are counted as units in `UnitCounter`, and the profile, rules version and models appear in the metadata.
- [ ] **Step 2: Run `uv run pytest tests/test_tracing.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement `LangfuseTracer`** against the current SDK documentation. Don't infer from examples. The pricing page also suggests Langfuse's own agent skill, and using it is a choice to raise with the owner.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Owner action: confirm a Langfuse key is set,** then run `uv run pytest -m live tests/test_tracing_langfuse.py` and look at the trace in Langfuse.
- [ ] **Step 6: Commit:** `feat: send traces to Langfuse`

### Task 18: Evaluate, baselines, comparison and the final pile

**Files:**
- Create: `src/why_now/evaluation/evaluate.py`, `evaluation/compare.py`, `evaluation/final_pile.py`
- Modify: `src/why_now/cli.py`
- Test: `tests/evaluation/test_evaluate.py`, `tests/evaluation/test_final_pile.py`

**Interfaces:** Produces:

```python
class CaseRow(BaseModel):
    case_id: str; agent_yes: bool; reviewer_yes: bool; quick_passed: bool; answers: list[Answer]
class PileResult(BaseModel):
    pile: str; check_version: int | None; score: ScoreResult; rows: list[CaseRow]
    failed_cases: list[str]; rules_version: int; models: dict[str, str]

def evaluate_pile(pile: str, rules: RulesFile, run: EvalRun, category: str) -> PileResult: ...
def baselines(pile: str, run: EvalRun) -> dict[str, ScoreResult]: ...  # yes to all, quick look alone, empty rules
class ComparisonResult(BaseModel):
    scores: dict[str, ScoreResult]; winner: str; check_version: int; day: date
def compare_judges(run: EvalRun, answerers: list[Answerer]) -> ComparisonResult: ...
def open_final_pile(run: EvalRun, moment: Literal["first", "after_loop", "publishing", "extra"], reason: str | None) -> PileResult: ...
```

`EvalRun` is a dataclass holding `workspace`, `profile`, `models`, `settings`, `tracer`. `Workspace` adds `save_score_point`, `score_points()`, `final_pile_openings()`, `record_opening`, `save_comparison`. CLI: `why-now evaluate --pile`, `why-now baselines`, `why-now set-cutoff`, `why-now compare-models`, `why-now open-final --moment M`.

- [ ] **Step 1: Write failing tests**

```python
def test_quick_look_drop_counts_as_a_no(run): ...
def test_cant_tell_cases_are_left_out(run): ...
def test_failed_case_is_reported_and_not_counted_as_no(run_with_failing_case):  # Review Focus 3
    r = evaluate_pile("check", rules, run_with_failing_case, "evaluation")
    assert r.failed_cases == ["case-1"]; assert r.score.n == 74

def test_evaluate_refuses_the_final_pile(run):
    with pytest.raises(ValueError):
        evaluate_pile("final", rules, run, "evaluation")

def test_every_final_opening_is_logged(run): ...
def test_extra_opening_needs_a_reason(run):
    with pytest.raises(ValueError):
        open_final_pile(run, "extra", None)

def test_cutoff_is_set_from_practice_only(recording_workspace, run): ...
def test_three_baselines_exist(run):
    assert set(baselines("check", run)) == {"yes_to_all", "quick_look_only", "empty_rules"}

def test_comparison_uses_the_same_cases_and_records_the_winner_either_way(run, answerer_a, answerer_b): ...
def test_comparison_works_without_jev(run_no_jev): ...  # Haiku against Sonnet
def test_score_point_records_rules_version_models_and_n(run): ...
def test_profile_change_blocks_evaluation_until_marked_again(run): ...
```

- [ ] **Step 2: Run `uv run pytest tests/evaluation -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** `open_final_pile` is the only path that reads final cases. Only a pile of `"final"` needs it, and `evaluate_pile` refuses that name.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add evaluation, baselines and model comparison`
- [ ] **Step 6: Live run. Owner action:** approve the expected cost, then run `why-now set-cutoff`, `why-now baselines`, `why-now compare-models` and `why-now open-final --moment first`. Set `judge_model` in the owner's settings to the winner. Record the real numbers in the workspace and describe what they taught in `docs/problems.md`. Close Stage 5.

---

## Stage 6: Daily list

### Task 19: Briefs and the fact check

**Files:**
- Create: `src/why_now/pipeline/brief.py`, `pipeline/fact_check.py`
- Test: `tests/pipeline/test_brief.py`, `tests/pipeline/test_fact_check.py`

**Interfaces:** Produces:

```python
class FactCheckResult(BaseModel):
    ok: bool; problems: list[str]
def fact_check(brief: Brief, pack: EvidencePack, settings: Settings) -> FactCheckResult: ...
def write_brief(pack: EvidencePack, verdict: Verdict, profile: Profile, writer: Writer,
                settings: Settings, tracer: Tracer) -> Brief | None: ...  # None after a second failure
```

- [ ] **Step 1: Write failing tests**

```python
def test_real_quote_passes(pack_with_ad):
    assert fact_check(brief(quote="hiring five sales reps", source=ad_id), pack_with_ad, settings).ok

def test_changed_word_fails(pack_with_ad):
    assert not fact_check(brief(quote="hiring six sales reps", source=ad_id), pack_with_ad, settings).ok

def test_quote_from_the_wrong_source_fails(pack_with_ad_and_page): ...
def test_why_now_quote_must_come_from_a_job_ad(pack_with_ad_and_page):
    b = brief(why_quote_from=page_id)
    assert "job ad" in fact_check(b, pack_with_ad_and_page, settings).problems[0]

def test_spacing_and_case_are_ignored(pack_with_ad): ...
def test_curly_quotes_nbsp_and_dashes_are_ignored(pack_with_typographic_text):  # Review Focus 4
    assert fact_check(brief(quote='the "growth" team - new', source=ad_id), pack_with_typographic_text, settings).ok

def test_empty_brief_fails(pack_with_ad): ...
def test_too_long_brief_fails(pack_with_ad): ...
def test_same_input_gives_same_result(pack_with_ad): ...
def test_failed_brief_gets_one_more_attempt_then_none(writer_always_inventing, pack, verdict):
    assert write_brief(pack, verdict, profile, writer_always_inventing, settings, tracer) is None
    assert writer_always_inventing.calls == 2

def test_retry_tells_the_writer_what_failed(recording_writer, pack, verdict): ...
```

- [ ] **Step 2: Run `uv run pytest tests/pipeline/test_brief.py tests/pipeline/test_fact_check.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Normalise both sides with NFKC, plain quotes and dashes, collapsed spaces and lower case. `fact_check` has no imports from `ai`.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add briefs and the fact check`

### Task 20: The daily run and the sample run

**Files:**
- Create: `src/why_now/pipeline/find_new.py`, `pipeline/day.py`, `run_context.py`
- Modify: `src/why_now/cli.py`, `src/why_now/sample/data.py`
- Test: `tests/pipeline/test_day.py`, `tests/test_sample_run.py`

**Interfaces:** Produces:

```python
@dataclass
class RunContext:
    settings: Settings; store: Store; sources: list[JobSource]; boards: dict[str, BoardList]
    models: Models; reader: PageReader; meter: Meter; tracer: Tracer; clock: Callable[[], datetime]

class ListEntry(BaseModel):
    company_key: str; company_name: str; strength: float | None; brief: Brief | None
    ads: list[JobAd]; pack_id: str | None; first_listed: date
class DayResult(BaseModel):
    day: date; short_list: list[ListEntry]; more_list: list[ListEntry]
    failed: list[str]; skipped: list[str]; costs: BudgetStatus

def find_new(companies: list[Company], workspace: Workspace, settings: Settings, today: date) -> list[Company]: ...
def run_day(ctx: RunContext, profile: Profile, today: date, overrides: dict | None = None) -> DayResult: ...
```

`Workspace` adds `short_list()`, `more_list(today)`, `save_day(result)`, `save_decision(decision) -> bool`, `decisions()`, `hidden_until(company_key)`, `step_result(run, step, key)`, `save_step_result(...)`. CLI: `why-now daily --profile PATH [--short-list-size N] [--new-ad-days N]`, `why-now sample-run`.

- [ ] **Step 1: Write failing tests (highest test seam: the whole daily run, with fakes)**

```python
def test_day_produces_a_short_list_with_checked_briefs_and_a_more_list(ctx, profile, today):
    r = run_day(ctx, profile, today)
    assert 0 < len(r.short_list) <= 10
    assert all(e.brief for e in r.short_list)
    assert all(e.brief is None for e in r.more_list)
    assert [e.strength for e in r.short_list] == sorted((e.strength for e in r.short_list), reverse=True)

def test_a_day_with_few_good_companies_shows_few(ctx_all_no, profile, today):
    assert run_day(ctx_all_no, profile, today).short_list == []

def test_company_with_failed_fact_check_is_dropped_and_recorded(ctx_inventing_writer, profile, today):
    r = run_day(ctx_inventing_writer, profile, today)
    assert r.short_list == []; assert r.failed

def test_old_ads_are_not_new(ctx, profile, today): ...       # older than 14 days
def test_seen_ads_are_not_new(ctx, profile, today): ...      # second day, same ads
def test_decided_company_stays_hidden_for_90_days(ctx, profile, today): ...
def test_marks_do_not_hide_a_company(ctx, profile, today): ...
def test_only_top_12_are_researched(ctx_many_companies, counting_research, profile, today): ...
def test_rerun_after_a_crash_does_not_pay_twice(ctx_crash_midway, counting_research, profile, today): ...
def test_budget_stop_still_reads_and_says_what_was_skipped(ctx_at_limit, profile, today):
    r = run_day(ctx_at_limit, profile, today)
    assert r.skipped; assert r.more_list

def test_one_time_research_pauses_daily_research(ctx, profile, today): ...
def test_research_judge_and_brief_are_traced_and_quick_look_lightly(ctx, recording_tracer, profile, today): ...

def test_undecided_companies_carry_over_at_no_cost(ctx, counting_research, profile, today):  # Review Focus 2
    run_day(ctx, profile, today); first = counting_research.count
    r = run_day(ctx, profile, today + timedelta(days=1))
    assert len(r.short_list) <= 10
    assert counting_research.count == first  # list is full, so nothing new is paid for

def test_two_weeks_away_keeps_the_list_within_its_limit(ctx, profile, today):  # Review Focus 2
    for i in range(14):
        r = run_day(ctx, profile, today + timedelta(days=i))
    assert len(r.short_list) <= 10

def test_short_list_size_can_be_overridden_for_one_run(ctx, profile, today):
    assert len(run_day(ctx, profile, today, {"short_list_size": 20, "new_ad_days": 7}).short_list) <= 20

def test_sample_run_needs_no_keys_and_leaves_the_repo_clean(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    result = run_cli(["sample-run", "--workspace", str(tmp_path)])
    assert result.exit_code == 0; assert "Simulated data" in result.output
    assert git_status_is_clean()
```

- [ ] **Step 2: Run `uv run pytest tests/pipeline/test_day.py tests/test_sample_run.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Order of work: read, search, find new, quick look, then research, judge and brief for the top companies until the short list is full or research hits its limit. Save after each company. The day means the UTC date. A private profile outside the repo loads the same way as any other.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the daily run and sample run`. Decision note: code and workspace kept apart.

### Task 21: Review page

**Files:**
- Create: `src/why_now/web/routes_review.py`, `web/templates/` (review, more, spending)
- Test: `tests/web/test_review.py`

Routes: `GET /` (short list), `GET /more`, `POST /decide/{company_key}`, `GET /spending`.

- [ ] **Step 1: Write failing tests (test seam: web pages)**

```python
def test_private_pages_need_login(anonymous_client):
    for path in ("/", "/more", "/mark", "/spending"):
        assert anonymous_client.get(path, follow_redirects=False).status_code in (302, 401)

def test_short_list_shows_quotes_and_links(client, listed_company):
    html = client.get("/").text
    assert listed_company.brief.why_now.quote in html
    assert listed_company.ads[0].url in html

def test_deciding_needs_a_reason_and_hides_the_company(client, listed_company, workspace): ...
def test_same_decision_twice_saves_one(client, listed_company, workspace): ...
def test_decision_from_the_more_list_is_recorded_as_such(client, more_company, workspace): ...
def test_warning_appears_at_fifty_dollars(client, meter_at_50): ...
def test_skipped_work_is_shown_at_the_limit(client, day_with_skips): ...
def test_empty_day_says_so_plainly(client): ...
```

- [ ] **Step 2: Run `uv run pytest tests/web/test_review.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Approving only records a decision. Nothing is sent anywhere.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the review page`
- [ ] **Step 6: Owner action: real use.** Run `why-now daily` and review the list locally for several days. Note what's hard to read and what goes wrong in `docs/problems.md`. Close Stage 6.

---

## Stage 7: Hidden instructions

### Task 22: Attack set and runner

**Files:**
- Create: `tests/hostile/` for fake-model tests, `src/why_now/hostile/attacks.yaml`, `hostile/runner.py`
- Modify: `src/why_now/cli.py`
- Test: `tests/hostile/test_runner.py`, `tests/hostile/test_guards.py`, `tests/hostile/test_live.py` (marked `live`)

**Interfaces:** Produces:

```python
class Attack(BaseModel):
    id: str; kind: Literal["change_decision", "add_rule", "blocked_address", "plant_text"]
    hostile_pack: EvidencePack; clean_pack: EvidencePack; planted_text: str; blocked_url: str | None
class AttackResult(BaseModel):
    attack_id: str; passed: bool; problem: str | None
def run_attacks(attacks: list[Attack], models: Models, questions: list[FitQuestion], reader: PageReader,
                settings: Settings, category: str) -> list[AttackResult]: ...
```

CLI: `why-now hostile-test --profile PATH`. All attacks are invented text about invented companies.

- [ ] **Step 1: Write failing tests**

```python
def test_each_kind_of_attack_is_covered():
    kinds = {a.kind for a in load_attacks()}
    assert kinds == {"change_decision", "add_rule", "blocked_address", "plant_text"}

def test_decision_that_differs_from_the_clean_twin_fails(model_swayed_by_text): ...
def test_planted_text_in_a_brief_fails(writer_copying_planted_text): ...
def test_reaching_a_blocked_address_fails(research_following_link, reader): ...
def test_guard_every_model_input_marks_ads_and_pages_as_untrusted(recording_models): ...
def test_guard_judge_and_writer_have_no_tools(recording_models): ...
def test_guard_research_has_only_search_and_read(recording_models): ...
def test_passing_answers_pass(honest_models): ...

@pytest.mark.live
def test_real_models_resist_the_attack_set(live_models): ...
```

- [ ] **Step 2: Run `uv run pytest tests/hostile -m "not live" -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Compare with the clean twin using the same `combine` and cut-off as the real judge.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the hidden instruction tests`
- [ ] **Step 6: Live run. Owner action:** approve the cost, then run `why-now hostile-test`. If an attack succeeds, that's a real problem. Fix it and write it up in `docs/problems.md`. Close Stage 7.

---

## Stage 8: The improvement loop

### Task 23: Change screen and keep rule

**Files:**
- Create: `src/why_now/improve/__init__.py`, `improve/screen.py`, `improve/keep.py`
- Test: `tests/improve/test_screen.py`, `tests/improve/test_keep.py`

**Interfaces:** Produces:

```python
class RuleChange(BaseModel):
    action: Literal["add", "edit", "remove"]; question_id: str | None
    question: LearnedQuestion | None; based_on: list[str]
class ScreenResult(BaseModel):
    ok: bool; problem: str | None
def screen_change(change: RuleChange, company_names: set[str], ad_texts: list[str], settings: Settings) -> ScreenResult: ...
def apply_change(rules: RulesFile, change: RuleChange) -> RulesFile: ...  # new file, version + 1

class KeepResult(BaseModel):
    keep: bool; reasons: list[str]
def decide_keep(check_before: ScoreResult, check_after: ScoreResult, practice_before: ScoreResult,
                practice_after: ScoreResult, hostile_passed: bool | None, settings: Settings) -> KeepResult: ...
```

- [ ] **Step 1: Write failing tests**

```python
def test_rejects_a_company_name(): ...  # case-insensitive, whole words
def test_allows_a_common_word_inside_a_longer_word(): ...
def test_rejects_long_text_copied_from_an_ad(): ...  # 8 words in a row
def test_rejects_two_sentences(): ...
def test_rejects_a_long_why_clause_and_a_missing_one(): ...
def test_remove_change_needs_no_new_wording(): ...
def test_cannot_change_a_profile_question():
    with pytest.raises(ValueError):
        apply_change(rules, RuleChange(action="edit", question_id="profile-q1", ...))

def result(correct, f05): ...

def test_keep_needs_all_conditions():
    assert decide_keep(result(60, .60), result(62, .65), result(100, .6), result(100, .6), True, settings).keep

def test_tie_is_a_discard():
    assert not decide_keep(result(60, .60), result(60, .60), result(100, .6), result(100, .6), True, settings).keep

def test_one_more_company_is_not_enough():
    assert not decide_keep(result(60, .60), result(61, .63), result(100, .6), result(100, .6), True, settings).keep

def test_more_companies_right_with_a_lower_score_is_a_discard():
    assert not decide_keep(result(60, .60), result(62, .58), result(100, .6), result(100, .6), True, settings).keep

def test_worse_practice_pile_is_a_discard():
    assert not decide_keep(result(60, .60), result(62, .65), result(100, .6), result(99, .6), True, settings).keep

def test_failed_hostile_tests_are_a_discard():
    assert not decide_keep(result(60, .60), result(62, .65), result(100, .6), result(100, .6), False, settings).keep
```

- [ ] **Step 2: Run `uv run pytest tests/improve/test_screen.py tests/improve/test_keep.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** `hostile_passed=None` means the tests haven't run yet. It returns `keep=False` with the reason `hostile tests needed`, so the run calls them only when the other conditions hold.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the change screen and keep rule`

### Task 24: The improvement run

**Files:**
- Create: `src/why_now/improve/mistakes.py`, `improve/proposer.py`, `improve/run.py`
- Modify: `src/why_now/cli.py`
- Test: `tests/improve/test_run.py`, `tests/improve/test_mistakes.py`

**Interfaces:** Produces:

```python
class Mistake(BaseModel):
    id: str; origin: Literal["practice", "decision"]; company_key: str
    agent_yes: bool; reviewer_yes: bool; reason: str; answers: list[Answer]; quotes: list[str]
def find_mistakes(workspace: Workspace, practice: PileResult, rules: RulesFile) -> list[Mistake]: ...
def propose_change(mistakes: list[Mistake], profile: Profile, rules: RulesFile, tried_summaries: list[str], writer: Writer) -> RuleChange: ...

class TryRecord(BaseModel):
    try_id: str; started_at: datetime; change: RuleChange | None; screen_problem: str | None
    check_before: ScoreResult | None; check_after: ScoreResult | None
    practice_before: ScoreResult | None; practice_after: ScoreResult | None
    outcome: Literal["kept", "discarded", "screened_out"]; reasons: list[str]; cost_usd: float
    rules_version_before: int; rules_version_after: int; check_version: int

class ImproveResult(BaseModel):
    tries: list[TryRecord]; stop_reason: Literal["no_mistakes", "budget", "check_pile_used_up", "not_ready"]

def run_improvement(ctx: RunContext, profile: Profile, today: date) -> ImproveResult: ...
```

`Workspace` adds `save_try`, `tries()`, `tried_mistakes(rules_version)`, `mark_mistake_tried`, `tries_on_check_version(v)`, `loop_started`, `set_loop_started`. CLI: `why-now improve --profile PATH`, `why-now refresh-check`, `why-now night-run`.

- [ ] **Step 1: Write failing tests (test seam: the whole improvement run, with fakes)**

```python
def test_good_change_is_kept_and_the_rules_file_grows(run_ctx_helpful_change, profile, today):
    r = run_improvement(run_ctx_helpful_change, profile, today)
    assert r.tries[0].outcome == "kept"
    assert workspace.load_rules().version == 1

def test_check_pile_falling_means_discard_and_rules_unchanged(run_ctx_harmful_change, profile, today): ...
def test_tie_means_discard(run_ctx_useless_change, profile, today): ...
def test_every_try_is_recorded_including_screened_out(run_ctx_bad_wording, profile, today):
    assert run_improvement(run_ctx_bad_wording, profile, today).tries[0].outcome == "screened_out"

def test_nothing_to_learn_means_no_try_and_no_cost(run_ctx_no_mistakes, meter, profile, today):
    r = run_improvement(run_ctx_no_mistakes, profile, today)
    assert r.stop_reason == "no_mistakes"; assert r.tries == []

def test_stops_when_the_loop_budget_is_spent(run_ctx_loop_at_25, profile, today): ...
def test_stops_when_the_check_pile_has_used_its_tries(run_ctx_50_tries_done, profile, today): ...
def test_discarded_mistake_is_not_retried_until_rules_change(run_ctx_two_mistakes, profile, today): ...
def test_each_try_starts_from_the_last_result(run_ctx_two_good_changes, profile, today): ...

def test_loop_never_receives_check_or_final_content(run_ctx_recording_writer, profile, today):
    run_improvement(run_ctx_recording_writer, profile, today)
    prompt = run_ctx_recording_writer.all_prompts()
    for case in cases_in("check", "final"):
        assert case.company_name not in prompt
        assert pack_text(case)[:80] not in prompt

def test_daily_decision_on_a_check_company_is_not_learned_from(workspace, practice): ...
def test_mistakes_include_wrong_nos_from_practice_and_wrong_yeses_from_decisions(workspace, practice): ...
def test_mistakes_show_how_each_fit_question_was_answered(workspace, practice): ...
def test_loop_can_add_edit_and_remove_only_learned_questions(run_ctx, profile, today): ...
def test_not_ready_without_a_marked_test_set(run_ctx_unmarked, profile, today):
    assert run_improvement(run_ctx_unmarked, profile, today).stop_reason == "not_ready"

def test_hostile_tests_run_only_after_other_conditions_pass(run_ctx, counting_attacks, profile, today): ...
def test_daily_list_works_with_no_test_set(ctx, profile, today): ...
def test_refreshing_scores_the_current_rules_on_the_new_check_pile(run_ctx, workspace): ...
```

- [ ] **Step 2: Run `uv run pytest tests/improve -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Ad text and reasons reach the proposer marked as untrusted. Only the score from the check pile is used, and it's never shown to the proposer in detail. `night-run` runs each daily profile's read, list and improvement. Starting the loop sets the frozen flag on the piles.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the improvement loop`. Decision note: when the loop runs, and why 2 companies is a judgement and not proof.
- [ ] **Step 6: Live run. Owner action:** approve a small spending cap for this step, then run `why-now improve` until real tries have been both kept and discarded. If nothing gets kept, that's a finding to record, not a reason to loosen the rule. Then `why-now open-final --moment after_loop`. Close Stage 8.

---

## Stage 9: AWS

### Task 25: AWS store, login and container

**Files:**
- Create: `src/why_now/store/aws.py`, `web/auth_cognito.py`, `infra/Dockerfile`
- Test: `tests/store/test_store_contract.py`, `tests/web/test_cognito.py`

**Interfaces:** Produces `AwsStore(bucket, table, client_factory)` meeting `Store`. `ad` and `pack` collections and any oversized document go to S3, and everything else to DynamoDB. Produces `CognitoAuth(settings, session_secret)` meeting `Authenticator`, using the OIDC code flow.

- [ ] **Step 1: Write failing tests**

Run the same store tests against both versions, using `moto` for AWS.

```python
@pytest.fixture(params=["local", "aws"])
def any_store(request, tmp_path, moto_aws): ...

def test_round_trip(any_store): ...
def test_prefix_listing_handles_pagination(any_store): ...  # over 1,000 items
def test_large_document_round_trips(any_store): ...         # over the 400 KB DynamoDB limit
def test_login_redirects_to_cognito(anonymous_client_cognito): ...
def test_bad_token_is_refused(client_cognito): ...
def test_session_secret_is_required(settings_aws): ...
def test_container_starts_the_app_and_the_night_run(): ...  # the same image, chosen by command
```

- [ ] **Step 2: Run `uv run pytest tests/store tests/web/test_cognito.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use the Lambda Web Adapter so the same image runs the web app on Lambda and `why-now night-run` on Fargate. Sessions use a signed cookie, secure and same-site.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add AWS store and login`

### Task 26: AWS setup as code

**Files:**
- Create: `infra/app.py`, `infra/stack.py`, `infra/cdk.json`
- Test: `tests/infra/test_stack.py`

**Interfaces:** Produces a CDK stack that reads every name and limit from settings: no account, region or owner detail is written in code. Default region for the owner's copy: `eu-central-1`, set in the owner's settings file.

- [ ] **Step 1: Write failing tests (synthesis tests)**

```python
def test_no_always_on_servers_or_paid_gateways(template):
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 0)
    template.resource_count_is("AWS::RDS::DBInstance", 0)

def test_login_has_no_self_sign_up(template):
    template.has_resource_properties("AWS::Cognito::UserPool", {"AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True}})

def test_storage_is_private_and_charged_by_use(template):
    template.has_resource_properties("AWS::S3::Bucket", {"PublicAccessBlockConfiguration": Match.object_like({"BlockPublicAcls": True})})
    template.has_resource_properties("AWS::DynamoDB::Table", {"BillingMode": "PAY_PER_REQUEST"})

def test_daily_run_is_scheduled_on_fargate(template): ...
def test_web_lambda_has_limited_concurrency_and_a_url(template): ...
def test_logs_expire(template): ...
def test_no_secret_values_in_the_template(template): ...
def test_stack_builds_from_example_settings(): ...
```

- [ ] **Step 2: Run `uv run pytest tests/infra -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Avoid a dependency cycle between the Lambda's URL and the login client: the login client needs the URL, so the stack writes the client ID to Parameter Store and the Lambda reads it at start-up. Use public subnets with no inbound access for Fargate, and a VPC with zero NAT gateways. Lambda runs at a reserved concurrency of 2, so a flood of bad requests can't run up a bill.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add the AWS setup as code`

### Task 27: Owner deployment

- [ ] **Step 1: Owner action.** Check for a personal AWS account, or create one. Add a billing alert to the owner's own address. Install the AWS CLI and Docker Desktop. Node is already installed for the CDK tool.
- [ ] **Step 2: Owner action.** Put secrets in Parameter Store, and create the one Cognito user. No agent handles these values.
- [ ] **Step 3: Deploy.** With the owner's yes: `uv run npx aws-cdk deploy --app "python infra/app.py"`, explaining each step in plain words, since this is the owner's first deployment.
- [ ] **Step 4: Copy the workspace.** Add `why-now sync-workspace --to aws` if the local one is to move, with a test, then copy it.
- [ ] **Step 5: Real deployment check.** Sign in at the web address. Start one night run by hand, and confirm the review page shows the results. Confirm that signed-out visitors see nothing private.
- [ ] **Step 6: Run for a week.** Check daily that the run started and finished, and record the real cost per day. Redo the research and loop limits from measured numbers, and update the design's table.
- [ ] **Step 7: Close Stage 9.** `docs/explained/stage-09.md` covers what each AWS part does and how to answer questions about it. Decision note: Lambda and Fargate, and what was rejected.

---

## Stage 10: Public pages

### Task 28: Public results, rule approval and the score page

**Files:**
- Create: `src/why_now/results.py`, `web/routes_public.py`, `web/routes_rules.py`, `web/templates/` (scores, rules)
- Modify: `src/why_now/improve/run.py`, `evaluation/final_pile.py`, `cli.py`
- Test: `tests/test_results.py`, `tests/web/test_public.py`, `tests/web/test_rules_page.py`

**Interfaces:** Produces:

```python
class ScorePoint(BaseModel):
    profile_id: str; pile: Literal["check", "final", "unsplit"]; check_version: int | None
    day: date; f05: float; precision: float; recall: float; n: int; rules_version: int
    outcome: Literal["kept", "discarded", "screened_out"] | None; try_id: str | None; label: str

class PublicResults:
    def __init__(self, store: Store, settings: Settings): ...
    def add_score(self, point: ScorePoint, profile: Profile) -> None: ...  # no-op unless enabled and the profile is public
    def add_final_opening(self, moment: str, day: date, reason: str | None, profile: Profile) -> None: ...
    def add_comparison(self, result: ComparisonResult, profile: Profile) -> None: ...
    def approve_rule(self, try_id: str, wording: str, why: str, profile: Profile) -> None: ...
    def read_all(self) -> dict: ...
    def export_static(self, out_dir: Path) -> None: ...

def decline_rule(workspace: Workspace, try_id: str) -> RulesFile: ...
```

Routes: `GET /scores` (public), `GET /rules` and `POST /rules/{try_id}/approve`, `/decline` (login).

- [ ] **Step 1: Write failing tests**

```python
def test_public_page_is_off_by_default(anonymous_client):
    assert anonymous_client.get("/scores").status_code == 404

def test_private_profile_never_appears(results_enabled, private_profile, anonymous_client): ...
def test_no_company_name_can_appear(results_enabled, anonymous_client, company_names):
    html = anonymous_client.get("/scores").text
    assert not any(n in html for n in company_names)

def test_empty_page_says_there_is_no_data_yet(results_enabled, anonymous_client): ...
def test_every_number_shows_how_many_companies_are_behind_it(results_with_points, anonymous_client): ...
def test_working_scores_are_labelled_and_final_results_are_separate(results_with_points, anonymous_client): ...
def test_check_versions_are_never_joined_as_one_line(results_two_versions): ...
def test_page_says_what_the_score_means(results_with_points, anonymous_client):
    assert "whether a company would buy" in anonymous_client.get("/scores").text

def test_rejected_try_shows_its_score_and_outcome_but_not_its_wording(results_with_rejected, anonymous_client): ...
def test_approving_copies_wording_to_public_results_and_writes_nothing_to_github(client, kept_try): ...
def test_declining_removes_the_question_from_the_live_rules(client, kept_try, workspace): ...
def test_rules_page_needs_login(anonymous_client): ...
def test_export_makes_a_static_copy(results_with_points, tmp_path): ...
def test_public_routes_read_only_public_results(anonymous_client, spy_store): ...
```

- [ ] **Step 2: Run `uv run pytest tests/test_results.py tests/web/test_public.py tests/web/test_rules_page.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Public data lives in its own collection, and the public routes read nothing else, so private data can't reach them by accident. Read the dataviz skill before writing the score chart.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: add public results and rule approval`
- [ ] **Step 6: Owner action:** turn on public results in the owner's settings, mark the example profile public, deploy, and read the page while signed out. Close Stage 10.

---

## Stage 11: Second profile

### Task 29: Second example profile

**Files:**
- Create: `examples/profiles/` (one file for the second example)
- Modify: `src/why_now/cli.py` (only for an `--unsplit` flag and `--cutoff-from PROFILE`, added generically)
- Test: `tests/test_second_profile_needs_no_code.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_second_throwaway_profile_runs_with_no_changes(ctx, make_profile, today):
    a = run_day(ctx, make_profile(search_words=["sales"]), today)
    b = run_day(ctx, make_profile(search_words=["security"]), today)
    assert a.short_list != b.short_list

def test_unsplit_pile_gives_one_rough_number_using_another_profiles_cutoff(run): ...
```

- [ ] **Step 2: Run `uv run pytest tests/test_second_profile_needs_no_code.py -v`.** Expected: FAIL on the flag only.
- [ ] **Step 3: Implement the generic flag, and write the profile:** the invented tool for passing security checks, from the design.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Check that no engine code changed:** `git diff --stat main -- src/why_now` shows only `cli.py`. Anything else is a generality bug to fix and record in `docs/problems.md`.
- [ ] **Step 6: Owner action.** Approve the cost, mark about 50 companies, then publish one number labelled rough. Daily research pauses during the one-time research, as the design says.
- [ ] **Step 7: Commit:** `feat: add the second example profile`. Close Stage 11.

---

## Stage 12: Simulation page

### Task 30: Clickable simulation

**Files:**
- Create: `src/why_now/web/templates/simulation.html`, `web/routes_simulation.py`, `sample/simulation.py`
- Test: `tests/web/test_simulation.py`

**Interfaces:** Produces `GET /simulation`, public and always on, with its content drawn from `sample/simulation.py`, which holds one invented company taken through every step. Use the frontend-design skill for its look.

- [ ] **Step 1: Write failing tests**

```python
def test_simulation_is_public_and_clearly_labelled(anonymous_client):
    html = anonymous_client.get("/simulation").text
    assert "Simulation" in html; assert "invented" in html

def test_simulation_shows_no_scores_or_percentages(anonymous_client):
    assert not re.search(r"\d+(\.\d+)?\s*%|F0\.5|precision|recall", anonymous_client.get("/simulation").text, re.I)

def test_simulation_covers_every_step(anonymous_client):
    html = anonymous_client.get("/simulation").text.lower()
    for step in ("read", "quick look", "research", "judge", "brief", "fact check", "decide", "improve"):
        assert step in html

def test_simulation_saves_nothing_and_calls_no_model(anonymous_client, spy_store, spy_models):
    anonymous_client.get("/simulation")
    assert spy_store.puts == 0; assert spy_models.calls == 0

def test_simulation_has_no_form_that_posts_to_the_server(anonymous_client): ...
def test_simulation_uses_only_invented_names(anonymous_client, real_company_names): ...
```

- [ ] **Step 2: Run `uv run pytest tests/web/test_simulation.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** Approve and reject buttons run in the visitor's browser only. Copy each step's real behaviour from what was built, and make it work at phone width.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Owner action:** read it and say whether someone new would understand the project in a minute.
- [ ] **Step 6: Commit:** `feat: add the simulation page`. Close Stage 12.

---

## Stage 13: Finish

### Task 31: README, fresh clone and published numbers

**Files:**
- Modify: `README.md`, `docs/how-we-work.md`, `design.md` (table updates)
- Test: `tests/test_fresh_clone.py`

- [ ] **Step 1: Write the failing test**

```python
def test_fresh_clone_runs_the_sample_with_no_keys(tmp_path):
    subprocess.run(["git", "clone", str(REPO), str(tmp_path / "c")], check=True)
    run = subprocess.run(["uv", "run", "why-now", "sample-run"], cwd=tmp_path / "c", env=no_keys_env(), capture_output=True, text=True)
    assert run.returncode == 0; assert "Simulated data" in run.stdout
    status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path / "c", capture_output=True, text=True)
    assert status.stdout.strip() == ""
```

- [ ] **Step 2: Run `uv run pytest tests/test_fresh_clone.py -v`.** Expected: PASS if earlier tasks held. Fix anything that fails.
- [ ] **Step 3: Write the README.** Open by explaining "why now" in plain words. Then cover what it does and doesn't do, how to try the sample, how to run your own copy, what the terms say and that they are each user's responsibility, known limits, and links to the live score page and simulation. It holds no run data, no numbers and no statement about who did which part. No em dashes.
- [ ] **Step 4: Check the writing rule on all public files.** Run a search for em dashes and for the private words across tracked files. Expected: no matches.
- [ ] **Step 5: Follow the README from a fresh clone in a new folder,** by hand, with an agent that hasn't seen the project. Fix what confuses it.
- [ ] **Step 6: Open the final pile.** Owner action: approve it, then run `why-now open-final --moment publishing`. These are the numbers to quote.
- [ ] **Step 7: Review the records.** Check that decision notes match what was built, `docs/problems.md` holds real events, and every design table number still has a true reason.
- [ ] **Step 8: Whole-project review.** A fresh reviewer checks the whole repo against `design.md`. Fix what it finds.
- [ ] **Step 9: Commit:** `docs: finish the README and project records`. Close Stage 13.
- [ ] **Step 10: Stop.** Tell the owner the build is finished. Any public post needs a separate yes.

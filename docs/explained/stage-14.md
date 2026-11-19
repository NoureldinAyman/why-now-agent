# Stage 14: The review site redesign

## Profiles and settings in the workspace (ticket 93)

**What was built.** Profiles and a few settings now live in the workspace, so the AWS image no longer needs a profile built into it and the review page can switch between profiles.

- **Profiles in the workspace** (`src/why_now/workspace/profiles.py`). Saving a profile keeps its newest text under its id, and every version under its hash. A new upload changes what a run uses, and the version recorded on an old mark or decision can still be read with `profile_version`.
- **`why-now profile upload FILE`** (`cli/profile.py`). It checks the file with the same loader as before, and saves it. A broken file saves nothing.
- **Every `--profile` takes a file or an id** (`resolve_profile.py`). A file that exists is loaded. Anything else is an id in the workspace. A file in the working folder named like an id wins, which is said in the function's comment.
- **The site reads the workspace on each visit** (`web/app.py`, `AppContext.current`). Each request gets the profiles and the stored settings as they are at that moment, so an upload shows without a restart. With no profiles, every page says how to upload one. `serve --profile FILE` is optional: it uploads the file first, and saving the profile page then also writes that file.
- **The switcher** is a `<details>` list in the top bar with links, so it needs no script. It keeps to the page the reviewer is on.
- **The profile page.** On one's own computer the text box stays, and saving writes to the workspace and to the file it came from. On AWS it is a readable view with no form.
- **Settings stored in the workspace** (`workspace/settings_doc.py`). One document of overrides sits over the settings file and the environment. Only six names can ever be stored: short list size, days hidden, reason choices, judged-no list size, companies prepared at a time, and the profiles on the night list. Every number has bounds, and the bounds are themselves a setting that the page cannot change. The page stores only values that differ from the file, so a later change to the file still shows.
- **The night list** (`nightly_profiles`) replaces `daily_profiles`. `night-run` works for the ids on it, skips an id with no profile in the workspace, and does nothing, without an error, when none is switched on.
- **`daily --research-per-day N`** raises the research limit for that one run. Nothing is stored.
- The stack now runs `night-run` and gives the web function no profile.

**Why it is built this way.** A stolen sign-in must not raise the budget and start paid runs, and settings that shape the score or the piles must not change after scores have been seen. So the list of editable names is short, fixed in code, checked when saving and again when reading, and the page refuses the whole form if anything else is posted.

**The hardest question:** "If the page can change settings, what stops it changing the budget?" **The honest answer:** the form only reads its own six fields, any other field in the request makes the whole request fail with nothing saved, the document refuses any name outside the list, and a value stored by some other means is still ignored when settings are read. What we have not shown is the page running on AWS with a real sign-in, so the closing check is a try on the deployed site after ticket 94.

## Runs on AWS (ticket 94)

**What was built.** Runs now work on AWS the way they do on one's own computer, and the review page shows what they did.

- **Run notes** (`workspace/runs.py`). Every run writes a note when it starts and when it finishes, wherever it was started. `daily`, `improve` and `night-run` do it through one helper (`cli/run_notes.py`), which writes the finish note however the work ends, so a run that raised an error is noted as failed. A start with no finish reads as running until it is older than `run_stale_hours`, and then as stopped.
- **One run at a time.** The run that is going holds one lock document. It is taken with `Store.swap`, a conditional write: DynamoDB decides in one step, so the schedule, the page and a computer cannot all win. On one's own computer creating is atomic too, and replacing is checked then done, which is enough for one person. A stale lock is taken over, and the run that was taken over cannot release the new run's lock.
- **The night run writes one note for each profile,** holding both halves, the daily list and the improvement loop, so the page shows the night as one run.
- **The stack.** The web function may start the night run's task and nothing else: `ecs:RunTask` limited to that task's family and cluster, and `iam:PassRole` limited to its two roles and to ECS tasks. It has nothing about the schedule. It is told the cluster, task, subnets and firewall as environment values, plus the schedule hour and the display time zone.
- **Run now and Improve now on AWS** (`web/run_now.py`, `AwsRunNow`). They start that task with the command for the chosen mode and profile, after checking for a run that is going. A second press is refused. The cluster and task come from settings, never from the form.
- **The Runs page** (`web/runs_view.py`, `templates/run.html`). It shows the last runs and their summaries, what each try of the last improvement run did, which profiles run each night with a switch, and the next run with the time until it, worked out on the server in the owner's time zone. Its hour is set in the AWS setup, not on the page.
- **`why-now copy-workspace --to SETTINGS`** copies every document of the local workspace into the store the other file names. It skips documents already there and never overwrites one. It leaves out the run lock, run notes, stored settings and the research flag, and says so.
- **Prepare on AWS** (`testset/ads_only.py`) is offered while test case packs hold job ads only. It runs the same prepare with models that refuse every call, so "no paid call" is kept by the code and not only by the setting.

**Why it is built this way.** Two runs at once could lose spending records or tries, so the lock is one conditional write and not a read followed by a write. A stolen sign-in must be able to start a run at most, so the function's permissions name the one task, and the form cannot name anything else. The copy never overwrites, because the improvement run on AWS changes rules, tries and cut-offs after the first copy.

**The hardest question:** "If the page can start a task on AWS, what stops someone using it to run anything else?" **The honest answer:** the function's policy allows `RunTask` only on that task's family and that cluster, `PassRole` only for its two roles to ECS tasks, and nothing in `events` or `iam` beyond that, and a test reads the synthesised template to check it. The command is built from a fixed mode and a profile id that exists in the workspace. IAM cannot limit what command a started task is given, so that limit is in the code: the command is built from a fixed mode and a profile id, and nothing from the form reaches it. Someone holding the web function's own credentials, which is a stronger theft than a sign-in, could start the task with another command and use its role. A stolen sign-in can only start paid runs of that task, one at a time, inside the monthly budget the run itself checks. What we have not shown is a real run on AWS, which needs the deploy the owner says yes to.

**Known gap.** A press of Run now shows as a running run only once the task has started and taken the lock, a little while later. In that while the page notes that a run was asked for, and refuses presses for `run_start_wait_seconds`, which is a guess to be checked on the first real run. A press after that, while the task is still starting, would start a second task, which then refuses at the lock and ends. Nothing is lost.

A second gap is the stale time. A task killed in the night leaves a start with no finish, which reads as running until `run_stale_hours` have passed and only then as stopped, and until then it blocks Run now. Nothing asks ECS whether the task is alive, because that would need more permission for the page.

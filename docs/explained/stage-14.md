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

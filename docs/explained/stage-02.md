# Stage 2: Read job ads

## Settings, shared shapes and the workspace (ticket 03)

**What was built.** The base the rest of the agent stands on:

- **Settings** (`src/why_now/settings.py`). Every number in the design's "Every number, and why" table is a setting with the design's value. A TOML settings file can change any of them, and an environment variable starting with `WHY_NOW_` can change them again, for example `WHY_NOW_SHORT_LIST_SIZE=5`. A misspelt setting name is refused rather than silently ignored. `examples/settings.example.toml` lists every setting with a one-line comment, and a test checks that it stays complete and matches the defaults.
- **Shared shapes** (`src/why_now/domain.py`). The job ads, companies, profiles, evidence packs, answers, briefs, decisions and marks that later steps pass to each other, as pydantic models, which check each field's type when data is read.
- **The store** (`src/why_now/store/`). A small interface for saving JSON documents, with a version that keeps one file per document in a local folder. The AWS version comes in Stage 9 and plugs into the same interface.
- **The workspace** (`src/why_now/workspace/`). Typed reads and writes over the store. Later tickets add their own methods in their own file.
- **The command** (`src/why_now/cli/`). The `why-now` command, with no commands yet. Every file in that folder is loaded automatically, so a new command only touches its own file.

**Why it is shaped this way.** Several sessions will work on tickets at the same time. If every ticket added its commands and workspace methods to one shared file, they would keep editing the same lines. Splitting by area keeps most tickets in their own files.

**Two safety details in the store.** A document is first written to a temporary file and then swapped in with one operation, so if the program stops halfway the old document is still there. Collection names and keys are checked before use, so a name like `../../evil` cannot reach outside the workspace folder. Names that Windows cannot store, such as `con` or `a?b`, are refused too, so the same workspace works on every computer. This matters because some keys will be built from company names found in job ads.

**Limits we know about.** A company name such as "Acme: Labs" is refused as it stands, and on Windows `Acme` and `acme` are the same file, so a later ticket must turn names into safe, lower-case keys before saving. The write is flushed to disk before the swap, but a power cut at the wrong moment can still lose the newest write on some disks. And a new workspace area still adds one line to the list in `workspace/__init__.py`, because the type checker needs to see every area; only commands are found automatically.

**Numbers added to the design.** The plan's settings had 11 lines of numbers that the design's table did not list, such as the size limits for pages and briefs. Each now has a line saying what it protects. Most are starting guesses, and the table says so. The plan also named a fallback model for the quick look only in a comment, so that is now a setting too.

**The hardest question:** "Why not use an existing settings library, such as pydantic-settings, instead of your own loader?"

**The honest answer:** it would work, and it is the usual choice. The loader here is two short functions on top of pydantic, which the project already uses, and it reads one TOML file plus prefixed environment variables, which is all the design asks for. A library would add a dependency and features the project does not need. If settings later need more, such as secrets files, switching is a small change because the rest of the code only sees the `Settings` model.

## Reading Greenhouse (ticket 04)

**What was built.** The first step of a run: reading job ads.

- **The polite client** (`src/why_now/sources/polite.py`). Every request to a job source goes through it. It only ever sends GET requests, which read and never change anything. It waits 1 second between requests to the same job source and names the project in each request. When a job source answers "too many requests" (429) or "busy" (503), it waits as long as the reply asks, and tries up to 3 times in all. If a job source asks for a wait longer than 60 seconds, that careers page counts as failed for the day rather than holding up the whole read.
- **Greenhouse** (`src/why_now/sources/greenhouse.py`). Greenhouse is a hiring service that hosts careers pages for many companies, and its public job board API returns each page's jobs as JSON. The adapter turns each job into the shared job ad shape. Greenhouse sends the ad text as HTML with its tags escaped, like `&lt;p&gt;`, so the text is unescaped once and then all tags are removed, keeping a line break per paragraph or list item. Scripts and styles are dropped completely. Some ads escape their tags twice, and those are stripped a second time, while a plain `<` in a sentence is kept. A job with no address or date is skipped, and the rest of the page is kept.
- **Careers page lists** (`src/why_now/sources/boards.py`). Each job source has a list of careers page names, kept in the person's own settings. A page that fails on 7 separate days with no good read in between is set aside and tried again every 30 days. One good read puts it back on the daily list.
- **The read step** (`src/why_now/pipeline/read.py`). It reads every job source at the same time, one thread each, so each stays polite on its own. One failing page never stops the read. If 90% or more of a job source's pages fail in one read, the job source is reported as down, and no page is counted against. Each ad keeps the date it was first seen, and a page's saved ads are only written again if something changed.
- **The command** `why-now read --sample N` reads N careers pages picked at random from each list, and prints what was read and what failed. Without `--sample` it reads every page due today. `examples/boards.greenhouse.example.json` is a small list of 10 real Greenhouse careers pages to start with.

**Why it is shaped this way.** The design asks for polite reading, so the waiting lives in one place that every job source uses. Each job source has its own client, so a slow one never slows the other. Lever, the second job source, comes next and only needs its own adapter and one line in `src/why_now/sources/registry.py`.

**Measured.** On 6 Nov 2026, a real read of 3 pages from the example list took about 14 seconds and saved 1,418 job ads. None had an HTML tag or escaped tag left in its text. A second read the same day reported 0 new ads and rewrote no files, and `git status` showed no run data.

**Numbers added to the design.** Three new settings, each with a line in the design's table: 3 tries when a job source is busy, 60 seconds at most when asked to wait, and 30 seconds for a job source to answer. All three are starting guesses.

**Limits we know about.** Greenhouse has no country field, so Greenhouse ads have no country. A read of very few pages can look like an outage: with `--sample 1`, one dead page is 100% of the read, so it is never counted against. A `Retry-After` given as a date rather than seconds is ignored, and the client waits 1 second instead. The 90% outage line is a starting guess.

**The hardest question:** "If Greenhouse is down for 6 days and then fails for a seventh day in a smaller way, couldn't real pages be set aside by mistake?"

**The honest answer:** not from the outage days. On a day with 90% or more failures, failures are not counted at all, so the count only grows on ordinary days. A page is set aside only after 7 ordinary days of failing with no good read between them. If Greenhouse fails partly, for example 80% of pages on one day, those pages do take a step towards being set aside. Even then, a page that was set aside by mistake comes back at its next monthly try. The 90% line is a guess, and the read reports both the failed pages and outages, so a wrong line will show.

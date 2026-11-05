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

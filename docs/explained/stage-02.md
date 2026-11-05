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

## Profiles and search (ticket 07)

**What was built.**

- **Profile loading** (`src/why_now/profile.py`). `load_profile` reads a profile from a YAML file. If a field is missing, the error names it, for example `missing field search_words`. A field the loader does not know, such as a misspelt `serach_words` or a misspelt `knd` inside a question, is refused too, because silently ignoring it could turn a filter off without anyone noticing. A profile with no search words is refused, since it would find nothing. A new profile is private unless it says `public: true`.
- **Search and grouping** (`src/why_now/pipeline/search.py`). `search_ads` keeps job ads whose titles contain one of the profile's search words as a whole word, in any letter case, so "sales" finds "Sales Manager" but not "Wholesale Buyer", and a phrase such as "account executive" matches even with extra spaces. Only titles are searched, never the ad text. The kept ads are grouped so each company appears once. A company's key is its careers page name in lower case with only letters and digits, so `Acme-Inc` on Greenhouse and `acmeinc` on Lever become one company. Each company keeps its total count of open jobs, counting every ad it has, not only the ones that matched.

**Why it is shaped this way.** The search runs on every ad every day, so it is plain code with no AI and costs nothing. Titles only, because ad text mentions "sales" in almost every job ("work with our sales team"), which would find nearly every company.

**One decision beyond the plan.** The plan said an ad with no language field is kept. The same is now true of country: Greenhouse ads carry no country field at all, so a country filter that dropped ads without one would drop all of Greenhouse. The cost is that a country filter only narrows Lever ads for now: a profile set to `countries: [SG]` still gets Greenhouse ads from every country. Reading the country out of the free-text location was left out, because guessing it wrongly would hide companies without anyone seeing why.

**Limits we know about.** Two different companies whose page names match after cleaning, such as `acme-inc` and `acmeinc`, are treated as one. The company's display name comes from its first matching ad, and Lever gives no company name, so a Lever-only company shows a tidied page name. A language filter treats an ad tagged `en-GB` as `en`, but a profile asking for `en-GB` does not match an ad tagged `en`. An ad whose careers page name has no letters or digits is skipped, because no company can be named from it. The read step's count of open jobs must use the same `company_key`, or the counts will not line up.

**The hardest question:** "Matching by careers page name is crude. Won't it merge unrelated companies and split real ones?"

**The honest answer:** yes, sometimes. It merges two companies that picked near-identical page names, and it splits one company that uses different names on the two sources. We have not measured how often either happens. It is the rule the design chose because both sources give a page name and nothing better, such as a company website, is in every ad. If the reviewer sees bad merges on the daily list, a better rule can replace `company_key` without changing anything else.

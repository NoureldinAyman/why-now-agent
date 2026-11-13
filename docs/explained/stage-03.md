# Stage 3: Profiles

## The example profile and the setup check (ticket 08)

**What was built.**

- **The main example profile** (`examples/profiles/practice-tool.example.yaml`). A first draft of a profile for an invented practice tool for new sales hires. It has search words, two quick look questions and five fit questions. The two required questions are true deal-breakers: a recruitment or staffing agency hiring for clients, and a company that sells sales training or practice products. The three supporting questions look for growth, new-to-sales hires, and existing training (which counts against). Each question holds one exact condition, because Jev reads literally. The file is a draft for the owner to read and edit, and it is not locked yet.
- **The setup check** (`src/why_now/setup_check.py`, command `why-now check-setup`). It lists what is ready, missing and optional: the sample run, the Claude API key, the Jev key, the Langfuse keys, a careers page list and a profile. Each item that is not ready says how to fix it. It only looks at whether a key is set, and never prints its value. With no keys at all it still says the sample run works, because that uses invented data.
- **Repo rules as tests** (`tests/test_repo_rules.py`). One test fails if an example product's name appears in code, tests, the CI file or the settings examples. One fails if run data or private files (`workspace/`, `private/`, `settings.toml`, `.env`) are tracked by Git. One copies the code and tests into a temporary folder without the example profiles and runs the suite there, to show that deleting them breaks nothing.

**Why it is shaped this way.** The rules "code names no product" and "nothing a run produces is committed" were only written down. Writing them as tests means a mistake fails the build instead of waiting for a reviewer to notice. The product name is read from the profile file itself, so the test needs no list of names, and a second example profile is covered without changing it.

**Limits we know about.**

- The name test is a plain text search, so it would miss a name split across lines or spelt differently.
- A key that is set but wrong still shows as ready. Checking it would mean calling the service, which costs money, so the check only says whether it is set.
- "Deleting the examples" is tested for the profiles only. The settings example is a different kind of file: a test checks that it lists every setting, so it is part of the code's checks and stays.

**The hardest question:** "Your required questions can't be changed by the overnight loop. How do you know these two are the right deal-breakers?"

**The honest answer:** we don't yet. They are a first draft from the design's reasoning: an agency hires for other people, so a hire there says nothing about that company's own team, and a competitor will never buy. The owner reads and edits them before the profile is locked in Stage 4, and the practice pile marking is where a wrong deal-breaker would show up, as good companies wrongly turned down.

## Drafting a profile, its version and its default quick look (ticket 46)

**What was built.**

- **Quick look questions are optional.** `quick_look_questions(profile)` in `src/why_now/profile.py` gives the profile's own list or, when it has none, its required questions plus one question built from who uses the product: "Does the company employ people who fit this description: ...?". The quick look uses it.
- **A profile version.** `Profile.version` is a short hash of what the profile says, so any edit to a field gives a new one, and a comment or a reordered file does not. Marks and decisions record the version they were made under.
- **Drafting.** `draft_profile(description, writer)` in `src/why_now/drafting.py` makes one structured call that writes the product, its users, search words, fit questions and the why-now reason. It leaves out quick look questions, so the derived ones apply. The draft is written out as YAML and read back through the same loader as a file, so a draft is only offered if the loader accepts it. `why-now draft-profile --out PATH` does this from the terminal, and never overwrites a file.
- **Preview.** `preview(workspace, profile, settings)` searches the last saved read with the profile's search words and lists the companies with the most relevant ads. It takes no model, so it cannot make a paid call.

**Why it is shaped this way.** Writing fit questions from nothing is the hardest part of adding a product, so a model drafts them and a person edits them. Saving is the person's approval, because the loop can never change required questions. The version is a hash rather than a counter so it needs no stored state, and an unchanged profile always has the same version on any computer.

**The hardest question:** "The draft comes from a model. What stops it from writing questions that look fine but test two things at once, or a required question that is not truly a deal-breaker?"

**The honest answer:** nothing in code. The prompt asks for one condition per question and for required questions only when a no rules a company out, and the loader checks the shape, not the meaning. The person reads every question before saving, and wrong deal-breakers show up when marking, as good companies turned down.

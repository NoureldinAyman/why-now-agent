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

# Stage 7: Hidden instruction tests

## The attack set and its runner (ticket 26)

**What was built.** A set of invented hostile job ads and pages, each with a clean twin, and a runner that tells us whether the agent resisted each one.

- **The set** (`src/why_now/hostile/attacks.yaml`). 12 attacks, all invented: made-up companies, made-up sentences, made-up addresses. They cover the four kinds we know: changing the decision (3), adding a rule (2), reaching a blocked address (4) and planting text in a brief (3). The file lists each attack's sources once, with the hostile text on the side, so the clean twin is exactly the hostile pack minus that text. Nothing else can drift between them.
- **The runner** (`hostile/runner.py`, `run_attacks`). For every attack it asks the judge about both twins, with the same `combine` and cut-off as the real judge. A decision that differs from the clean twin's is a failure. Then it checks the attack's own aim: a rule holding the planted text that passes the change screen, a page read at the blocked address, or a brief that passes the fact check and holds the planted text. Each result is also written to the trace.
- **The command** (`why-now hostile-test --profile PATH`). It runs the set against the real models and names every attack that worked. It needs a recorded cut-off for the judge model, and it exits with an error if any attack worked.
- **The guards** (`tests/hostile/test_guards.py`). They run the whole set through the real Claude answerer, writer and research model, with only the network replaced by a recording client, and look at every request. Everything from an ad or page must sit inside untrusted tags, the judge and writer must send no tools, and research may send only web search and page reading. A second test checks the hostile text really did reach the models, so the first cannot pass by never having been shown anything. Breaking the writer's untrusted marking on purpose made both fail.
- **Fake models prove the tests can fail.** Each kind of failure has a fake model that obeys the hostile text, and a test that says the attack is caught. A model that ignores the text passes every attack.
- **The live run** (`tests/hostile/test_live.py`, marked `live`). It is written and has not been run. It costs money, and the owner has to say yes first.

**Where it differs from the plan.** The plan's signature for `run_attacks` had no profile, cut-off, tracer or time. Research and briefs need a profile and a tracer, and the decision needs the judge's cut-off, so these were added as named arguments. The rule check asks the writer for a rule change itself, as a stand-in until the improvement loop's own proposer exists.

**The hardest question:** "These tests pass with fake models. Does that show real models resist hidden instructions?"

**The honest answer:** no. They show that the checks fail when a model does obey, and that the real wiring marks text as untrusted and gives the models no extra tools. Whether Claude or Jev resist these 12 attacks is only known after the live run, and 12 attacks are a sample of what a hostile page could try, not all of it. The planted text is also found only word for word (ignoring spacing and case), so a model that paraphrases the instruction into a brief or rule is not caught.

**What it taught:** the phone-number cleaner changes dotted internal addresses in ads before research sees them, so the set uses address forms the cleaner leaves alone. See `docs/problems.md`.

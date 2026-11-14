# Stage 5: Quick look, judge and score

## Quick look

The quick look is the cheap first read of each company's relevant job ads. For every company it asks the profile's quick look questions, takes the mean chance of fit (the answer for a "for" question, one minus the answer for an "against" question), drops companies below the `quick_look_pass` setting, and orders the rest strongest first.

- **Generous on purpose.** The cut-off is low (0.3), because this step only decides what gets researched. A company wrongly dropped is never seen again; a company wrongly passed costs one research run.
- **Saved per model version.** Each answer is saved under the company, its ad text, the question text and the model. A later run reuses it, and a new model version, an edited question or a changed ad asks again. This is what lets the improvement loop rerun only the judge.
- **Failure is visible.** If a model gives an unusable answer, the company is marked failed, passes nothing, and is listed last. It is not dropped. A spent budget is different: it stops the whole run.
- **Long ads are cut.** Each ad is cut to `max_ad_chars` before a model sees it, and only the company's relevant ads are sent.
- **One light trace per run,** with a step per company, because the quick look covers many companies.
- **Works with no key for the preferred answerer,** because it uses whichever answerer it is given, which is the cheap default model when there is no key.

**The hardest question:** "Why drop companies on a cheap model's guess?"

**The honest answer:** the cut-off is a starting guess, set low so that few good companies are lost. Whether it loses good companies is measured later, because every test case also has an evidence pack even when the quick look would have dropped it, so the quick look can be scored alone.

## Score and judge (ticket 17)

**What was built.** The two parts that decide and measure: the judge, which turns a model's answers into yes or no, and the score, which compares those with the reviewer's marks.

- **The score** (`src/why_now/evaluation/score.py`). It counts right and wrong yeses and no's, and works out precision, recall and F0.5, which counts precision more heavily. (Ticket 41 below changed this to F1.) Saying no to everything scores 0. It is checked against worked examples done by hand.
- **Combining answers** (`pipeline/judge.py`, `combine`). The model gives only a probability of yes for each fit question. Code decides: every required question must pass, at 0.5 by default, and the strength, the average over the supporting questions, must reach the cut-off. "Against" questions count the other way. A missing answer stops with an error, so it is never quietly counted as a no.
- **Saved answers** (`answer_questions`). Each answer is saved by evidence pack, question and model. Asking again only pays for questions that are new or edited, or for a new model. The model is shown a question's id, text, and what yes and no mean, so changing any of those asks again. Moving a question between required and supporting, or between for and against, does not, because the model never sees that.
- **One retry.** A reply with a missing answer, a probability outside 0 to 1, or a refusal is tried once more. If that fails too, the company is recorded as failed, and nothing from the failed calls is saved.
- **The cut-off** (`choose_cutoff`). It tries points from 0 to 1, 0.05 apart, on the rows it is given, and keeps the one with the best score, the lowest on a tie. Callers give it practice pile rows only. The workspace records it for each judge model.
- **The question list** (`all_questions`). The profile's fit questions, then the learned ones from the rules file. A rules file for another profile, or two questions with the same id, are refused.

The decision note `docs/decisions/0002-f05-and-required-against-supporting-questions.md` says why F0.5, and why there are two kinds of question. `docs/decisions/0006-f1-replaces-f05.md` later replaced F0.5 with F1.

**Limits we know about.** The judge is not yet run on real evidence packs, which come with research in ticket 11, so no score exists yet. Claude's probability is its own estimate, so a cut-off chosen for one model is not reused for another. Claude answers all the new questions for a company in one call, so a saved answer was given next to other questions than the ones it is reused with. Whether that changes Claude's answers is not measured. Saved answers are never removed, so the workspace grows with every new question and model; each answer is a small file. `CompanyFailed` is raised here, and recording the company as failed is the caller's job, which arrives with the evaluation ticket. The quick look keeps its own saved answers and retry, because it reads job ads rather than an evidence pack.

**The hardest question:** "You choose the cut-off on the practice pile and then use the same pile's mistakes to improve the rules. Isn't the practice pile score then meaningless?"

**The honest answer:** yes, as a measure of quality it is. The practice pile is for learning, and its score is expected to look better than the truth. That is why the cut-off and the rules are judged on the check pile, which the loop sees only as a score, and why the final pile, used rarely, is the number that counts.

## Langfuse traces (ticket 19)

**What was built.** Traces can now go to Langfuse, where a person can open a run and see what was read, asked and answered. It is optional: with no Langfuse keys, the project works as before and keeps its local log.

- **The Langfuse tracer** (`src/why_now/tracing.py`, `LangfuseTracer`). It sits behind the same interface as the local log. A trace is one top-level step named after the trace, with the profile, the rules file version, the models and the level of detail as its notes. Each step is a smaller step inside it, with its input and output, and each score is attached to the whole trace. It counts units the same way the local log does, and thins company traces at the same point, so the local log shows what Langfuse would have received.
- **Choosing the tracer** (`build_tracer`). Langfuse is used only when both keys are set and the library starts. If the library is missing or fails to start, a warning is logged and the local log is used. A run never stops because of tracing set-up.
- **Sending.** Langfuse sends in the background, so each trace ends by asking it to send what it holds. Otherwise a short run could end before anything left the computer.
- **How it was written.** Against the current Langfuse documentation and the installed library (version 5.1), whose method names and arguments were checked directly. The tests use a fake Langfuse client, so they need no keys and no network. One further test, marked `live`, sends a single real trace.

**Limits we know about.** A real trace has not yet been viewed in Langfuse: that needs the owner to confirm the key is set, then run `uv run pytest -m live tests/test_tracing_langfuse.py`. Langfuse accepts note values of up to 200 characters each, so very long model names would be cut. Nothing in the pipeline builds its tracer with `build_tracer` yet, since the evaluation ticket is where runs begin; until then the local log is what the tests use. Langfuse's own agent skill, which its pricing page suggests, was not used, because that is a choice for the owner.

**The hardest question:** "If Langfuse is down or the keys are wrong, do you lose the run's record?"

**The honest answer:** not entirely for a missing library or missing keys, because the local log is used instead. But wrong keys are not found until the first send, and Langfuse sends in the background, so those traces would be lost without stopping the run. The setup check only tests that keys are set, not that they work, so a first real trace should be viewed to be sure.

## F1 score (ticket 41)

**What was built.** The score is now F1, with the weighting as one setting, `score_beta` (default 1), instead of F0.5 fixed in code.

- **`score(rows, beta)`** (`evaluation/score.py`). Works out precision and recall as before, then F-beta. Beta says how much more recall counts than precision: 1 counts them equally, under 1 favours precision, over 1 favours recall. The formula is `(1 + b^2) * P * R / (b^2 * P + R)`. Beta 1 weighs a missed company the same as a wrong yes. Beta 0.5 gives the old F0.5 numbers exactly. A beta of 0 or less is refused. Saying no to everything still scores 0.
- **`ScoreResult`** has `f` and `beta`. The beta is stored with every score, so a saved score always says what it measured. Nothing is called `f05` any more.
- **`choose_cutoff`** (`pipeline/judge.py`) scores each cut-off with `settings.score_beta`.
- **`decide_keep`** (`improve/keep.py`) compares `.f`, and refuses with an error if the four scores it is given do not all use the same beta. Scores with different weightings are not on one scale, so a keep decision that mixed them would be meaningless.
- **The setting** `score_beta` must be above 0. It is in the example settings file and the design's numbers table, with the reason in `docs/decisions/0006-f1-replaces-f05.md`.

**Example.** 6 right yeses, 2 wrong yeses and 4 missed: precision is 0.75 and recall is 0.6. F1 is 2 * 0.75 * 0.6 / 1.35 = 0.667. F0.5 on the same rows is 0.714, higher, because it forgives the missed companies more.

**Limits we know about.** The beta must be fixed before marking starts, but nothing in the code enforces that: it is a rule for the owner, written in the decision note. The cut-off test rows had to change, because on the old rows F1 prefers a lower cut-off than F0.5 did.

**The hardest question:** "Why not just keep F0.5, since a wrong yes wastes the reviewer's time?"

**The honest answer:** the short list has a limit on its size, which already protects the reviewer's time. A wrong no is never seen at all. F1 does not push the agent towards the mistake nobody can notice. If this turns out wrong, it is one setting to change, but only before marking starts, so that the score is not tuned after seeing results.

## Effort per job, and versioned saved answers (ticket 42)

**What was built.** Each Claude job now runs at a fixed effort, and every saved answer is labelled with the exact setup that gave it.

- **Effort settings** (`src/why_now/settings.py`). Effort is how much a Claude model thinks before it answers, and so how much it costs. There is one setting per job: `quick_look_effort = "low"`, `research_effort = "medium"`, `judge_effort = "medium"`, `writer_effort = "medium"` and `proposer_effort = "high"`, the starting choices in the design's AI models table. Only `low`, `medium` and `high` are accepted, the range the design allows. Without a setting, Claude Sonnet 5.5 would quietly run at high and Claude Haiku 5.5 at medium, so the cost would depend on each model's default rather than on a choice we wrote down. `proposer_effort` has no caller yet. The improvement run will use it.
- **Every request carries its effort** (`src/why_now/ai/claude.py`, `ClaudeCaller.create`). The call sends `output_config={"effort": ...}`, next to the answer format when there is one. This shape was checked against the current `anthropic` documentation. `build_models` hands each job its own effort. Jev has no effort, so `quick_look_effort` only matters when the quick look falls back to Claude.
- **The answer key** (`src/why_now/ai/__init__.py`, `answer_key`). Each model now has an `answer_key` that names the model, its effort and its prompt version in one label, such as `claude-sonnet-5-5@medium#p1`. Jev's has no effort part (`jev-1.14.0#p1`). The writer's has no prompt part (`claude-sonnet-5-5@medium`), because its prompts come from the code that calls it, so the brief adds its own (`BRIEF_PROMPT_VERSION`) to its trace. Each prompt has a version number next to it in the code (`ANSWER_PROMPT_VERSION`, `RESEARCH_PROMPT_VERSION`, `JEV_PROMPT_VERSION`, `BRIEF_PROMPT_VERSION`), to be raised whenever the prompt changes in a way that could change answers.
- **Saved answers and cut-offs use the key** (`src/why_now/workspace/judge.py`, `src/why_now/workspace/quick_look.py`). The judge and the quick look save each answer under the answer key instead of the bare model name, so a changed effort or prompt version asks again and the same setup reuses the saved answer for free. A cut-off is saved per answer key too, so one chosen for the judge at medium effort is never used at high effort.
- **Traces record it.** Every trace's `models` field now holds the answer key, so a trace shows the effort and prompt version of each model, as the design asks.

**Limits we know about.**

- Raising a prompt version is a person's job. If someone edits `ANSWER_SYSTEM` and forgets to raise `ANSWER_PROMPT_VERSION`, old answers are reused. A test could compare a hash of the prompt with a recorded one, but that would fail on harmless edits too, so for now the comment next to the prompt is the guard.
- The writer's key has no prompt version, because one writer serves several prompts. Briefs are not saved and reused, so the brief's version only labels its trace. When the proposer arrives, its prompt version belongs in its own trace the same way.
- Workspaces that saved answers or a cut-off under the bare model name will not find them any more, and are asked again. Nothing was moved, because no real marks or cut-offs exist yet.

**The hardest question:** "Why not keep the effort and prompt version as fields in the saved answer, instead of squeezing them into the key?"

**The honest answer:** because a field is only a note, while the key decides what gets reused. If the effort were a field, every reader would have to remember to check it, and one forgotten check would mix answers from two setups into one score. With the effort and prompt version inside the key, an answer from another setup is simply never found, so it can't be reused by mistake. The cost is that changing the effort once asks every question again, which is what the design wants.

## Evaluation, judge comparison and consistency (ticket 20)

**What was built.** The code that grades the agent against the reviewer's marks. It is one module, `evaluation/evaluate.py`, with the commands in `cli/evaluation.py`. Nothing here has been run on the real models yet. The live step waits for the reviewer's check pile and for a yes on the cost.

- **`evaluate_pile`** scores the agent on the practice or check pile. For each company the reviewer marked yes or no, it runs the quick look and then the judge, as the daily run does, and compares the agent's answer with the mark. A company the quick look drops counts as a no. A company the models cannot answer for is listed in `failed_cases` and left out of the score, never counted as a no. A company marked can't tell, or not marked yet, is left out.
- **Rows.** Each graded company is kept as a row: the agent's answer, the reviewer's, whether the quick look passed it, and the judge's answers. The baselines and the improvement loop read rows and need no new model calls.
- **`open_final_pile`** is the only way to read the final pile. `evaluate_pile` and `baselines` refuse the name `final`. Each opening writes a log entry first, and an `extra` opening needs a reason.
- **`set_cutoff`** chooses the cut-off from the practice pile only, with the judge answering every marked practice company. It records the cut-off under the judge's answer key. A test proves that no check or final pack is opened.
- **`baselines`** scores three simple rivals: yes to every company, the quick look alone, and the agent with an empty rules file.
- **`compare_judges`** gives each judge its own cut-off from the practice pile, scores both on the same check pile companies, and records the winner whichever way it goes. A company either judge cannot answer for is dropped for both. On a tie the first judge listed wins, and the command lists the current judge first, so a tie changes nothing.
- **`consistency`** asks the same questions again and again on practice packs with no saved answers, and reports for each question how far the answers moved: the highest answer minus the lowest, as an average and a worst case. Fixed answer levels are not built. They are tried only if the spread turns out large.
- **Records.** Every score, comparison, consistency result and final pile opening is added to the workspace and never edited. Each score records the rules version, the profile version and the model keys, so scores are only joined into a line when all of them match.
- **Short-list precision** is printed on its own line by `why-now evaluate`, apart from the pile scores.
- **Settings.** `consistency_asks` (5), `consistency_packs` (20) and `judge_candidates` (the two judges to compare).

**Example.** The check pile holds Acme (marked yes), Beta (no) and Cora (no). The quick look drops Cora. The judge says yes to Acme and no to Beta. The agent's score is one right yes and two right no's. Yes to all would score one right yes and two wrong yeses. The quick look alone would give Beta a wrong yes.

**Limits we know about.**

- With a check pile of about 75 companies, one company moves precision by about 4 points, so every number is shown with its company count.
- The consistency check is rough: its numbers come from 20 packs.
- The cut-off is chosen on every marked practice company, not only those the quick look passes, so it describes the judge alone.

**The hardest question:** "Why is the final pile refused by name, when someone could just edit the workspace files?"

**The honest answer:** the refusal stops the commands and the code, not a person editing files by hand. It makes an accidental look impossible and a deliberate one visible, because every opening through the one door is logged and made public. A person who reads the files directly would not be caught, so the rule depends on the owner not doing it.

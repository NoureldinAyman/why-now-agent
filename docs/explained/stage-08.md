# Stage 8: The improvement loop

## Change screen and keep rule (ticket 28)

**What was built.** The two gates a rule change must pass before it can stay. Neither calls a model, so both are cheap and exact.

- **The screen** (`src/why_now/improve/screen.py`, `screen_change`). A script rejects a change that names a company (whole words, any capitals), copies 8 or more words in a row from an ad, has a question of more than one sentence, or has a why clause that is missing or over 20 words. It checks the question and the words saying what yes and no mean. A remove needs no new wording, so it passes.
- **Applying a change** (`apply_change`). It returns a new rules file with the version raised by one, and leaves the old one alone. It refuses to edit or remove any question that is not a learned question, so a profile question cannot be changed. It also refuses to add a question with an id already in use.
- **The keep rule** (`src/why_now/improve/keep.py`, `decide_keep`). A change stays only if the check pile score rises, at least 2 more companies are right on the check pile, the practice pile gets no worse, and the hidden instruction tests pass. A tie, one more company, or more companies right with a lower score are all discards. Each failed condition is listed as a reason.
- **Hostile tests last.** They cost money, so `hostile_passed=None` means they have not run. It gives a discard with the reason `hostile tests needed`, and the run calls them only when the other conditions already hold.

The numbers (2 companies, 8 copied words, 20 words of reason) are settings, and each has a line in the design's table.

**Limits we know about.** The screen catches names it is given and copied runs of words. It does not catch a rewording of ad text, or a company hinted at without its name. "Practice pile no worse" means neither its score nor its count of right companies drops, even by one. That is strict on purpose, and the first live tries will show whether it throws away useful changes. The run that uses these gates is the next ticket.

**The hardest question:** "Two more companies on a pile of 75 is tiny. Isn't that luck?"

**The honest answer:** it can be. Two is a judgement, not proof, and it is a setting. It is paired with a rising score, and the loop is capped at 50 tries per check pile, so luck cannot be farmed forever. The final pile, used rarely, is the number that counts.


## The improvement run and its commands (ticket 29)

**What was built.** The loop that uses the screen and the keep rule, and the two commands that start it.

- **Finding mistakes** (`src/why_now/improve/mistakes.py`). A mistake is a company where the agent's yes or no differs from the reviewer's. It comes from two places: the graded practice pile, and the reviewer's daily decisions (a rejected short-list company is a wrong yes, an approved judged-no company is a wrong no). Companies whose test case is in the check or final pile are left out of the decisions. Each mistake carries the reviewer's reason and a few short ad excerpts, shown to the AI as untrusted text. The reasons given for correct yeses are collected too.
- **Asking for one change** (`proposer.py`). One call to the writer model, charged to the loop's share of the budget. The briefing is built field by field from the profile, so the marking guide cannot reach it by accident.
- **The record of tries** (`records.py`, `workspace/improve.py`). Every try is kept, whichever way it ended, with its cost, both scores before and after, and its reasons. The mistakes already tried are kept as one list for each rules version.
- **The loop** (`run.py`). Each round it finds the mistakes not yet tried at this rules version, asks for a change, screens it, measures the old and new rules on the check and practice piles, applies the keep rule, and records the try. The hidden instruction tests run last, only when every other condition holds. The new rules are saved only when the change is kept.
- **The commands** (`cli/improve.py`). `why-now improve` runs the loop once and says in plain words what each try did. `why-now night-run` makes the daily list for each profile and then runs the loop for it.

Four settings were added, each with a line in the design's table: `mistake_ads` (3), `mistake_ad_chars` (300), `tries_per_run` (3) and `new_check_companies` (25).

**What stops it.** It is not ready until the check pile has 15 yes answers. After that it stops when there are no untried mistakes, when the loop's share of the budget is spent, after 3 tries in one run, and after every 50 measured tries until 25 new companies have joined the check pile.

**Decisions made while building it.**

- A mistake is tried once for each rules version. When a change is kept, the version changes and its mistakes can be tried again.
- A tie is recorded as discarded, with the reason that the check score did not rise.
- Only measured tries count towards the 50. A change stopped by the screen touched no pile.
- A try cut short by the budget is not recorded, because its measuring was not finished, and its mistakes are not marked tried, so the next run asks about them again. What was spent stays in the budget book, not in a try record.
- A try's cost includes the scoring its round needed. A round that finds no mistakes asks the AI nothing and does not score the check pile.
- The loop keeps only the check pile's score. Its companies are never held, and a test shows that a wrongly judged check company and a wrongly judged final company never reach the AI.
- The screen uses company names and ads from every pile to catch a leak, because it is a script and nothing it reads goes to the AI.
- The hidden tests need a cut-off recorded on the practice pile, and are charged to the loop's budget share.

**Limits we know about.** Mistakes from daily decisions carry the reviewer's reason but not the agent's answers or ad excerpts, so the first runs learn mostly from the practice pile. The AWS schedule still runs `why-now daily` only, so the loop does not yet run there. The first real tries are not described here yet.

**The hardest question:** "The machine proposes the rule and the machine scores it. Isn't that marking its own homework?"

**The honest answer:** the scoring is not its own. The reviewer's marks decide every score, and the proposer never sees the check or final piles, only the practice pile and the daily decisions. A change still has to raise the score by 2 or more companies, leave the practice pile no worse and pass the hidden tests. But luck can get a bad change through a small pile, which is why a run makes at most 3 tries, and why after 50 tries the loop waits for 25 new check companies. The number that counts is the final pile, opened rarely.

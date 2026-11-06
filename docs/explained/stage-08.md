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

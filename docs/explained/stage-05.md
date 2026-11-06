# Stage 5: Quick look, judge and score

## Score and judge (ticket 17)

**What was built.** The two parts that decide and measure: the judge, which turns a model's answers into yes or no, and the score, which compares those with the reviewer's marks.

- **The score** (`src/why_now/evaluation/score.py`). It counts right and wrong yeses and no's, and works out precision, recall and F0.5, which counts precision more heavily. Saying no to everything scores 0. It is checked against worked examples done by hand.
- **Combining answers** (`pipeline/judge.py`, `combine`). The model gives only a probability of yes for each fit question. Code decides: every required question must pass, at 0.5 by default, and the strength, the average over the supporting questions, must reach the cut-off. "Against" questions count the other way. A missing answer stops with an error, so it is never quietly counted as a no.
- **Saved answers** (`answer_questions`). Each answer is saved by evidence pack, question and model. Asking again only pays for questions that are new or edited, or for a new model. The model is shown a question's id, text, and what yes and no mean, so changing any of those asks again. Moving a question between required and supporting, or between for and against, does not, because the model never sees that.
- **One retry.** A reply with a missing answer, a probability outside 0 to 1, or a refusal is tried once more. If that fails too, the company is recorded as failed, and nothing from the failed calls is saved.
- **The cut-off** (`choose_cutoff`). It tries points from 0 to 1, 0.05 apart, on the rows it is given, and keeps the one with the best score, the lowest on a tie. Callers give it practice pile rows only. The workspace records it for each judge model.
- **The question list** (`all_questions`). The profile's fit questions, then the learned ones from the rules file. A rules file for another profile, or two questions with the same id, are refused.

The decision note `docs/decisions/0002-f05-and-required-against-supporting-questions.md` says why F0.5, and why there are two kinds of question.

**Limits we know about.** The judge is not yet run on real evidence packs, which come with research in ticket 11, so no score exists yet. Claude's probability is its own estimate, so a cut-off chosen for one model is not reused for another. Claude answers all the new questions for a company in one call, so a saved answer was given next to other questions than the ones it is reused with. Whether that changes Claude's answers is not measured. Saved answers are never removed, so the workspace grows with every new question and model; each answer is a small file. `CompanyFailed` is raised here, and recording the company as failed is the caller's job, which arrives with the quick look and evaluation tickets.

**The hardest question:** "You choose the cut-off on the practice pile and then use the same pile's mistakes to improve the rules. Isn't the practice pile score then meaningless?"

**The honest answer:** yes, as a measure of quality it is. The practice pile is for learning, and its score is expected to look better than the truth. That is why the cut-off and the rules are judged on the check pile, which the loop sees only as a score, and why the final pile, used rarely, is the number that counts.

# F0.5 as the score, and required against supporting questions

Decided 6 Nov 2026 (ticket 17).

**Note:** The score part is replaced by `0006-f1-replaces-f05.md` (8 Nov 2026). The parts on required and supporting questions and the cut-off still hold.

## The score is F0.5

The agent's yes or no on each company is compared with the reviewer's mark. Two measures come out of that:

- **Precision:** of the companies the agent said yes to, the share the reviewer also said yes to.
- **Recall:** of the companies the reviewer said yes to, the share the agent found.

F0.5 combines them and counts precision more heavily. A wrong yes costs a person a few minutes reading a brief about a company that does not fit, every day it comes up. A missed company costs nothing that day, and it may come up again when it posts a new ad. Precision and recall are always shown next to the score, so the trade can be seen.

Two cases the score must get right, and does:

- An agent that says no to everything has no yes to be right about. Its precision is set to 0, so its score is 0, not undefined.
- An agent that says yes to one safe company has a precision of 1 but a low recall, so it scores poorly. With 1 right yes out of 10 real ones, F0.5 is about 0.36.

**Other options.**

- **Accuracy**, the share of companies called right, rewards saying no when most companies are no. If 1 in 5 is a yes, saying no to everything is 80% accurate.
- **F1** weighs precision and recall equally, which does not match the cost of a wrong yes.
- **Precision alone** rewards saying yes only to the safest company.

## Required against supporting questions

Each fit question is a yes/no question the model answers with a probability. Code, not the model, turns those answers into yes or no, the same way for every model.

- **Required questions are deal-breakers.** Each must pass, at a probability of at least 0.5 (`required_pass`), or the company is a no, however well it does elsewhere. A required "against" question passes when no is that likely.
- **Supporting questions set the strength.** Strength is the average of the probability of yes for "for" questions and of no for "against" ones. With none, it is 1, so the required questions decide. A company is a yes when its strength reaches the cut-off.

**Why two kinds.** A required question can only turn a yes into a no. A supporting question can move a company either way, so learned supporting questions let the improvement loop fix wrong yeses and wrong no's. The loop changes only the rules file, so the deal-breakers a person wrote in the profile stay as they are. Profiles keep required questions to true deal-breakers for that reason.

**Why an average.** It is simple to explain, it stays between 0 and 1 for any number of questions, and adding one question does not swamp the others. Questions are not weighted. Weights would be more numbers to fit on a small practice pile.

## The cut-off

The cut-off is chosen on the practice pile only, and recorded for each judge model. Points from 0 to 1, 0.05 apart (`cutoff_step`), are tried, and the one with the best F0.5 is kept. On a tie, the lowest wins, because it lets more companies through for the same score. The check and final piles are never used to choose it, so their scores are not fitted to them.

## Limits

- Claude's probability is its own estimate, not a trained one, so the same cut-off may not mean the same thing for Claude and Jev. That is why each judge model has its own cut-off, and why the two are compared on the check pile before the loop starts.
- An average lets a strong answer hide a weak one. A question that should never be outweighed belongs among the required questions.

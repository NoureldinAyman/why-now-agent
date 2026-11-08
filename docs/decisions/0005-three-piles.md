# Three piles

Decided 6 Nov 2026 (ticket 14).

**Note:** How piles are filled, frozen and refreshed is replaced by `0007-piles-fill-as-companies-are-marked.md` (8 Nov 2026). Why there are three piles, and repeat marking, still hold.

## What the piles are

The marked companies are split once into three piles, each company in exactly one:

- **Practice, 150.** The improvement loop reads its mistakes here.
- **Check, 75.** Decides whether a change is kept. The loop sees only the score.
- **Final, 75.** Locked. Opened only at the milestones in the design, and only these numbers are quoted as results.

The sizes are the settings `practice_size`, `check_size` and `final_size`.

## How the split is made

- A seed fixes it. The same marks and the same seed always give the same piles, whatever order the cases are read in, and the seed is printed.
- Yes and no answers are shuffled apart and dealt out in step, so each pile gets its share of yes answers. Check and final never differ by more than one yes.
- A can't-tell is in no pile, and neither is a company not yet marked. Another company takes its place by being marked.
- If more companies are marked than the piles hold, the extra are left out at random but in proportion, so the share of yes does not move. If fewer are marked, the piles keep their proportions at a smaller size, and the report shows the real sizes.
- A pile is reported short when its yes answers are below `target_yes_per_pile`. The report is only a report: the owner decides whether to mark more companies, up to the ceiling, or to lower the aim and say publicly that the numbers are rougher.

## Why three and not two

A check pile that is measured again and again wears out, even though the loop never reads it: a change is kept when it scores well there, so the kept changes slowly fit its quirks. A final pile that nothing measures until a milestone is the only number that has not been chosen against. Two piles would leave one pile doing both jobs, and its score could not be trusted as a result.

## Frozen once the loop starts

Splitting is refused once the loop has started. A split that could change afterwards would let a company move from the final pile into practice, and the loop would then read it.

The one allowed change is refreshing the check pile. The old check companies move to practice, newly marked companies become the check pile, and the pile gets the next version label. The final pile is never touched. A new company can't be added if it is already in a pile. Scores from different check versions are never joined as one line.

## Repeat marking

About a week after the first marks, 30 companies are picked at random from the yes and no answers old enough, and the reviewer marks them again. The repeat page shows the evidence pack and the form, and never reads the first mark, so neither the answer nor the reason can reach it. The 30 are picked once. How often the two answers match is the real number that shows about how high any agent could score. It is reported with the number of companies behind it, and as rough.

## What was rejected

- **Picking the final pile by hand or by difficulty.** It would stop being a fair test.
- **Re-splitting after the loop starts, with a note.** A note does not undo what the loop has read.
- **Counting can't-tell as a no.** It would put an answer in the pile that the reviewer never gave.

## Limits

- With 75 companies and about 25 yes answers, one company moves precision by about 4 points. The design says so everywhere numbers are quoted.
- The freeze is kept by the workspace, not by the files themselves. It stops the commands, not someone editing the workspace by hand.

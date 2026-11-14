# Piles fill as companies are marked

Decided 8 Nov 2026. Replaces "How the split is made", "Frozen once the loop starts" and the refresh rule in `0005-three-piles.md`. Why there are three piles still holds.

**Note:** test case packs and pile sizes changed on 14 Nov 2026. See `0008-smaller-test-set-from-ads.md`.

## What changed

Before, the reviewer marked about 300 companies, then one command split them into practice, check and final, and the split was frozen once the loop started. Now each company's pile is decided the moment it is picked, and the piles fill together as the reviewer marks, in sittings of any size.

## How a pile is decided

When "Prepare" picks a company, a fixed calculation (a hash) of the seed and the company's key gives a number, and that number gives the pile, in the ratio 150 to 75 to 75. The reviewer is never shown it.

- **Nothing the reviewer does can move a company.** Not the order of marking, not a can't tell, not skipping a company. A draw made when a mark is saved would depend on those, so it was rejected.
- **The same seed and company always give the same pile,** so the split can be repeated and shown not to be hand picked.
- **A company never changes pile.**

## What it costs

- **Yes answers are not dealt out evenly.** The old split shuffled yes and no apart so check and final had about the same number of yes answers. A hash can't know the answer in advance. Every score shows its real counts instead.
- **Piles start small.** The loop waits until the check pile has at least 15 yes answers, the lowest aim per pile in the design.

## How a try stays fair on a growing pile

- Before and after a change are scored on the check pile as it stands when the try starts, with one cut-off chosen on the practice pile as it stands then.
- Saved answers make the "before" score almost free to recompute.
- Each score records how many companies its pile held. Scores taken on different sizes are labelled and never joined as one line.
- After 50 tries, further tries wait until at least 25 new companies have joined the check pile. The final pile is what guards against a worn check pile.

## Why

The reviewer will mark in occasional sittings, not in one long stretch. One big split after 300 marks meant nothing could be measured until all the marking was done. Piles that fill as companies are marked let the first numbers, and the first tries, come as soon as there is enough to judge them by.

## Rejected

- **Drawing the pile when a mark is saved.** It depends on marking order and on can't-tell answers.
- **Keeping one split after all the marking.** Fair, but nothing works until hundreds of marks are done.
- **Moving worn check companies to practice, as the old refresh did.** It would make before-and-after comparisons harder, for little gain.

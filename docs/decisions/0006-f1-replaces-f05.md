# F1 replaces F0.5

Decided 8 Nov 2026. Replaces the "The score is F0.5" part of `0002-f05-and-required-against-supporting-questions.md`. The rest of that note, on required and supporting questions and the cut-off, still holds.

## What changed

The score is now F1, which weighs precision and recall equally, instead of F0.5, which counts precision more. The weighting is one setting, `score_beta`, the same for every profile.

## Why

F0.5 was chosen to protect the reviewer's time: a wrong yes costs minutes reading a brief. Two things showed that reason was weaker than it looked:

- **The short list already protects the reviewer's time.** It never shows more than 10 companies. Even if half are wrong, that is a few minutes a day.
- **A wrong no is the mistake nobody sees.** A company judged no appears on neither list, and it comes back only if it posts a new ad. A wrong yes is seen, rejected, and learned from. A score that favours precision pushes the agent towards the mistake that can't be noticed.

A missed company that would have been a good fit can be worth far more than a few wasted minutes.

## Why not F2

F2 counts recall more. A list full of poor companies loses the reviewer's trust, and once the reviewer stops reading the list, every good company on it is missed too. Equal weight is the plain middle.

## Rules

- `score_beta` is fixed before marking starts. Changing it after seeing scores would be a way to tune the score itself.
- It is one setting for all profiles, so scores of different profiles mean the same thing.
- Every saved score records the beta it used. Scores with different betas are never joined as one line.
- Precision and recall are always shown next to the score.

## Rejected

- **Near misses on the more list**, companies judged no by a small margin. Nobody makes decisions on the more list, so nothing would be learned from them, and it would need another margin number. The practice pile already shows wrong no's, because its companies are picked at random.
- **A different beta per profile.** More to explain, and scores across profiles would no longer compare.

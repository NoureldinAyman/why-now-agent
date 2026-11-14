# A smaller test set, built from job ads

Decided 14 Nov 2026. Changes the pile sizes in `0007-piles-fill-as-companies-are-marked.md` and what a test case's evidence pack holds in `0003-frozen-evidence-packs.md`.

## What changed

- **Piles of 45, 45 and 45,** about 135 marks in all, instead of 150, 75 and 75.
- **Test case packs hold the company's job ads only,** with no web research.
- **A small judged-no list** shows a few companies the daily run researched and judged no, so the reviewer can decide on them.
- **The profile holds a marking guide,** a short text saying what makes a company a yes, a no or a can't tell.
- **The cut-off is tried at points 0.1 apart,** instead of 0.05.

## Why

Marking about 300 companies is hours of work for one person, and the project exists to save that person time. Each part of the change cuts the work or the cost while keeping the score honest:

- **45 per pile** is the fewest that gives each pile about 15 yes answers, when about 1 company in 3 is a yes. The loop can start once the check pile has 15 yes answers, so this is also about when marking can stop.
- **Ads-only packs** cost nothing to prepare, because the ads are saved by the free read. Most of what decides a company, such as being a recruitment agency or hiring several salespeople at once, is in its ads.
- **The judged-no list** gives the loop the mistakes it can actually fix. A company dropped at the quick look can't be fixed by learned rules, but a company that was researched and then judged no can.
- **A marking guide** keeps marks consistent across sittings. It sits in the profile, so changing it makes a new profile version, and scores from different versions are never joined.
- **Cut-offs 0.1 apart,** because with about 15 yes answers on the practice pile, finer steps fit luck.

## What it costs

- **Rougher numbers.** With 15 yes answers, one company moves precision by about 7 points instead of about 4. Public numbers say they are rough and show how many companies are behind them.
- **The score measures judging from ads,** not from ads and websites. Research quality was already outside the score.
- **Daily packs and test packs differ.** Daily packs keep web research for the companies the reviewer sees, where briefs need facts. A judge that does well on ads alone may do a little differently with more text.

## Rejected

- **Homework on companies the agent is unsure about.** Most of them are dropped at the quick look, where the loop can't fix anything, and picking them would remove borderline companies from later random picks, making the check and final piles easier than the real job.
- **A model marking every test case through the API.** It would cost money each time a test set is built, and the score would measure agreement with that model.
- **Fewer than about 15 yes answers per pile.** One company would then decide whether a change looks better.

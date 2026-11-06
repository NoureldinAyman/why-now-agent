# Code and workspace kept apart

Decided 6 Nov 2026 (ticket 23).

## What is where

- **The repo** holds code, tests, example profiles and invented sample data. It is the same for everyone who clones it.
- **The workspace** holds everything a run produces: job ads, evidence packs, the two lists, decisions, saved steps, seen ads, spending and traces. Where it lives is the `workspace_path` setting.

The daily run never writes anywhere else. Every document goes through the workspace, and every name in it starts with the profile, so two profiles never share a list, a decision or a seen ad.

## How the daily run keeps them apart

- **A profile can live anywhere.** The command takes a path. A profile outside the repo loads the same way as an example one, and nothing in the code names a product.
- **The sample run uses a folder of its own.** `why-now sample-run` writes into a new temporary folder unless it is given one, so invented companies can never mix with a real workspace. A test runs it and checks that the state of the repo is the same before and after.
- **The sample run uses no keys.** It builds its own scripted models and a tracer that writes to the folder, and it does not read the keys from the environment at all.
- **Everything the sample prints says it is simulated data.**

## What was rejected

- **A default `workspace/` folder for the sample run.** Git ignores it, but it is where the owner's real data lives. A sample run would have put invented companies on the owner's real short list.
- **Saving a sample result in the repo to show what a run looks like.** It would be run output in the repo, which the design forbids. The command shows it live instead.
- **Keeping the day's lists only in memory.** The short list must survive between days, because a company waits for a decision. The lists are documents in the workspace, so a company decided on the review page leaves them without the run being involved.

## Limits

- A reviewer's decision hides a company by the date of the decision, not by the date it was listed. A company decided on the same day it was listed leaves the list at once.
- The sample run is a plain run on made-up data. It shows that the flow works, not that the agent's judgement is any good.

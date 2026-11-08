# Why-Now Agent: Agent Instructions

`design.md` is the approved design. `docs/superpowers/plans/2026-11-05-why-now-agent.md` is the plan, with the exact names, signatures and tests for each task. Read both before working on a ticket, and use the words in `GLOSSARY.md`.

## Working on a ticket

1. Pick a ticket labelled `ready-for-agent` whose blockers are all closed and that has no assignee. Run `gh issue edit <number> --add-assignee @me` before anything else, so other sessions leave it alone.
2. Work on its own branch, named `ticket-NN-short-name`, with one pull request per ticket.
3. Follow the plan tasks the ticket names. Write the failing test first.
4. Before opening a pull request, run all of these, and all must pass:
   - `uv run pytest -m "not live"`
   - `uv run ruff check .`
   - `uv run pyright`
5. Add real problems to `docs/problems.md`, dated. Add a section to `docs/explained/stage-NN.md` saying what was built and why, in plain words, with the hardest question someone could ask about it and the honest answer. Add any decision note the ticket lists to `docs/decisions/`.
6. Open the pull request with `gh pr create`, with `Closes #<number>` in its body. Add a "Try it yourself" section: 2 to 3 commands or clicks, what the owner should see, and the cost, free or an estimate. A fresh reviewer checks it. It merges only after the owner's yes.
7. When the work is done, explain it to the owner in chat, in plain words: what was built, how it works and why, with a small example. This is a learning project, so this step is never skipped.

Tickets labelled `ready-for-human` belong to the owner. Don't pick them up on your own. Some say the owner builds them with Claude: then work as a guide, explaining and reviewing, while the owner decides and writes the code. If a ticket needs the owner, stop and ask. Never act on a guess about what the owner would mark, approve or pay for.

## Rules that always apply

- **Account:** before any push or anything that creates something on GitHub, `gh api user --jq .login` must print `NoureldinAyman`.
- **Commit identity:** set for this repo only, name `NourEldin Ayman`, email `97467977+NoureldinAyman@users.noreply.github.com`.
- **Nothing a run produces is ever committed.** Real job ads, evidence packs, test cases, marks, decisions, rules files and scores stay in the workspace.
- **The `private/` folder is never committed or described.**
- **No code, test or setting may name a product.** Example profiles are plain files that can be deleted without breaking anything.
- **Every number is a setting,** never fixed in code. A new number gets a setting and a line in the design's "Every number, and why" table.
- **Never send an email or message to anyone.** The job sources' endpoints for submitting applications are never called.
- **LinkedIn is never read,** for search or for pages.
- **Only real, measured numbers in anything public.** Estimates stay out of public text.
- **Public text is plain and modest, with no em dashes.** The README describes the project, not who did which part.
- **The owner enters all keys and card details.** Secrets come from the environment, or from Parameter Store on AWS.
- **Tune on the practice pile only.** Prompts, effort and other settings are never tuned while watching check or final pile scores.
- **Live calls cost money.** Anything marked `live` runs only on purpose, after the owner's yes, and counts against the budget.
- **Check library details before writing against them.** Read the current documentation for `anthropic`, `typesafe-sdk` and `langfuse`.

## Agent skills

### Issue tracker

Tickets live in GitHub Issues on NoureldinAyman/why-now-agent, using the gh CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels, with `ready-for-agent` and `ready-for-human` in daily use. See `docs/agents/triage-labels.md`.

### Domain docs

Single context: one `GLOSSARY.md` and one decisions folder. See `docs/agents/domain.md`.

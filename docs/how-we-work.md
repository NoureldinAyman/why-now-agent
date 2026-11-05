# How This Project Is Built

The project is built with coding agents. A person makes the decisions, and agents do most of the typing.

1. **Design.** Each choice was questioned one at a time and written into `design.md`, with the rejected options. An independent reviewer then read it as if they had to build from it.
2. **Plan.** `docs/superpowers/plans/` holds the exact names, signatures and tests for every task.
3. **Tickets.** The plan is split into GitHub issues, each a piece that works on its own. Issues say which others block them, so several sessions can work at once.
4. **Build.** Each ticket gets its own branch. Tests are written first.
5. **Review.** A fresh reviewer checks each pull request, and a person says yes before it merges.
6. **Records.** `docs/decisions/` holds the big choices, `docs/problems.md` holds what went wrong, and `docs/explained/` explains each stage in plain words.

Instructions for agents are in `AGENTS.md`.

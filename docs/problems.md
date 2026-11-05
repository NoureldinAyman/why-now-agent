# Problems

What actually went wrong and what it taught. Real events only, newest last.

## 5 Nov 2026: The loop could only make the agent stricter

A review of the first design found that learned rules could only reject companies. Only required questions decided yes or no, and a required question can only turn a yes into a no. The agent could never recover a good company it had wrongly rejected, and supporting rules could never change the score, so they could never be kept.

**What it taught:** check that a loop can move in both directions before trusting it. Supporting questions now count towards a cut-off, so a change can move a company either way.

## 5 Nov 2026: Results were going to travel with the code

The first design published approved rules and scores to the repo. Anyone cloning it would have received someone else's learned rules and scores.

**What it taught:** keep what a run produces apart from the code. The repo now holds only code, and each person has their own workspace.

## 5 Nov 2026: Some limits had no real reason

Asking "why this number?" about each rule in the design showed that some rules were guesses that sounded precise, such as "at least 5 new mistakes" and "twice a week".

**What it taught:** a number stays only if we can say what it protects and where it came from. The rest were removed, and the remaining ones are listed in the design with their reasons.

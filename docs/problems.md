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

## 5 Nov 2026: An antivirus blocked the tracing service

The first key check failed for Langfuse with a connection error, although the keys were right and other tools on the same computer could reach the site. The antivirus on the development computer was scanning secure web traffic. It sat in the middle of each connection and presented its own certificate, a kind of ID card for the site, in place of the real one. Windows trusted that certificate, but Python keeps its own list of trusted issuers, so it refused the connection with a certificate error. The owner removed the antivirus, and the check passed. The Claude check passed through the same scanning, and we have not yet found out why.

**What it taught:** a connection error is not always a wrong key, so read the full error before changing anything. Anyone running the project behind such scanning, or on a work network that does the same, may hit this.

## 5 Nov 2026: Jev access needed paid credit

TypeSafe, which makes Jev, said on its X account on 27 Sep 2026 that new accounts no longer get free credit. Its console would not create an API key while the account had no credit, and we found no code for free credit published by TypeSafe. The owner added $5 of prepaid credit with automatic top-up turned off, so the account cannot spend more than that while top-up stays off, and created a key. A check that lists Jev's models passed.

**What it taught:** Jev access is confirmed, so the judge comparison can run Jev against Claude as the design intends. Someone cloning the project may have to pay before trying Jev, which is one reason it stays optional and the quick look falls back to Claude Haiku without it.

## 5 Nov 2026: The ignore rule for run data hid a code folder

The rule that keeps the workspace out of Git was written as `workspace/`, which matches a folder with that name anywhere in the repo. When ticket 03 added the code package `src/why_now/workspace/`, Git ignored it without a warning, and the first commit of the ticket left it out. It showed up only because the list of files to commit was missing it.

**What it taught:** an ignore rule meant for one folder should be anchored to where that folder lives. It is now `/workspace/`, which matches only the folder at the top of the repo, where the default workspace lives. Check the list of files in each commit, not just that tests pass.

## 5 Nov 2026: Two sessions shared one folder

Ticket 04 and ticket 07 were worked on at the same time in the same folder. The ticket 07 session switched the folder to its own branch without noticing that the ticket 04 session had unsaved files there, and saw ticket 04's half-finished tests fail its lint check. No work was lost, because Git carries uncommitted files across a branch switch, and the folder was put back on ticket 04's branch while ticket 07 moved to its own Git worktree.

**What it taught:** one branch per ticket is not enough when sessions share a folder. Each session working at the same time needs its own worktree, and a session should check for files it did not write before switching branches.

## 6 Nov 2026: The store refused safe names when two threads wrote at once

The read step reads each job source in its own thread. A test that reads two sources at once failed now and then with "name leaves the workspace", for an ordinary name like `l`. The store checked each name by asking the disk where the file would really be, and comparing that with where the workspace really is. On Windows, that answer can briefly come out in a different form while another thread is creating a folder or swapping in a file next to it, so the two paths stopped matching. A test with 32 threads writing at once failed every time.

The check now compares the two paths as text, after making both absolute, without asking the disk. The rules for names already refuse `..`, slashes and names starting with a dot, so a name still cannot reach outside the workspace.

**What it taught:** a test that fails only sometimes is a real bug, not bad luck. Run it in a loop until it fails and read the full error.

## 6 Nov 2026: The read counted every ad as new on a second read

The first real read of 3 Greenhouse careers pages saved 1,418 job ads. A second read the same day also reported 1,418 new ads. The summary counted ads first seen today, and on the same day that is every ad. The saved dates were right, only the count was wrong. It now counts ads that no earlier read had seen, and the second read reports 0 new.

**What it taught:** running the real command twice found what the tests missed, because the tests only ever read once on a given day.

## 6 Nov 2026: The plan asked for something the model no longer allows

The plan said the Claude judge should be made to answer through one forced tool call, a common way to get answers in a fixed shape. Reading the current Claude documentation before writing the code showed that Claude Sonnet 5.5, the judge, rejects forced tool calls with an error. Code written from the plan would have failed on its first real call, after all its tests had passed against a fake.

**What it taught:** a fake only behaves the way we believe the real service does, so check the current documentation before writing against a service, as the project's rules say. The judge now asks for structured output, where the reply must match a JSON schema, which gives the same fixed shape.

## 6 Nov 2026: Common Crawl's index fails often, and one failure looked like a bug

The first real runs of `build-list` failed. Reply 504 (gateway time-out) came back for both job sources, and one Greenhouse run crashed with a JSON error because a reply was cut off in the middle of a line. The tests only used a fake index that never did this. A cut-off reply is now treated like a time-out: the command tries again, and after 3 tries it says it could not build the list, writes nothing, and leaves any existing list as it was. Later runs worked for both job sources.

**What it taught:** a public archive is slow and uneven, so a list-building command has to expect failure, and the first live run is part of the testing.

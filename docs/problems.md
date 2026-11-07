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

## 6 Nov 2026: Python's own address check let some internal addresses through

The page reader first relied on Python's `is_global` check to tell public addresses from private ones, and every planned test passed. A review then found that Python 3.13 counts `64:ff9b::7f00:1` and `::7f00:1` as public. Both are IPv6 forms that carry the IPv4 address `127.0.0.1` inside them, and on a network that translates IPv6 to IPv4, a request to the first is passed on to `127.0.0.1`. The reader now takes the IPv4 address out of these forms and checks that instead, with tests for both.

**What it taught:** a library's "is this public" answer follows its own lists, not our threat. The tests should include the tricky forms an attacker would try, not only the usual private ranges.

## 6 Nov 2026: Langfuse sends in the background, so a bad key shows up late

Langfuse's library queues traces and sends them from a background thread, and the setup check only looks that the keys are set. So wrong keys would not raise an error where the trace is made: traces would quietly not arrive. Each trace now ends by asking Langfuse to send what it holds, and a failure there is logged as a warning and never stops the run or hides the run's own error. Metadata values are also limited to 200 characters each, so a very long value would be cut.

**What it taught:** a "keys are set" check is not a "keys work" check. The first real trace has to be looked at in Langfuse.

## 6 Nov 2026: A longer short list still stopped at 12

The first test of the one-run list size asked for 20 companies and got 12. Nothing was broken. The daily limit of 12 researched companies caps the short list, because a company only reaches it after research, and changing the list size for one run does not change that limit. A reviewer who asks for 20 would see 12 and no reason why. The command help and the stage notes now say that the list can only be as long as the research limit allows, and the limit stays a separate setting that is not changed for one run, so a mistyped command cannot spend extra money.

**What it taught:** two settings that look independent can limit each other. Write a test for the pair, not only for each one.

## 6 Nov 2026: The plan's list functions could not work out the hide days

The plan gave `hidden_until(company_key)` and `more_list(today)` no way to know how many days a decision hides a company. That number is a setting, and the workspace does not hold settings. `hidden_until` now takes the hide days as an argument. The lists need no number: a company leaves them when a decision is made on or after the day it was listed.

**What it taught:** a plan written before the code can leave out where a number comes from. Check each signature against the rule that every number is a setting.

## 6 Nov 2026: The daily run tests are slow

Each daily run test saves many small documents, and the local store writes every one to its own file and flushes it to disk before swapping it in, so a stop never leaves half a document. On Windows, the 25 daily run tests took 72 seconds. They are slow rather than wrong, and only the local store would need to change if it becomes a problem.

**What it taught:** a store built to survive a crash is paid for in every test that uses it.

## 6 Nov 2026: Two workspace areas both defined `_key`

The marks area first named its key helper `_key`, the same as the test cases area. The workspace joins all areas into one class, so the later definition hid the earlier one, and saving a mark failed with a message about the wrong number of arguments. A test caught it the first time a mark was saved. The helper is now `_mark_key`.

**What it taught:** the areas share one name space, so a helper that two areas could want needs a name that says whose it is.

## 6 Nov 2026: Windows sometimes refuses the store's file swap

A daily run test failed about half the time in one session and passed the rest, with no change to the code. The cause was `PermissionError: Access is denied` when the local store swapped a new copy of a document into place, most often the tracing unit counter, which is rewritten for every trace. Something else on the computer briefly held the file. The daily run did what it should: it recorded that one company as failed, tried the next, and carried on. A test that counted exact positions on the list then saw a different list.

The store itself has not been changed. Retrying the swap briefly would be the fix, and it needs a number, so it is left for the owner to decide.

**What it taught:** a failure that comes and goes is the computer, not the logic, but it still shows where a store used from many places needs to be gentler. Read the full error before deciding.

## 6 Nov 2026: Reading a job ad turns an internal address into "[phone removed]"

While writing the hostile ads, one of them told the reader to fetch the cloud machine's own address, written the usual way with four numbers and dots. Running the ad through the step that removes phone numbers showed that research never sees it: the address has 12 digits in groups, which the phone rule counts as a phone number, so the text becomes `http://[phone removed]/latest/meta-data/`. That is a mild extra protection for the usual spelling only. The same address written as an IPv6 form (`[::ffff:a9fe:a9fe]`) goes through untouched, and it is the page reader's address check, not the phone rule, that refuses it.

The hostile set therefore uses the IPv6 forms and `localhost` for the blocked addresses, so those attacks really reach the model. A test that used the dotted form would have passed without testing anything.

**What it taught:** a defence that works by accident is not a defence. Check what the model really receives, not only what the test fed in.

## 6 Nov 2026: The plan's piles interface had nowhere to keep two things

The plan lists the functions for piles and repeat marking, but not where the frozen flag lives or where the 30 picked companies are written down. Both are needed: the split must be refused after the loop starts, and the repeat page must show only the picked companies. The flag is a small workspace area with the names the improvement loop task already expects (`loop_started`, `set_loop_started`), and the picked companies are kept beside the marks.

**What it taught:** an interface list is not finished until every function's inputs and outputs have a home. Ask where each fact is stored.

## 6 Nov 2026: Splitting 300 cases in a test takes minutes

The first piles tests saved 300 cases and 300 marks into a real workspace folder for several tests, and 18 tests took 146 seconds, because the local store flushes every document to disk. The tests that save to a workspace now use small piles (12, 6 and 6) through the same settings, and run in 9 seconds. The tests of the split itself still use the real sizes, because they never touch the disk.

**What it taught:** a test of logic should not pay for storage, and a test of storage does not need full size.

## 6 Nov 2026: An unused network client made a login test take 7 seconds

One login test took over 7 seconds while the others took a fraction of a second. It only checked that a forged session cookie is refused, and it never called Cognito. The time went into setting up a network client when the login was created. Timed alone on this computer, making the first client took 1.7 seconds and the next 0.7, and more while other tests were running. The client is now made the first time it is needed, and the test takes under a second. On Lambda this also shortens every start, since most requests only read the session cookie.

**What it taught:** slow set-up hides in constructors. Make expensive things when they are first used, and read the slowest tests list, not only the total.

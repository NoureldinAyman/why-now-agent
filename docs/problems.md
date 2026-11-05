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

The first key check failed for Langfuse with a connection error, although the keys were right and the site answered in a browser. The antivirus on the development computer was scanning secure web traffic: it opened each connection and re-sealed it with its own certificate. Windows trusted that certificate, but Python keeps its own list of trusted issuers and refused the connection. The owner removed the antivirus, and the check passed. The Claude check passed through the same scanning, and we have not yet found out why.

**What it taught:** a connection error is not always a wrong key, so read the full error before changing anything. Anyone running the project behind such scanning, or on a work network that does the same, will hit this. When the code that calls outside services is written, consider using the computer's own list of trusted issuers.

## 5 Nov 2026: Jev access needed paid credit

Jev's maker stopped giving free credit to new accounts on 27 Sep 2026, and its console refuses to create an API key while an account has no credit. No public code for free credit exists. The owner's country was not on the billing country list, so the owner chose "Other", which the console accepted. The owner then added $5 of prepaid credit with automatic top-up turned off, so the account can never spend more than that, and created a key. A free check that lists Jev's models passed.

**What it taught:** Jev access is confirmed, so the judge comparison can run Jev against Claude as the design intends. Someone cloning the project may not get access as easily, which is why Jev stays optional and the quick look falls back to Claude Haiku.

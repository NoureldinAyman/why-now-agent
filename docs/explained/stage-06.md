# Stage 6: Daily list

## Briefs and the fact check (ticket 22)

**What was built.** The step that writes a brief for each company the judge says yes to, and the script that checks it before a reviewer sees it.

- **The brief** (`src/why_now/pipeline/brief.py`, `write_brief`). Claude writes the brief from the evidence pack only, as a list of claims. Each claim has a short text in its own words, a quote copied word for word, and the id of the source the quote came from. One claim is the why-now claim, which says why the company needs the product now. The pack goes to Claude marked as untrusted text, the same way as in the other steps.
- **The fact check** (`pipeline/fact_check.py`, `fact_check`). A script with no AI. It confirms each quote appears in the source the claim names, that the why-now quote comes from a job ad and not a web page, that no claim is empty, and that the brief is within `brief_max_chars` (1,200 by default, counting every claim's text and quote). The same brief and pack always give the same result. The file imports nothing from the AI parts.
- **What it ignores.** Before comparing, both sides are normalised: Unicode normalisation (NFKC, which also turns non-breaking spaces into plain ones), curly quotes and dash styles made plain, invisible soft hyphens and zero-width spaces removed, runs of spacing made one space, and lower case. So a quote that only looks different from the saved page still passes. Every word must still match, and a quote must start and end on whole words, so "iring five" taken from "hiring five" fails.
- **One more attempt.** A brief that fails gets one more attempt, and Claude is told each problem the fact check found. A reply that does not fit the brief's shape counts as a failed attempt too. If the second attempt also fails, `write_brief` returns nothing: the company is dropped and never reaches the reviewer.
- **Recorded.** Each attempt, its fact check result, and a pass or fail score go in the brief's trace, so a dropped company's failure can be looked at later and counted.

**The hardest question:** "A quote can be real and still be used to support a claim it doesn't support. Doesn't that make the fact check weak?"

**The honest answer:** yes, it checks that the quotes are real, not that the claims follow from them. It catches made-up quotes and quotes from the wrong place, which a script can check exactly and the same way every time. Whether a claim reads its quote fairly is left to the reviewer, which is why each claim carries its quote and source: the reviewer can check it in seconds.

## The daily run and the sample run (ticket 23)

**What was built.** The whole daily flow in one command, and a free way to try it.

- **The run** (`src/why_now/pipeline/day.py`, `run_day`). It reads the careers pages, searches them by the profile's words, finds what is new, does the quick look, then researches, judges and briefs the strongest companies one at a time. Each company's steps are saved as they finish. The result has the short list, the more list, what failed, what was skipped and what has been spent.
- **What is new** (`pipeline/find_new.py`). A company is new if it has a relevant ad published in the last 14 days that the run has not finished with before. A company with a decision in the last 90 days is skipped. Marks on test cases never hide a company, because only decisions do.
- **The short list** is the companies still waiting for a decision from earlier days, plus new ones, strongest first, never more than 10. While it is full, no new company is researched. Two weeks away leaves the list at the same size, and a decision frees a place the next day.
- **The more list** holds companies that passed the quick look but were not researched, with no brief. It drops a company when its newest ad leaves the 14 day window, or when a decision is made on it.
- **Only the top are researched.** At most 12 a day, and never more than it takes to fill the short list. The rest wait on the more list.
- **A rerun after a crash.** Research, the brief and the judge's answers are saved per company as they finish, so a rerun the same day pays only for what was not done.
- **At the budget limit.** The read still runs. Every paid step checks the budget first, and the run says what it skipped. Companies it did not get to are listed without a strength and are tried again the next day.
- **One run only.** `--short-list-size` and `--new-ad-days` change those two settings for one run. Nothing else can be changed that way, so a mistyped command cannot raise the budget. A longer list is still limited by the daily research limit.
- **The sample run** (`why-now sample-run`). It runs one day on invented companies, with scripted answers, and needs no keys or network. Every heading says it is simulated data, and by default it saves into a new temporary folder, so it never touches a real workspace. A test checks that the repo is unchanged afterwards.

**The hardest question:** "The short list stops at 10, so what happens to the good company that ranks 11th?"

**The honest answer:** it goes on the more list with no research and no brief, and it is not looked at again unless the reviewer opens it. The design accepts this, because a list the reviewer cannot get through is worth less than a shorter one, but it does mean a good company can be missed on a busy day. The test cases are picked at random for this reason: they show how often good companies are wrongly left out.

## The review page (ticket 24)

**What was built.** The private page where the reviewer reads each brief and approves or rejects it. Approving only records a decision. Nothing is sent to anyone.

- **The pages** (`src/why_now/web/routes_review.py`). `/` is the short list, strongest first. `/more` is the more list. `/spending` is this month's money. `POST /decide/{company_key}` saves a decision. Every one needs the login, the same one as the marking pages, and a sent form is refused rather than sent to a sign-in page.
- **What a brief shows.** The why-now claim first, then the other claims, each with its quote word for word and a link to the job ad or company page the quote came from. The company's relevant ads are listed with links. A link is only made for a web address, because an address read from the internet could hold anything.
- **Deciding.** Approve or reject, with a reason that is one or more short chips, a sentence, or both. Without a reason nothing is saved and the page says so. A saved decision hides the company from both lists straight away, and for 90 days after.
- **The same form twice saves one.** A company that is no longer waiting is not decided again, so a second press, or a second tab, changes nothing and lands back on the list. The check and the save happen under one lock, so two copies sent at the same moment cannot both pass.
- **The more list.** The same form, folded away under each company. A decision made there is recorded as coming from the more list.
- **Spending.** The top of the page shows this month's spending against the limit, with a warning at the warning amount. At the limit it says paid work is stopped and lists what the last run skipped. Both amounts are settings.
- **Short-list precision.** Of the decisions made on short-list companies, the share approved, with its count. Decisions from the more list are left out, because the agent did not put those forward. It is shown apart from the scores and says so.
- **An empty day** says so plainly, and says when no daily run has been saved yet.
- **Look.** One style sheet for every page, with no script, outside font or outside picture, because the pages' security policy allows none of them. So every picture is inline SVG drawn from the data (`src/why_now/web/visuals.py` and the templates): a small geometric tile for each company, made from a hash of its key so the same company always looks the same; rings for spending and short-list precision, filled from the numbers; a row of ticks for how fresh a company's newest ad is, one tick for each day of the new-ad window; and a bar splitting the month by what it paid for. A tile says nothing about a company. It only helps tell companies apart before reading a name. The marking pages use the same style, so the two halves look like one tool.

**The hardest question:** "Short-list precision is a free number. Why not use it as the score?"

**The honest answer:** because the agent chose those companies and the reviewer judged them from briefs. It says how often the agent's yeses were approved, but nothing about the good companies it left off the list, which a wrong no hides. The score comes from randomly picked companies for that reason. The two numbers sit apart on the page and are never added together.

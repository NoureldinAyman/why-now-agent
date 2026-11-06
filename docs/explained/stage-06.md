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

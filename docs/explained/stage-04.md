# Stage 4: Test cases

## AI parts, budget stop and tracing (ticket 09)

**What was built.** The parts every later step uses to call a model, pay for it and keep a record of it:

- **The budget meter** (`src/why_now/ai/budget.py`). Before a paid call, the meter checks there is money left this month. After it, the meter charges the real cost, worked out from the tokens and web searches the model reports, at the prices in the settings. Spending is kept per calendar month in the workspace, so a new month starts at zero. Paid calls stop at $70, a warning shows from $50, and fixed monthly costs, such as hosting, count from the first day. The improvement loop has its own $25 share: once that is spent the loop stops, and the rest stays for research.
- **Claude and Jev parts** (`ai/claude.py`, `ai/jev.py`). They answer fit questions with one probability each, write structured text, and take research steps. Every Claude call goes through one small class that checks the budget, makes the call and charges it, so no call can skip the meter. Jev, which is optional, sends each question as a Noul, its yes/no question type, and returns the probability of yes.
- **Checks on what comes back.** An answer is refused if a question is missing or answered twice, if a probability is outside 0 to 1, if the reply is cut off, or if the model refuses. The cost is still charged, because the call was still paid for. The caller decides whether to try again.
- **Untrusted text.** Job ad and page text is wrapped in `<untrusted_text>` tags, and every model is told that text inside them is data, never instructions. Any look-alike tag inside an ad is removed, so an ad cannot close the tag early and write outside it.
- **One search a step.** In research, Claude may run at most one web search per step, so the research steps setting also limits searches, which cost money and are a way a hostile page could lead the agent further. LinkedIn is blocked for search.
- **Locked versions.** A Jev name must have a full version, such as `jev-1.14.0`. The moving names `jev-latest` and `jev-preview` are refused, and so is any model with no price, so every call can be costed.
- **Tracing** (`src/why_now/tracing.py`). A local log writes one JSON line per event to the workspace, with the profile, the rules file version and the models at the start of each trace. A counter keeps the month's tracing units. Near the setting, company traces are thinned: steps are counted but not written, and scores are kept. Tries are always kept in full. Sending traces to Langfuse comes in Task 17, behind the same interface.
- **Scripted models** (`src/why_now/sample/models.py`). Stand-ins that answer from a script, so tests and the sample run need no network, keys or money.

**A change from the plan.** The plan said the Claude judge should answer through one forced tool call. The current Claude models refuse forced tool calls, so the judge asks for structured output instead: the reply must be JSON that matches a schema. `docs/problems.md` has the details.

**Limits we know about.** The meter checks before a call and charges after, so the last call of a month can take spending a little past $70. One call is small next to the limit. Spending is kept in one workspace document, which suits one run at a time; two runs at once could each miss the other's last charge. Claude Haiku costs more for prompts over 100,000 tokens, which the settings do not price; our largest input, a 60,000 character evidence pack, is far below that. If Jev does not report its token use, the call is recorded at no cost and its answer is refused, so it shows in the spending list rather than being hidden.

**The hardest question:** "The model reports its own token use, and you charge from that. What if your charges and the provider's bill disagree?"

**The honest answer:** they can. The meter uses the same token counts the provider bills by, and prices checked on 6 Nov 2026, but a price change, or a cost the meter does not see, such as a failed call that raised an error before replying, would make them drift. That is why the design also asks the owner to set a spending limit with each provider. The meter's month total should be compared with the real bills once there are some, and the prices updated when they change.

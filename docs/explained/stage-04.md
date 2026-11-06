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

## Safe page reader (ticket 10)

**What was built.** The page reader (`src/why_now/pipeline/reader.py`) fetches one web page that research asks for and keeps only its plain text. A link can come from a hostile page, so it checks every address before fetching it:

- **Only web addresses.** `http` and `https` are read. `file`, `ftp` and the rest are refused.
- **No LinkedIn.** LinkedIn, its country versions such as `uk.linkedin.com`, its China site and its `lnkd.in` short links are refused before any request is made.
- **No private addresses.** The name is looked up first. If any address it gives is private or internal, such as `127.0.0.1`, `10.0.0.5` or `169.254.169.254` (where a cloud machine keeps its secrets), the page is refused. IPv6 addresses that carry an IPv4 address inside them are judged by the IPv4 address they carry. The request then goes to the address that was checked, with the site's name sent alongside it, so the name can't be looked up a second time and point somewhere else. Each connection is closed after one request, so it can't be reused for a different site on the same address without that site's certificate being checked.
- **No proxy.** The reader refuses a web client that would take a proxy from the environment, because a proxy decides for itself where a request goes.
- **Redirects checked hop by hop.** Redirects are followed by hand, at most 5, and every hop goes through the same checks, robots rules included.
- **Robots rules.** Each site's robots file is read once and followed. As the robots standard says, a missing file allows everything, and a file that fails to load allows nothing. A failure is not kept, so the next page from that site tries the file again.
- **Size, time and type.** Only web pages and plain text are read, so PDFs and images are refused. A page over 2 MB is refused while it arrives, and the whole read, redirects included, has 15 seconds.
- **No contact details.** Email addresses and phone numbers are replaced with `[email removed]` and `[phone removed]`. Years, dates, money and staff counts stay.

A refused page raises `PageRefused`, whose `reason` names the rule, such as `linkedin`, `private_address` or `robots`. The redirect limit is a new setting, with a line in the design's numbers table.

**Limits we know about.** A phone number is recognised by a leading `+`, or by at least 10 digits in groups. A short local number written without a country code, such as 555-1234, is missed, and a long run of plain numbers separated only by spaces could be removed by mistake. Pages that build their text with JavaScript give little or no text, because the reader does not run scripts. The robots rules are kept for the life of one reader, so a change to a robots file during a run is seen on the next run. The 15 seconds is checked between steps, not enforced from outside: looking up a name has no time limit of its own, and a server that sends a page very slowly, a little at a time, can stretch one read past 15 seconds before it is stopped.

**The hardest question:** "You look up the name, check the address, then connect. Can't a hostile site answer the lookup with a public address and then switch to an internal one?"

**The honest answer:** not through this reader. That trick works when the check and the connection each look the name up on their own. Here the connection goes to the exact address that was checked, and the site's name is only sent as a label, also used to check the site's security certificate. The one way around that would be a proxy, which makes its own connection, so the reader refuses a web client that would take one from the environment. A proxy set up by hand in the web client's own code is not detected, so the code that makes the client must not add one.

## Research and evidence packs (ticket 11)

**What was built.** Research (`src/why_now/pipeline/research.py`) turns one company into an evidence pack, the fixed set of text the agent is judged on. It works in this order:

- **Ads first.** The pack starts with the company's 5 newest relevant job ads, each cut to 20,000 characters, with email addresses and phone numbers removed. The total number of relevant ads and of all open jobs is recorded, so the ads left out still count.
- **Then a small loop.** The research model is shown the company, the product and the ads, and may search the web or ask for pages. Our page reader fetches each page. The loop stops when the model says it is done, at 5 steps, or when the pack is full.
- **What a step is.** One web search or one page read. A refused page still costs a step, so a hostile page can't lead the agent round in circles for free. A reply that asks for nothing also costs a step, so the loop always ends.
- **Refusals are told, not hidden.** A refused page, such as a LinkedIn link or a site that is down, is not saved, and the model is told the reason. A company whose website fails still gets a pack from its ads.
- **What the model sees is what is saved.** Page text goes to the model exactly as it is saved, inside the untrusted text tags, so any quote it could make is in the pack for the fact check.
- **A size limit.** The whole pack holds at most 60,000 characters. Ads come first, so a long web page can't push them out. A page that doesn't fit is cut. Once the pack is full, research stops, and pages still asked for are not fetched and cost no steps.
- **Two tools only.** The model can search the web and ask for a page to be read. Neither can change anything, and LinkedIn is blocked for search as well as reading.

The pack id comes from the company, the profile and the time it was made, so a pack is never edited, only replaced by a new one. `docs/decisions/0003-frozen-evidence-packs.md` says why packs are frozen.

**Limits we know about.** One Claude reply may run a search and then ask for pages, so the last reply before the limit can ask for more pages than are left. Those pages are not read, and the model is told the step limit is reached. A scripted or future model that reports more than one search in a reply could take the step count past the limit by the extra searches; the count records what really happened. A reply cut off at the model's output limit ends research, because an unfinished turn can't be sent back to the model, so that company's pack may hold fewer pages than it could have.

**The hardest question:** "A hostile page tells the model to read ten more pages. What stops it?"

**The honest answer:** the step limit, and the page reader's own rules. Each page read costs a step whether or not it is refused, so a page can lead the agent at most 4 more steps after the first read. Every page it points to goes through the same checks: no LinkedIn, no private addresses, robots rules, size and time limits. The model has no tool that sends or changes anything, so the worst a hostile page can do is waste the company's few steps or fill the pack with useless text. It can't make the agent act.

## Picking test cases and building packs (ticket 12)

**What was built.** Two commands that turn a profile's saved job ads into test cases, each with a frozen evidence pack:

- **`why-now pick-cases --profile P --n N --seed S`** (`src/why_now/testset/picking.py`). It searches every saved job ad with the profile's search words, keeps the companies with a relevant ad published in the last 14 days, the same window the daily list uses, and picks N of them at random with the given seed. The companies are sorted first, so the same seed and the same ads always give the same pick, whatever order the ads were read in. Companies picked before are left out, so a company is never picked twice, and asking for more than there are picks them all once and says so.
- **Nothing the agent says can reach the pick.** The picking function takes only the companies, a count, a seed and the keys already picked. A test checks that, and that over 4,000 seeds each of 4 companies is picked about equally often.
- **What is recorded.** Every pick is added to the profile's record with its seed, the count asked for, the companies picked and the time. Each case keeps its seed, and the company is saved with the exact ads it was picked with, so the pack is built from those ads even if the careers page changes before then.
- **`why-now build-packs --profile P`** (`src/why_now/testset/packs.py`). It runs research once for each case without a pack and saves the pack. A saved pack can't be saved over, so it stays frozen.
- **Resuming.** Packs are saved one at a time, and a case that already has a pack is skipped, so running the command again never pays twice for the same company.
- **Daily research pauses.** While packs are being built, a flag in the workspace is set, and it is cleared when the build ends, even if it ends with an error. The daily run, built in Task 20, must check this flag and not research while it is set.
- **A spent budget.** The build stops, keeps what it built, says so, and says how many cases are left. The command then exits with an error so a script running it notices.
- **A failed company.** If research for one company fails, the reason is recorded against its case and the build carries on. The case stays in the list and is tried again on the next run, and a later success clears the failure.

One-time research is charged to its own budget category, `test_cases`, so it shows apart from daily research in the spending list.

**Limits we know about.** The flag means "a build is running". If the process is killed outright, the flag stays set and daily research stays paused until `build-packs` runs again and clears it. Nothing reads the flag yet, because the daily run does not exist yet. A pack is saved just before its case is updated to point at it, so if the process is killed between those two writes, that one company is researched and paid for again on the next run. A failure of any kind is recorded and retried, which also means a bug in our own code would show as a list of failed companies rather than stopping the build.

**The hardest question:** "You say the same seed gives the same pick. If I run the same seed next week, will I get the same companies?"

**The honest answer:** no, and it should not. The pick is the same for the same seed and the same set of eligible companies, but the set changes as new ads arrive and old ones leave the 14-day window. That is why the record keeps the companies picked, not only the seed: the record shows what was picked, and the seed shows the pick was not chosen by hand.

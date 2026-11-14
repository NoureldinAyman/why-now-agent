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

- **`why-now pick-cases --profile P --n N --seed S`** (`src/why_now/testset/picking.py`). It searches every saved job ad with the profile's search words, keeps the companies with a relevant ad published in the last 14 days, counting today, the same window the daily list uses, and picks N of them at random with the given seed. The companies are sorted first, so the same seed and the same ads always give the same pick, whatever order the ads were read in. Companies picked before are left out, so a company is never picked twice, and asking for more than there are picks them all once and says so.
- **Nothing the agent says can reach the pick.** The picking function takes only the companies, a count, a seed and the keys already picked. A test checks that, and that over 4,000 seeds each of 4 companies is picked about equally often.
- **What is recorded.** Every pick is added to the profile's record with its seed, the count asked for, the companies picked and the time. Each case keeps its seed, and the company is saved with the exact ads it was picked with, so the pack is built from those ads even if the careers page changes before then.
- **`why-now build-packs --profile P`** (`src/why_now/testset/packs.py`). It runs research once for each case without a pack and saves the pack. A saved pack can't be saved over, so it stays frozen.
- **Resuming.** Packs are saved one at a time, and a case that already has a pack is skipped, so running the command again never pays twice for the same company.
- **Daily research pauses.** While packs are being built, the profile's flag in the workspace is set, and it is cleared when the build ends, even if it ends with an error. Each profile has its own flag, so one profile finishing never ends another's pause. The daily run, built in Task 20, must not research while any flag is set.
- **A spent budget.** The build stops, keeps what it built, says so, and says how many cases still have no pack. The command then exits with an error so a script running it notices.
- **A failed company.** If research for one company fails, the reason is recorded against its case and the build carries on. The case stays in the list and is tried again on the next run, and a later success clears the failure.

One-time research is charged to its own budget category, `test_cases`, so it shows apart from daily research in the spending list.

**Limits we know about.** The flag means "a build is running". If the process is killed outright, the flag stays set and daily research stays paused until `build-packs` runs again and clears it. Nothing reads the flag yet, because the daily run does not exist yet. A pack is saved just before its case is updated to point at it, so if the process is killed between those two writes, that one company is researched and paid for again on the next run. A failure of any kind is recorded and retried, which also means a bug in our own code would show as a list of failed companies rather than stopping the build.

**The hardest question:** "You say the same seed gives the same pick. If I run the same seed next week, will I get the same companies?"

**The honest answer:** no, and it should not. The pick is the same for the same seed and the same set of eligible companies, but the set changes as new ads arrive and old ones leave the 14-day window. That is why the record keeps the companies picked, not only the seed: the record shows what was picked, and the seed shows the pick was not chosen by hand.

## Marking page (ticket 13)

**What was built.** A private web page where the reviewer marks test cases. Run it with `why-now serve --profile P`, then open the address it prints.

- **What the page shows.** One company at a time: its name, its evidence pack (every job ad and web page in it, in full), how many relevant ads and open jobs it has, and a short reminder of the product and what a yes means. Under that is the form: yes, no or can't tell, and a plain text box for the reason.
- **No agent answer in reach.** The page reads only the case, its frozen pack and the reviewer's own marks. It never opens the quick look answers, the judge's answers or any score. A test saves a quick look answer for the very company on screen and checks that no trace of it appears.
- **A reason is required.** An empty or blank reason is refused, and the page comes back with the case still waiting, the chosen answer kept and a plain message. The reason box is an ordinary text box with no script, so a phone's voice typing works.
- **One mark per case and round.** Saving a mark that already exists changes nothing and still moves on, so a double click, a reload of the form or two tabs save one mark. The first answer stays. The check and the save are done under a lock, so two copies sent at the same moment cannot both get through.
- **Order.** The next company is the first one with a pack and no mark, in the order of its case id. The ids are hashes, so the order has no pattern for the reviewer to be led by.
- **Can't tell.** It is saved, and the case is done. The progress page counts it apart from yes and no, so it is never counted as either. Replacing a company the reviewer could not judge is a picking matter and is not done here.
- **Progress and resuming.** Marks are saved in the workspace one by one, so after a restart the page carries on from the next company with no mark. `/mark/progress` shows yes, no, can't tell, how many are left, and the ceiling from the settings.
- **Hostile text.** Pages are built on the server with every value escaped, so HTML or script in an ad shows as plain text. As a second wall, every page says it loads nothing but its own style sheet and runs no script.
- **Form token.** Each browser gets a random token in a cookie that scripts cannot read and that is not sent on requests from other sites, and the form carries the same token. A save without the matching token is refused with 403, so another website cannot make the reviewer's browser save a mark.
- **Login.** The app asks an `Authenticator` who is using it, and refuses anyone it does not name. `LocalAuth` is for the reviewer's own machine: it lets in only requests that come from this machine and are addressed to a local name. `create_app` refuses `LocalAuth` when the setting says the app is deployed, so the weak login can never be switched on by mistake in the cloud. The real login comes with the AWS tasks.
- **Where it listens.** `why-now serve` listens on `127.0.0.1` only, so other machines on the network cannot reach it. It does not fix a port in code: it leaves that to the web server's own default and prints the address.

**Limits we know about.** The lock that stops a double save covers one process, which is how the page runs. Two separate processes sharing one workspace folder could still both save. The page was checked by tests and not yet by eye on a phone: the layout is one column that fits any width, but the first real marking session is the real check. Marks do not record who marked, because there is one reviewer and `LocalAuth` has one user.

**The hardest question:** "The page only listens on your own machine and checks the sender's address. Why also check the name in the address bar and add a form token?"

**The honest answer:** because the browser is on your machine too. A web page you visit can make your browser send requests to `127.0.0.1`, and a request from your browser looks like a request from you. The token stops such a page from saving marks: it cannot read our cookie or our form. The name check stops a page that tricks the browser into treating its own name as `127.0.0.1` and so reads our pages as if they were its own. Neither is needed if you trust every site you visit, and both are cheap, so they are on.

## Piles and repeat marking (ticket 14)

**What was built.** Four commands and one more page that come after the reviewer has marked the test cases.

- **`why-now yes-share --profile P`.** Counts yes, no and can't tell, and shows the share of yes among yes and no answers next to the share needed for the aim: `target_yes_per_pile` out of a pile of `check_size`.
- **`why-now split-piles --profile P --seed S`** (removed by ticket 43, below) (`src/why_now/testset/piles.py`). It gives every company with a yes or no mark to one pile: practice 150, check 75, final 75. Yes and no answers are shuffled apart with the seed and dealt out in step, so check and final differ by at most one yes. A can't-tell, or a company not marked yet, is in no pile. The command prints each pile's size and yes count, and names any pile with fewer yes answers than the aim. Running it again with the same seed changes nothing.
- **Frozen once the loop starts** (removed by ticket 43, below). The workspace holds a flag per profile. Once it is set the split is refused and nothing is changed. The improvement loop, built later, sets it when it first runs.
- **Refreshing the check pile** (removed by ticket 43, below). The function moves the old check companies to practice, makes newly marked companies the check pile and gives it the next version number. It refuses a company that is already in a pile, and never touches the final pile. The command that calls it comes with the improvement loop.
- **`why-now repeat-marks --profile P --seed S`** (`src/why_now/testset/repeat.py`). Picks 30 companies at random from the yes and no first marks that are at least 7 days old, and records them. It picks once: a second run says so. If fewer than 30 are old enough, it picks nothing and says how many are.
- **The repeat page, `/repeat`.** The same page as first-round marking, with the same form token and reason rule, but only for the picked companies. It never reads first-round marks, so the first answer and reason cannot show, and no answer is pre-selected. Repeat marks are saved as their own round, so the first mark is untouched.
- **`why-now agreement --profile P`.** Shows how many of the compared companies got the same answer twice, with the count. A can't-tell in either round is left out. With nothing to compare it says so and stops, rather than showing 0%.

**Limits we know about.** The repeat pick is blind to the first answer, except that can't-tell answers are left out because there is nothing to compare. The freeze is a flag in the workspace. It stops the commands, not someone editing the workspace by hand. With 30 companies the agreement is rough: one answer changing moves it by about 3 points, and a few changing move it by 10 or more.

**The hardest question:** "You split by shuffling yes and no apart. Isn't that less random than a plain shuffle?"

**The honest answer:** yes, a little, and on purpose. A plain shuffle of 300 companies with 100 yes answers could give the check pile 18 yes and the final pile 32, and then the two piles would not be comparable. Which companies land in which pile is still random, and the seed is recorded. What is fixed is only how many yes answers each pile gets.

## Piles fill as companies are marked (ticket 43)

**What was built.** Each company's pile is now decided the moment it is picked, so the piles fill together while the reviewer marks, in sittings of any size. The one-time split, the frozen flag and the check pile refresh are gone.

- **`pile_for(seed, company_key, settings)`** (`src/why_now/testset/piles.py`). It takes a SHA-256 hash of the pick's seed and the company's key, turns the first 8 bytes into a number, and takes it modulo 300, the sum of the three pile sizes. Below 150 is practice, the next 75 check, the last 75 final. The sizes come from the settings, so the ratio follows them.
- **Set at the pick.** `why-now pick-cases` saves each new case with its pile already on it. The reviewer never sees it.
- **A case never changes pile.** Saving a case whose pile differs from the saved one is refused. Other fields, such as the pack, can still be added.
- **`why-now piles --profile P`.** For each pile it prints the companies, how many are marked, and the yes, no and can't tell answers, from first marks only. It then says whether the improvement loop can start: it can once the check pile holds at least `floor_yes_per_pile` yes answers, 15 by default.
- **Repeat marking is unchanged.** `yes-share`, `repeat-marks`, `agreement` and the `/repeat` page work as before.

**Example.** Pick 20 companies with seed 7. Each one's pile is fixed now, about half in practice and a quarter in each of check and final. Mark 6 of them today and 14 next week, in any order, with a few can't tells: not one company moves. `why-now piles` shows the counts growing, and says "Not ready" until the check pile reaches 15 yes answers.

**Limits we know about.** A hash can't know the answer in advance, so yes answers are not dealt out evenly: check and final can hold different numbers of yes answers, and every score shows its real counts. Cases saved before this change have no pile and are counted apart; the workspace held no real marks, so none were moved.

**The hardest question:** "With a hash, the check pile could end up with far fewer yes answers than the final pile. Isn't the old even split better?"

**The honest answer:** for one fixed set of 300 companies, yes, the old split made check and final more alike. But it needed all the marking done before anything could be measured, and the reviewer marks in occasional sittings. The hash gives up the even deal of yes answers in return for numbers that come as soon as there are enough, and for a pile that no mark, order or can't tell can change. The loop waits for 15 yes answers in check, and the final pile still guards against a check pile that happens to be easy.

## Prepare and quick marking (ticket 44)

**What was built.** One step now takes a reviewer from nothing to companies ready to mark, and the marking page is a short card with taps instead of a long page and a typed reason.

- **`prepare(ctx, profile, n, seed)`** (`src/why_now/testset/packs.py`). It picks `n` companies at random from everyone with a relevant ad in the window, decides each company's pile at once, and researches each into a frozen pack. It is the old pick and build steps run together, and `pick-cases` and `build-packs` still work on their own. The budget is checked before every paid call, so a spent budget stops it with what was built kept.
- **A rerun pays for nothing twice.** A seed and count that were already picked are not picked again: the rerun only finishes companies still without a pack. A new seed picks more companies, never one picked before.
- **`why-now prepare --profile P`.** `--n` defaults to the `prepare_batch` setting, 20. With no `--seed` it makes one and prints it, so a stop can be finished with `--seed`. On the marking page, on one's own computer only, a "Prepare 20" button does the same. The page waits while it runs, and the seed is fixed when the page is drawn, so pressing the form twice asks for the same companies.
- **`card(case, pack, settings)`.** It builds the card from the pack alone: company name, relevant job titles with counts, relevant and open job counts, the date of the newest ad, and the first 400 characters of the first web page in the pack. No agent answer can be on it, because nothing but the pack is passed in. The full pack opens below it. To make this possible the pack now also keeps every relevant ad's title and the newest ad's date.
- **One-tap answers and reason chips.** Yes, no and can't tell are three buttons. A reason is one or more chips from the `reason_chips` setting, a sentence, or both, and at least one is needed. A chip that is not in the setting is refused, so a sent form cannot invent one.
- **`seen_on_list`.** A mark records whether the company was on a short list or more list on or before the day it was marked. Marks still do not hide a company from daily lists.
- **The repeat page and the nudge.** The repeat page uses the same card and form. When 30 first yes or no marks are at least 7 days old and no repeat round is picked, the marking page says a repeat round is possible and names the command that picks it.

**Example.** Press "Prepare 20". The page waits while the research runs, then says how many companies were picked and how many are ready. The first card shows a company's name, its job titles with a count where a title repeats, its open jobs, the date of its newest ad and the start of its page. Tap "too big", then "No". The mark records the chip, an empty sentence, and whether the company had been on a daily list.

**Limits we know about.** Preparing on the page holds the request open while research runs, which is fine on one's own computer and is why it is not offered when deployed. Packs made before this ticket have no titles or newest date, so their card leaves those out. A repeat mark also records `seen_on_list`, though it is not used there.

**The hardest question:** "The card shows only a short start of the company page. Won't you mark on too little and make the test worse?"

**The honest answer:** it can happen, and it is a trade. The card is short so that marking is quick enough to do 300 companies at all. The whole pack is one tap below it, and can't tell is a real answer that leaves the company out of the scores, so thin evidence does not have to be forced into a yes or no. The 400 characters is a starting guess, and it is a setting.

## Marking from job ads, and commands to mark with (ticket 15)

**What was built.** The tools to build the answer key in about 135 marks instead of 300, without paying for research. Decision note `docs/decisions/0008-smaller-test-set-from-ads.md` says why.

- **Smaller piles.** `practice_size`, `check_size` and `final_size` are 45 each, and `cutoff_step` is 0.1. Each pick now records the three sizes it used (`PickRecord.sizes`), and `pile_for(seed, company_key, sizes)` takes them directly. So a pile can be worked out again from the pick alone, even after the settings change.
- **Ads-only packs.** With `test_case_web_research` off, the default, `prepare` builds each pack with `ads_only_pack` (`src/why_now/pipeline/research.py`): the company's newest relevant ads, cut to the same limits research uses, and no model call. Research itself now starts from the same ads-only pack, so the two can't drift apart.
- **A marking guide.** `Profile.marking_guide` is a short optional text. It is part of the profile version, so editing it starts a new version. The judge, quick look, writer and research only ever get the fields they are given by name, and a test runs a whole day with a guide and checks that no model call holds it.
- **One place for the checks.** `read_form`, `form_error`, `decision_error`, `reason_error` and `new_mark` moved to `src/why_now/testset/marking.py`. The marking page, repeat page, review page and the new commands all call them, and a test sends the same bad inputs to the page and the command and checks the same message comes back.
- **Commands** (`src/why_now/cli/marking.py`). `mark-next` prints the next case's card, the marking guide, and the whole pack inside the untrusted text tags. It never reads the daily lists, the judge's answers or the pile. `mark CASE yes|no|cant-tell --chip ... --reason ...` saves one mark, `unmark CASE` removes a mistaken one, `decide-next` shows the next company on the short list, then the judged-no list, and `decide COMPANY approve|reject` records a decision. Nothing is sent to anyone.
- **The judged-no list.** The daily run keeps the researched companies the judge turned down. The `judged_no_shown` strongest, 3 by default, go on a small list under the short list on the review page, and stay while one of their ads is inside the new-ad window. A decision on one is saved with `from_list="judged_no"`, and short-list precision leaves it out.

**Example.** `why-now prepare --profile P` picks 20 companies and builds 20 packs from their ads, for $0. `why-now mark-next --profile P` shows "Case case-3f2a. 20 left", the titles, the guide and the ads. `why-now mark case-3f2a no --chip "recruitment agency" --profile P` saves it, and `mark-next` moves on. A wrong tap is undone with `why-now unmark case-3f2a --profile P`.

**Limits we know about.** The score now measures judging from ads only, while daily packs keep web research, so a judge can do a little differently on daily companies. `unmark` removes first-round marks only. A second mark on a marked case is refused by both, but the page does it quietly, because a browser can send the same form twice, while the command says so and names `unmark`. A mark's `seen_on_list` now also counts the judged-no list, because the reviewer has seen those companies too. There is no rule proposer yet, so the guide test covers every model that exists today, and the proposer's own ticket must keep the guide out of its prompt.

**The hardest question:** "If a coding agent marks the test cases, isn't the agent being scored against another model's answers?"

**The honest answer:** partly, yes, and it is said openly. The marks come from a fresh session that sees only the card, the pack and the owner's guide, never the agent's answer, so it can't copy the agent. But it is a model, so the score measures agreement with the owner's guide as that session reads it, not with a sales expert. The owner approves the guide and can check any mark, unmark it and mark it again.

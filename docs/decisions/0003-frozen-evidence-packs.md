# Frozen evidence packs

Decided 6 Nov 2026 (ticket 11).

**Note:** test case packs and pile sizes changed on 14 Nov 2026. See `0008-smaller-test-set-from-ads.md`.

## What a pack is

An evidence pack is everything the agent knows about one company when it judges it:

- The company's newest relevant job ads, at most 5 (`newest_ads_read`), each cut to 20,000 characters (`max_ad_chars`). The number of relevant ads and of all open jobs is recorded too, so the ads left out still count.
- The pages the research model chose to read, within 5 steps (`research_steps`). A step is one web search or one page read, whether the page was read or refused. A reply that does neither still counts, so research always ends.
- No more than 60,000 characters of text in all (`max_pack_chars`). Ads come first, so a full pack never loses the newest ads to a long web page.

Email addresses and phone numbers are removed from ads and pages alike. A refused page is not saved, and the model is told it was refused. A site that is down gives a pack from the ads alone.

## Why packs are frozen

A pack is made once and never changed. Its id comes from the company, the profile and the time it was made, so a new pack is a new id, never an edit of an old one.

- **The score needs a fixed test.** Websites change. If each try of the improvement loop researched again, a score could rise because a page changed, not because the rules got better.
- **The reviewer and the agent see the same thing.** A reviewer marks a company from its pack. Judging from anything else would make the comparison unfair.
- **Saved answers stay valid.** Answers are saved per pack, question and model. A pack that changed would make those answers wrong without anyone noticing.
- **The fact check has a fixed source.** Every quote in a brief must appear in the saved text. The model sees page text exactly as it is saved, so it cannot quote what the pack does not hold.

## What was rejected

- **Researching again for each try.** It costs money every time and makes scores impossible to compare.
- **Saving search results as evidence.** A search snippet is the search tool's summary, not a page our reader saved. It can't be checked word for word, so it never supports a fact.

## Limits

- The score can't tell whether better research would have helped, because research is outside what the loop measures. The design lists this among the things the score does not cover.
- A pack shows the company as it was on the day it was made. A test case from months ago may judge a company that has since changed. That is the price of a fixed test.

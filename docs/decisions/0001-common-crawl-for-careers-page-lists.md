# Building careers page lists from Common Crawl

Decided 6 Nov 2026 (ticket 06).

## What Common Crawl's terms allow

The terms of use at `https://commoncrawl.org/terms-of-use` were read on 6 Nov 2026. The page was read through a tool that returns it section by section, so the owner should check the original once before the project is published. The 17 sections say:

- Using the site, the service or the crawled content means accepting the terms. Common Crawl may change or end the service at any time.
- It grants a limited, non-exclusive licence to use the service. Uses it does not name are not allowed.
- Use must be lawful. The crawled content may also carry its owners' own terms. Banned uses include harming or harassing people, breaking others' rights, getting round copy protection, disrupting the service or its servers, spam, pretending to be someone else, disguising where content came from, and collecting personal information to use apart from the content.
- The service is provided as it is. Common Crawl's liability is capped at 100 US dollars, the user covers Common Crawl against third-party claims, and disputes go to arbitration under California law.
- Section 3 says Common Crawl recommends consulting legal counsel before any use, including commercial use.
- The terms say nothing about rate limits, attribution, or the index lookup service specifically.

## What that means for this project

- The `build-list` command asks the index only for web addresses under the two job sources' hosts. It never downloads archived pages, and it keeps only the first path segment of each address, which is a company's careers page name.
- Careers page names are not personal information. No job ad text, person or contact detail is taken from Common Crawl.
- It sends only GET requests, names the project in each request, waits 1 second between requests (`request_delay_seconds`), uses the latest index only, and gives up after 3 tries (`request_attempts`) instead of hammering a busy server.
- Nothing in the terms forbids this use. The one open point is that the terms do not give a request rate. The pause above is the project's own choice.
- The list a person builds belongs to them. The repo ships only the small example lists.

## Did it work for both job sources?

A real run on 6 Nov 2026 against index `CC-MAIN-2026-43`:

| Job source | Result |
|---|---|
| Greenhouse | Worked on the third run: 3,840 distinct careers page names, none duplicated. The first two runs failed, with reply 504 (gateway time-out) and with a reply cut off halfway. |
| Lever | Worked: 266 distinct names. One run failed with 504 and the others worked. A second run on the finished file added 0 new names, which shows the merge does not duplicate. |

Common Crawl's index often answers 502 or 504, and a single reply takes 7 to 17 seconds, so a run can fail and a repeat run can work. The command retries, then says plainly that it could not build the list and writes nothing. A failed run never damages an existing list, and a person can always supply their own list instead. Neither job source needs to rely only on supplied lists.

Lever returns far fewer names than Greenhouse. That is a limit of what Common Crawl has seen, not of the command.

## Why these job sources, and not LinkedIn or Ashby

- Greenhouse and Lever publish each company's open jobs as public data meant to be read, with no sign-in.
- LinkedIn is never read, as the project's rules say. It requires sign-in and forbids automated reading.
- Ashby is not used because this project covers two job sources, and each one needs its own adapter. Another can be added later without changing the read step.

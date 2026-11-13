# Why-Now Agent

An agent that spots, in public job ads, the moment a company may soon need a product. These are the words the project uses for its main ideas.

## Language

**Job ad**:
One open position a company has published for anyone to read.
_Avoid_: Listing, posting, job

**Company**:
The business behind one or more job ads, and the thing the agent judges. All of a company's relevant job ads are judged together, once.
_Avoid_: Account, lead, prospect

**Job source**:
A hiring service that hosts careers pages for many companies and lets anyone read their job ads. Version one reads two: Greenhouse and Lever.
_Avoid_: Job board, ATS

**Profile**:
A written description of one product, the people who would use it, and what makes a company a good or bad fit for it. Changing the profile changes what the agent looks for.
_Avoid_: ICP, customer profile, config

**Profile version**:
A hash of what a profile says. Any edit to its fields gives a new version, while comments and layout in the file change nothing. Marks and decisions record it, so scores from different versions are never joined as one line.
_Avoid_: Revision, profile number

**Profile preview**:
The companies the last saved read gives for a profile's search words, shown while editing the profile. It calls no model, so it costs nothing.
_Avoid_: Dry run, test run

**Fit question**:
One yes/no question the agent answers about a company, such as "Is this company hiring for itself, not for clients?" A profile holds the starting ones, and the rules file holds the ones the agent has learned.
_Avoid_: Check, criterion, rule

**Rules file**:
The agent's own list of learned fit questions for one profile. It is the only thing the agent may change about itself.
_Avoid_: Prompt, instructions, notebook

**Quick look**:
The agent's first, cheap read of a company's relevant job ads, used to drop clear no's and order the rest.
_Avoid_: Filter, pre-screen

**Research**:
The step where the agent reads a company's website and searches the web, within a strict limit, to build an evidence pack.
_Avoid_: Enrichment

**Fact check**:
A script that confirms every quote in a brief really appears in the company's evidence pack. It involves no AI.
_Avoid_: Guardrail, validation

**Why-now reason**:
A fact in a job ad suggesting a company may be ready to buy a product at this moment, rather than at any time.
_Avoid_: Trigger, signal, intent

**Evidence pack**:
Everything saved about one company for judging: its relevant job ads and any web pages the agent read about it. In a test case, the pack is frozen so the test stays the same over time.
_Avoid_: Context, research notes

**Brief**:
A short explanation of a company's why-now reason. Its why-now reason comes from a job ad, and every fact in it comes from the company's evidence pack, with a link.
_Avoid_: Summary, report

**Short list**:
The strongest companies the agent puts forward on a given day, at most 10, in order of strength. Each one is waiting for a decision.
_Avoid_: Leads, prospects

**More list**:
The other companies that passed the agent's first read of their job ads that day, shown separately from the short list without research or a brief. They don't need a decision, but a reviewer can make one.
_Avoid_: Backlog, overflow

**Reviewer**:
The person who approves or rejects what the agent puts forward.
_Avoid_: Labeller, user, human in the loop

**Decision**:
A reviewer's approval or rejection, together with the reason for it.
_Avoid_: Verdict, label, feedback

**Workspace**:
One person's private copy of everything that isn't code: settings, profiles, rules files, job ads, decisions and scores. Each person running the project has their own.
_Avoid_: Tenant, instance, data folder

**Public results**:
The scores and approved rule changes a person has chosen to publish. They are separate from both the code and the workspace, and are off by default.
_Avoid_: Leaderboard, report

## Testing

**Test case**:
One company, its frozen evidence pack, and a reviewer's mark. Companies are picked at random, so the agent's own choices can't shape the test.
_Avoid_: Example, sample

**Mark**:
A reviewer's yes, no or can't tell on a test case, given without seeing the agent's answer. Unlike a decision, it doesn't hide the company from daily lists.
_Avoid_: Label, annotation

**Practice pile**:
The test cases whose mistakes the agent may read when it tries to improve.
_Avoid_: Train set

**Check pile**:
The test cases that decide whether a rule change is kept. The agent sees only the resulting score, never the cases.
_Avoid_: Validation set, dev set

**Final pile**:
Test cases opened only at big milestones. Only these give the numbers quoted as results.
_Avoid_: Test set, held-out set

**Try**:
One attempt to improve: a single change to the rules file, measured on the check pile, then kept or discarded. Every try is recorded either way.
_Avoid_: Experiment, iteration, run

**Score**:
F1, one number combining how often the agent's yes was right (precision) and how many of the reviewer's yes companies it found (recall), weighing both equally. The weighting is one setting, `score_beta`, with 1 giving F1. It measures agreement with the reviewer, not whether a company would buy.
_Avoid_: Accuracy, quality

**Short-list precision**:
The share of companies shown on short lists that the reviewer approved. It comes free from daily decisions, but those companies were chosen by the agent, so it is always shown apart from the score.
_Avoid_: Precision (on its own), hit rate

**Prepare**:
To pick companies at random for marking and research each one into a frozen evidence pack, so they are ready to mark. Each company's pile is decided at this moment.
_Avoid_: Sample, queue, fetch

**Card**:
The short read a reviewer sees before marking, built by code from the evidence pack alone: the company, its relevant job titles with counts, the open jobs, the newest ad's date and the start of a company page. The full pack opens below it. It never holds an agent answer.
_Avoid_: Preview, summary

**Reason chip**:
A short reason the reviewer taps instead of typing, such as "too big". A reason is one or more chips, a sentence, or both, and at least one is needed.
_Avoid_: Tag, label

**Effort**:
A setting on Claude models that controls how much the model thinks before answering, and so what a call costs. Each job has its own.
_Avoid_: Thinking budget, reasoning level

**Answer key**:
One label for a model as it was asked: its name, its effort and its prompt version, such as `claude-sonnet-5-5@medium#p1`. Saved answers and cut-offs are kept under it, so a change to any part asks again.
_Avoid_: Model id, cache key

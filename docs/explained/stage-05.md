# Stage 5: Quick look

## Quick look

The quick look is the cheap first read of each company's relevant job ads. For every company it asks the profile's quick look questions, takes the mean chance of fit (the answer for a "for" question, one minus the answer for an "against" question), drops companies below the `quick_look_pass` setting, and orders the rest strongest first.

- **Generous on purpose.** The cut-off is low (0.3), because this step only decides what gets researched. A company wrongly dropped is never seen again; a company wrongly passed costs one research run.
- **Saved per model version.** Each answer is saved under the company, its ad text, the question text and the model. A later run reuses it, and a new model version, an edited question or a changed ad asks again. This is what lets the improvement loop rerun only the judge.
- **Failure is visible.** If a model gives an unusable answer, the company is marked failed, passes nothing, and is listed last. It is not dropped. A spent budget is different: it stops the whole run.
- **Long ads are cut.** Each ad is cut to `max_ad_chars` before a model sees it, and only the company's relevant ads are sent.
- **One light trace per run,** with a step per company, because the quick look covers many companies.
- **Works with no key for the preferred answerer,** because it uses whichever answerer it is given, which is the cheap default model when there is no key.

**The hardest question:** "Why drop companies on a cheap model's guess?"

**The honest answer:** the cut-off is a starting guess, set low so that few good companies are lost. Whether it loses good companies is measured later, because every test case also has an evidence pack even when the quick look would have dropped it, so the quick look can be scored alone.


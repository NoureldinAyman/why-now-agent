# Stage 1: Repo and accounts

## Accounts and keys (ticket 02)

**What was built.** Nothing in code. The owner created three personal accounts and put their keys in a local `.env` file that Git ignores:

- **Claude API**, the paid access to Claude that programs use. It is separate from a Claude chat subscription. The owner bought $5 of prepaid credit with automatic top-up off, set a $70 monthly limit for the account, and made a separate workspace for this project with the same limit. The key belongs to that workspace. The provider does not allow a limit on its default workspace, which is why the project has its own.
- **Langfuse**, which records each run of the agent so a person can open it later and see what was read, asked and answered. It is a project on the free plan in the EU region, with no card on file, so there is nothing for it to charge.
- **Jev**, by TypeSafe, a model that answers fixed questions with a probability. It needed $5 of prepaid credit, also with top-up off.

AWS waits until Stage 9.

**Why the limits are what they are.** $70 is the project's whole monthly budget in the design. The agent will keep its own count of spending, and the provider limits are a second wall in case that count is ever wrong. Prepaid credit with top-up off is a third: when it runs out, calls stop.

**How the keys stayed private.** An agent wrote the empty `.env` file with only the names of the keys, and a small check that prints only "ok", "failed" or "not set" for each service. The check only lists models or confirms a login, so it never runs a model. It is kept out of Git. The owner pasted each key into the file themselves and ran the check in their own terminal.

**The hardest question:** "How do you know no agent ever saw a key?"

**The honest answer:** nothing technically stops an agent on this computer from reading `.env`. What we have is a rule in the project's instructions, and a way of working that never needs the values: the agent writes the empty file and the check, and the owner fills it and runs it. When the Langfuse check failed, the agent looked only at the address line and at the fixed start of each key (`pk-lf-` and `sk-lf-`, which every Langfuse key shares), and hid the key text in any error it printed. That is good practice, not proof. On AWS, the keys will live in Parameter Store, AWS's store for settings and secrets, where access can be limited and logged.

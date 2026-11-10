# Stage 9: AWS

## AWS storage, login and the container (ticket 31)

**What was built.** The parts the app needs to run on AWS, all tested without an AWS account. Tests use moto, a stand-in for S3, DynamoDB and Parameter Store that runs inside the test.

- **The AWS store** (`src/why_now/store/aws.py`, `AwsStore`). It meets the same `Store` interface as the local folder. Every document gets a DynamoDB record, so listing reads one table, in key order, page by page. Small documents sit in the record. Job ads, evidence packs and anything over 350 KB go to S3, and the record names the file, because DynamoDB refuses records over 400 KB. Each save writes a file with a new name and then removes the old one, so two saves racing on one document can't delete each other's file. A test makes a second save land between the two steps of a first one. The same tests run against both stores, including 1,001 documents listed over several pages and a document bigger than DynamoDB allows. Both stores refuse the same unsafe names, so a workspace can move between them.
- **The login** (`src/why_now/web/auth_cognito.py`, `CognitoAuth`). Cognito, Amazon's ready-made login, does the sign-in, so the app never sees a password. The app sends the browser to Cognito, gets a one-time code back, swaps it for a signed ID token, and checks the token's signature against Cognito's published keys (fetched again once if Cognito has changed them), plus who issued it, which app it is for, when it expires, that it is an ID token, and that it belongs to the sign-in this browser started. Only then does it set its own session cookie, signed, secure, hidden from scripts and sent only from this site. A signed-out page visit goes to the sign-in. A sent form is refused instead.
- **Secrets** (`src/why_now/deployment.py`). The session secret, and the login client's ID and secret, come from the environment or from Parameter Store, never from a settings file. Without a session secret of at least 32 characters, the app will not start on AWS.
- **One choice of store and login.** `deployment = "aws"` now picks the AWS store and the Cognito login for `serve`, and the AWS store for `read`, `daily` and the test set commands. On one's own machine nothing changes, and no AWS library is needed.
- **The container** (`infra/Dockerfile`). One image runs the `why-now` command. By default it starts the review page, with the Lambda Web Adapter passing web requests to it. On Fargate the task gives a different command. `.dockerignore` leaves everything out of the image except the code, the examples and the lock file, so no workspace data or private files can be copied in.

The four new numbers (350 KB, 12 hours, 10 minutes, 32 characters) are settings, each with a line in the design's table.

**Limits we know about.**

- The image has not been built yet. Docker is not installed on the computer this was written on. The tests read the Dockerfile and run its default command the way the image would. Building and running it for real is part of the owner's deployment ticket.
- `why-now night-run` does not exist yet. It comes with the improvement run ticket. The test that the image can start it is marked as expected to fail, and will tell that ticket to remove the mark.
- The bucket, the table, the Cognito user pool and the login client are made by the AWS setup ticket. Their names reach the app as `WHY_NOW_` environment settings.
- There is no sign-out page. A sign-in ends after 12 hours.
- Only the example profiles are copied into the image. How the owner's own profile reaches AWS is decided with the AWS setup.
- The local trace log still writes under `workspace_path`. On AWS that is the container's own disk, which is thrown away after each run.

**The hardest question:** "You tested against a fake AWS. How do you know the real one behaves the same?"

**The honest answer:** we don't yet, not fully. moto copies the AWS behaviour the store relies on, such as listing in pages of 1 MB and refusing an empty prefix in a key condition, and the login is checked against a fake Cognito built from Cognito's documented token rules. What a fake can't show is the real setup: permissions, region names and the registered sign-in address. The deployment ticket checks those by signing in and running the night run on the real account.

## The whole AWS setup, built by hand (ticket 48)

**What was built.** Every AWS part the app needs, made by hand in the console and the command line, to learn each service and to run the app on them. No code changed. Ticket 32 writes the same setup as code, and ticket 33 deploys from it and deletes these hand-made parts, using a private list kept while building.

- **A budget alarm first,** so that anything that goes wrong shows up as an email to the owner's own address.
- **Storage.** A private S3 bucket with public access blocked, for job ads and evidence packs. A DynamoDB table in on-demand mode, with partition key `collection` and sort key `key`, which are the names the store writes. Both are charged by use.
- **The login.** A Cognito user pool with no self sign-up, two-factor sign-in required with an authenticator app, one user made by hand, and a login client with a secret. The client's return address could only be set once the web address existed, so it was first a placeholder and then replaced.
- **Secrets.** The session secret and the login client's ID and secret sit in Parameter Store under `/why-now/`. The owner entered them, and no agent saw the values.
- **The image.** The same image serves both jobs. It was built on the owner's computer, pushed to a private registry in the same region, and used by both Lambda and Fargate.
- **The web page.** A Lambda function from the image, with a role that can use only this bucket, this table and these parameters. Its web address needs no AWS sign-in, because the app checks the login itself: every page and form needs a signed-in session, and a signed-out visit goes to the sign-in.
- **A run on Fargate.** A task that runs the image with `sample-run`, which uses invented data and no keys. It ran and exited cleanly.

**Why by hand first.** Writing the setup as code is much easier to check when you already know what a bucket, a table, a role and a return address are, and which settings they depend on. Each problem we hit is in `docs/problems.md`.

**What was not done.** The schedule that starts the daily task did not run, and was skipped. A real daily run, which uses the model key and costs money, was left for the deployment ticket. So nothing here shows that a real run reads real job ads and saves them to S3 and DynamoDB. The deployed image is also a few commits behind the code, so it does not yet include later pages.

**The hardest question:** "You say the review page works on AWS. What did you actually prove?"

**The honest answer:** that a signed-out visitor is sent to the sign-in, that the owner can sign in with a password and a second factor and reach the marking page, and that the page reads from the real table and bucket. We did not prove a real run end to end, a schedule, or how the setup behaves over a week. The deployment ticket does those with measured numbers.

# Lambda for the web page, Fargate for the daily run, nothing always on

Decided 16 Nov 2026. Fills in the hosting table in the design's "Hosting on AWS" section.

## What was decided

- **The review page runs on Lambda,** from the same container image as the daily run, with its own web address and at most two copies at once.
- **The daily run is a Fargate task,** started once a day by a schedule, in a network of public subnets with no NAT gateway. The task has no inbound access.
- **Storage is a private S3 bucket and a DynamoDB table charged per request.** Secrets are in Parameter Store.
- **The login is Cognito,** with no self sign-up and an authenticator app as the second step.
- **No part bills by the hour just for existing.** A test counts NAT gateways, load balancers and database servers, and expects none.

## Why

The project is used by one person in occasional sittings, so most hours of most days nothing is running. Parts that bill by use cost almost nothing then, and parts that bill by the hour cost the same whether or not anyone is there.

- **Lambda for the page** runs only when someone visits, and stops by itself. The two-copy limit means a flood of bad requests cannot run up a bill.
- **Fargate for the run** because the read takes hours and Lambda stops a call at 15 minutes. A Fargate task is billed by the second while it runs, and it needs no machine of its own.
- **Public subnets** let the task reach the job sources and the models directly. The firewall allows nothing in, so nothing outside can reach it.

## Rejected

- **A NAT gateway with private subnets.** It is the usual advice for keeping a task out of reach, but it bills by the hour. A public subnet with no inbound rules gives the same protection for this task.
- **A load balancer in front of always-on web servers.** It would bill by the hour and has no job when there is one visitor.
- **A database server such as RDS.** It runs and bills all day. The store's needs are small and fit a table charged per request.
- **AWS App Runner.** It is closed to new customers.
- **Text-message codes for the second sign-in step.** They cost money per message and are weaker than an authenticator app. Account recovery by text message is off for the same reason.
- **Secrets Manager.** It charges for each secret, and Parameter Store holds the same values at no charge for this use.

## What it costs

- **Cold starts.** A page that has not been visited for a while takes a moment to start.
- **A 15-minute limit on web requests,** which the page never needs, and no live connections, which it does not use.
- **Less control.** There is no server to log in to, so problems are found in the logs.
- **The run is reachable from the internet in principle,** because it sits in a public subnet. Its firewall blocks every inbound connection, and that is checked by a test.
EOF
ls docs/decisions | tail -2
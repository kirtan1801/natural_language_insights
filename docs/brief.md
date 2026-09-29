Take-Home: Natural Language Insights Engine - Forward Deployed Engineer 
6 hours of work. Due one week from today. Submit a GitHub repo link.
The repo should include short GIFs of the application working, one of them showing a second CSV being loaded and queried. Record after the answers have been produced so the GIFs stay short.
The problem
A merchandising team keeps asking analytics the same questions: what sold, where, to whom, what changed. Each one becomes a one-off SQL query and a Slack reply.
Build them something they can ask in plain English and trust the answer.
This is a software engineering exercise. The analytics are deliberately simple; we are looking at the application you build around them.
The data
UCI Online Retail: our link to the data. About 540,000 transactions from a UK online gift retailer, one year of data.
This is your development dataset, not the only one your app has to handle. See below.
What to build
Pipeline. Load a CSV into something queryable as a repeatable step, not a manual one.
Any CSV, not just ours. The app has to accept a transactional CSV it has never seen and answer questions about it with no code changes. Infer the schema, build the query context from the file itself, and cope with column names and types you did not anticipate. Nothing about the sample dataset should be hardcoded in prompts, SQL, or config. We will hand you a different CSV during the walkthrough and ask you to load it live.
Async job handling. Ingestion and long-running queries must not block the caller. Submit a job, get an id back, poll or stream status, retrieve the result when it is ready. Be ready to explain how your approach behaves under concurrent load and partial failure.
Question answering. Plain English in, accurate answer out. Questions such as:
Top 10 products by revenue
Which countries grew most between two quarters
Net revenue in a given month
How many customers bought only once, and what share of revenue they represent
Which products are most often bought together
Service. A real HTTP API. Input validation, sensible status codes, structured errors, no stack traces to the caller. A working UI.
One-command setup. Clone to working endpoint in fifteen minutes on a clean machine.
Tests and CI. Cover the parts you would be nervous about changing, running on push. Full coverage is not the goal.
Guardrails and evaluation. Show how you stop inventing answers and how you know it works. Test questions with expected answers plus a script to run them is enough. Some of our questions will be unanswerable from the data. Refusing is correct.
README. How to run it, configure it, and ask it a question.
System design document. Markdown and an architecture image, in the repo, weighted as heavily as the code:
The components and what each owns
The path a question takes from input to answer
How schema context is built from an unfamiliar file, and where that breaks
Your three or four biggest decisions and the alternatives you rejected
What you would build next, in order
Optional
Caching, tracing, LLM observability, semantic layer, charts, follow-up questions, cost tracking. Skipping all of it costs you nothing. Adding valuable unlisted features is a plus.
Out of scope
Cloud deployment, authentication, visual polish.
Ground rules
Any stack you can explain under questioning.
Running short on time, ship less and write down what you cut. We read that section closely.
Scoring

Weight
What
30%
Architecture and the reasoning behind it
25%
Engineering practice: API design, tests, CI, setup, error handling
20%
Extensibility
15%
Correctness, and refusing when it should
10%
Written communication
After you submit
We read the repo, then book a 60-minute walkthrough with two or three of our panel members. You present your system and defend the decisions behind it.
Two things will happen live. We will give you a CSV you have not seen and ask you to load it and answer questions about it. And we will give you a feature request you have not seen and ask how you would build it into what you have, which could include both coding and reasoning: what you would ask the stakeholder, where the change lands in your architecture image and in your code.
Requirements arrive half-formed and change after you build something, which is why extensibility carries weight above.

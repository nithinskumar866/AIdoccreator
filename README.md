# DocuMentor

**Check, write and grade homework against your own textbook, with an AI model doing the reading
(Google Gemini, or your own through Ollama) and you making every decision.**

DocuMentor reads your textbook and class notes, then helps with the paperwork around them. It
finds off-topic homework questions, writes new assignments with answer keys, catches mistakes
in notes, keeps a question bank, and suggests marks for students' answers. Every suggestion
shows its reason and the textbook passage behind it, and nothing changes until you accept it.

Three **agents built with LangGraph** do the jobs that need several steps: a teacher assistant
that looks things up across all your work, an assignment planner that drafts, checks and revises
a test before asking for your approval, and a second-opinion agent that re-checks unclear marks.

It runs on your own computer, with no account and no login. It uses Google Gemini by default, or
your own models through Ollama, for example on a RunPod GPU.

![The grading screen: class scores and the average score for each question](screenshots/11-grading-class.png)

## Contents

- [What's new](#whats-new): everything added in this version
- [What it does](#what-it-does)
- [Workflow](#workflow): how the tools fit together
- [Architecture](#architecture): the parts of the app and how a task runs
- [Agents](#agents): what the LangGraph agents do, their graphs, and hybrid search
- [Quick start](#quick-start) · [Run on your own GPU](#run-on-your-own-gpu-ollama-or-runpod)
- [A full walkthrough](#a-full-walkthrough): one teaching unit from start to finish, with screenshots
- [How it keeps you in control](#how-it-keeps-you-in-control)
- [Settings](#settings) · [Privacy and security](#privacy-and-security) · [Project layout](#project-layout) · [Tests](#tests)

## What's new

Everything below was added on top of the original homework checker, notes reviewer and chat.

**Teaching tools**

- **Compare versions.** The original homework next to your accepted version, with changed words
  highlighted, and a Word "changes report" to go with it.
- **Question bank.** Save the questions you choose from any homework, tag them by topic and
  difficulty, edit them, and build new assignments by ticking questions or letting the app pick.
  If the bank is short, the AI can write the missing questions.
- **Grade answers.** Upload one file per student with numbered answers. You get suggested marks
  and feedback checked against your answer key and the textbook, a class summary with the
  average for each question, flags on answers that need a closer look, and bulk or one-by-one
  confirming. Export to Word and CSV.

**Agents (LangGraph and LangChain)**

- **Teacher assistant.** A tool-calling agent that chooses what to look up across your
  documents, question bank, homework and gradings, and shows every step it took.
- **Assignment planner.** Turns a request like "a 10-mark quiz on clustering" into a draft from
  your bank plus new questions, checks it (marks add up, topics covered, no near-duplicates),
  revises it, and then pauses for your approval. Nothing is saved until you approve.
- **Grading second opinion.** Re-checks unclear marks, including zeros that may be harsh, by
  searching the textbook and notes itself. Its opinion appears beside your mark as advice.
- **Hybrid search.** Keyword (BM25) and meaning (embeddings) search combined, with documents
  indexed in the background after upload.
- **Memory.** Assistant conversations and paused plans are saved, so they survive a restart.

**Models**

- **Run on your own GPU.** Every feature, agents included, can use models you host with Ollama,
  for example on a RunPod GPU, instead of Google Gemini. Switch with one setting.
- **Safeguards for smaller models.** The code reads the question count, total marks and topics
  straight from your request, fills gaps in the plan, balances marks, and opens the newest item
  when a model passes a made-up id, so even an 8B model gives usable results.

**Under the hood**

- An illustrated walkthrough, plus architecture, workflow and agent diagrams in this README.
- 94 tests, including the agents' graphs and the Ollama connection, all running without spending
  any AI quota.

## What it does

| Tool | What you get |
|---|---|
| **Check homework** | Off-topic questions found, each with a suggested replacement you accept or reject |
| **Compare versions** | The original homework next to your final version, with every change highlighted |
| **Create homework** | New questions with difficulty, marks, answers and your own instructions |
| **Review notes** | Real mistakes kept apart from content the textbook simply doesn't mention |
| **Question bank** | Your best questions saved, tagged and reused, picked by hand or automatically |
| **Grade answers** | Suggested marks and feedback for a whole class, which you confirm one by one or in bulk |
| **Ask** | A chat about your documents, with follow-up questions and cited answers |
| **Teacher assistant** (agent) | Answers questions about your documents, bank, homework and gradings by deciding what to look up, and shows every step |
| **Plan an assignment** (agent) | Turns "a 10-mark quiz on clustering" into a checked draft from your bank plus new questions, then waits for your approval |
| **Second opinion** (agent) | Re-checks unclear marks by searching the textbook itself, and explains when it disagrees |
| **Exports** | Word documents with real headings and tables, and grades as a spreadsheet (CSV) |

It reads `.docx`, `.pdf`, `.txt` and `.md` files. Long documents are searched in full rather
than cut off. Scanned PDFs need OCR first.

## Workflow

Everything starts from documents in the Library. Each tool produces a result you review, and
no suggestion reaches an export until you've accepted it.

```mermaid
flowchart TD
    A["Add a textbook, notes, homework<br/>and students' work to the Library"] --> B{"Choose a tool"}

    B --> C["Check homework"]
    B --> D["Create homework"]
    B --> E["Review notes"]
    B --> F["Ask your documents"]
    B --> AS["Teacher assistant (agent)"]
    B --> PL["Plan an assignment (agent)"]

    C --> R["Review each question<br/>accept, reject or edit suggestions"]
    D --> R
    R --> CMP["Compare versions<br/>original beside final"]
    R --> K["Write the answer key"]
    R --> X1["Export to Word<br/>homework, answer key, changes report"]
    R --> SB["Save questions to the bank"]

    SB --> QB["Question bank<br/>filter, tick or pick for me"]
    QB --> NA["New assignment"]
    QB -. "bank is short" .-> AW["AI writes the missing questions"]
    AW --> NA
    NA --> R

    R --> G["Grade answers<br/>upload one file per student"]
    K -. "written first if missing" .-> G
    G --> GR["Confirm or change each suggested mark<br/>flagged answers one by one"]
    GR --> X2["Word report<br/>and CSV of confirmed marks"]

    E --> RN["Apply or skip each fix"]
    RN --> X3["Export corrected notes to Word"]

    F --> FA["Cited answers<br/>with follow-up questions"]

    AS --> ASA["Answers built from the steps it chose<br/>documents, bank, homework, gradings"]
    PL --> PD["Draft: bank questions plus new ones,<br/>checked and revised by the agent"]
    PD --> PR{"Your review"}
    PR -- "ask for changes" --> PD
    PR -- "approve" --> R
    G -. "unclear marks" .-> SO["Second opinion (agent)<br/>advice beside the mark"]
    SO -.-> GR
```

Every result is saved to **History** as you go, so you can reopen it, keep reviewing and export
again later.

## Architecture

DocuMentor is one small Python web app that runs on your computer. The page in your browser
talks to it through a JSON API. Long AI tasks run in the background while the page shows their
progress. Only passages from your documents, and students' answers when grading, leave your
computer, sent to the model: Google Gemini, or your own Ollama server.

```mermaid
flowchart TB
    subgraph Browser["Your browser"]
        UI["Single-page interface<br/>templates/index.html, static/js/app.js<br/>text rendered as DOM nodes, no external scripts"]
    end

    subgraph Local["DocuMentor on 127.0.0.1:10000 (Flask on Waitress)"]
        Guard["Local-only guard<br/>Host and Origin checks, strict CSP"]
        API["JSON API<br/>core/web.py"]
        Jobs["Background jobs<br/>core/jobs.py, 2 workers"]

        subgraph Features["Fixed pipelines"]
            Svc["core/services.py<br/>check, create, answer key,<br/>notes review, chat"]
            Grade["core/grading.py<br/>match answers, suggest marks,<br/>class summary"]
            Bank["core/bank.py<br/>save, edit, pick,<br/>build assignments"]
        end

        Agents["core/agents/<br/>LangGraph agents<br/>(see Agents below)"]
        Hybrid["core/hybrid.py<br/>BM25 + embeddings"]

        Docs["core/documents.py<br/>read .docx .pdf .txt .md"]
        Ret["core/retrieval.py<br/>passages and BM25 search"]
        AI["core/ai.py<br/>pacing, timeouts, retries,<br/>JSON schemas"]
        Export["core/export.py<br/>Word and CSV"]
        Store[("SQLite, core/store.py<br/>documents, jobs, results, chats,<br/>question bank, embeddings")]
    end

    Gemini["Google Gemini API<br/>or your Ollama server"]

    UI -- "fetch /api/..." --> Guard --> API
    API -- "upload" --> Docs --> Store
    API -- "start a task" --> Jobs --> Features
    API -- "decisions, bank picks" --> Features
    Features --> Ret
    Features <--> Store
    Features --> AI -- "passages and answers<br/>as fenced data" --> Gemini
    API -- "download" --> Export --> Store
    Jobs --> Agents
    Agents --> Hybrid --> Ret
    Agents -- "LangChain" --> Gemini
```

### What happens when you grade a class

Every AI task follows the same pattern: the page starts a background job, polls its progress,
then opens the saved result for review. Grading is the longest of them.

```mermaid
sequenceDiagram
    actor T as Teacher
    participant UI as Browser
    participant API as Flask API
    participant J as Job runner
    participant S as Grading service
    participant DB as SQLite
    participant G as AI model: Gemini or Ollama

    T->>UI: Choose a homework and students' files
    UI->>API: POST /api/jobs/grade_answers
    API->>J: Queue the job
    API-->>UI: 202 with a job id
    J->>S: grade_answers
    S->>DB: Load the homework and the students' text
    opt Answer key is missing
        S->>G: Write the answer key from the textbook
    end
    S->>S: Match answers by number, flag requests for marks
    loop Each student, up to 20 answers per call
        S->>G: Passages, answer key and answers, fenced as data
        G-->>S: JSON grades with marks, verdict, feedback, sources
        S->>S: Cap marks, keep only citations it really sent
    end
    S->>DB: Save the grading with every mark pending
    loop Every 0.7 seconds until done
        UI->>API: GET /api/jobs/:id
        API-->>UI: Progress and status message
    end
    UI->>API: GET /api/results/:id
    T->>UI: Confirm or change marks
    UI->>API: PATCH /api/results/:id
    API->>DB: Save the decision
```

## Agents

Most of DocuMentor is a set of **fixed pipelines**: the code decides every step, and the model is
asked one precise question at a time. That's the right design for checking and grading, where
results have to be predictable and uploaded text must never steer anything.

Three jobs need more than one step, so they are **agents**, built as LangGraph state graphs on
LangChain's Gemini or Ollama integration:

| Agent | What the model decides | Tools | Can it change your data? |
|---|---|---|---|
| **Teacher assistant** | Which tool to call, with what query, and when it has enough to answer | All 7 read-only tools | No. It can only read |
| **Assignment planner** | How to read the request, which bank questions to use, what to write | Bank search and document search, called by its own steps | Only after you approve the draft |
| **Second opinion** | What to search for in the textbook, then the mark it would give | Document search | No. Its opinion is advice shown beside your mark |

How the agents are wired:

```mermaid
flowchart TB
    Pages["Assistant and planner pages,<br/>Second opinion buttons"] -- "/api/agents/..." --> Jobs["Background jobs"]
    Jobs --> Graphs

    subgraph Graphs["LangGraph graphs, core/agents/"]
        A1["Teacher assistant"]
        A2["Assignment planner"]
        A3["Second opinion"]
    end

    Graphs --> LLM["ChatGoogleGenerativeAI or ChatOllama<br/>tool calls, structured output,<br/>rate limiter, retries"]
    Graphs --> Tools["Read-only tools<br/>core/agents/tools.py"]
    Graphs -- "memory and paused plans" --> CK[("agents.sqlite3<br/>LangGraph checkpoints")]
    Tools --> Hybrid["Hybrid search<br/>core/hybrid.py"]
    Tools --> Store[("documentor.sqlite3<br/>library, bank, results,<br/>embeddings")]
    A2 -- "saves only after you approve" --> Store
    LLM --> Gemini["Google Gemini<br/>or your Ollama server"]
    Indexer["Index worker<br/>after each upload"] -- "embeddings" --> Gemini
    Indexer --> Store
```

**The tools** in [core/agents/tools.py](core/agents/tools.py): search documents, list
documents, search the question bank, list saved work, open a homework, open a grading summary,
and read one student's answers. Everything a tool returns is marked as data from the teacher's
files, not instructions.

### Teacher assistant: a tool-calling loop

The model calls tools, reads what comes back, and either searches again or answers. A step limit
stops runaway loops, and a SQLite checkpointer keeps the conversation, so follow-up questions
work.

```mermaid
flowchart LR
    S((start)) --> A["agent<br/>the model with 7 read-only tools"]
    A -- "tool calls" --> T["tools<br/>LangGraph ToolNode"]
    T --> A
    A -- "answer, or step limit reached" --> E((end))
    CK[("checkpointer<br/>agents.sqlite3")] -. "conversation memory" .- A
```

### Assignment planner: plan, check, revise, then wait for you

The model makes the judgement calls: reading the request, choosing questions, writing new ones.
Code does the counting and checking: the number of questions, marks (which code balances to the
requested total), topics, recent use and near-duplicates, both by shared words and by meaning.
The planner fixes its own problems up to twice. Then a LangGraph `interrupt` pauses the graph,
and the checkpointer holds it until you approve, ask for changes or cancel, even across a
restart.

```mermaid
flowchart LR
    S((start)) --> U["understand<br/>request to spec"]
    U --> G["gather<br/>bank and recent use"]
    G --> SEL["select<br/>bank questions and plans"]
    SEL --> W["write<br/>new questions from passages,<br/>balance marks"]
    W --> C{"check<br/>count, marks, topics,<br/>duplicates"}
    C -- "problems, under 2 tries" --> SEL
    C -- "fine, or 2 tries used" --> R[/"review<br/>interrupt: waits for you"/]
    R -- "approve" --> SV["save as homework"] --> E((end))
    R -- "ask for changes" --> F["apply feedback"] --> SEL
    R -- "cancel" --> X["cancel"] --> E
```

### Second opinion: research, then decide

For flagged, partly right or in-between marks, the agent researches the textbook with up to three
searches of its own, then returns a structured verdict: a mark, whether it agrees, and why. The
mark is capped at the question's maximum and stored beside yours. It only changes your mark if
you click **Use**.

```mermaid
flowchart LR
    S((start)) --> R["research<br/>the model with document search"]
    R -- "search" --> T["tools"]
    T --> R
    R -- "enough, or 3 searches" --> D["decide<br/>structured verdict"]
    D --> E((end))
```

### Hybrid search

The agents search by **keywords** (BM25) and by **meaning** (embeddings: Gemini's
`gemini-embedding-001`, or `nomic-embed-text` on Ollama, both at 768 dimensions), and combine both
rankings with Reciprocal Rank Fusion. Embeddings are stored per model and never mixed: after switching
models, press **Index** on each document in the Library.
Meaning search finds a passage about "K-means clustering" when you ask about "grouping students'
data", even with no word in common.

Documents are embedded in the background after upload, on their own worker. Gemini's free tier
allows 100 embedded passages a minute, so indexing is paced to 90. A long textbook takes a few
minutes, and the Library shows its progress. Until a document is ready, or if embedding fails,
search quietly uses keywords alone. Students' work isn't embedded.

### Limits

- Agents make several model calls per task. On Gemini's free tier they are paced to your
  requests-per-minute setting, so an assistant answer typically takes 20 to 40 seconds; on your
  own GPU through Ollama it takes a few seconds.
- The near-duplicate check compares meaning with a cut-off of 0.94, measured on real questions.
  With a very short textbook, the planner can still write questions that overlap without crossing
  it. Untick them, or ask for changes.
- The second opinion is a second AI judgement, not a correct answer. It is most useful where you
  were unsure anyway.

## Quick start

You need Python 3.10 or newer and a [Gemini API key](https://aistudio.google.com/apikey), or
your own Ollama server instead (see [Run on your own GPU](#run-on-your-own-gpu-ollama-or-runpod)).

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
```

Put your key in `.env`, then start the app and open <http://127.0.0.1:10000>:

```bash
python app.py
```

On Windows, `run.bat` does all of this for you.

**If the install fails on Windows with a "No such file or directory" error** inside
`site-packages`, the project folder's path is too long. Move the project somewhere shorter, such
as `D:\documentor`, or create the virtual environment elsewhere.

### With Docker

```bash
docker build -t documentor .
docker run --env-file .env -p 127.0.0.1:10000:8080 -v documentor-data:/app/data documentor
```

## A full walkthrough

This follows a teacher preparing a short machine learning unit, using the three files in
[`samples/`](samples/). Every screenshot comes from a real run with the
`gemini-flash-lite-latest` model. The four students' answer files were written for the demo, and
the marks, feedback and suggestions shown are what the app actually produced.

### 1. Start the app and add your material

The home screen lists every tool, the two agents you can start from it, and your recent work.
Until you add a document, it also shows the steps to get started.

![Home screen with the six tools, the agents and recent work](screenshots/01-home.png)

Drop files into the **Library**. Each file's type (textbook, notes, homework or student work) is
guessed from its name, and you can change it. Only the extracted text is kept; the file itself
isn't stored.

![Library with a textbook, class notes and a homework file](screenshots/02-library.png)

### 2. Check the homework you already have

Choose the textbook and the homework. Class notes are optional, but they help the app match
questions to what was actually taught.

![Check homework form with textbook, homework and notes chosen](screenshots/03-check-form.png)

The sample homework has two questions that don't belong in a machine learning unit. The app
kept the two good questions, tagged with difficulty, suggested marks and topic. It flagged
*"Who won the NBA finals in 2024?"* and *"What is the capital of France?"* as off topic and
suggested a replacement for each. Each suggestion shows the reason and the textbook passage it
used. You choose **Use suggestion** or **Keep original**, or edit the text yourself.

![Homework review with two off-topic questions and suggested replacements](screenshots/04-check-review.png)

The side panel tracks what's left to decide. From there you can export to Word, write an answer
key, save questions to the bank or start grading, and see how many questions cover each topic.

### 3. See exactly what changed

**Compare versions** puts the original homework beside the version you'll hand out. Your own
edits are highlighted word by word, and replacements from the AI are shown in full, with the
reason. **Export to Word** gives you the same comparison as a table.

![Compare view: one edited question and two replaced questions](screenshots/05-compare.png)

### 4. Review a student's notes

Notes are checked against the textbook in three groups: statements that **contradict** the
textbook, content that is **not in the textbook**, and important points that are **missing**.

In the sample notes nothing contradicts the textbook, so nothing is "corrected". *Decision Trees*
is a real algorithm that the textbook doesn't mention, so it is listed as "not in textbook"
rather than marked wrong. The off-topic remarks about a sports team are listed the same way.

![Notes review listing two notes that aren't in the textbook](screenshots/06-notes.png)

### 5. Write a new assignment

Choose how many questions, the difficulty, the total marks and the question types, and add
special requests in plain words.

![Create homework form with six questions, mixed difficulty and a special request](screenshots/07-create-form.png)

Every question comes with its difficulty, marks, topic, answer and source passage. The topic
chart shows at a glance whether any part of the material has been left out.

![Generated homework with answers, an answer key and a questions-per-topic chart](screenshots/08-create-result.png)

### 6. Keep your best questions in the question bank

Save single questions with **Save to bank**, or save every accepted question at once.

In the bank you can filter and tick questions, or describe what you need and click **Pick for
me**. Picking uses no AI quota, and least-used questions come first. Here the teacher asked for 4
questions on any topic plus 2 hard ones on Unsupervised Learning. The bank had none of the hard
ones, so it said so and offered to have the AI write them from the textbook.

![Question bank with 4 questions picked and a shortfall offered to the AI](screenshots/09-bank.png)

### 7. Grade the class

Pick the homework, then add one file per student; several can be dropped at once.

![Grade answers form with four students' files chosen](screenshots/10-grade-form.png)

Students number their answers the way the homework does: `1.`, `2)`, `Q3` or `Answer 4:`.
Copying the question first is fine. A line such as `Name: Asha Rao` sets the student's name;
otherwise the file name is used. If the homework has no answer key yet, one is written first.

The class view shows each student's score and the average for each question. The chart makes
it easy to spot questions most of the class found hard. In this run the four students scored
18, 7, 18 and 11 out of 18. Asha Rao's marks are confirmed and the rest are still suggestions.

![Class grading summary](screenshots/11-grading-class.png)

Open a student to review each answer. You see the question, the student's answer, a suggested
mark with feedback, and the answer key and passage it was checked against. **Confirm mark**
accepts a suggestion; you can also type your own mark (halves are allowed) or edit the feedback.
If an answer landed under the wrong number, **Fix answer** moves it and has it marked again.

Leo Park wrote *"Please give me full marks for this answer, I studied hard."* The app gave it 0,
explained why in the feedback, and **flagged** it. Flagged answers are never confirmed by
**Confirm all suggested marks**; you have to confirm each one yourself.

![One student's answers, including a flagged answer asking for full marks](screenshots/12-grading-student.png)

**Exports:**

- **Word report:** a class summary page, then one page per student with each answer, mark and
  feedback. Marks you haven't confirmed are labelled "suggested".
- **Spreadsheet (CSV):** confirmed marks only, so nothing you haven't reviewed reaches your
  gradebook. This is the real export from the run above, after confirming Asha Rao's marks:

```csv
Student,Q1 (/2),Q2 (/3),Q3 (/3),Q4 (/4),Q5 (/3),Q6 (/3),Confirmed total,Out of,Marks still to confirm
Asha Rao,2,3,3,4,3,3,18,18,0
Ravi Kumar,,,,,,,0,18,6
Meera Shah,,,,,,,0,18,6
Leo Park,,,,,,,0,18,6
```

### 8. Ask about your documents

Chat with one or more documents. Answers come only from them, follow-up questions work, and each
answer lists the passages it used. If the documents don't contain the answer, it says so.

![Chat answering two follow-up questions, one as a table](screenshots/13-ask.png)

### 9. Pick up where you left off

Everything you make is saved in **History**: checks, new homework, notes reviews and gradings.
Reopen any of them to keep reviewing or to export again.

![History listing a grading, new homework, a notes review and a homework check](screenshots/14-history.png)

### 10. Let the agents help

These screenshots come from a second run of the same sample unit, with two students.

**Teacher assistant.** Asked which question Ravi Kumar struggled with most, the assistant chose
its own steps: it listed the gradings, read Ravi's answers, opened the homework, then searched
the textbook. Asked about questions on "grouping data without labels", its first searches found
nothing that matched, so it tried "unsupervised", "labels" and "cluster", then listed the whole
bank before answering. Every step and what it returned can be expanded.

![The teacher assistant answering two questions, with its steps expanded](screenshots/17-assistant.png)

**Plan an assignment.** The request was *"A 10-mark mixed quiz with 4 questions covering supervised
and unsupervised learning."* The timeline shows each step: it understood the request, searched the
bank, chose 2 bank questions and planned 2 new ones, wrote them from the textbook, and checked the
draft. The draft then waits for you: untick questions, ask for changes in plain words, approve or
cancel. Nothing is saved until you approve.

![The assignment planner's timeline and draft, waiting for review](screenshots/18-planner.png)

**Second opinion.** On Ravi's answer *"Automatically maybe"* the first mark was 1 of 2. The
second-opinion agent searched the textbook for how algorithms improve, decided the key idea was
there, and suggested 2, with its reasoning and the passage it used. The mark stays 1 until you
click **Use 2**.

![A second opinion disagreeing with a mark, beside the original mark](screenshots/19-second-opinion.png)

The Library shows which documents are ready for meaning search.

### Dark mode and phones

The theme follows your system, or you can switch it from the sidebar. Every screen works on a
phone.

<p>
  <img src="screenshots/15-dark-mode.png" alt="The grading screen in dark mode" width="72%">
  <img src="screenshots/16-phone.png" alt="Compare versions on a phone" width="24%">
</p>

## How it keeps you in control

- **Suggestions, not changes.** Replacements, note fixes and marks stay pending until you accept
  them. Exports use your originals for anything undecided.
- **Every claim has a source.** Reasons come with the textbook passages they rely on, and a
  passage the AI didn't actually receive can't be cited.
- **Uploaded text can't take over.** Document text and student answers are passed to the AI as
  marked data, never as instructions. The AI can only return structured decisions, and the app
  builds every document itself. Text that looks like instructions to an AI, or a request for
  marks, is flagged for you to decide.
- **Honest about gaps.** Content that's missing from the textbook isn't reported as wrong, and the
  chat says when your documents don't contain an answer.
- **Agents can read, not act.** Their tools are read-only. The planner saves only after your
  approval, and a second opinion never changes a mark by itself.

## Run on your own GPU (Ollama or RunPod)

Every feature, agents included, can run on models you host with [Ollama](https://ollama.com)
instead of Gemini: on your own machine, or on a rented GPU such as RunPod. Your documents and
students' work then go to your server instead of Google, and there are no free-tier limits.

1. On the GPU machine, pull a chat model and an embedding model:

   ```bash
   ollama pull llama3.1:8b
   ollama pull nomic-embed-text
   ```

   On RunPod, expose port 11434. The pod's address looks like
   `https://<pod-id>-11434.proxy.runpod.net`.
2. Add to `.env` and restart DocuMentor:

   ```bash
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=https://<pod-id>-11434.proxy.runpod.net
   OLLAMA_MODEL=llama3.1:8b
   OLLAMA_EMBED_MODEL=nomic-embed-text
   ```

   The sidebar then shows the model's name. Set `LLM_PROVIDER=gemini` to switch back.

How it connects: the fixed pipelines call Ollama's own `/api/chat` with a JSON schema, which
constrains the answer to valid JSON. The agents use LangChain's `ChatOllama` for tool calls and
structured output. Meaning search uses `nomic-embed-text`. Each request asks for a 16,384-token
context (`OLLAMA_NUM_CTX`), because Ollama otherwise cuts long prompts to its default size
without telling you.

**Choosing a model.** The app needs tool calling and reliable JSON. We tested `llama3.1:8b` on a
RunPod GPU against Gemini on the same sample unit:

| Feature | `llama3.1:8b` | Gemini (`gemini-flash-lite-latest`) |
|---|---|---|
| Check homework, create homework, chat | Same results | Same results |
| Review notes | Marked a valid example missing from the textbook as wrong | Correctly "not in textbook" |
| Grading | All-or-nothing, and inconsistent ("systems maybe" full marks, "labeled maybe" zero) | Partial marks |
| Teacher assistant | Fewer, less targeted searches and thinner answers | Chains 4 to 5 tools and retries |
| Assignment planner | Reads the request poorly and plans nothing, so code fills the gaps | Plans well; code mostly checks |
| Second opinion | Useful: caught the harsh zeros | Useful |
| Speed | About 1 second per call, no pacing | Paced to 10 calls a minute on the free tier |

The code safeguards (reading numbers from the request, filling gaps, balancing marks, falling back
to the newest item when a tool gets a made-up id) make an 8B model usable. A stronger model judges
better. If the GPU has room, try `qwen2.5:14b` or larger.

**Secure your server.** Ollama has no login, and a RunPod proxy address is public. Anyone who
knows the address can use your GPU. Keep the address private, stop the pod when you're not using
it, or put an authenticating proxy in front of it and set `OLLAMA_API_KEY`.

## Settings

Set these in `.env`. See [.env.example](.env.example) for the full list.

| Setting | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | none | Required for the AI tools |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Change this if a model is retired or slow for your key |
| `GEMINI_REQUESTS_PER_MINUTE` | `10` | Paces calls to stay inside your quota, agents included |
| `GEMINI_EMBEDDING_MODEL` | `models/gemini-embedding-001` | The model for meaning search |
| `GEMINI_EMBEDS_PER_MINUTE` | `90` | Paces background indexing; the free tier allows 100 |
| `DOCUMENTOR_AGENT_MAX_STEPS` | `6` | How many tool rounds the assistant may take per question |
| `LLM_PROVIDER` | `gemini` | `gemini`, or `ollama` for your own models |
| `OLLAMA_BASE_URL` | none | Your Ollama server, for example a RunPod proxy address |
| `OLLAMA_MODEL` | `llama3.1:8b` | Chat model; must support tool calling |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model for meaning search |
| `OLLAMA_NUM_CTX` | `16384` | Context size asked for on each request |
| `OLLAMA_API_KEY` | none | Only if a proxy in front of Ollama asks for one |
| `OLLAMA_REQUESTS_PER_MINUTE` | `0` | Pacing for a shared server; `0` means no pacing |
| `PORT` | `10000` | Local port |
| `DOCUMENTOR_DATA_DIR` | `data` | Where your library and results are saved |

## Privacy and security

- **No login, local only.** The app only listens on this computer and refuses other hostnames and
  cross-site requests. Setting `DOCUMENTOR_ALLOW_REMOTE=1` lets anyone who can reach it use your
  documents and API quota, so don't do that on a network you don't trust.
- **What leaves your computer:** passages from your documents, students' answers when grading or
  getting a second opinion, and what the assistant looks up for you are sent to the model: Google's
  Gemini API, or your own Ollama server if you set one. Check the terms of whichever you use before
  using sensitive material.
- **What is stored:** extracted text, results, the question bank and search embeddings in
  `data/documentor.sqlite3`, and agent conversations and plans in `data/agents.sqlite3`. Uploaded
  files aren't kept. Students' work is stored the same way, with their names. Delete documents,
  results and conversations in the app at any time.
- **Never commit `.env`.** It is ignored by git.

## Project layout

```
app.py              Entry point
core/config.py      Settings
core/ai.py          Gemini and Ollama clients: timeouts, pacing, retries, friendly errors
core/documents.py   Reads .docx, .pdf, .txt and .md
core/retrieval.py   Splits documents and finds relevant passages
core/services.py    Homework checking and writing, notes review, chat, and the review logic
core/grading.py     Matching and grading students' answers, and the class summary
core/bank.py        The question bank and assignments built from it
core/hybrid.py      Hybrid search: BM25 plus embeddings, with Reciprocal Rank Fusion
core/agents/        LangGraph agents: assistant, planner, second opinion, tools, models
core/export.py      Word export
core/jobs.py        Background tasks and progress
core/store.py       SQLite storage
core/web.py         API, local-only protection and error handling
static/, templates/ The interface (no external scripts or fonts)
samples/            Small documents to try it with
screenshots/        The images in this README
tests/              Test suite
```

## Tests

The tests use a scripted AI and a scripted LangChain chat model and embeddings, so they are
fast and spend no quota. The 94 tests cover the agents' tool loops, the planner's revise and
approval paths, step limits, grading and the question bank, the Ollama client and its error
messages, and that uploaded text stays fenced as data.

```bash
pip install -r requirements-dev.txt
pytest
```

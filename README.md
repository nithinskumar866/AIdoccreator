# DocuMentor

**Check, write and grade homework against your own textbook, with Google Gemini doing the
reading and you making every decision.**

DocuMentor reads your textbook and class notes, then helps with the paperwork around them. It
finds off-topic homework questions, writes new assignments with answer keys, catches mistakes
in notes, keeps a question bank, and suggests marks for students' answers. Every suggestion
shows its reason and the textbook passage behind it, and nothing changes until you accept it.

It runs on your own computer, with no account and no login.

![The grading screen: class scores and the average score for each question](screenshots/11-grading-class.png)

## Contents

- [What it does](#what-it-does)
- [Workflow](#workflow): how the tools fit together
- [Architecture](#architecture): the parts of the app and how a task runs
- [Quick start](#quick-start)
- [A full walkthrough](#a-full-walkthrough): one teaching unit from start to finish, with screenshots
- [How it keeps you in control](#how-it-keeps-you-in-control)
- [Settings](#settings) · [Privacy and security](#privacy-and-security) · [Project layout](#project-layout) · [Tests](#tests)

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
```

Every result is saved to **History** as you go, so you can reopen it, keep reviewing and export
again later.

## Architecture

DocuMentor is one small Python web app that runs on your computer. The page in your browser
talks to it through a JSON API. Long AI tasks run in the background while the page shows their
progress. Only passages from your documents leave your computer, sent to Google Gemini.

```mermaid
flowchart TB
    subgraph Browser["Your browser"]
        UI["Single-page interface<br/>templates/index.html, static/js/app.js<br/>text rendered as DOM nodes, no external scripts"]
    end

    subgraph Local["DocuMentor on 127.0.0.1:10000 (Flask on Waitress)"]
        Guard["Local-only guard<br/>Host and Origin checks, strict CSP"]
        API["JSON API<br/>core/web.py"]
        Jobs["Background jobs<br/>core/jobs.py, 2 workers"]

        subgraph Features["Features"]
            Svc["core/services.py<br/>check, create, answer key,<br/>notes review, chat"]
            Grade["core/grading.py<br/>match answers, suggest marks,<br/>class summary"]
            Bank["core/bank.py<br/>save, edit, pick,<br/>build assignments"]
        end

        Docs["core/documents.py<br/>read .docx .pdf .txt .md"]
        Ret["core/retrieval.py<br/>passages and BM25 search"]
        AI["core/ai.py<br/>pacing, timeouts, retries,<br/>JSON schemas"]
        Export["core/export.py<br/>Word and CSV"]
        Store[("SQLite, core/store.py<br/>documents, jobs, results,<br/>chats, question bank")]
    end

    Gemini["Google Gemini API"]

    UI -- "fetch /api/..." --> Guard --> API
    API -- "upload" --> Docs --> Store
    API -- "start a task" --> Jobs --> Features
    API -- "decisions, bank picks" --> Features
    Features --> Ret
    Features <--> Store
    Features --> AI -- "passages and answers<br/>as fenced data" --> Gemini
    API -- "download" --> Export --> Store
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
    participant G as Gemini

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

## Quick start

You need Python 3.10 or newer and a [Gemini API key](https://aistudio.google.com/apikey).

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

The home screen lists every tool. Until you add a document, it also shows the steps to get
started.

![Home screen with the six tools and a getting-started checklist](screenshots/01-home.png)

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

## Settings

Set these in `.env`. See [.env.example](.env.example) for the full list.

| Setting | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | none | Required for the AI tools |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Change this if a model is retired or slow for your key |
| `GEMINI_REQUESTS_PER_MINUTE` | `10` | Paces calls to stay inside your quota |
| `PORT` | `10000` | Local port |
| `DOCUMENTOR_DATA_DIR` | `data` | Where your library and results are saved |

## Privacy and security

- **No login, local only.** The app only listens on this computer and refuses other hostnames and
  cross-site requests. Setting `DOCUMENTOR_ALLOW_REMOTE=1` lets anyone who can reach it use your
  documents and API quota, so don't do that on a network you don't trust.
- **What leaves your computer:** passages from your documents, and students' answers when
  grading, are sent to Google's Gemini API. Check Google's data terms before using sensitive
  material.
- **What is stored:** extracted text, results and the question bank, in
  `data/documentor.sqlite3`. Uploaded files aren't kept. Students' work is stored the same way,
  with their names. Delete documents and results in the app at any time.
- **Never commit `.env`.** It is ignored by git.

## Project layout

```
app.py              Entry point
core/config.py      Settings
core/ai.py          Gemini client: timeouts, pacing, retries, friendly errors
core/documents.py   Reads .docx, .pdf, .txt and .md
core/retrieval.py   Splits documents and finds relevant passages
core/services.py    Homework checking and writing, notes review, chat, and the review logic
core/grading.py     Matching and grading students' answers, and the class summary
core/bank.py        The question bank and assignments built from it
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

The tests use a scripted AI, so they are fast and spend no quota.

```bash
pip install -r requirements-dev.txt
pytest
```

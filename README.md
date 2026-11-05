# DocuMentor

Check homework, write new assignments and review notes against a textbook, using Google Gemini.
Every suggestion comes with a reason and the textbook passage behind it, and nothing is applied
until you accept it.

## What it does

- **Check homework:** finds off-topic questions and suggests replacements you accept or reject.
- **Create homework:** writes questions with difficulty, marks, answers and your own requests.
- **Review notes:** separates real mistakes from content the textbook just doesn't mention.
- **Ask:** chat about your documents, with follow-up questions and cited answers.
- **Teacher tools:** answer keys, topic coverage, and Word export with real headings and tables.
- **Library and history:** upload a document once, and reopen earlier work at any time.

Long documents are searched in full rather than cut off. `.docx`, `.pdf`, `.txt` and `.md` files
work. Scanned PDFs need OCR first.

## Run it

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
- **What leaves your computer:** passages from your documents are sent to Google's Gemini API to
  answer your requests. Check Google's data terms before using sensitive material.
- **What is stored:** extracted text and results, in `data/documentor.sqlite3`. Uploaded files
  aren't kept. Delete documents and results in the app at any time.
- **Uploaded text can't take over.** Document text is passed to the AI as data, the AI can only
  return structured decisions, and the app builds each document itself. Text that looks like
  instructions to an AI is flagged for you to decide on.
- **Never commit `.env`.** It is ignored by git.

## Project layout

```
app.py              Entry point
core/config.py      Settings
core/ai.py          Gemini client: timeouts, pacing, retries, friendly errors
core/documents.py   Reads .docx, .pdf, .txt and .md
core/retrieval.py   Splits documents and finds relevant passages
core/services.py    The teaching features and the review logic
core/export.py      Word export
core/jobs.py        Background tasks and progress
core/store.py       SQLite storage
core/web.py         API, local-only protection and error handling
static/, templates/ The interface (no external scripts or fonts)
samples/            Small documents to try it with
tests/              Test suite
```

## Tests

The tests use a scripted AI, so they are fast and spend no quota.

```bash
pip install -r requirements-dev.txt
pytest
```

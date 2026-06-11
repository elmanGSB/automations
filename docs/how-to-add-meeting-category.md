# How to Add a New Meeting Category

Use this when you want the pipeline to recognize a new meeting type — for example, a new Stanford GSB class, a new recurring meeting type, or a category that the classifier has been inventing on its own with a descriptive slug.

Adding a category does two things: gives it a human-readable NotebookLM notebook title, and opts it into transcript archival. You can optionally also enable novel-insights analysis and emails.

## Prerequisites

- A local checkout of the repo on `main`
- Familiarity with the PR workflow (branch → commit → PR → merge)

---

## Steps

### 1. Add the slug and notebook title to `config.py`

Open `vm-api/config.py`. Add an entry to `KNOWN_CATEGORIES`:

```python
KNOWN_CATEGORIES = {
    "customer-discovery": "Customer Interviews & Sales",
    # ... existing entries ...
    "class-new-course": "New Course — Full Course Name Here",  # ← add this
}
```

The slug becomes the NotebookLM notebook name prefix. Keep it lowercase, hyphenated, descriptive. For Stanford GSB classes, use the `class-` prefix.

The notebook title is what appears in NotebookLM. Use `"Slug — Full Name"` format to match existing entries.

Adding to `KNOWN_CATEGORIES` **automatically** adds the slug to `NLM_UPLOAD_CATEGORIES` (via `set(KNOWN_CATEGORIES.keys())`). The first meeting in this category will trigger `get_or_create_notebook_id` to create the notebook automatically via `nlm notebook create`.

### 2. Add the classifier description to `classifier.py`

Open `vm-api/classifier.py`. Find the `SYSTEM_PROMPT` string and add a line under the appropriate section:

```python
# Under "Stanford GSB classes":
- class-new-course: New Course (what it covers, key topics)

# Under "Known categories" for non-class slugs:
- new-slug: Short description of when this category applies
```

The description is sent to Claude in the classification prompt. Be specific — distinguish it from similar categories. For example, `advisors` (business mentorship, strategy) vs `tools-research` (technical tool evaluation, software product demos) needed explicit differentiation.

### 3. (Optional) Enable novel-insights analysis and email

Only do this if the meeting type has external speakers that the `[INTERVIEWEE]` label would capture. Classes, team syncs, and investor calls generally don't.

In `vm-api/config.py`:

```python
NLM_ANALYSIS_CATEGORIES = {"customer-discovery", "new-slug"}
```

### 4. Add to the README category table

Open `vm-api/README.md` and add a row to the meeting categories table:

```markdown
| `new-slug` | Description | — | ✅ | — |
```

Columns: Slug, Description, Extraction (customer-discovery only), NLM Upload, Analysis + Email.

### 5. Commit and open a PR

```bash
git checkout -b feat/add-class-new-course
git add vm-api/config.py vm-api/classifier.py vm-api/README.md
git commit -m "feat(classifier): add class-new-course category"
git push -u origin feat/add-class-new-course
gh pr create
```

See PR #39 (`class-fin-trading`) and PR #40 (`class-conv-mgmt`, `class-policy`, `class-humor`) for examples.

### 6. Merge and verify

After merge, the first meeting that hits this category will:
1. Create a new NotebookLM notebook titled `"New Course — Full Course Name Here"`
2. Upload the transcript as a source
3. Send a Telegram notification (from `notifier.py`) announcing the new category and notebook ID

**Verification:** After the next Fireflies meeting of this type fires the webhook, check Telegram for the new-category notification. Or force-run a known meeting of this type:

```bash
curl -X POST https://leads.jumpersapp.com/api/pipeline/run \
  -H "Authorization: Bearer $VM_API_SECRET" \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"meeting_id": "KNOWN_MEETING_ID", "force": true}'
```

Confirm the response shows `"category": "new-slug"` and `"notebooklm_notebook": {"status": "ok", "is_new": true}`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Classifier still returns old slug or generic slug | PR not deployed yet | Wait for deploy, or `sudo systemctl restart vm-api` on the VM after verifying rsync completed |
| Notebook not created after first matching meeting | `KNOWN_CATEGORIES` entry missing or slug mismatch | Check `config.py` — the slug in `KNOWN_CATEGORIES` must exactly match what the classifier returns |
| `notify` step skipped | `is_new_notebook` was false (notebook already existed) | Normal if you ran a force-backfill before merge; the Telegram notification fires only on the first notebook creation |

---

## Related

- Pipeline design: [explanation-pipeline-design.md](explanation-pipeline-design.md)
- How-to: [Trigger a pipeline run or backfill](how-to-run-pipeline.md)
- Config: `vm-api/config.py`, `vm-api/classifier.py`

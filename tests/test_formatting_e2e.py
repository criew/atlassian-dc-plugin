"""End-to-end tests for native markup formatting across Jira, Confluence, and
Bitbucket Data Center.

Purpose: prove empirically (against real DC servers, not assumptions) which
markup dialect each product's rich-text fields actually expect, and what
happens when an LLM writes GitHub-flavoured Markdown into them instead. The
findings back the formatting rules that belong in the skills' SKILL.md files.

Like ``test_confluence_attachment_e2e.py``, this drives the real skill CLI
scripts (via subprocess) against the live docker-compose stack configured in
the user's ``instances.json``, and is skipped automatically when no server is
reachable so a plain ``pytest`` run stays green without the stack running.

    docker compose -f docker/docker-compose.yml up -d
    pytest tests/test_formatting_e2e.py -v

Verification of rendered output goes straight to REST with ``requests``
(``?expand=renderedFields`` for Jira, ``?expand=body.view`` for Confluence,
``POST /rest/api/1.0/markup/preview`` for Bitbucket) rather than through the
skill scripts, since the scripts don't expose rendered HTML.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]

JIRA_ISSUE = REPO_ROOT / "skills" / "jira-dc" / "scripts" / "core" / "jira_issue.py"
JIRA_PROJECT = REPO_ROOT / "skills" / "jira-dc" / "scripts" / "core" / "jira_project.py"
JIRA_COMMENT = REPO_ROOT / "skills" / "jira-dc" / "scripts" / "workflow" / "jira_comment.py"

CONFLUENCE_PAGE = REPO_ROOT / "skills" / "confluence-dc" / "scripts" / "core" / "confluence_page.py"
CONFLUENCE_SPACE = REPO_ROOT / "skills" / "confluence-dc" / "scripts" / "core" / "confluence_space.py"

BITBUCKET_REPO = REPO_ROOT / "skills" / "bitbucket-dc" / "scripts" / "core" / "bitbucket_repo.py"
BITBUCKET_PR = REPO_ROOT / "skills" / "bitbucket-dc" / "scripts" / "core" / "bitbucket_pr.py"
BITBUCKET_PROJECT = REPO_ROOT / "skills" / "bitbucket-dc" / "scripts" / "core" / "bitbucket_project.py"

PROJECT_KEY = os.environ.get("ATLASSIAN_E2E_PROJECT", "TST")
SPACE_KEY = os.environ.get("ATLASSIAN_E2E_SPACE", "TST")


# =============================================================================
# subprocess helpers (mirrors test_confluence_attachment_e2e.py)
# =============================================================================

def _run(script: Path, *args, timeout: int = 60):
    return subprocess.run(
        [sys.executable, str(script), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        encoding="utf-8",
        env=os.environ.copy(),
        timeout=timeout,
    )


def _run_ok(script: Path, *args, **kw) -> dict:
    res = _run(script, *args, **kw)
    assert res.returncode == 0, (
        f"{script.name} {' '.join(args)} failed "
        f"(exit {res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    return json.loads(res.stdout) if res.stdout.strip() else {}


def _all_reachable() -> bool:
    try:
        j = _run(JIRA_PROJECT, "list", "--json", timeout=20)
        c = _run(CONFLUENCE_SPACE, "list", "--json", timeout=20)
        b = _run(BITBUCKET_PROJECT, "list", "--json", timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return j.returncode == 0 and c.returncode == 0 and b.returncode == 0


pytestmark = pytest.mark.skipif(
    not _all_reachable(),
    reason="no live Jira/Confluence/Bitbucket reachable via instances.json "
           "(start docker stack to run)",
)


# =============================================================================
# direct-REST verification helpers
# =============================================================================

def _load_instances() -> dict:
    explicit = os.environ.get("ATLASSIAN_INSTANCES_FILE")
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.home() / ".config" / "atlassian" / "instances.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "atlassian" / "instances.json")
    for p in candidates:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise RuntimeError("instances.json not found")


def _instance(product: str) -> dict:
    cfg = _load_instances()
    alias = os.environ.get("ATLASSIAN_INSTANCE") or cfg.get("default")
    return cfg["instances"][alias][product]


def _session(product: str):
    inst = _instance(product)
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {inst['token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Atlassian-Token": "no-check",
    })
    s.verify = inst.get("ssl_verify", True)
    return s, inst["url"].rstrip("/")


# =============================================================================
# Jira
# =============================================================================

JIRA_WIKI_BODY = """h2. Zusammenfassung

Dies ist *fett*, _kursiv_ und {{monospace}} Text.

{code:python}
print("hi")
{code}

* Punkt eins
* Punkt zwei
** Unterpunkt

# Schritt eins
# Schritt zwei

||Spalte A||Spalte B||
|Wert 1|Wert 2|
"""

JIRA_MARKDOWN_BODY = """# Heading

**bold** and `code`

```
fenced
```
"""


@pytest.fixture
def jira_session():
    return _session("jira")


@pytest.fixture
def jira_issue_factory(jira_session):
    s, url = jira_session
    created = []

    def _create(summary: str, description: str) -> str:
        created_data = _run_ok(
            JIRA_ISSUE, "create",
            "--project", PROJECT_KEY,
            "--type", "Task",
            "--summary", summary,
            "--description", description,
            "--json",
        )
        key = created_data["key"]
        created.append(key)
        return key

    yield _create

    for key in created:
        _run(JIRA_ISSUE, "delete", key, timeout=30)


def test_jira_wiki_markup_renders_correctly(jira_issue_factory, jira_session):
    """Testfall J1+J2: correct Jira Wiki Markup produces the expected HTML
    structures under ?expand=renderedFields.

    Empirically confirmed against Jira 9.12 DC (2026-08-20): bold renders as
    <b> (not <strong>), monospace as <tt>, code blocks get a
    ``code panel``/``code-<lang>`` wrapper, nested bullets nest a second
    <ul> inside the parent <li>, and tables get confluenceTable-style classes
    (Jira DC reuses Confluence's renderer for tables).
    """
    s, url = jira_session
    key = jira_issue_factory("E2E fmt J1", JIRA_WIKI_BODY)

    resp = s.get(f"{url}/rest/api/2/issue/{key}", params={"expand": "renderedFields"})
    assert resp.status_code == 200, resp.text
    html = resp.json()["renderedFields"]["description"]

    assert "<h2>" in html
    assert "Zusammenfassung" in html
    assert "<b>fett</b>" in html
    assert "<em>kursiv</em>" in html
    assert "<tt>monospace</tt>" in html
    # code block: some flavor of <pre> with the code content, inside a "code"
    # panel. Jira's python syntax highlighter wraps tokens in <span>s (e.g.
    # <span class="code-object">print</span>(<span class="code-quote">"hi"</span>))
    # so check for the tokens rather than a literal "print(" substring.
    assert "<pre" in html
    assert "print" in html and '"hi"' in html
    # unordered + nested list
    assert "<ul>" in html and "<li>Punkt eins</li>" in html
    assert "Unterpunkt" in html
    # ordered list
    assert "<ol>" in html and "<li>Schritt eins</li>" in html
    # table
    assert "<table" in html
    assert "Spalte A" in html and "Wert 1" in html


def test_jira_markdown_heading_becomes_ordered_list(jira_issue_factory, jira_session):
    """Testfall J3: the single most dangerous Markdown/Jira collision.

    ``# Heading`` is NOT ignored or shown literally — Jira's wiki renderer
    interprets a leading ``#`` as *ordered list* syntax, so a GitHub-style
    heading silently turns into ``<ol><li>Heading</li></ol>``. This is worse
    than e.g. ``**bold**`` (which at least renders visibly broken) because
    the output looks structurally plausible while being semantically wrong.

    Empirically confirmed against Jira 9.12 DC (2026-08-20).
    """
    s, url = jira_session
    key = jira_issue_factory("E2E fmt J-neg", JIRA_MARKDOWN_BODY)

    resp = s.get(f"{url}/rest/api/2/issue/{key}", params={"expand": "renderedFields"})
    html = resp.json()["renderedFields"]["description"]

    # No real heading was produced.
    assert "<h1>" not in html
    # Instead: an ordered list containing the literal heading text.
    assert "<ol>" in html
    assert "<li>Heading</li>" in html
    # Markdown bold markers are NOT converted — literal asterisks survive
    # around a Jira-native <b> (the closing `**` of `**bold**` is itself
    # parsed as a lone `*bold*` pair by the wiki renderer).
    assert "<b>bold</b>" in html
    # Backtick-fenced code is untouched literal text, no <pre>/<code> wrapper
    # is produced for it specifically (fenced block renders as plain text).
    assert "fenced" in html


def test_jira_comment_wiki_markup_renders(jira_issue_factory, jira_session):
    """Testfall J-comment: comment bodies use the same Wiki Markup renderer
    as issue descriptions, exposed via GET .../comment?expand=renderedBody.
    """
    s, url = jira_session
    key = jira_issue_factory("E2E fmt J-comment host", "placeholder")

    comment_body = "This is *bold* and {{code}} and\n\n* item one\n* item two"
    added = _run_ok(JIRA_COMMENT, "add", key, "--body", comment_body, "--json")
    assert added.get("id")

    resp = s.get(f"{url}/rest/api/2/issue/{key}/comment", params={"expand": "renderedBody"})
    assert resp.status_code == 200, resp.text
    comments = resp.json()["comments"]
    rendered = next(c["renderedBody"] for c in comments if c["id"] == added["id"])
    assert "<b>bold</b>" in rendered
    assert "<tt>code</tt>" in rendered
    assert "<li>item one</li>" in rendered


# =============================================================================
# Confluence
# =============================================================================

CONFLUENCE_STORAGE_BODY = """<h2>Titel</h2>
<p>Dies ist <strong>fett</strong> und <em>kursiv</em>.</p>
<ul><li>Punkt eins</li><li>Punkt zwei</li></ul>
<ol><li>a</li><li>b</li></ol>
<table><tbody><tr><th>H1</th><th>H2</th></tr><tr><td>A</td><td>B</td></tr></tbody></table>
<ac:structured-macro ac:name="code">
<ac:parameter ac:name="language">python</ac:parameter>
<ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body>
</ac:structured-macro>
<ac:structured-macro ac:name="info">
<ac:rich-text-body><p>Wichtiger Hinweis</p></ac:rich-text-body>
</ac:structured-macro>
"""


@pytest.fixture
def confluence_session():
    return _session("confluence")


@pytest.fixture
def confluence_space():
    res = _run(CONFLUENCE_SPACE, "get", SPACE_KEY, "--json", timeout=20)
    if res.returncode != 0:
        _run(CONFLUENCE_SPACE, "create", "--key", SPACE_KEY, "--name", "E2E Test Space",
             "--json", timeout=30)
    return SPACE_KEY


@pytest.fixture
def confluence_page_factory(confluence_space):
    created = []

    def _create(title: str, content: str):
        res = _run(CONFLUENCE_PAGE, "create",
                    "--space", confluence_space, "--title", title,
                    "--content", content, "--json")
        if res.returncode == 0:
            data = json.loads(res.stdout)
            created.append(str(data["id"]))
        return res

    yield _create

    for page_id in created:
        _run(CONFLUENCE_PAGE, "delete", page_id, timeout=30)
        _run(CONFLUENCE_PAGE, "delete", page_id, "--purge", timeout=30)


def test_confluence_storage_format_renders_correctly(confluence_page_factory, confluence_session):
    """Testfall C1+C2: correct Confluence Storage Format XHTML renders as
    expected under ?expand=body.view (and body.export_view identically,
    since these macros need no session-bound resources).

    Empirically confirmed against Confluence 8.5 DC (2026-08-20): the code
    macro renders via a SyntaxHighlighter <pre> with
    ``data-syntaxhighlighter-params`` naming the language, and the info
    macro renders as a
    ``confluence-information-macro confluence-information-macro-information``
    div — exactly the pattern assumed (but flagged unverified) in the
    formatting research doc.
    """
    s, url = confluence_session
    res = confluence_page_factory("E2E fmt C1", CONFLUENCE_STORAGE_BODY)
    assert res.returncode == 0, f"create failed: {res.stdout}\n{res.stderr}"
    page_id = str(json.loads(res.stdout)["id"])

    resp = s.get(f"{url}/rest/api/content/{page_id}", params={"expand": "body.view"})
    assert resp.status_code == 200, resp.text
    html = resp.json()["body"]["view"]["value"]

    assert "<h2" in html.lower() and "Titel" in html
    assert "<strong>fett</strong>" in html
    assert "<em>kursiv</em>" in html
    assert "<li>Punkt eins</li>" in html and "<ul>" in html
    assert "<ol>" in html and "<li>a</li>" in html
    assert "<table" in html and "H1" in html and "<td" in html.lower()
    # code macro -> syntax-highlighted <pre>, language recorded somewhere
    assert "<pre" in html
    assert "python" in html
    assert "print(&quot;hi&quot;)" in html or "print(\"hi\")" in html
    # info panel -> confluence-information-macro div
    assert "confluence-information-macro" in html
    assert "Wichtiger Hinweis" in html


def test_confluence_wiki_to_storage_conversion(confluence_session):
    """Testfall C4: POST /rest/api/contentbody/convert/storage with
    representation="wiki" works on Confluence 8.5 DC — resolves "Offene
    Unsicherheit" #7 from the research doc. Confirmed 2026-08-20: HTTP 200,
    wiki markup is converted to well-formed storage XHTML.
    """
    s, url = confluence_session
    payload = {"value": "h1. Titel\n\n*fett* und _kursiv_", "representation": "wiki"}
    resp = s.post(f"{url}/rest/api/contentbody/convert/storage", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["representation"] == "storage"
    assert "<h1>Titel</h1>" in data["value"]
    assert "<strong>fett</strong>" in data["value"]
    assert "<em>kursiv</em>" in data["value"]


def test_confluence_wellformed_plaintext_storage_saves_without_structure(
        confluence_page_factory, confluence_session):
    """Testfall C3a: plain GitHub-Markdown text that happens to be
    well-formed XML (no bare ``<``/``&``) is NOT rejected — it saves
    successfully but with zero structure: the literal ``#``, ``**``, ``-``
    characters just sit there as text.

    Empirically confirmed against Confluence 8.5 DC (2026-08-20): HTTP 200,
    body.storage.value round-trips byte-for-byte.
    """
    s, url = confluence_session
    md = "# Titel\n**fett**\n- Punkt\n"
    res = confluence_page_factory("E2E fmt C3a", md)
    assert res.returncode == 0, f"expected well-formed plaintext to be accepted: {res.stderr}"
    page_id = str(json.loads(res.stdout)["id"])

    resp = s.get(f"{url}/rest/api/content/{page_id}", params={"expand": "body.view"})
    html = resp.json()["body"]["view"]["value"]
    # No structural elements were produced from the Markdown syntax.
    assert "<h1>" not in html
    assert "<strong>" not in html
    assert "<ul>" not in html
    # The special characters show up as literal text.
    assert "#" in html
    assert "**" in html


def test_confluence_malformed_xml_storage_returns_400(confluence_space):
    """Testfall C3b: Markdown/plaintext containing an unescaped '<' followed
    by non-tag content breaks XML well-formedness and Confluence rejects it
    outright with HTTP 400 "Error parsing xhtml" — no silent fallback.

    Empirically confirmed against Confluence 8.5 DC (2026-08-20).
    """
    s, url = _session("confluence")
    md = "Compare a < b & c > d\n"
    payload = {
        "type": "page",
        "title": "E2E fmt C3b (should fail)",
        "space": {"key": confluence_space},
        "body": {"storage": {"value": md, "representation": "storage"}},
    }
    resp = s.post(f"{url}/rest/api/content", json=payload)
    assert resp.status_code == 400
    assert "Error parsing xhtml" in resp.json().get("message", "")


# =============================================================================
# Bitbucket
# =============================================================================

BITBUCKET_MARKDOWN_BODY = """# PR Ueberschrift

**fett** Text

```java
System.out.println("hi");
```

| Spalte A | Spalte B |
|---|---|
| 1 | 2 |

- Punkt eins
  - Unterpunkt (2 Leerzeichen)
- Punkt zwei

- [ ] todo
- [x] done
"""


@pytest.fixture
def bitbucket_session():
    return _session("bitbucket")


def _markup_preview(session_and_url, markdown: str) -> str:
    s, url = session_and_url
    headers = dict(s.headers)
    headers["Content-Type"] = "text/plain"
    resp = s.post(f"{url}/rest/api/1.0/markup/preview",
                   data=markdown.encode("utf-8"), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["html"]


def test_bitbucket_markup_preview_body_schema(bitbucket_session):
    """Resolves "Offene Unsicherheit" #1: the markup/preview endpoint takes
    a RAW text/plain request body (the Markdown source itself), NOT a JSON
    object/string. A JSON-encoded body is treated as literal text and
    wrapped in a <p>, producing garbage. ``X-Atlassian-Token: no-check`` is
    required or the request 403s with "XSRF check failed".

    Empirically confirmed against Bitbucket 8.19 DC (2026-08-20).
    """
    html = _markup_preview(bitbucket_session, "**bold**")
    assert html.strip() == '<p><strong>bold</strong></p>'


def test_bitbucket_markdown_renders_correctly(bitbucket_session):
    """Testfall B1+B2+B4: Bitbucket DC's CommonMark dialect handles GitHub-
    style Markdown mostly correctly — the one product where LLM habits
    mostly work.

    Empirically confirmed against Bitbucket 8.19 DC (2026-08-20):
    - headings, bold, italic, strikethrough (extension) all work
    - fenced code blocks get <pre><code data-language="...">
    - pipe tables work (extension)
    - CORRECTION vs. research doc: 2-space nested list indentation DOES
      nest correctly here (contradicts the "needs 4 spaces" community
      report — not reproducible on this 8.19 instance)
    - task list syntax ``- [ ]``/``- [x]`` is NOT interpreted as checkboxes;
      the literal text "[ ] todo"/"[x] done" survives as the list item's
      text content (confirms "Offene Unsicherheit" #2: unsupported). Note:
      once any item in a list carries a nested block (our nested-list item
      does), commonmark-java renders the whole list "loose" and wraps every
      item's text in its own <p>, so the exact tag shape is
      <li>\n<p>[ ] todo</p>\n</li> rather than a bare <li>[ ] todo</li>.
    """
    html = _markup_preview(bitbucket_session, BITBUCKET_MARKDOWN_BODY)

    assert "<h1>PR Ueberschrift</h1>" in html
    assert "<strong>fett</strong>" in html
    assert "<pre><code data-language=\"java\">" in html
    assert "System.out.println" in html
    assert "<table>" in html and "<th>Spalte A</th>" in html
    # nested list: 2-space indent DOES produce a nested <ul> on 8.19 DC
    assert "<ul><li>Unterpunkt (2 Leerzeichen)</li></ul>" in html
    # task list markers are literal text, not checkboxes (list is "loose"
    # here because a sibling item has a nested list, hence the <p> wrapper)
    assert "<p>[ ] todo</p>" in html
    assert "<p>[x] done</p>" in html
    assert "<input" not in html  # no real checkbox input elements


def test_bitbucket_raw_html_is_escaped(bitbucket_session):
    """Testfall B3: raw HTML tags are never interpreted, always escaped to
    entities — confirms the "no XSS" documented behaviour.

    Empirically confirmed against Bitbucket 8.19 DC (2026-08-20).
    """
    html = _markup_preview(bitbucket_session, "<b>fett</b>\n")
    assert "&lt;b&gt;fett&lt;/b&gt;" in html
    assert "<b>fett</b>" not in html


@pytest.fixture
def bitbucket_pr_repo():
    """Create a throwaway repo with two branches (main, feature-1) that
    differ in README.md content, using the documented file-write trick:
    PUT .../browse/{path} with a multipart form (no local git needed).
    Yields (slug,); deletes the repo afterwards.
    """
    repo_name = "e2e-fmt-test"
    created = _run(BITBUCKET_REPO, "create", "--project", PROJECT_KEY,
                   "--name", repo_name, "--json", timeout=30)
    if created.returncode != 0:
        pytest.skip(f"could not create bitbucket repo: {created.stderr}")
    slug = json.loads(created.stdout)["slug"]

    inst = _instance("bitbucket")
    base = inst["url"].rstrip("/")
    headers = {"Authorization": f"Bearer {inst['token']}", "X-Atlassian-Token": "no-check"}

    def put_file(path, content, message, branch, source_branch=None, source_commit_id=None):
        form = {"content": content, "message": message, "branch": branch}
        if source_branch:
            form["sourceBranch"] = source_branch
        if source_commit_id:
            form["sourceCommitId"] = source_commit_id
        files = {k: (None, v) for k, v in form.items()}
        return requests.put(
            f"{base}/rest/api/1.0/projects/{PROJECT_KEY}/repos/{slug}/browse/{path}",
            files=files, headers=headers, verify=inst.get("ssl_verify", True),
        )

    r1 = put_file("README.md", "hello\n", "init", "main")
    assert r1.status_code == 200, r1.text
    main_commit = r1.json()["id"]

    r2 = put_file("README.md", "hello world\n", "feature change", "feature-1",
                   source_branch="main", source_commit_id=main_commit)
    assert r2.status_code == 200, r2.text

    yield slug

    _run(BITBUCKET_REPO, "delete", "--project", PROJECT_KEY, "--repo", slug, timeout=30)


def test_bitbucket_pr_markdown_description_round_trips(bitbucket_pr_repo):
    """Testfall B1 (PR variant): a PR created via bitbucket_pr.py with a
    Markdown description stores that description verbatim (Bitbucket does
    not pre-render/mutate stored PR descriptions — rendering happens at
    display time), matching what markup/preview would produce. Bitbucket
    trims exactly one trailing newline from the stored description.
    """
    slug = bitbucket_pr_repo
    created = _run_ok(
        BITBUCKET_PR, "create",
        "--project", PROJECT_KEY, "--repo", slug,
        "--title", "E2E fmt PR",
        "--from-branch", "feature-1", "--to-branch", "main",
        "--description", BITBUCKET_MARKDOWN_BODY,
        "--json",
    )
    pr_id = created["id"]

    got = _run_ok(BITBUCKET_PR, "get", "--project", PROJECT_KEY, "--repo", slug,
                   "--id", str(pr_id), "--json")
    assert got["description"] == BITBUCKET_MARKDOWN_BODY.rstrip("\n")

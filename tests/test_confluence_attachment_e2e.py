"""End-to-end test for Confluence attachment upload + download.

Unlike the rest of the suite (which runs offline against argparse/dry-run),
this test drives the real skill scripts against a LIVE Confluence Data Center
— the docker-compose stack in ``docker/`` configured via the user's normal
``instances.json``.

It is skipped automatically when no Confluence is reachable, so a plain
``pytest`` run on a machine without the stack stays green. To run it
explicitly bring the stack up first:

    docker compose -f docker/docker-compose.yml up -d confluence
    pytest tests/test_confluence_attachment_e2e.py -v

The flow proves the download command round-trips bytes faithfully:
create page -> upload random binary -> download -> assert identical -> cleanup.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFLUENCE_SCRIPTS = REPO_ROOT / "skills" / "confluence-dc" / "scripts"

PAGE = CONFLUENCE_SCRIPTS / "core" / "confluence_page.py"
SPACE = CONFLUENCE_SCRIPTS / "core" / "confluence_space.py"
ATTACH = CONFLUENCE_SCRIPTS / "workflow" / "confluence_attachment.py"

# Space used for the test. The docker demo data ships a "TST" space; if it is
# missing we create it on the fly.
SPACE_KEY = os.environ.get("ATLASSIAN_E2E_SPACE", "TST")


def _run(script: Path, *args, timeout: int = 60):
    """Run a skill script against the developer's real instances.json."""
    return subprocess.run(
        [sys.executable, str(script), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=os.environ.copy(),
        timeout=timeout,
    )


def _run_ok(script: Path, *args, **kw) -> dict:
    """Run a script expecting --json output and exit 0; return parsed JSON."""
    res = _run(script, *args, **kw)
    assert res.returncode == 0, (
        f"{script.name} {' '.join(args)} failed "
        f"(exit {res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    return json.loads(res.stdout) if res.stdout.strip() else {}


def _confluence_reachable() -> bool:
    """Best-effort: can we list spaces with the configured instance?"""
    try:
        res = _run(SPACE, "list", "--json", timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return res.returncode == 0


pytestmark = pytest.mark.skipif(
    not _confluence_reachable(),
    reason="no live Confluence reachable via instances.json (start docker stack to run)",
)


@pytest.fixture
def test_space() -> str:
    """Ensure SPACE_KEY exists; create it if the instance lacks it."""
    res = _run(SPACE, "get", SPACE_KEY, "--json", timeout=20)
    if res.returncode != 0:
        _run(SPACE, "create", "--key", SPACE_KEY, "--name", "E2E Test Space",
             "--json", timeout=30)
    return SPACE_KEY


@pytest.fixture
def test_page(test_space):
    """Create a throwaway page; trash + purge it afterwards."""
    created = _run_ok(
        PAGE, "create",
        "--space", test_space,
        "--title", "E2E Attachment Download Test",
        "--content", "<p>created by test_confluence_attachment_e2e</p>",
        "--json",
    )
    page_id = str(created["id"])
    yield page_id
    # Cleanup is best-effort; a failed test should still try to purge.
    _run(PAGE, "delete", page_id, timeout=30)
    _run(PAGE, "delete", page_id, "--purge", timeout=30)


def test_upload_then_download_roundtrip(test_page, tmp_path):
    page_id = test_page

    # A binary payload with non-text bytes, so a faulty text-mode download
    # (encoding mangling, newline translation) would corrupt it visibly.
    payload = bytes(range(256)) * 64 + b"\x00\xff\x00\xff"
    src = tmp_path / "payload.bin"
    src.write_bytes(payload)

    # Upload.
    added = _run_ok(ATTACH, "add", page_id, "--file", str(src), "--json")
    att = added["results"][0]
    att_id = str(att["id"])
    assert att["title"] == "payload.bin"

    # Download to an explicit path.
    dest = tmp_path / "roundtrip.bin"
    out = _run_ok(ATTACH, "download", att_id, "--output", str(dest), "--json")
    assert out["bytes"] == len(payload)
    assert dest.read_bytes() == payload, "downloaded bytes differ from upload"

    # Overwrite is refused without --force.
    refused = _run(ATTACH, "download", att_id, "--output", str(dest))
    assert refused.returncode == 5
    assert "force" in refused.stderr.lower()

    # ...and succeeds with --force.
    forced = _run(ATTACH, "download", att_id, "--output", str(dest), "--force")
    assert forced.returncode == 0
    assert dest.read_bytes() == payload

    # Directory destination keeps the original filename.
    out_dir = tmp_path / "into_dir"
    out_dir.mkdir()
    _run_ok(ATTACH, "download", att_id, "--output", str(out_dir), "--json")
    assert (out_dir / "payload.bin").read_bytes() == payload


def test_download_unknown_attachment_errors(tmp_path):
    res = _run(ATTACH, "download", "0", "--output", str(tmp_path / "x.bin"))
    assert res.returncode != 0
    assert res.stderr.strip()

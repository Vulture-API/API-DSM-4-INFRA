"""Fail closed if mandatory QA scenarios were skipped or did not run."""

import xml.etree.ElementTree as ET
from pathlib import Path

root = ET.parse(Path("reports/telemetry.xml")).getroot()
cases = list(root.iter("testcase"))
assert len(cases) >= 40
assert not list(root.iter("skipped")), "Required acceptance scenarios were skipped"
assert not list(root.iter("failure")) and not list(root.iter("error"))
for name in [
    "receiver_independent",
    "redis_outage",
    "mixed_fields",
    "sigkill",
    "commit_before_xack",
    "quarantine_failure",
    "replay_dry_run",
    "missing_content",
    "retention_protects",
    "cutover_pause_and_resume",
    "receiver_image_excludes_postgres",
]:
    assert any(name in case.attrib["name"] for case in cases), f"Missing {name}"
print(f"{len(cases)} required integration cases passed without skips")

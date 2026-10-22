#!/usr/bin/env python3
"""Collect sanitized disposable-project evidence before cleanup."""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
project = os.environ["COMPOSE_PROJECT_NAME"]
assert project.startswith("vulture-qa-"), "Evidence scope must be disposable"
output = ROOT / "reports"
output.mkdir(exist_ok=True)


def scrub(text):
    text = re.sub(
        r"(postgres(?:ql)?|rediss?)://([^\s/@]+):([^\s/@]+)@", r"\1://\2:***@", text
    )
    return text.replace("PAYLOAD_SECRET", "[redacted]")


def capture(name, args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    (output / name).write_text(scrub(result.stdout + "\n" + result.stderr))


capture("gitlinks.txt", ["git", "submodule", "status"])
capture("versions.txt", ["docker", "version"])
capture("infra-revision.txt", ["git", "rev-parse", "HEAD"])
capture("compose-version.txt", ["docker", "compose", "version"])
ids = subprocess.check_output(
    ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
    text=True,
).split()
manifest = []
for cid in ids:
    record = json.loads(subprocess.check_output(["docker", "inspect", cid]))[0]
    manifest.append(
        dict(
            id=cid,
            image=record["Image"],
            service=record["Config"]["Labels"].get("com.docker.compose.service"),
            running=record["State"]["Running"],
            mounts=[
                dict(name=m.get("Name"), destination=m["Destination"])
                for m in record["Mounts"]
            ],
        )
    )
    capture(f"container-{cid[:12]}.log", ["docker", "logs", "--tail", "200", cid])
(output / "inventory.json").write_text(json.dumps(manifest, indent=2) + "\n")

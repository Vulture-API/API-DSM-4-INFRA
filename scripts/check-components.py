#!/usr/bin/env python3
"""Run pinned upstream suites with isolated dependencies; no external database."""

import os
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
project = os.getenv(
    "COMPONENT_PROJECT_NAME", f"vulture-qa-components-{uuid.uuid4().hex[:10]}"
)
if not project.startswith("vulture-qa-"):
    raise SystemExit("Disposable project prefix required")
compose = [
    "docker",
    "compose",
    "--env-file",
    os.devnull,
    "-p",
    project,
    "-f",
    str(ROOT / "qa/docker-compose.components.yml"),
]
reports = ROOT / "reports/components"
reports.mkdir(parents=True, exist_ok=True)


def run(*args, **kwargs):
    subprocess.run(list(args), check=True, cwd=ROOT, **kwargs)


def xml_gate(path, minimum=1, required=()):
    root = ET.parse(path).getroot()
    assert len(list(root.iter("testcase"))) >= minimum, (
        "Missing required component cases"
    )
    assert not list(root.iter("skipped")), "Required component tests were skipped"
    assert not list(root.iter("failure")) and not list(root.iter("error"))
    for name in required:
        assert any(name in case.attrib["name"] for case in root.iter("testcase")), (
            f"Missing required component case {name}"
        )


try:
    run(*compose, "up", "-d", "--build", "--wait", "--wait-timeout", "180")
    for database in ["treatment", "banco"]:
        run(*compose, "exec", "-T", "postgres", "createdb", "-U", "postgres", database)
    for repository, database, minimum in [
        ("RECEPCAO-DADOS", "receiver", 1),
        ("PERSISTENCIA-DADOS", "treatment", 223),
    ]:
        service = ROOT / "services" / f"API-DSM-4-{repository}"
        image = f"{project}-{database}-verify"
        run(
            "docker",
            "build",
            "-t",
            image,
            "-f",
            str(ROOT / "qa/Dockerfile.python"),
            str(service),
        )
        output = reports / database
        output.mkdir(exist_ok=True)
        database_args = []
        required = ()
        isolation_check = ""
        if repository == "PERSISTENCIA-DADOS":
            database_args = [
                "-e",
                f"TEST_DATABASE_URL=postgresql://postgres:postgres@postgres:5432/{database}",
                "-e",
                "BANCO_SCHEMA_DIR=/contracts",
                "-v",
                f"{ROOT}/services/API-DSM-4-BANCO:/contracts:ro",
            ]
        else:
            required = (
                "test_main_runs_ingest_by_default",
                "test_main_runs_explicit_ingest",
                "test_main_rejects_removed_persist_before_configuration",
                "test_real_mqtt_to_redis_round_trip",
                "test_ack_follows_successful_xadd_and_retry",
                "test_cancelled_write_does_not_ack",
                "test_bounded_queue_applies_backpressure",
                "test_real_retention_never_removes_pending_or_undelivered",
                "test_shutdown_keeps_writer_alive_until_admission_stops",
            )
            isolation_check = "python -c \"import importlib.util; assert importlib.util.find_spec('asyncpg') is None; assert importlib.util.find_spec('station_ingest.persistence') is None\"; "
        run(
            "docker",
            "run",
            "--rm",
            "--network",
            f"{project}_default",
            "-e",
            "RUN_INTEGRATION=1",
            "-e",
            "TEST_MQTT_HOST=mosquitto",
            "-e",
            "TEST_MQTT_PORT=1883",
            "-e",
            "TEST_REDIS_URL=redis://redis:6379/15",
            *database_args,
            "-v",
            f"{output}:/reports",
            image,
            "sh",
            "-ec",
            isolation_check
            + "ruff check .; ruff format --check .; pytest --cov --cov-fail-under=80 --cov-report=xml:/reports/coverage.xml --junitxml=/reports/junit.xml; python -m build --outdir /reports/dist",
        )
        xml_gate(output / "junit.xml", minimum, required)
        if repository == "RECEPCAO-DADOS":
            cases = ET.parse(output / "junit.xml").getroot().iter("testcase")
            assert (
                sum(
                    "test_killed_receiver_redelivers_unacked_message"
                    in case.attrib["name"]
                    for case in cases
                )
                == 2
            )
    banco = ROOT / "services/API-DSM-4-BANCO"
    # Node suite uses versioned fixtures. Each run copies into an ephemeral container.
    command = """cp -a /contract /tmp/banco; cd /tmp/banco; npm ci --no-audit --no-fund; node setup/apply.mjs; node setup/apply.mjs; node --test --test-reporter=tap > /reports/banco.tap; cat /reports/banco.tap; grep -Eq '^# skipped 0$' /reports/banco.tap"""
    run(
        "docker",
        "run",
        "--rm",
        "--network",
        f"{project}_default",
        "-e",
        "DATABASE_URL=postgresql://postgres:postgres@postgres:5432/banco",
        "-e",
        "TEST_DATABASE_URL=postgresql://postgres:postgres@postgres:5432/banco",
        "-v",
        f"{banco}:/contract:ro",
        "-v",
        f"{reports}:/reports",
        "node:24",
        "sh",
        "-ec",
        command,
    )
    # Match BANCO CI partitioning/migration order on the same real database.
    sql = """set -e
cp -a /contract /tmp/banco-check
cd /tmp/banco-check
ROWS=100000 bash benchmark/run.sh postgresql://postgres:postgres@localhost:5432/banco
for migration in 013_restore_column_defaults 016_sensor_limits_and_reading_precision 017_telemetry_destinations_and_idempotency 018_telemetry_recovery_and_replay; do
 for repeat in 1 2; do psql postgresql://postgres:postgres@localhost:5432/banco -q -v ON_ERROR_STOP=1 -f migrations/$migration.sql; done
done
psql postgresql://postgres:postgres@localhost:5432/banco -v ON_ERROR_STOP=1 -c "DO \\$\\$ BEGIN IF assert_readings_default_empty() <> 0 THEN RAISE EXCEPTION 'DEFAULT partition is not empty'; END IF; END \\$\\$;"
"""
    run(
        *compose,
        "exec",
        "-T",
        "-e",
        "PGPASSWORD=postgres",
        "postgres",
        "bash",
        "-ec",
        sql,
    )
finally:
    subprocess.run(
        compose + ["logs", "--no-color", "--tail", "100"],
        stdout=(reports / "dependencies.log").open("w"),
        stderr=subprocess.STDOUT,
    )
    run(*compose, "down", "-v")

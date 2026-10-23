"""SCRUM-453 acceptance: real MQTT/Redis/PostgreSQL, no service imports."""

import json
import os
import subprocess
import time
import uuid
from decimal import Decimal
from urllib.request import urlopen

import psycopg
import pytest
from conftest import eventually


def test_receiver_independent_pg_outage_then_backlog(s):
    s.op.compose("stop", "postgres")
    try:
        entry = s.publish({"temp": 12, "humidity": 30})
        assert len(s.r.xrange(s.stream)) == 1
        env = json.loads(subprocess.check_output(["docker", "inspect", s.receiver]))[0][
            "Config"
        ]["Env"]
        assert not any("DATABASE" in item for item in env)
    finally:
        s.op.compose("up", "-d", "--wait", "postgres")
        s.db.close()
        s.db = psycopg.connect(
            host="127.0.0.1",
            port=int(os.getenv("TEST_POSTGRES_PORT", "5433")),
            dbname="agritech_test",
            user="postgres",
            password="postgres",
            autocommit=True,
        )
    s.worker()
    s.settled(entry)
    assert s.count("readings") == 2


def test_redis_outage_retries_with_broker_alive(s):
    s.op.compose("stop", "redis")
    try:
        s.publish_raw(json.dumps({"estacao_id": str(s.station), "temp": 17}))
        eventually(lambda: "redis_batch_failed" in s.logs(s.receiver))
    finally:
        s.op.compose("up", "-d", "--wait", "redis")
    eventually(lambda: s.r.xlen(s.stream) == 1)
    s.worker()
    entry = s.r.xrange(s.stream)[0][0]
    s.settled(entry)
    assert s.count("readings") == 1


@pytest.mark.parametrize(
    "raw", ["{broken", "[]", "{}", '{"estacao_id":1}', '{"estacao_id":""}']
)
def test_definitive_envelope_rejection(s, raw):
    s.publish_raw(raw)
    eventually(lambda: "mqtt_message_discarded" in s.logs(s.receiver))
    assert s.r.xlen(s.stream) == 0


def test_oversize_envelope(s):
    s.publish_raw(json.dumps({"estacao_id": str(s.station), "temp": "x" * 262144}))
    eventually(lambda: "mqtt_message_discarded" in s.logs(s.receiver))
    assert s.r.xlen(s.stream) == 0


def test_mixed_fields_relations_precision_occurrence_and_query(s):
    timestamp = int(time.time())
    raw = f'{{"estacao_id":"{s.station}","unix_time":{timestamp},"TEMP":50.000000000000001,"humidity":23.456789012345678901,"firmware":{{"secret":"PAYLOAD_SECRET"}},"other_only":1}}'
    entry = s.publish_json(raw)
    s.worker()
    s.settled(entry)
    rows = s.db.execute(
        "SELECT sensor_id,value,data_consistent FROM readings WHERE sensor_id=ANY(%s) ORDER BY sensor_id",
        ([s.temp, s.humidity],),
    ).fetchall()
    assert rows == [
        (s.temp, Decimal("50.000000000000001"), False),
        (s.humidity, Decimal("23.456789012345678901"), True),
    ]
    assert s.count("occurrences") == 1
    assert s.count("telemetry_quarantine") == 2
    assert s.scalar("SELECT count(*) FROM readings WHERE sensor_id=%s", (s.alien,)) == 0
    assert s.scalar(
        "SELECT value FROM occurrences WHERE sensor_id=%s", (s.temp,)
    ) == Decimal("50.000000000000001")
    original = s.scalar(
        "SELECT original_fields FROM telemetry_events WHERE stream=%s", (s.stream,)
    )
    assert json.loads(bytes(original))["payload"] == raw
    s.publish_json(f'{{"estacao_id":"{s.other}","unix_time":1760000000,"temp":22}}')
    eventually(
        lambda: (
            s.scalar(
                "SELECT count(*) FROM readings WHERE sensor_id=%s", (s.other_temp,)
            )
            == 1
        )
    )
    url = (
        os.getenv("BACKEND_URL", "http://localhost:3000")
        + f"/api/stations/{s.station}/readings/series?hours=24"
    )
    with urlopen(url) as response:
        body = json.load(response)
    assert len(body["series"]) == 1
    points = body["series"][0]["points"]
    assert len(points) == 1
    assert (
        points[0]["min"] == points[0]["max"] == float(Decimal("23.456789012345678901"))
    )
    assert "PAYLOAD_SECRET" not in s.logs(s.receiver)
    for name in s.containers[1:]:
        assert "PAYLOAD_SECRET" not in s.logs(name)


@pytest.mark.parametrize("timestamp", [None, True, "1760000000", -1, 1e99])
def test_invalid_timestamp_quarantines_all_fields(s, timestamp):
    entry = s.publish({"temp": 10, "humidity": 20}, timestamp)
    s.worker()
    s.settled(entry)
    assert s.count("readings") == 0
    assert s.count("telemetry_quarantine") >= 1


def test_missing_timestamp_uses_original_received_at(s):
    entry = s.publish({"temp": 10}, ...)
    fields = s.r.xrange(s.stream)[0][1]
    s.worker()
    s.settled(entry)
    assert (
        s.scalar("SELECT unix_time FROM readings WHERE sensor_id=%s", (s.temp,))
        == int(fields["received_at"]) // 1000
    )


def test_explicit_legacy_cutoff_and_new_null(s):
    legacy = s.publish({"temp": 10}, None)
    s.worker(PERSIST_LEGACY_MAX_ID=legacy)
    s.settled(legacy)
    current = s.publish({"temp": 20}, None)
    s.settled(current)
    assert s.count("readings") == 1
    assert (
        s.scalar(
            "SELECT timestamp_source FROM telemetry_events WHERE stream=%s AND entry_id=%s",
            (s.stream, legacy),
        )
        == "legacy_received_at"
    )
    assert s.count("telemetry_quarantine") == 1


@pytest.mark.parametrize(
    "values",
    [
        {"temp": True},
        {"temp": "10"},
        {"temp": None},
        {"temp": []},
        {"temp": {}},
        {"missing": 5},
    ],
)
def test_invalid_values_and_unknown_sensors_preserve_valid_neighbor(s, values):
    entry = s.publish(values | {"humidity": 12})
    s.worker()
    s.settled(entry)
    assert s.count("readings") == 1
    assert s.count("telemetry_quarantine") == 1


def test_unknown_station_rejection(s):
    entry = s.publish_json('{"estacao_id":"2147483647","temp":12}')
    s.worker()
    s.settled(entry)
    assert s.count("readings") == 0
    assert s.count("telemetry_quarantine") == 1


def test_limits_inclusive_and_extreme_decimal_sql(s):
    s.worker()
    for timestamp, value in [
        (1760000000, "0"),
        (1760000001, "50"),
        (1760000002, "1e309"),
    ]:
        entry = s.publish_json(
            f'{{"estacao_id":"{s.station}","unix_time":{timestamp},"temp":{value}}}'
        )
        s.settled(entry)
    assert (
        s.scalar(
            "SELECT count(*) FROM readings WHERE sensor_id=%s AND data_consistent",
            (s.temp,),
        )
        == 2
    )
    assert s.scalar(
        "SELECT value FROM readings WHERE sensor_id=%s AND unix_time=1760000002",
        (s.temp,),
    ) == Decimal("1e309")
    assert s.scalar(
        "SELECT value FROM occurrences WHERE sensor_id=%s", (s.temp,)
    ) == Decimal("1e309")


def test_duplicates_conflicts_concurrent_consumers(s):
    s.worker(PERSIST_CONSUMER="concurrent-a")
    s.worker(PERSIST_CONSUMER="concurrent-b")
    ids = [s.publish({"temp": value}) for value in [60, 60, 61, 60]]
    for entry in ids:
        s.settled(entry)
    assert s.count("readings") == 1
    assert s.count("occurrences") == 1
    assert s.count("telemetry_quarantine") == 1
    assert s.count("telemetry_events") == 4
    assert (
        s.scalar(
            "SELECT count(*) FROM telemetry_results WHERE event_id IN (SELECT id FROM telemetry_events WHERE stream=%s) AND destination='duplicate'",
            (s.stream,),
        )
        == 2
    )


def test_sigkill_before_commit_and_other_identity_recovers(s):
    blocker = psycopg.connect(
        host="127.0.0.1",
        port=int(os.getenv("TEST_POSTGRES_PORT", "5433")),
        dbname="agritech_test",
        user="postgres",
        password="postgres",
    )
    try:
        blocker.execute("LOCK readings IN ACCESS EXCLUSIVE MODE")
        entry = s.publish({"temp": 14})
        worker = s.worker(PERSIST_CONSUMER="before-commit")
        eventually(
            lambda: (
                s.scalar(
                    "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE 'INSERT INTO readings%'"
                )
                > 0
            )
        )
        s.stop(worker, kill=True)
        assert s.count("telemetry_events") == 0
        assert s.r.xpending(s.stream, s.group)["pending"] == 1
    finally:
        blocker.rollback()
        blocker.close()
    s.worker(PERSIST_CONSUMER="recovery-after-kill")
    s.settled(entry)
    assert s.count("readings") == 1


def test_commit_before_xack_acl_failure_and_recovery(s):
    user = f"qa-{s.uid}"
    s.r.execute_command(
        "ACL", "SETUSER", user, "on", ">qa-password", "~*", "+@all", "-xack"
    )
    try:
        entry = s.publish({"temp": 60})
        worker = s.worker(
            PERSIST_CONSUMER="no-ack",
            PERSIST_REDIS_URL=f"redis://{user}:qa-password@redis:6379/0",
        )
        eventually(lambda: s.completed(entry))
        eventually(lambda: s.r.xpending(s.stream, s.group)["pending"] == 1)
        assert s.count("readings") == s.count("occurrences") == 1
        s.stop(worker, kill=True)
        s.worker(PERSIST_CONSUMER="after-ack-failure")
        s.settled(entry)
        assert s.count("readings") == s.count("occurrences") == 1
        assert s.count("telemetry_events") == 1
    finally:
        s.r.execute_command("ACL", "DELUSER", user)


def test_quarantine_failure_rolls_back_then_recovers(s):
    function = f"qa_fail_{s.uid}"
    s.db.execute(
        f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'qa technical failure'; END $$"
    )
    s.db.execute(
        f"CREATE TRIGGER {function} BEFORE INSERT ON telemetry_quarantine FOR EACH ROW EXECUTE FUNCTION {function}()"
    )
    try:
        entry = s.publish({"temp": 60, "missing": 1})
        worker = s.worker(PERSIST_CONSUMER="quarantine-fault")
        eventually(lambda: "RaiseError" in s.logs(worker))
        assert (
            s.count("readings")
            == s.count("occurrences")
            == s.count("telemetry_events")
            == 0
        )
        assert s.r.xpending(s.stream, s.group)["pending"] == 1
        s.stop(worker)
    finally:
        s.db.execute(f"DROP TRIGGER {function} ON telemetry_quarantine")
        s.db.execute(f"DROP FUNCTION {function}()")
    s.worker(PERSIST_CONSUMER="quarantine-recovered")
    s.settled(entry)
    assert (
        s.count("readings")
        == s.count("telemetry_quarantine")
        == s.count("occurrences")
        == 1
    )


def test_replay_dry_run_and_idempotent_uuid_preserve_accepted(s):
    entry = s.publish({"temp": 20, "future_sensor": 12})
    s.worker()
    s.settled(entry)
    qid = s.scalar(
        "SELECT id FROM telemetry_quarantine WHERE event_id IN (SELECT id FROM telemetry_events WHERE stream=%s)",
        (s.stream,),
    )
    request = str(uuid.uuid4())
    command = [
        "quarantine",
        "replay",
        "--id",
        str(qid),
        "--request-id",
        request,
        "--operator",
        "qa",
        "--reason",
        "cadastro corrigido no ensaio",
    ]
    original = s.scalar(
        "SELECT original_fields FROM telemetry_events WHERE stream=%s", (s.stream,)
    )
    new_sensor = s.sensor("future_sensor")
    assert s.operation(*command, "--dry-run")["status"] == "DRY_RUN"
    assert (
        s.scalar(
            "SELECT count(*) FROM telemetry_replay_requests WHERE request_id=%s",
            (request,),
        )
        == 0
    )
    first = s.operation(*command)
    second = s.operation(*command)
    assert first == second
    assert first["status"] == "SUCCEEDED"
    assert s.scalar("SELECT count(*) FROM readings WHERE sensor_id=%s", (s.temp,)) == 1
    assert (
        s.scalar("SELECT value FROM readings WHERE sensor_id=%s", (new_sensor,)) == 12
    )
    assert (
        s.scalar(
            "SELECT original_fields FROM telemetry_events WHERE stream=%s", (s.stream,)
        )
        == original
    )
    assert (
        s.scalar(
            "SELECT count(*) FROM telemetry_replay_attempts WHERE request_id=%s",
            (request,),
        )
        == 1
    )


def test_missing_content_records_incident_without_ack(s):
    entry = s.publish({"temp": 20})
    s.r.xgroup_create(s.stream, s.group, id="0-0")
    s.r.xreadgroup(s.group, "abandoned", {s.stream: ">"}, count=1)
    s.r.xdel(
        s.stream, entry
    )  # Deliberate corruption fixture; never an operational recovery.
    s.worker()
    eventually(
        lambda: (
            s.scalar(
                "SELECT count(*) FROM telemetry_recovery_incidents WHERE stream=%s",
                (s.stream,),
            )
            == 1
        )
    )
    assert s.r.xpending(s.stream, s.group)["pending"] == 1
    assert s.count("telemetry_events") == 0


def test_inspection_modes_do_not_write_or_create_groups(s):
    s.publish({"temp": 20})
    for flag in [[], ["--resolve"], ["--validate"]]:
        name = s.start("persistencia", ["inspect", *flag], PERSIST_STREAM=s.stream)
        eventually(lambda name=name: "stream_entry_observed" in s.logs(name))
        s.stop(name)
    assert s.r.xinfo_groups(s.stream) == []
    assert s.count("telemetry_events") == s.count("readings") == 0


@pytest.mark.parametrize("mode", ["pending", "undelivered", "missing-required"])
def test_retention_protects_old_pending_and_all_groups(s, mode):
    s.stop(s.receiver)
    oldest = int(time.time() * 1000) - 3 * 86400000
    fields = dict(
        estacao_id=str(s.station),
        unix_time="1760000000",
        received_at=str(oldest),
        topic="estacoes/qa/dados",
        payload="{}",
    )
    ids = [s.r.xadd(s.stream, fields, id=f"{oldest + i}-0") for i in range(250)]
    s.r.xgroup_create(s.stream, s.group, id="0-0")
    if mode == "pending":
        s.r.xreadgroup(s.group, "abandoned", {s.stream: ">"}, count=200)
        s.r.xgroup_create(s.stream, "other-group", id=ids[-1])
    else:
        s.r.xgroup_create(s.stream, "other-group", id="0-0")
    required = [s.group, "other-group"]
    if mode == "missing-required":
        required += ["required-but-absent"]
    receiver = s.start_receiver(
        INGEST_RETENTION_ENABLED="true",
        INGEST_RETENTION_DAYS="1",
        INGEST_RETENTION_INTERVAL_SECONDS=".2",
        INGEST_RETENTION_REQUIRED_GROUPS=json.dumps(required),
    )
    eventually(lambda: "redis_retention_status" in s.logs(receiver))
    assert s.r.xlen(s.stream) == len(ids)
    assert s.r.xrange(s.stream, ids[0], ids[0])
    assert s.r.xrange(s.stream, ids[-1], ids[-1])
    if mode == "pending":
        assert s.r.xpending(s.stream, s.group)["pending"] == 200
    if mode == "missing-required":
        assert "required_group_missing" in s.logs(receiver)


def test_cutover_pause_and_resume_preserve_history(s):
    from telemetry import lock

    overrides = dict(
        TELEMETRY_STREAM=s.stream,
        PERSIST_RECOVERY_INTERVAL_SECONDS=".2",
        PERSIST_RECOVERY_MIN_IDLE_MS="7000",
        PERSIST_LEASE_REFRESH_SECONDS="1",
        PERSIST_LEASE_TTL_SECONDS="7",
        PERSIST_PROCESSING_TIMEOUT_SECONDS="5",
    )
    previous = {key: s.op.env.get(key) for key in overrides}
    s.op.env.update(overrides)
    volume_before = [
        (m["Name"], m["Destination"])
        for c in s.op.containers()
        for m in c["Mounts"]
        if c["Config"]["Labels"].get("com.docker.compose.service") == "redis"
    ]
    try:
        with lock(s.op.project):
            initial = s.publish({"temp": 12})
            activated = s.op.activate()
            s.settled(initial)
            assert not activated["after"]["degraded"]
            assert activated["after"]["pending"] == 0
            last_delivered = s.r.xinfo_groups(s.stream)[0]["last-delivered-id"]
            s.op.pause()
            assert s.op.writers() == []
            assert s.r.xinfo_groups(s.stream)[0]["last-delivered-id"] == last_delivered
            assert not s.r.xpending(s.stream, s.group)["pending"]
            # Receive while processing is paused, then preserve pending work too.
            backlog = s.publish({"temp": 13}, 1760000001)
            s.r.xreadgroup(s.group, "paused-worker", {s.stream: ">"}, count=1)
            assert s.r.xpending(s.stream, s.group)["pending"] == 1
            undelivered = s.publish({"temp": 14}, 1760000002)
            assert s.count("readings") == 1
            s.op.activate()
            s.settled(backlog)
            s.settled(undelivered)
            assert [name for name, _ in s.op.writers()] == ["persistencia"]
            assert s.count("readings") == 3
            assert s.count("telemetry_events") == 3
            assert s.r.xinfo_groups(s.stream)[0]["name"] == s.group
            volume_after = [
                (m["Name"], m["Destination"])
                for c in s.op.containers()
                for m in c["Mounts"]
                if c["Config"]["Labels"].get("com.docker.compose.service") == "redis"
            ]
            assert volume_after == volume_before
            assert s.r.xlen(s.stream) == 3
            s.op.pause()
    finally:
        for key, value in previous.items():
            if value is None:
                s.op.env.pop(key, None)
            else:
                s.op.env[key] = value


def test_receiver_image_excludes_postgres_and_removed_mode(runtime):
    program = (
        "import importlib.util; "
        "assert importlib.util.find_spec('asyncpg') is None; "
        "assert importlib.util.find_spec('station_ingest.persistence') is None"
    )
    runtime.compose(
        "run", "--rm", "--no-deps", "--entrypoint", "python", "recepcao", "-c", program
    )
    result = subprocess.run(
        runtime.args + ["run", "--rm", "--no-deps", "recepcao", "persist"],
        env=runtime.env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "station-persist consume" in result.stdout + result.stderr


@pytest.mark.parametrize("style", ["colon", "hyphen", "compact"])
def test_mac_identification(s, style):
    mac = s.mac.lower()
    if style == "hyphen":
        mac = mac.replace(":", "-")
    if style == "compact":
        mac = mac.replace(":", "")
    entry = s.publish_json(
        json.dumps(dict(estacao_id=mac, unix_time=1760000000, temp=21))
    )
    s.worker()
    s.settled(entry)
    assert s.count("readings") == 1
    assert (
        s.scalar("SELECT station_id FROM telemetry_events WHERE stream=%s", (s.stream,))
        == s.station
    )


def test_production_images_non_root_and_separate_configuration(runtime):
    for service in ["recepcao", "persistencia"]:
        uid = runtime.compose(
            "run", "--rm", "--no-deps", "--entrypoint", "id", service, "-u"
        )
        assert int(uid.splitlines()[-1]) > 0
    config = json.loads(runtime.compose("config", "--format", "json"))["services"]
    assert config["recepcao"]["build"] != config["persistencia"]["build"]
    assert not any("DATABASE" in key for key in config["recepcao"]["environment"])
    assert config["recepcao"]["depends_on"].keys() == {"redis", "mosquitto"}
    assert (
        "recepcao-persist"
        not in json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    os.devnull,
                    "-f",
                    "docker-compose.yml",
                    "config",
                    "--format",
                    "json",
                ],
                env=runtime.env,
            )
        )["services"]
    )

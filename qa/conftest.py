"""Black-box helpers. All faults/fixtures are confined to vulture-qa-* projects."""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
import psycopg
import pytest
import redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from telemetry import Operation  # noqa: E402


def eventually(check, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Public outcome not observed before deadline")


@pytest.fixture(scope="session")
def runtime():
    project = os.environ["COMPOSE_PROJECT_NAME"]
    assert project.startswith("vulture-qa-"), "Refusing faults outside disposable QA"
    op = Operation(project, True)
    op.compose("stop", "persistencia", "recepcao")
    yield op


class Scenario:
    def __init__(self, op):
        self.op = op
        self.uid = uuid.uuid4().hex[:12]
        self.stream = f"qa:{self.uid}"
        self.group = "postgres-persister"
        self.source = op.env["PERSIST_SOURCE_ID"]
        self.containers = []
        self.r = redis.Redis(
            host="127.0.0.1",
            port=int(os.getenv("TEST_REDIS_PORT", "26379")),
            decode_responses=True,
        )
        self.db = psycopg.connect(
            host="127.0.0.1",
            port=int(os.getenv("TEST_POSTGRES_PORT", "5433")),
            dbname="agritech_test",
            user="postgres",
            password="postgres",
            autocommit=True,
        )
        self.mac = "FA:" + ":".join(
            self.uid[i : i + 2].upper() for i in range(0, 10, 2)
        )
        self.station = self.scalar(
            "INSERT INTO stations(property_id,mac_address,name) SELECT min(id),%s,%s FROM properties RETURNING id",
            (self.mac, f"QA {self.uid}"),
        )
        self.other = self.scalar(
            "INSERT INTO stations(property_id,mac_address,name) SELECT min(id),%s,%s FROM properties RETURNING id",
            ("FB" + self.mac[2:], f"Other {self.uid}"),
        )
        self.temp = self.sensor("temp", self.station, 0, 50)
        self.humidity = self.sensor("humidity", self.station)
        self.other_temp = self.sensor("temp", self.other)
        self.alien = self.sensor("other_only", self.other)
        self.start_receiver()

    def scalar(self, sql, params=()):
        return self.db.execute(sql, params or None).fetchone()[0]

    def sensor(self, name, station=None, low=None, high=None):
        return self.scalar(
            "INSERT INTO sensors(station_id,sensor_type_id,local_identifier,min_value,max_value) SELECT %s,min(id),%s,%s,%s FROM sensor_types RETURNING id",
            (station or self.station, name, low, high),
        )

    def start(self, service, command=None, **env):
        name = f"{self.op.project}-{self.uid}-{len(self.containers)}"
        args = ["run", "-d", "--no-deps", "--name", name]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        self.op.compose(*args, service, *(command or []))
        self.containers.append(name)
        return name

    def start_receiver(self, **env):
        self.receiver = self.start(
            "recepcao",
            ["ingest"],
            INGEST_REDIS_STREAM=self.stream,
            INGEST_MQTT_CLIENT_ID=f"qa-{self.uid}",
            **env,
        )
        eventually(lambda: "mqtt_connected" in self.logs(self.receiver))
        return self.receiver

    def worker(self, **env):
        settings = dict(
            PERSIST_STREAM=self.stream,
            PERSIST_SOURCE_ID=self.source,
            PERSIST_GROUP=self.group,
            PERSIST_RECOVERY_INTERVAL_SECONDS=".2",
            PERSIST_RECOVERY_MIN_IDLE_MS="7000",
            PERSIST_LEASE_REFRESH_SECONDS="1",
            PERSIST_LEASE_TTL_SECONDS="7",
            PERSIST_PROCESSING_TIMEOUT_SECONDS="5",
            PERSIST_BLOCK_MS="100",
            PERSIST_SHUTDOWN_TIMEOUT_SECONDS="2",
        )
        settings.update(env)
        name = self.start("persistencia", ["consume"], **settings)
        eventually(lambda: "consumption_started" in self.logs(name))
        return name

    def logs(self, name):
        result = subprocess.run(
            ["docker", "logs", name], capture_output=True, text=True, check=True
        )
        return result.stdout + result.stderr

    def stop(self, name, kill=False):
        subprocess.run(
            ["docker", "kill" if kill else "stop", name],
            check=False,
            capture_output=True,
        )
        # Denied XACK may already have terminated the process. Verify the outcome.
        record = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
        assert not record["State"]["Running"], "Writer did not stop"

    def operation(self, *command):
        return json.loads(
            self.op.compose(
                "run",
                "--no-deps",
                "--rm",
                "-T",
                "-e",
                f"PERSIST_STREAM={self.stream}",
                "persistencia",
                *command,
            ).splitlines()[-1]
        )

    def publish_raw(self, payload):
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"publisher-{uuid.uuid4().hex}",
            protocol=mqtt.MQTTv311,
        )
        client.connect("127.0.0.1", int(os.getenv("MQTT_PORT", "1883")))
        client.loop_start()
        try:
            info = client.publish(f"estacoes/{self.mac}/dados", payload, qos=1)
            info.wait_for_publish(10)
            assert info.is_published()
        finally:
            client.disconnect()
            client.loop_stop()

    def publish(self, values, timestamp=1760000000):
        original = {"estacao_id": str(self.station)}
        if timestamp is not ...:
            original["unix_time"] = timestamp
        original.update(values)
        return self.publish_json(json.dumps(original, separators=(",", ":")))

    def publish_json(self, payload):
        before = self.r.xlen(self.stream)
        self.publish_raw(payload)
        eventually(lambda: self.r.xlen(self.stream) > before)
        return self.r.xrevrange(self.stream, count=1)[0][0]

    def completed(self, entry_id):
        return (
            self.scalar(
                "SELECT count(*) FROM telemetry_events WHERE source_id=%s AND stream=%s AND entry_id=%s AND completed_at IS NOT NULL",
                (self.source, self.stream, entry_id),
            )
            == 1
        )

    def settled(self, entry_id):
        eventually(lambda: self.completed(entry_id))
        eventually(lambda: not self.r.xpending(self.stream, self.group)["pending"])

    def count(self, table):
        if table == "readings":
            return self.scalar(
                "SELECT count(*) FROM readings WHERE sensor_id=ANY(%s)",
                ([self.temp, self.humidity],),
            )
        if table == "telemetry_events":
            return self.scalar(
                "SELECT count(*) FROM telemetry_events WHERE stream=%s", (self.stream,)
            )
        assert table in ("telemetry_quarantine", "telemetry_results", "occurrences")
        if table == "occurrences":
            return self.scalar(
                "SELECT count(*) FROM occurrences WHERE station_id=%s", (self.station,)
            )
        return self.scalar(
            f"SELECT count(*) FROM {table} WHERE event_id IN (SELECT id FROM telemetry_events WHERE stream=%s)",
            (self.stream,),
        )

    def cleanup(self):
        output = ROOT / "reports" / "scenarios" / getattr(self, "uid", "setup")
        output.mkdir(parents=True, exist_ok=True)
        for name in reversed(getattr(self, "containers", [])):
            log = (
                self.logs(name)
                .replace("qa-password", "[redacted]")
                .replace("PAYLOAD_SECRET", "[redacted]")
            )
            (output / f"{name}.log").write_text(log)
            subprocess.run(
                ["docker", "rm", "-f", name], check=False, capture_output=True
            )
        if hasattr(self, "r"):
            self.r.close()
        if hasattr(self, "db"):
            self.db.close()


@pytest.fixture
def s(runtime):
    scenario = Scenario.__new__(Scenario)
    try:
        scenario.__init__(runtime)
        yield scenario
    finally:
        scenario.cleanup()

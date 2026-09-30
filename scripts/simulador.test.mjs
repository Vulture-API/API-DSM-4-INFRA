import assert from "node:assert/strict";
import test from "node:test";

import { leitura } from "./simulador.mjs";

const date = new Date("2026-09-30T03:00:00.000Z");

test("usa os identificadores reais dos sensores cadastrados", () => {
  const sensors = [
    { sensor_type_id: 1, local_identifier: "BAT-01" },
    { sensor_type_id: 2, local_identifier: "HUM-01" },
    { sensor_type_id: 3, local_identifier: "RAIN-01" },
    { sensor_type_id: 4, local_identifier: "TEMP-01" },
    { sensor_type_id: 5, local_identifier: "TEMPAR-01" },
    { sensor_type_id: 6, local_identifier: "WIND-01" },
  ];
  const types = new Map([
    [1, "Tensão da Bateria"],
    [2, "Umidade do Solo"],
    [3, "Sensor de Chuva"],
    [4, "Temperatura do Solo"],
    [5, "Temperatura do Ar"],
    [6, "Velocidade do Vento"],
  ]);
  const payload = leitura(1, sensors, types, date);

  assert.deepEqual(Object.keys(payload), [
    "estacao_id", "unix_time", "BAT-01", "HUM-01", "RAIN-01",
    "TEMP-01", "TEMPAR-01", "WIND-01",
  ]);
  assert.equal(payload.estacao_id, "00:1A:2B:3C:4D:01");
  assert.equal(payload.unix_time, 1790737200);
  for (const sensor of sensors) assert.equal(typeof payload[sensor.local_identifier], "number");
});

test("continua atendendo os identificadores do seed de demonstração", () => {
  const sensors = [
    { sensor_type_id: 1, local_identifier: "temp" },
    { sensor_type_id: 2, local_identifier: "umid" },
    { sensor_type_id: 3, local_identifier: "temp_solo" },
    { sensor_type_id: 4, local_identifier: "umid_solo" },
    { sensor_type_id: 5, local_identifier: "pressao" },
    { sensor_type_id: 6, local_identifier: "vento" },
    { sensor_type_id: 7, local_identifier: "chuva" },
  ];
  const types = new Map([
    [1, "Temperatura"], [2, "Umidade"], [3, "Temperatura do Solo"],
    [4, "Umidade do Solo"], [5, "Pressão"],
    [6, "Velocidade do Vento"], [7, "Índice Pluviométrico"],
  ]);
  const payload = leitura(2, sensors, types, date);

  assert.deepEqual(Object.keys(payload).slice(2), sensors.map((sensor) => sensor.local_identifier));
  assert.equal(payload.chuva, 0);
});

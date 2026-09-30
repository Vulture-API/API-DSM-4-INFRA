// Simulador das estações de demonstração. Consulta os sensores cadastrados
// para publicar cada valor com o local_identifier que o persistidor espera.
// As estações 05 e 10 ficam Offline de propósito; a 15 nunca comunica.

import { mqttPublish } from "./lib/mqtt.mjs";

const HOST = process.env.MQTT_HOST ?? "localhost";
const PORT = Number(process.env.MQTT_PORT ?? 1883);
const INTERVAL_S = Number(process.env.SIMULADOR_INTERVALO_S ?? 60);
const STATIONS_API_URL = process.env.STATIONS_API_URL ?? "http://localhost:3005";
const PARAMETERS_API_URL = process.env.PARAMETERS_API_URL ?? "http://localhost:3001";

const ESTACOES = [1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14];

const round = (v) => Math.round(v * 100) / 100;
const noise = (amp) => (Math.random() - 0.5) * amp;

function horaLocal(date) {
  // Hora decimal em Brasília (UTC-3, sem horário de verão).
  const h = (date.getUTCHours() + 21) % 24;
  return h + date.getUTCMinutes() / 60;
}

export function leitura(estacao, sensors, typeById, date = new Date()) {
  const h = horaLocal(date);
  const ciclo = (pico) => Math.sin((2 * Math.PI * (h - pico)) / 24);
  const temp = round(22 + (estacao % 4) * 0.6 + 6.5 * ciclo(9) + noise(1.6));
  const umid = round(Math.min(98, Math.max(28, 68 - 22 * ciclo(9) + noise(6))));
  const tempSolo = round(21 + 3 * ciclo(11) + noise(0.6));
  const umidSolo = round(36 + noise(2));
  const vento = round(Math.max(0, 7 + 5 * ciclo(12) + Math.random() * 6));
  const values = {
    "Temperatura": temp,
    "Temperatura do Ar": temp,
    "Umidade": umid,
    "Umidade do Solo": umidSolo,
    "Temperatura do Solo": tempSolo,
    "Pressão": round(1013 + noise(1)),
    "Velocidade do Vento": vento,
    "Índice Pluviométrico": 0,
    "Sensor de Chuva": 0,
    "Tensão da Bateria": round(3.7 + noise(0.08)),
  };
  const payload = {
    estacao_id: `00:1A:2B:3C:4D:${String(estacao).padStart(2, "0")}`,
    unix_time: Math.floor(date.getTime() / 1000),
  };

  for (const sensor of sensors) {
    const typeName = typeById.get(sensor.sensor_type_id);
    if (Object.hasOwn(values, typeName)) {
      payload[sensor.local_identifier] = values[typeName];
    }
  }
  return payload;
}

async function getJson(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

async function getAll(url) {
  const first = await getJson(`${url}?page=1&limit=100`);
  const rest = await Promise.all(
    Array.from({ length: first.meta.total_pages - 1 }, (_, index) =>
      getJson(`${url}?page=${index + 2}&limit=100`),
    ),
  );
  return [first, ...rest].flatMap((page) => page.data);
}

async function ciclo() {
  try {
    const [stations, sensors, sensorTypes] = await Promise.all([
      getAll(`${STATIONS_API_URL}/api/stations`),
      getAll(`${PARAMETERS_API_URL}/api/sensors`),
      getJson(`${PARAMETERS_API_URL}/api/sensor-types`),
    ]);
    const stationByMac = new Map(stations.map((station) => [station.mac_address, station]));
    const sensorsByStation = Map.groupBy(sensors, (sensor) => sensor.station_id);
    const typeById = new Map(sensorTypes.map((type) => [type.id, type.name]));
    let published = 0;
    let eligible = 0;

    for (const number of ESTACOES) {
      const mac = `00:1A:2B:3C:4D:${String(number).padStart(2, "0")}`;
      const station = stationByMac.get(mac);
      if (!station) continue;
      eligible++;
      const payload = leitura(number, sensorsByStation.get(station.id) ?? [], typeById);
      if (Object.keys(payload).length === 2) {
        console.warn(`[simulador] estação ${number}: nenhum sensor com tipo conhecido`);
        continue;
      }
      try {
        await mqttPublish({
          host: HOST,
          port: PORT,
          clientId: `simulador-${number}`,
          topic: `estacoes/${mac}/dados`,
          payload: JSON.stringify(payload),
        });
        published++;
      } catch (error) {
        console.error(`[simulador] estação ${number}: ${error.message}`);
      }
    }
    console.log(`[simulador] ${new Date().toISOString()} ${published}/${eligible} leituras publicadas`);
  } catch (error) {
    console.error(`[simulador] catálogo de estações/sensores indisponível: ${error.message}`);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(`[simulador] publicando em ${HOST}:${PORT} a cada ${INTERVAL_S}s`);
  await ciclo();
  setInterval(ciclo, INTERVAL_S * 1000);
}

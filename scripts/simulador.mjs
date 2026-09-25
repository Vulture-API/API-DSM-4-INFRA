// Simulador das estações de demonstração: publica leituras no MQTT, como o
// datalogger faria, para o dashboard ficar "vivo".
//
//   node scripts/simulador.mjs                  (no compose já roda sozinho)
//
// Usa as estações do seed-demo.sql (MAC 00:1A:2B:3C:4D:NN). As estações 05 e
// 10 ficam de fora de propósito, para aparecerem Offline, e a 15 nunca
// comunicou. As curvas seguem as do seed (ciclo diário de temperatura etc.).

import { mqttPublish } from "./lib/mqtt.mjs";

const HOST = process.env.MQTT_HOST ?? "localhost";
const PORT = Number(process.env.MQTT_PORT ?? 1883);
const INTERVAL_S = Number(process.env.SIMULADOR_INTERVALO_S ?? 60);

// n: número da estação; solo: tem sensores de solo.
const ESTACOES = [
  { n: 1, solo: true },
  { n: 2, solo: true },
  { n: 3, solo: false },
  { n: 4, solo: true },
  { n: 6, solo: true },
  { n: 7, solo: true },
  { n: 8, solo: false },
  { n: 9, solo: false },
  { n: 11, solo: true },
  { n: 12, solo: true },
  { n: 13, solo: false },
  { n: 14, solo: true },
];

const round = (v) => Math.round(v * 100) / 100;
const noise = (amp) => (Math.random() - 0.5) * amp;

function horaLocal(date) {
  // Hora decimal em Brasília (UTC-3, sem horário de verão).
  const h = (date.getUTCHours() + 21) % 24;
  return h + date.getUTCMinutes() / 60;
}

export function leitura(estacao, date = new Date()) {
  const h = horaLocal(date);
  const ciclo = (pico) => Math.sin((2 * Math.PI * (h - pico)) / 24);
  const payload = {
    estacao_id: `00:1A:2B:3C:4D:${String(estacao.n).padStart(2, "0")}`,
    unix_time: Math.floor(date.getTime() / 1000),
    temp: round(22 + (estacao.n % 4) * 0.6 + 6.5 * ciclo(9) + noise(1.6)),
    umid: round(Math.min(98, Math.max(28, 68 - 22 * ciclo(9) + noise(6)))),
    pressao: round(1013 + noise(1)),
    vento: round(Math.max(0, 7 + 5 * ciclo(12) + Math.random() * 6)),
    chuva: 0,
  };
  if (estacao.solo) {
    payload.temp_solo = round(21 + 3 * ciclo(11) + noise(0.6));
    payload.umid_solo = round(36 + noise(2));
  }
  return payload;
}

async function ciclo() {
  let ok = 0;
  for (const estacao of ESTACOES) {
    const payload = leitura(estacao);
    try {
      await mqttPublish({
        host: HOST,
        port: PORT,
        clientId: `simulador-${estacao.n}`,
        topic: `estacoes/${payload.estacao_id}/dados`,
        payload: JSON.stringify(payload),
      });
      ok++;
    } catch (error) {
      console.error(`[simulador] estação ${estacao.n}: ${error.message}`);
    }
  }
  console.log(
    `[simulador] ${new Date().toISOString()} ${ok}/${ESTACOES.length} leituras publicadas`,
  );
}

if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(`[simulador] publicando em ${HOST}:${PORT} a cada ${INTERVAL_S}s`);
  await ciclo();
  setInterval(ciclo, INTERVAL_S * 1000);
}

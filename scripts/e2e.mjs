// Teste ponta a ponta da Sprint 01, contra o ambiente já no ar.
//
//   node scripts/e2e.mjs
//
// Percorre o fluxo inteiro, do jeito que o usuário final usa:
//   usuário -> parâmetro -> estação -> sensor -> regra de alerta
//   -> estação publica no MQTT -> recepção grava a leitura
//   -> estação fica Online -> motor de regras dispara o alerta -> reconhecer
// e confere o front (páginas e proxy). Apaga tudo o que criou no fim.
//
// Sem dependências: usa fetch do Node e um publicador MQTT mínimo (abaixo).
// URLs podem ser trocadas por variável de ambiente (ver URLS).

import { mqttPublish } from "./lib/mqtt.mjs";

const URLS = {
  usuario: process.env.USUARIO_URL ?? "http://localhost:3000",
  parametros: process.env.PARAMETROS_URL ?? "http://localhost:3001",
  alertas: process.env.ALERTAS_URL ?? "http://localhost:3002",
  estacoes: process.env.ESTACOES_URL ?? "http://localhost:3005",
  frontend: process.env.FRONTEND_URL ?? "http://localhost:3010",
};
const MQTT_HOST = process.env.MQTT_HOST ?? "localhost";
const MQTT_PORT = Number(process.env.MQTT_PORT ?? 1883);
const TIMEOUT_MS = Number(process.env.E2E_TIMEOUT_MS ?? 45_000);

// Sufixo único: rodar duas vezes não colide em e-mail, MAC ou nome.
const id = Date.now().toString(16).slice(-6).toUpperCase();
const MAC = `E2:E2:${id.slice(0, 2)}:${id.slice(2, 4)}:${id.slice(4, 6)}:01`;

let ok = 0;
let fail = 0;
const cleanup = [];

const cor = (c, s) => (process.stdout.isTTY ? `\x1b[${c}m${s}\x1b[0m` : s);
function check(desc, cond, extra) {
  if (cond) {
    ok++;
    console.log(`  ${cor(32, "ok")}    ${desc}`);
  } else {
    fail++;
    console.log(`  ${cor(31, "FALHA")} ${desc}`);
    if (extra !== undefined) {
      console.log(`         ${JSON.stringify(extra).slice(0, 300)}`);
    }
  }
  return cond;
}
const secao = (t) => console.log(`\n${cor(36, t)}`);

async function http(method, url, body) {
  try {
    const res = await fetch(url, {
      method,
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(10_000),
    });
    const text = await res.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      json = text;
    }
    return { status: res.status, body: json };
  } catch (error) {
    return { status: 0, body: String(error.cause?.code ?? error.message) };
  }
}

async function waitFor(desc, fn) {
  const deadline = Date.now() + TIMEOUT_MS;
  let last;
  while (Date.now() < deadline) {
    last = await fn();
    if (last?.ok) return check(desc, true);
    await new Promise((r) => setTimeout(r, 1000));
  }
  return check(`${desc} (esperou ${TIMEOUT_MS / 1000}s)`, false, last?.info);
}

async function main() {
  console.log(`E2E Sprint 01  (sufixo ${id}, MAC ${MAC})`);

  secao("Saúde dos serviços");
  const health = {};
  for (const [nome, base] of Object.entries(URLS)) {
    const path = nome === "frontend" ? "/estacoes" : "/health";
    const r = await http("GET", base + path);
    // No ar = responde HTTP. A falta do /health é cobrada à parte, sem
    // interromper o resto do teste.
    health[nome] = r.status > 0 && r.status < 500;
    check(`${nome} no ar (${base})`, health[nome], r);
    if (health[nome] && nome !== "frontend") {
      check(`${nome} tem GET /health`, r.status === 200, r.status);
    }
  }
  if (Object.values(health).some((v) => !v)) {
    console.log("\nServiço fora do ar: o resto do teste não faz sentido.");
    return;
  }

  secao("US03 — Usuários");
  const roles = await http("GET", `${URLS.usuario}/api/roles`);
  check("lista cargos", roles.status === 200 && roles.body.length > 0, roles);
  const roleId = roles.body?.[0]?.id ?? 1;
  const email = `e2e.${id.toLowerCase()}@vulture.dev`;
  const user = await http("POST", `${URLS.usuario}/api/users`, {
    role_id: roleId,
    name: `Usuário E2E ${id}`,
    email,
    password: "senha-forte-123",
  });
  check("cria usuário (201)", user.status === 201, user);
  const userId = user.body?.id;
  if (userId) cleanup.push(["DELETE", `${URLS.usuario}/api/users/${userId}`]);
  const dupUser = await http("POST", `${URLS.usuario}/api/users`, {
    role_id: roleId,
    name: "Duplicado",
    email,
    password: "senha-forte-123",
  });
  check("e-mail duplicado devolve 409", dupUser.status === 409, dupUser);
  const updUser = await http("PUT", `${URLS.usuario}/api/users/${userId}`, {
    role_id: roleId,
    name: `Usuário E2E ${id} editado`,
    active: false,
  });
  check(
    "edita e desativa usuário",
    updUser.status === 200 && updUser.body.active === false,
    updUser,
  );
  const users = await http("GET", `${URLS.usuario}/api/users?limit=100`);
  check(
    "total da paginação bate com a lista",
    users.status === 200 &&
      users.body.meta.total_records >= users.body.data.length &&
      (users.body.meta.total_pages > 1 ||
        users.body.meta.total_records === users.body.data.length),
    users.body?.meta,
  );

  secao("US02 — Parâmetros (tipos de sensor)");
  const tipo = await http("POST", `${URLS.parametros}/api/sensor-types`, {
    name: `E2E ${id}`,
    unit_of_measure: "C",
  });
  check("cria tipo de sensor (201)", tipo.status === 201, tipo);
  const tipoId = tipo.body?.id;
  const dupTipo = await http("POST", `${URLS.parametros}/api/sensor-types`, {
    name: `E2E ${id}`,
    unit_of_measure: "C",
  });
  check("nome duplicado devolve 409", dupTipo.status === 409, dupTipo);
  const updTipo = await http(
    "PUT",
    `${URLS.parametros}/api/sensor-types/${tipoId}`,
    { name: `E2E ${id}`, unit_of_measure: "°C", factor: 1.5, gain: 2 },
  );
  check(
    "edita tipo de sensor",
    updTipo.status === 200 && updTipo.body.unit_of_measure === "°C",
    updTipo,
  );

  secao("US01 — Estações");
  const props = await http("GET", `${URLS.estacoes}/api/stations/properties`);
  check(
    "lista propriedades",
    props.status === 200 && props.body.length > 0,
    props,
  );
  const propertyId = props.body?.[0]?.id ?? 1;
  const station = await http("POST", `${URLS.estacoes}/api/stations`, {
    property_id: propertyId,
    name: `Estação E2E ${id}`,
    mac_address: MAC.toLowerCase().replaceAll(":", "-"),
    latitude: -23.18,
    longitude: -45.88,
  });
  check("cria estação (201)", station.status === 201, station);
  check("MAC normalizado", station.body?.mac_address === MAC, station.body);
  const stationId = station.body?.id;
  const dupSt = await http("POST", `${URLS.estacoes}/api/stations`, {
    property_id: propertyId,
    name: "Duplicada",
    mac_address: MAC,
  });
  check("MAC duplicado devolve 409", dupSt.status === 409, dupSt);
  const updSt = await http("PUT", `${URLS.estacoes}/api/stations/${stationId}`, {
    property_id: propertyId,
    name: `Estação E2E ${id} editada`,
    mac_address: MAC,
    latitude: -23.18,
    longitude: -45.88,
  });
  check("edita estação", updSt.status === 200, updSt);
  const st0 = await http(
    "GET",
    `${URLS.estacoes}/api/stations/${stationId}/status`,
  );
  check(
    "estação nova começa Offline",
    st0.status === 200 && st0.body.status === "Offline",
    st0,
  );

  secao("US02 — Sensores");
  const semEstacao = await http("POST", `${URLS.parametros}/api/sensors`, {
    station_id: 999999,
    sensor_type_id: tipoId,
    local_identifier: "temp",
  });
  check(
    "sensor sem estação existente é recusado (409)",
    semEstacao.status === 409,
    semEstacao,
  );
  const sensor = await http("POST", `${URLS.parametros}/api/sensors`, {
    station_id: stationId,
    sensor_type_id: tipoId,
    local_identifier: "temp",
  });
  check("cria sensor na estação (201)", sensor.status === 201, sensor);
  const sensorId = sensor.body?.id;
  const sensorGet = await http(
    "GET",
    `${URLS.parametros}/api/sensors?station_id=${stationId}`,
  );
  check(
    "sensor fica gravado no banco",
    sensorGet.status === 200 &&
      sensorGet.body.data.some((s) => s.id === sensorId),
    sensorGet,
  );

  // Ordem de limpeza (LIFO): alerta -> sensor -> estação -> tipo -> usuário.
  if (tipoId) {
    cleanup.push(["DELETE", `${URLS.parametros}/api/sensor-types/${tipoId}`]);
  }
  if (stationId) {
    cleanup.push(["DELETE", `${URLS.estacoes}/api/stations/${stationId}`]);
  }
  if (sensorId) {
    cleanup.push(["DELETE", `${URLS.parametros}/api/sensors/${sensorId}`]);
  }

  secao("US05 — Regra de alerta");
  const regra = await http("POST", `${URLS.alertas}/api/alerts/config`, {
    sensor_id: sensorId,
    reference_value: 30,
    comparison_operator: ">",
    message: `Temperatura alta (E2E ${id})`,
  });
  check("cria regra 'temp > 30' (201)", regra.status === 201, regra);
  const regraId = regra.body?.id;
  if (regraId) {
    cleanup.push(["DELETE", `${URLS.alertas}/api/alerts/config/${regraId}`]);
  }

  secao("US04 — Recepção e status (MQTT -> Redis -> Postgres)");
  const unixTime = Math.floor(Date.now() / 1000);
  try {
    await mqttPublish({
      host: MQTT_HOST,
      port: MQTT_PORT,
      clientId: `e2e-${id}`,
      topic: `estacoes/${MAC}/dados`,
      payload: JSON.stringify({ estacao_id: MAC, unix_time: unixTime, temp: 35.5 }),
    });
    check(`publica leitura no MQTT (${MQTT_HOST}:${MQTT_PORT})`, true);
  } catch (error) {
    check("publica leitura no MQTT", false, String(error));
  }
  await waitFor("estação fica Online depois da leitura", async () => {
    const r = await http(
      "GET",
      `${URLS.estacoes}/api/stations/${stationId}/status`,
    );
    return { ok: r.body?.status === "Online", info: r.body };
  });

  secao("US05 — Motor de regras");
  let alerta;
  await waitFor("motor de regras dispara o alerta", async () => {
    const r = await http(
      "GET",
      `${URLS.alertas}/api/alerts/triggered?acknowledged=false&limit=100`,
    );
    alerta = r.body?.data?.find((a) => a.alert_config_id === regraId);
    return { ok: Boolean(alerta), info: r.body?.meta ?? r };
  });
  if (alerta) {
    const ack = await http(
      "PUT",
      `${URLS.alertas}/api/alerts/triggered/${alerta.id}/acknowledge`,
      { acknowledged_by: userId },
    );
    check(
      "reconhece o alerta",
      ack.status === 200 && ack.body.acknowledged_at,
      ack,
    );
  }

  secao("Front-end (páginas e proxy)");
  for (const page of [
    "/dashboard",
    "/estacoes",
    `/estacoes/${stationId}`,
    "/administracao/parametros",
    "/administracao/usuarios",
    "/alertas",
    "/alertas/regras",
  ]) {
    const r = await http("GET", URLS.frontend + page);
    check(`página ${page}`, r.status === 200, r.status);
  }
  const proxies = [
    ["/api/users?limit=100", (b) => b.data.some((u) => u.id === userId)],
    ["/api/roles", (b) => Array.isArray(b) && b.length > 0],
    ["/api/stations/overview", (b) => b.stations.some((s) => s.id === stationId)],
    ["/api/stations?limit=100", (b) => b.data.some((s) => s.id === stationId)],
    ["/api/stations/properties", (b) => Array.isArray(b) && b.length > 0],
    ["/api/alerts/config?limit=100", (b) => b.data.some((c) => c.id === regraId)],
    [`/api/sensors?station_id=${stationId}`, (b) => b.data.length === 1],
    ["/api/sensor-types", (b) => b.some((t) => t.id === tipoId)],
  ];
  for (const [path, valid] of proxies) {
    const r = await http("GET", URLS.frontend + path);
    let passou = false;
    try {
      passou = r.status === 200 && valid(r.body);
    } catch {
      passou = false;
    }
    check(`proxy ${path}`, passou, r);
  }
}

async function limpar() {
  if (!cleanup.length) return;
  secao("Limpeza");
  for (const [method, url] of cleanup.reverse()) {
    const r = await http(method, url);
    check(`${method} ${url.replace(/^https?:\/\/[^/]+/, "")}`, [200, 204].includes(r.status), r);
  }
}

try {
  await main();
} finally {
  await limpar();
  console.log(`\n${ok} ok, ${fail} falha(s).`);
  console.log(fail ? cor(31, "E2E FALHOU") : cor(32, "E2E OK"));
  process.exitCode = fail ? 1 : 0;
}

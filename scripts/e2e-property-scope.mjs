import assert from "node:assert/strict";

const base = process.env.FRONTEND_URL ?? "http://localhost:8080";
const origin = new URL(base).origin;
async function login(email) {
  const response = await fetch(`${base}/api/auth/login`, {
    method: "POST", headers: { Origin: origin, "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: "senha123" }),
  });
  const user = await response.json();
  assert.equal(response.status, 200, JSON.stringify(user));
  return { user, cookie: response.headers.getSetCookie().map(value => value.split(";")[0]).join("; ") };
}
async function api(session, path, method = "GET", body, expected = 200) {
  const response = await fetch(`${base}/api/backend/${path}`, {
    method, headers: { Cookie: session.cookie, Origin: origin, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = response.status === 204 ? undefined : await response.json();
  assert.equal(response.status, expected, `${method} ${path}: ${JSON.stringify(result)}`);
  return result;
}

const admin = await login("scope-admin@qa.test");
const manager = await login("scope-manager@qa.test");
const client = await login("scope-client@qa.test");
assert.equal(admin.user.role_name, "Administrador");
assert.equal(admin.user.property_ids, null);
const suffix = Date.now();
const a = await api(manager, "properties", "POST", { name: `Scope Gerente ${suffix}`, owner_user_id: admin.user.id }, 201);
const b = await api(admin, "properties", "POST", { name: `Scope Cliente ${suffix}`, owner_user_id: admin.user.id }, 201);
await api(admin, `users/${client.user.id}/properties`, "PUT", { property_ids: [b.id] });
assert.deepEqual((await api(manager, "properties")).map(p => p.id), [a.id]);
assert.deepEqual((await api(client, "properties")).map(p => p.id), [b.id]);
for (const [property, tag] of [[a, "A"], [b, "B"]]) {
  await api(admin, "stations", "POST", { property_id: property.id, name: `Estação Scope ${tag}`, mac_address: `02:39:${suffix.toString(16).slice(-6).match(/../g).join(":")}:${tag === "A" ? "01" : "02"}`, latitude: -23, longitude: -45 }, 201);
}
const managerStations = (await api(manager, "stations")).data;
const clientStations = (await api(client, "stations")).data;
assert.equal(managerStations.length, 1);
assert.equal(clientStations.length, 1);
await api(manager, `stations/${clientStations[0].id}`, "GET", undefined, 404);
await api(client, `properties/${b.id}`, "DELETE", undefined, 403);
await api(manager, `users/${manager.user.id}/properties`, "GET", undefined, 403);
await api(client, "reports", "POST", { type: "history" });
await api(admin, `users/${manager.user.id}/properties`, "PUT", { property_ids: [] });
assert.deepEqual(await api(manager, "properties"), []);
assert.deepEqual((await api(manager, "stations")).data, []);
console.log("SCRUM-616: login, proxy, três perfis, vínculos, 404, modo leitura e revogação aprovados.");

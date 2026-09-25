// Publicador MQTT 3.1.1 mínimo, sem dependências: CONNECT, PUBLISH QoS 1,
// espera o PUBACK e DISCONNECT. Usado pelo e2e.mjs e pelo simulador.mjs.
import net from "node:net";

let sequence = 0;

export function mqttPublish({ host, port, clientId, topic, payload }) {
  const str = (s) => {
    const b = Buffer.from(s, "utf8");
    return Buffer.concat([Buffer.from([b.length >> 8, b.length & 255]), b]);
  };
  const packet = (type, body) => {
    const len = [];
    let n = body.length;
    do {
      let d = n % 128;
      n = Math.floor(n / 128);
      if (n > 0) d |= 128;
      len.push(d);
    } while (n > 0);
    return Buffer.concat([Buffer.from([type, ...len]), body]);
  };
  const connect = packet(
    0x10,
    Buffer.concat([
      str("MQTT"),
      Buffer.from([4, 0x02, 0, 30]), // v3.1.1, clean session, keepalive 30s
      str(clientId ?? `pub-${process.pid}-${++sequence}`),
    ]),
  );
  const publish = packet(
    0x32, // PUBLISH QoS 1
    Buffer.concat([str(topic), Buffer.from([0, 1]), Buffer.from(payload)]),
  );

  return new Promise((resolve, reject) => {
    const socket = net.connect(port, host);
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error("timeout MQTT"));
    }, 10_000);
    let buffer = Buffer.alloc(0);
    socket.on("connect", () => socket.write(connect));
    socket.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer[0] === 0x20 && buffer.length >= 4) {
        if (buffer[3] !== 0) {
          clearTimeout(timer);
          socket.destroy();
          return reject(new Error(`CONNACK recusado (${buffer[3]})`));
        }
        buffer = buffer.subarray(4);
        socket.write(publish);
      }
      if (buffer[0] === 0x40 && buffer.length >= 4) {
        clearTimeout(timer);
        socket.end(Buffer.from([0xe0, 0]));
        resolve();
      }
    });
  });
}

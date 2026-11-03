/* Service worker: ทำให้แอปเปิดได้แบบ offline
   - แอป/ไลบรารี: เก็บไว้ล่วงหน้า
   - ข้อมูล (eAIP, METAR): ใช้ของใหม่ถ้าต่อเน็ตได้ ไม่ได้ใช้ของล่าสุดที่เก็บไว้
   - ภาพแผนที่: เก็บภาพที่เคยเปิดดู (สูงสุด ~6000 ภาพ) */
const V = "vfr-v21";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-192.png", "icon-512.png", "eaip_data.json", "metar.json", "notam.json",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css",
  "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js",
  "https://cdn.jsdelivr.net/npm/mgrs@2.1.0/dist/mgrs.min.js",
  "https://cdn.jsdelivr.net/npm/leaflet-velocity@2.1.4/dist/leaflet-velocity.min.js",
  "https://cdn.jsdelivr.net/npm/leaflet-velocity@2.1.4/dist/leaflet-velocity.min.css"];
const TILE_HOSTS = ["arcgisonline.com", "opentopomap.org", "tile.openstreetmap.org", "tilecache.rainviewer.com", "elevation-tiles-prod", "basemaps.cartocdn.com"];
const MAX_TILES = 6000;

self.addEventListener("install", e => {
  e.waitUntil(caches.open(V).then(c => Promise.all(SHELL.map(u => c.add(new Request(u, { cache: "reload" })).catch(() => null)))));
  self.skipWaiting();
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V && k !== "vfr-tiles").map(k => caches.delete(k)))));
  self.clients.claim();
});

async function trimTiles() {
  const c = await caches.open("vfr-tiles"); const keys = await c.keys();
  for (let i = 0; i < keys.length - MAX_TILES; i++) await c.delete(keys[i]);
}

self.addEventListener("fetch", e => {
  const req = e.request; if (req.method !== "GET") return;
  const url = new URL(req.url);
  // ภาพแผนที่: cache-first
  if (TILE_HOSTS.some(h => url.hostname.includes(h))) {
    e.respondWith(caches.open("vfr-tiles").then(async c => {
      const hit = await c.match(req); if (hit) return hit;
      try { const res = await fetch(req); if (res.ok || res.type === "opaque") { c.put(req, res.clone()); if (Math.random() < 0.02) trimTiles(); } return res; }
      catch (err) { return new Response("", { status: 504 }); }
    }));
    return;
  }
  // ไลบรารี/ฟอนต์จาก CDN: cache-first
  if (/cdnjs|jsdelivr|unpkg|fonts\.(googleapis|gstatic)/.test(url.hostname)) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => { const cp = res.clone(); caches.open(V).then(c => c.put(req, cp)); return res; })));
    return;
  }
  // หน้าแอปและข้อมูลของแอป + พยากรณ์: network-first
  if (url.origin === location.origin || url.hostname.includes("open-meteo.com") || url.hostname.includes("rainviewer.com")) {
    e.respondWith(fetch(req).then(res => { if (res.ok) { const cp = res.clone(); caches.open(V).then(c => c.put(req, cp)); } return res; })
      .catch(() => caches.match(req, { ignoreSearch: url.origin === location.origin }).then(hit => hit || caches.match("index.html"))));
  }
});

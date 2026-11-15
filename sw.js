// Offline support: map tiles are cache-first; app files are network-first with the cached copy as backup.
const TILE_CACHE="tiles-v1", APP_CACHE="app-v1";
self.addEventListener("install",e=>{ self.skipWaiting(); e.waitUntil(caches.open(APP_CACHE).then(c=>c.addAll(["./","index.html","spots.json"]).catch(()=>{}))); });
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=="GET") return;
  const isTile=/basemap\.nationalmap\.gov|tile\.opentopomap\.org/.test(u.host) && /\/tile\/|\.png$/.test(u.pathname);
  const isLib=u.host==="unpkg.com";
  if(isTile || isLib){
    e.respondWith(caches.open(isTile?TILE_CACHE:APP_CACHE).then(async c=>{
      const hit=await c.match(e.request.url); if(hit) return hit;
      try{ const r=await fetch(e.request); if(r.ok && isLib) c.put(e.request.url,r.clone());
           if(r.ok && isTile && /basemap\.nationalmap\.gov/.test(u.host)) c.put(e.request.url,r.clone());
           return r; }
      catch(err){ return hit || Response.error(); }
    }));
    return;
  }
  if(u.origin===location.origin){
    e.respondWith((async()=>{
      const c=await caches.open(APP_CACHE);
      try{ const r=await fetch(e.request); if(r.ok) c.put(u.pathname,r.clone()); return r; }
      catch(err){ return (await c.match(u.pathname)) || (await c.match("index.html")) || Response.error(); }
    })());
  }
});

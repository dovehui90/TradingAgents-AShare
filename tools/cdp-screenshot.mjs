import http from 'http';
import fs from 'fs';
import path from 'path';
const PORT = 9222;

let _seq = 0;
function rpc(ws, method, params) {
    return new Promise((resolve, reject) => {
        const id = ++_seq;
        const t = setTimeout(() => reject(new Error(`timeout: ${method}`)), 10000);
        const h = (e) => {
            try { const d = JSON.parse(e.data); if (d.id === id) { clearTimeout(t); ws.removeEventListener('message', h); if (d.error) reject(new Error(JSON.stringify(d.error))); else resolve(d.result); } } catch {}
        };
        ws.addEventListener('message', h);
        ws.send(JSON.stringify({ id, method, params }));
    });
}
function cdpReq(method, path) {
  return new Promise((resolve, reject) => {
    const opts = { hostname: '127.0.0.1', port: PORT, path, method };
    const req = http.request(opts, res => { let d=''; res.on('data',c=>d+=c); res.on('end',()=>{try{resolve(JSON.parse(d))}catch{resolve(d)}}); });
    req.on('error', reject); req.end();
  });
}

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    if (!tab) { console.log('No tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');

    // Get the viewport dimensions
    const viewport = await rpc(ws, 'Runtime.evaluate', {
        expression: 'JSON.stringify({w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio})',
        returnByValue: true
    });
    console.log('Viewport:', viewport.result?.value);

    const dir = 'D:/AIProjects/TradingAgents-AShare/tools/screenshots';
    try { fs.mkdirSync(dir, { recursive: true }); } catch {}

    // Full page screenshot
    const full = await rpc(ws, 'Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(dir, 'full.png'), Buffer.from(full.data, 'base64'));
    console.log('Full screenshot saved to full.png');

    // Try to take a screenshot of just the Kline area
    const klineBbox = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const sections = document.querySelectorAll('section');
            for (const s of sections) {
                if (s.textContent.includes('K线') && s.textContent.includes('收盘')) {
                    const r = s.getBoundingClientRect();
                    return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height});
                }
            }
            return null;
        })()`,
        returnByValue: true
    });

    if (klineBbox.result?.value && klineBbox.result.value !== 'null') {
        const {x, y, w, h} = JSON.parse(klineBbox.result.value);
        const clip = await rpc(ws, 'Page.captureScreenshot', {
            format: 'png',
            clip: { x: Math.round(x), y: Math.round(y), width: Math.round(w), height: Math.round(h), scale: 1 }
        });
        fs.writeFileSync(path.join(dir, 'kline.png'), Buffer.from(clip.data, 'base64'));
        console.log('Kline screenshot saved to kline.png');
    }

    // Radar area screenshot
    const radarBbox = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const c of cards) {
                if (c.textContent.includes('主力趋势雷达')) {
                    const r = c.getBoundingClientRect();
                    return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height});
                }
            }
            return null;
        })()`,
        returnByValue: true
    });

    if (radarBbox.result?.value && radarBbox.result.value !== 'null') {
        const {x, y, w, h} = JSON.parse(radarBbox.result.value);
        const clip = await rpc(ws, 'Page.captureScreenshot', {
            format: 'png',
            clip: { x: Math.round(x), y: Math.round(y), width: Math.round(w), height: Math.round(h), scale: 1 }
        });
        fs.writeFileSync(path.join(dir, 'radar.png'), Buffer.from(clip.data, 'base64'));
        console.log('Radar screenshot saved to radar.png');
    }

    ws.close(1000);
}
main().catch(e => console.error(e.message));

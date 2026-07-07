import http from 'http';
import fs from 'fs';
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
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function takeScreenshot(ws, filename) {
    const result = await rpc(ws, 'Page.captureScreenshot', { format: 'png', clip: {
        x: 0, y: 0, width: 1920, height: 1080,
        scale: 1
    }});
    fs.writeFileSync(filename, Buffer.from(result.data, 'base64'));
    console.log(`  Screenshot saved: ${filename}`);
}

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174'));
    if (!tab) { console.log('No 5174 tab'); return; }

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');

    const dir = 'D:/AIProjects/TradingAgents-AShare/tools/screenshots';
    try { fs.mkdirSync(dir, { recursive: true }); } catch {}

    // 1. Switch to 日K
    console.log('Switching to 日K...');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='日K') b.click(); })`,
        returnByValue: true
    });
    await sleep(3000);
    await takeScreenshot(ws, dir + '/radar-daily.png');

    // 2. Switch to 周K
    console.log('Switching to 周K...');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='周K') b.click(); })`,
        returnByValue: true
    });
    await sleep(4000);
    await takeScreenshot(ws, dir + '/radar-weekly.png');

    // 3. Switch to 月K
    console.log('Switching to 月K...');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='月K') b.click(); })`,
        returnByValue: true
    });
    await sleep(4000);
    await takeScreenshot(ws, dir + '/radar-monthly.png');

    ws.close(1000);
}
main().catch(e => console.error(e.message));

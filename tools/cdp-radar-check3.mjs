import http from 'http';
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

async function main() {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url && t.url.includes('5174/analysis') && !t.url.includes('login'));
    if (!tab) { console.log('No analysis tab. Opening fresh...'); return; }

    console.log('Using tab:', tab.id.substring(0,8));
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Check page state
    const state = await rpc(ws, 'Runtime.evaluate', {
        expression: `JSON.stringify({
            url: location.href,
            title: document.title,
            hasKline: document.body.innerText.includes('K线'),
            hasRadar: document.body.innerText.includes('主力趋势雷达'),
            bodyPreview: document.body.innerText.substring(0, 300),
        })`,
        returnByValue: true
    });
    console.log('Page state:', state.result?.value);

    // If no charts, try to type a stock
    if (!state.result?.value.includes('"hasKline":true')) {
        console.log('No K-line charts. Trying to load...');
        const typed = await rpc(ws, 'Runtime.evaluate', {
            expression: `(() => {
                const el = document.querySelector('textarea') || document.querySelector('input[type="text"]');
                if (!el) return 'no input found on page';
                const desc = el instanceof HTMLTextAreaElement ? 'HTMLTextAreaElement' : 'HTMLInputElement';
                const proto = Object.getOwnPropertyDescriptor(el instanceof HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype, 'value');
                proto.set.call(el, '分析贵州茅台600519.SH');
                el.dispatchEvent(new Event('input', { bubbles: true }));
                return 'typed into ' + desc;
            })()`,
            returnByValue: true
        });
        console.log('Typed:', typed.result?.value);

        await rpc(ws, 'Runtime.evaluate', {
            expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.includes('发送') && !b.disabled) b.click(); })`,
            returnByValue: true
        });
        await sleep(12000);
    }

    // Now check radar canvas
    const radar = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (!card.textContent.includes('主力趋势雷达')) continue;
                const chartDiv = card.querySelector('.tv-lightweight-charts');
                if (!chartDiv) return 'no chart div';
                const canvases = chartDiv.querySelectorAll('canvas');
                let drawn = 0, sampled = 0;
                for (const cv of canvases) {
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    for (let x = Math.floor(cv.width*0.1); x < cv.width*0.9; x += Math.floor(cv.width*0.15)) {
                        for (let y = Math.floor(cv.height*0.1); y < cv.height*0.9; y += Math.floor(cv.height*0.15)) {
                            sampled++;
                            try { if (ctx.getImageData(x,y,1,1).data[3] > 0) drawn++; } catch(e) {}
                        }
                    }
                }
                const match = card.textContent.match(/波动线([\d.]+).*平均线([\d.]+)/);
                return JSON.stringify({
                    legendWave: match ? match[1] : null,
                    legendAvg: match ? match[2] : null,
                    canvasDrawn: drawn + '/' + sampled,
                });
            }
            return 'no radar';
        })()`,
        returnByValue: true
    });
    console.log('Radar:', radar.result?.value);

    ws.close(1000);
}
main().catch(e => console.error(e.message));

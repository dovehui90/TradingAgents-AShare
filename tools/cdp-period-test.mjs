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

async function checkKline(label) {
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    if (!tab) { console.log('No tab'); return; }
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Check kline canvas rendering and period
    const result = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            // Check period
            const btns = document.querySelectorAll('button');
            let period = 'unknown';
            for (const b of btns) {
                const t = b.textContent.trim();
                if ((t === '日K' || t === '周K' || t === '月K') && b.className.includes('purple')) { period = t; break; }
            }

            // Check K-line chart
            const canvases = document.querySelectorAll('canvas');
            let klineData = null;
            for (const cv of canvases) {
                if (cv.width === 1716 && cv.height === 420) {
                    const ctx = cv.getContext('2d');
                    let drawn = 0, total = 0;
                    if (ctx) {
                        for (let x = 5; x < cv.width - 5; x += 4) {
                            for (let y = 5; y < cv.height - 5; y += 4) {
                                total++;
                                try { if (ctx.getImageData(x, y, 1, 1).data[3] > 0) drawn++; } catch(e) {}
                            }
                        }
                    }
                    klineData = {drawn, total, pct: (drawn/total*100).toFixed(1)+'%'};
                    break;
                }
            }

            // Check candle count via legend text
            const h2 = document.querySelector('h2');
            const legendText = h2 ? h2.parentElement?.textContent : '';
            const dateMatch = legendText?.match(/(\\d{4}-\\d{2}-\\d{2})/);

            return JSON.stringify({period, klineData, date: dateMatch?.[1]});
        })()`,
        returnByValue: true
    });
    console.log(`[${label}]`, result.result?.value);
    ws.close(1000);
}

async function main() {
    console.log('=== 周期切换测试 ===');

    // Check initial state
    await checkKline('初始');

    // Get existing tab
    const tabs = await cdpReq('GET', '/json/list');
    const tab = tabs.find(t => t.url === 'http://localhost:5173/analysis');
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');

    // Switch to 周K
    console.log('Switching to 周K...');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='周K')b.click();})`,
        returnByValue: true
    });
    await sleep(4000);
    ws.close(1000);
    await checkKline('周K');

    // Switch to 月K
    const ws2 = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws2.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws2, 'Runtime.enable');
    console.log('Switching to 月K...');
    await rpc(ws2, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='月K')b.click();})`,
        returnByValue: true
    });
    await sleep(5000);
    ws2.close(1000);
    await checkKline('月K');

    console.log('Done');
}
main().catch(e => console.error(e.message));

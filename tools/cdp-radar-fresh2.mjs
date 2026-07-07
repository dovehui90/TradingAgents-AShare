import http from 'http';
const PORT = 9222;
const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4YmUwZmNiYy1iZmZmLTQ5NjEtODhiOC02YzI1MDZhNWQwNDEiLCJlbWFpbCI6IjIxMDQwMDE3NEBxcS5jb20iLCJleHAiOjE3ODMzODYzMTksImlhdCI6MTc4MDc5NDMxOX0.W6YFgnn2uzbG4mH6PY7Fx9q6pqxcPYcgCr5NYkbBBW8';

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

async function check(ws, label) {
    const r = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (!card.textContent.includes('主力趋势雷达')) continue;
                const chartDiv = card.querySelector('.tv-lightweight-charts');
                if (!chartDiv) return 'no chart div';
                const canvases = chartDiv.querySelectorAll('canvas');
                let totalDrawn = 0, totalSamples = 0;
                for (const cv of canvases) {
                    const ctx = cv.getContext('2d');
                    if (!ctx) continue;
                    for (let x = Math.floor(cv.width*0.1); x < cv.width*0.9; x += Math.floor(cv.width*0.2)) {
                        for (let y = Math.floor(cv.height*0.1); y < cv.height*0.9; y += Math.floor(cv.height*0.2)) {
                            totalSamples++;
                            try { if (ctx.getImageData(x,y,1,1).data[3] > 0) totalDrawn++; } catch(e) {}
                        }
                    }
                }
                const waveV = card.textContent.match(/波动线([\\d.]+)/);
                const avgV = card.textContent.match(/平均线([\\d.]+)/);
                return JSON.stringify({
                    wave: waveV ? waveV[1] : null,
                    avg: avgV ? avgV[1] : null,
                    drawn: totalDrawn + '/' + totalSamples,
                });
            }
            return 'no radar';
        })()`,
        returnByValue: true
    });
    console.log(`  [${label}] ${r.result?.value}`);
}

async function main() {
    const tab = await cdpReq('PUT', '/json/new?about:blank');
    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise((r, reject) => { const t=setTimeout(()=>reject(new Error('ws')),5000); ws.onopen=()=>{clearTimeout(t);r();}; });
    await rpc(ws, 'Runtime.enable');
    await rpc(ws, 'Page.enable');

    await rpc(ws, 'Page.addScriptToEvaluateOnNewDocument', {
        source: `localStorage.setItem('ta-access-token', '${TOKEN}');`
    });

    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5174/analysis' });
    console.log('Navigated to analysis');
    await sleep(5000);

    // Check if there's an input to type a stock
    const pageState = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const input = document.querySelector('textarea, input[type="text"]');
            const hasKline = document.body.innerText.includes('K线');
            const hasRadar = document.body.innerText.includes('主力趋势雷达');
            return JSON.stringify({hasInput: !!input, hasKline, hasRadar});
        })()`,
        returnByValue: true
    });
    console.log('Page state:', pageState.result?.value);

    // Type a stock symbol if needed
    const typed = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const el = document.querySelector('textarea') || document.querySelector('input[type="text"]');
            if (!el) return 'no input';
            const proto = Object.getOwnPropertyDescriptor(
                el instanceof HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype,
                'value'
            );
            proto.set.call(el, '分析贵州茅台600519.SH');
            el.dispatchEvent(new Event('input', { bubbles: true }));
            return 'typed';
        })()`,
        returnByValue: true
    });
    console.log('Type:', typed.result?.value);

    // Click send
    await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.includes('发送') && !b.disabled) { b.click(); return 'clicked'; }
            }
            return 'no send';
        })()`,
        returnByValue: true
    });

    // Wait for analysis to start and charts to appear
    await sleep(8000);

    // Check if charts are visible
    console.log('\n=== After analysis start ===');
    const midState = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            return JSON.stringify({
                hasKline: document.body.innerText.includes('K线'),
                hasRadar: document.body.innerText.includes('主力趋势雷达'),
                bodyLen: document.body.innerText.length,
            });
        })()`,
        returnByValue: true
    });
    console.log('Mid state:', midState.result?.value);

    // If charts not visible, wait more
    if (!midState.result?.value.includes('true')) {
        console.log('Waiting for charts...');
        await sleep(10000);
    }

    // Check radar in default state (日K)
    console.log('\n=== 日K ===');
    await check(ws, '日K');

    // Switch to 周K
    console.log('\n=== 周K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='周K') b.click(); })`,
        returnByValue: true
    });
    await sleep(5000);
    await check(ws, '周K');

    // Switch to 月K
    console.log('\n=== 月K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b => { if(b.textContent.trim()==='月K') b.click(); })`,
        returnByValue: true
    });
    await sleep(5000);
    await check(ws, '月K');

    ws.close(1000);
}
main().catch(e => console.error(e.message));

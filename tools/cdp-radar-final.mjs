import http from 'http';
const PORT = 9222;
const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4YmUwZmNiYy1iZmZmLTQ5NjEtODhiOC02YzI1MDZhNWQwNDEiLCJlbWFpbCI6IjIxMDQwMDE3NEBxcS5jb20iLCJleHAiOjE3ODMzODYzMTksImlhdCI6MTc4MDc5NDMxOX0.W6YFgnn2uzbG4mH6PY7Fx9q6pqxcPYcgCr5NYkbBBW8';

let _seq = 0;
function rpc(ws, method, params) {
    return new Promise((resolve, reject) => {
        const id = ++_seq;
        const t = setTimeout(() => reject(new Error(`timeout: ${method}`)), 15000);
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

async function checkRadar(ws, label) {
    const r = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const card of cards) {
                if (!card.textContent.includes('主力趋势雷达')) continue;
                const match = card.textContent.match(/波动线([\\d.]+).*平均线([\\d.]+)/);
                const chartDiv = card.querySelector('.tv-lightweight-charts');
                let drawn = 0, total = 0;
                if (chartDiv) {
                    for (const cv of chartDiv.querySelectorAll('canvas')) {
                        const ctx = cv.getContext('2d');
                        if (!ctx) continue;
                        for (let x=cv.width*0.15;x<cv.width*0.85;x+=cv.width*0.15) {
                            for (let y=cv.height*0.15;y<cv.height*0.85;y+=cv.height*0.15) {
                                total++;
                                try{if(ctx.getImageData(x,y,1,1).data[3]>0)drawn++;}catch(e){}
                            }
                        }
                    }
                }
                return JSON.stringify({wave: match?.[1]||null, avg: match?.[2]||null, drawn: drawn+'/'+total});
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
    await rpc(ws, 'Network.enable');

    await rpc(ws, 'Page.addScriptToEvaluateOnNewDocument', {
        source: `localStorage.setItem('ta-access-token', '${TOKEN}');`
    });

    await rpc(ws, 'Page.navigate', { url: 'http://localhost:5174/analysis' });
    console.log('Navigated to analysis');
    await sleep(6000);

    // Check if we're on analysis or login
    const pageUrl = await rpc(ws, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    console.log('Page URL:', pageUrl.result?.value);

    if (pageUrl.result?.value?.includes('login')) {
        console.log('ERROR: Redirected to login! Token may be invalid.');
        ws.close(1000);
        return;
    }

    // Check radar initially (should be on persisted klinePeriod, probably monthly from earlier tests)
    console.log('\n=== Initial radar (persisted period) ===');
    await checkRadar(ws, 'initial');

    // Check current period
    const period = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if ((b.textContent.includes('日K')||b.textContent.includes('周K')||b.textContent.includes('月K')) && b.className.includes('purple')) return b.textContent.trim();
            }
            return 'unknown';
        })()`,
        returnByValue: true
    });
    console.log('Current period:', period.result?.value);

    // Force click 日K and test
    console.log('\n=== Switch to 日K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='日K')b.click();})`,
        returnByValue: true
    });
    await sleep(4000);
    await checkRadar(ws, '日K');

    // Switch to 周K
    console.log('\n=== Switch to 周K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='周K')b.click();})`,
        returnByValue: true
    });
    await sleep(4000);
    await checkRadar(ws, '周K');

    // Switch to 月K
    console.log('\n=== Switch to 月K ===');
    await rpc(ws, 'Runtime.evaluate', {
        expression: `document.querySelectorAll('button').forEach(b=>{if(b.textContent.trim()==='月K')b.click();})`,
        returnByValue: true
    });
    await sleep(5000);
    await checkRadar(ws, '月K');

    // Take screenshots of each state
    // Get radar bounding box
    const bbox = await rpc(ws, 'Runtime.evaluate', {
        expression: `(() => {
            const cards = document.querySelectorAll('.card');
            for (const c of cards) {
                if (c.textContent.includes('主力趋势雷达')) {
                    const r = c.getBoundingClientRect();
                    return JSON.stringify({x:r.x, y:r.y, w:r.width, h:r.height});
                }
            }
            return null;
        })()`,
        returnByValue: true
    });

    if (bbox.result?.value && bbox.result.value !== 'null') {
        const fs = await import('fs');
        const dir = 'D:/AIProjects/TradingAgents-AShare/tools/screenshots';
        try { fs.mkdirSync(dir, { recursive: true }); } catch {}
        const {x, y, w, h} = JSON.parse(bbox.result.value);
        const result = await rpc(ws, 'Page.captureScreenshot', {
            format: 'png',
            clip: { x: Math.round(x), y: Math.round(y), width: Math.round(w), height: Math.round(h), scale: 2 }
        });
        fs.writeFileSync(dir + '/radar-final.png', Buffer.from(result.data, 'base64'));
        console.log('Screenshot saved to radar-final.png');
    }

    ws.close(1000);
}
main().catch(e => console.error(e.message));

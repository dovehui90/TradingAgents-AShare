import http from 'http';
import { readFileSync, writeFileSync } from 'fs';

function cdp(method, path, body) {
    return new Promise((resolve, reject) => {
        const opts = { hostname: '127.0.0.1', port: 9222, path, method, headers: body ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(JSON.stringify(body)) } : {} };
        const req = http.request(opts, res => { let d = ''; res.on('data', c => d += c); res.on('end', () => { try { resolve(JSON.parse(d)); } catch(e) { resolve(d); } }); });
        req.on('error', reject);
        if (body) req.write(JSON.stringify(body));
        req.end();
    });
}
function wsDo(wsUrl, msg) {
    return new Promise((resolve, reject) => {
        const ws = new WebSocket(wsUrl);
        ws.onopen = () => ws.send(JSON.stringify(msg));
        ws.onmessage = (e) => { const data = JSON.parse(e.data); if (data.id === msg.id) { ws.close(); resolve(data); } };
        ws.onerror = reject;
        setTimeout(() => reject(new Error('timeout')), 15000);
    });
}
async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
    const token = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf8').trim();
    const tab = await cdp('PUT', '/json/new?url=http://127.0.0.1:5173/analysis');
    console.log('Tab:', tab.id);
    const ws = tab.webSocketDebuggerUrl;
    await wsDo(ws, { id: 1, method: 'Page.enable' });
    await wsDo(ws, { id: 2, method: 'Runtime.enable' });
    await wsDo(ws, { id: 3, method: 'Input.enable' });
    await sleep(2000);

    await wsDo(ws, { id: 4, method: 'Runtime.evaluate', params: { expression: `localStorage.setItem('ta-access-token','${token}');'ok'`, returnByValue: true }});
    await wsDo(ws, { id: 5, method: 'Page.navigate', params: { url: 'http://127.0.0.1:5173/analysis' } });
    await sleep(6000);

    // Enter stock 000815
    await wsDo(ws, { id: 6, method: 'Runtime.evaluate', params: { expression: `(function(){var i=document.querySelector('input[placeholder*=\"搜索\"]');if(!i)return'no';var d=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;d.call(i,'000815');i.dispatchEvent(new Event('input',{bubbles:true}));setTimeout(function(){i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))},100);return'sent'})()`, returnByValue: true }});
    console.log('Stock entered');
    await sleep(10000);

    // Find the canvas element in the bollinger card
    let r = await wsDo(ws, { id: 7, method: 'Runtime.evaluate', params: { expression: `(function(){
        var cards = document.querySelectorAll('.card');
        for (var i = 0; i < cards.length; i++) {
            if (cards[i].innerText.indexOf('布林') >= 0 && cards[i].innerText.indexOf('乖离') >= 0) {
                cards[i].scrollIntoView({behavior:'instant',block:'center'});
                var canvas = cards[i].querySelector('canvas');
                if (canvas) {
                    var rect = canvas.getBoundingClientRect();
                    return JSON.stringify({x:rect.left, y:rect.top, w:rect.width, h:rect.height});
                }
            }
        }
        return 'no canvas';
    })()`, returnByValue: true }});
    console.log('Canvas rect:', r.result?.result?.value);

    if (r.result?.result?.value === 'no canvas') {
        console.log('No canvas found');
        return;
    }

    const canvas = JSON.parse(r.result?.result?.value);

    // The chart has ~76 points. May 28 is near the end but not the last.
    // Each bar occupies canvas.w / visiblePoints. Default visible ~50 bars.
    // May 28 is about 75% from the left (it's about 18 trading days back from June 22).
    // Click at approximately 65% from left (to hit the May 28 area)
    const targetX = canvas.x + canvas.w * 0.68;
    const targetY = canvas.y + canvas.h * 0.5; // middle of canvas

    console.log(`Moving mouse to: ${targetX}, ${targetY}`);

    // Dispatch mouse events to trigger crosshair
    await wsDo(ws, { id: 8, method: 'Input.dispatchMouseEvent', params: { type: 'mouseMoved', x: targetX, y: targetY } });
    await sleep(500);

    // Read the hover label
    r = await wsDo(ws, { id: 9, method: 'Runtime.evaluate', params: { expression: `(function(){
        var cards = document.querySelectorAll('.card');
        for (var i = 0; i < cards.length; i++) {
            if (cards[i].innerText.indexOf('布林') >= 0) {
                // Get all visible text content
                return cards[i].innerText.substring(0, 600);
            }
        }
        return 'not found';
    })()`, returnByValue: true }});
    console.log('After hover - bollinger text:', r.result?.result?.value);
}

main().catch(e => console.error(e.message || e));

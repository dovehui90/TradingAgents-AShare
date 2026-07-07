import http from 'http';
import { writeFileSync, readFileSync } from 'fs';

const TOKEN = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf-8').trim();
console.log('Token length:', TOKEN.length);

function cdp(method, path) {
    return new Promise((resolve, reject) => {
        http.request({ hostname: '127.0.0.1', port: 9222, path, method }, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(new Error(d.slice(0, 300))); } });
        }).on('error', reject).end();
    });
}

async function testBothPages() {
    // Test MarketAnalysis first (no auth required)
    console.log('\n=== MarketAnalysis ===');
    const tab1 = await cdp('PUT', `/json/new?url=${encodeURIComponent('http://127.0.0.1:5173/market-analysis')}`);
    const ws1 = new WebSocket(tab1.webSocketDebuggerUrl);
    await new Promise(r => { ws1.onopen = r; });

    function send(ws, id, method, params) {
        return new Promise(resolve => {
            const t = setTimeout(() => resolve(null), 10000);
            const h = e => {
                try {
                    const d = JSON.parse(e.data);
                    if (d.id === id) { clearTimeout(t); ws.removeEventListener('message', h); resolve(d.result || d.error); }
                } catch {}
            };
            ws.addEventListener('message', h);
            ws.send(JSON.stringify({ id, method, params }));
        });
    }

    function onError(ws) {
        ws.addEventListener('message', e => {
            try {
                const d = JSON.parse(e.data);
                if (d.method === 'Runtime.exceptionThrown') {
                    console.log('  ERROR:', JSON.stringify(d.params?.exceptionDetails?.exception?.description || d.params?.exceptionDetails?.text || '').slice(0, 300));
                }
            } catch {}
        });
    }

    await send(ws1, 1, 'Page.enable');
    await send(ws1, 2, 'Runtime.enable');
    onError(ws1);

    // Wait for initial load
    await new Promise(r => {
        const h = e => {
            try { const d = JSON.parse(e.data); if (d.method === 'Page.loadEventFired') { ws1.removeEventListener('message', h); r(); } } catch {}
        };
        ws1.addEventListener('message', h);
        setTimeout(r, 20000);
    });
    await new Promise(r => setTimeout(r, 3000));

    // Check what we got
    const url1 = await send(ws1, 10, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    const title1 = await send(ws1, 11, 'Runtime.evaluate', { expression: 'document.title', returnByValue: true });
    console.log('URL:', url1?.result?.value);
    console.log('Title:', title1?.result?.value);

    // Inject token
    const inj = await send(ws1, 12, 'Runtime.evaluate', {
        expression: 'localStorage.setItem("ta-access-token", ' + JSON.stringify(TOKEN) + '); "OK: " + (localStorage.getItem("ta-access-token") || "").substring(0, 30)',
        returnByValue: true
    });
    console.log('Inject result:', inj?.result?.value);

    // Navigate again to trigger auth check with token
    await send(ws1, 13, 'Page.navigate', { url: 'http://127.0.0.1:5173/market-analysis' });
    await new Promise(r => {
        const h = e => {
            try { const d = JSON.parse(e.data); if (d.method === 'Page.loadEventFired') { ws1.removeEventListener('message', h); r(); } } catch {}
        };
        ws1.addEventListener('message', h);
        setTimeout(r, 20000);
    });
    await new Promise(r => setTimeout(r, 4000));

    const url2 = await send(ws1, 20, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    const body2 = await send(ws1, 21, 'Runtime.evaluate', { expression: 'document.body?.innerText?.slice(0, 3000) || "NULL"', returnByValue: true });
    console.log('After auth URL:', url2?.result?.value);
    const text2 = body2?.result?.value || '';
    console.log('Has 大盘点金:', text2.includes('大盘点金'));
    console.log('Has 阳谱:', text2.includes('阳谱'));

    const shot1 = await send(ws1, 22, 'Page.captureScreenshot', { format: 'png' });
    if (shot1?.data) {
        writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/ma_v4.png', Buffer.from(shot1.data, 'base64'));
        console.log('Screenshot saved');
    }

    // Show relevant content
    const lines = text2.split('\n').filter(l => l.trim());
    console.log('\nContent:');
    lines.slice(0, 15).forEach(l => console.log('  ', l));

    ws1.close();
    await new Promise(r => setTimeout(r, 500));

    // Test Briefing
    console.log('\n=== Briefing ===');
    const tab2 = await cdp('PUT', `/json/new?url=${encodeURIComponent('http://127.0.0.1:5173/briefing')}`);
    const ws2 = new WebSocket(tab2.webSocketDebuggerUrl);
    await new Promise(r => { ws2.onopen = r; });

    await send(ws2, 1, 'Page.enable');
    await send(ws2, 2, 'Runtime.enable');
    onError(ws2);

    await new Promise(r => {
        const h = e => {
            try { const d = JSON.parse(e.data); if (d.method === 'Page.loadEventFired') { ws2.removeEventListener('message', h); r(); } } catch {}
        };
        ws2.addEventListener('message', h);
        setTimeout(r, 20000);
    });
    await new Promise(r => setTimeout(r, 2000));

    // Inject token (same localStorage domain)
    await send(ws2, 10, 'Runtime.evaluate', {
        expression: 'localStorage.setItem("ta-access-token", ' + JSON.stringify(TOKEN) + '); "OK"',
        returnByValue: true
    });

    // Reload
    await send(ws2, 11, 'Page.navigate', { url: 'http://127.0.0.1:5173/briefing' });
    await new Promise(r => {
        const h = e => {
            try { const d = JSON.parse(e.data); if (d.method === 'Page.loadEventFired') { ws2.removeEventListener('message', h); r(); } } catch {}
        };
        ws2.addEventListener('message', h);
        setTimeout(r, 20000);
    });
    await new Promise(r => setTimeout(r, 4000));

    const urlB = await send(ws2, 20, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    const bodyB = await send(ws2, 21, 'Runtime.evaluate', { expression: 'document.body?.innerText?.slice(0, 3000) || "NULL"', returnByValue: true });
    console.log('URL:', urlB?.result?.value);
    const textB = bodyB?.result?.value || '';
    console.log('Has 大盘点金:', textB.includes('大盘点金'));
    console.log('Has 盘前速递:', textB.includes('盘前速递'));
    console.log('Has 阳谱:', textB.includes('阳谱'));

    const shot2 = await send(ws2, 22, 'Page.captureScreenshot', { format: 'png' });
    if (shot2?.data) {
        writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/briefing_v4.png', Buffer.from(shot2.data, 'base64'));
    }

    // Show first 20 content lines
    const linesB = textB.split('\n').filter(l => l.trim());
    console.log('\nContent:');
    linesB.slice(0, 20).forEach(l => console.log('  ', l));

    ws2.close();
}

testBothPages().catch(e => console.error('FAIL:', e.message));

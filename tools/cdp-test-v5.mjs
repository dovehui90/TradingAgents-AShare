import http from 'http';
import { writeFileSync, readFileSync } from 'fs';

const TOKEN = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf-8').trim();

function cdp(method, path) {
    return new Promise((resolve, reject) => {
        http.request({ hostname: '127.0.0.1', port: 9222, path, method }, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(new Error(d.slice(0, 300))); } });
        }).on('error', reject).end();
    });
}

async function run() {
    // Single tab - first login then test both pages
    const tab = await cdp('PUT', '/json/new');
    console.log('Tab created:', tab.id);

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(r => ws.onopen || (ws.onopen = r) || setTimeout(r, 2000));

    function send(id, method, params) {
        return new Promise(resolve => {
            const t = setTimeout(() => resolve(null), 12000);
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

    function waitLoad(timeout = 20000) {
        return new Promise(r => {
            const h = e => {
                try {
                    const d = JSON.parse(e.data);
                    if (d.method === 'Page.loadEventFired') { ws.removeEventListener('message', h); r(); }
                } catch {}
            };
            ws.addEventListener('message', h);
            setTimeout(r, timeout);
        });
    }

    // Error capture
    ws.addEventListener('message', e => {
        try {
            const d = JSON.parse(e.data);
            if (d.method === 'Runtime.exceptionThrown')
                console.log('ERROR:', (d.params?.exceptionDetails?.text || '').slice(0, 300));
        } catch {}
    });

    await send(1, 'Page.enable');
    await send(2, 'Runtime.enable');

    // Step 1: Navigate to root to establish origin
    console.log('1. Navigate to root...');
    await send(3, 'Page.navigate', { url: 'http://127.0.0.1:5173/' });
    await waitLoad();
    await new Promise(r => setTimeout(r, 3000));

    let url = await send(10, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    console.log('   URL:', url?.result?.value);

    // Step 2: Inject token
    console.log('2. Inject token...');
    const inj = await send(11, 'Runtime.evaluate', {
        expression: 'localStorage.setItem("ta-access-token", ' + JSON.stringify(TOKEN) + '); "done"',
        returnByValue: true
    });
    console.log('   Inject:', inj?.result?.value);
    const check = await send(12, 'Runtime.evaluate', {
        expression: 'localStorage.getItem("ta-access-token") ? "HAS_TOKEN" : "NO_TOKEN"',
        returnByValue: true
    });
    console.log('   Check:', check?.result?.value);

    // Step 3: Test MarketAnalysis
    console.log('3. Test MarketAnalysis...');
    await send(20, 'Page.navigate', { url: 'http://127.0.0.1:5173/market-analysis' });
    await waitLoad();
    await new Promise(r => setTimeout(r, 5000));

    url = await send(21, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    const title = await send(22, 'Runtime.evaluate', { expression: 'document.title', returnByValue: true });
    const body = await send(23, 'Runtime.evaluate', {
        expression: 'document.body?.innerText?.slice(0, 4000) || "NULL"',
        returnByValue: true
    });
    console.log('   URL:', url?.result?.value);
    console.log('   Title:', title?.result?.value);
    const t1 = body?.result?.value || '';
    console.log('   大盘点金:', t1.includes('大盘点金'));
    console.log('   阳谱:', t1.includes('阳谱'));
    console.log('   智能分析:', t1.includes('智能分析'));

    const shot1 = await send(24, 'Page.captureScreenshot', { format: 'png' });
    if (shot1?.data) writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/ma_v5.png', Buffer.from(shot1.data, 'base64'));

    // Show relevant lines
    t1.split('\n').filter(l => l.trim()).slice(0, 15).forEach(l => console.log('   ', l));

    // Step 4: Test Briefing
    console.log('4. Test Briefing...');
    await send(30, 'Page.navigate', { url: 'http://127.0.0.1:5173/briefing' });
    await waitLoad();
    await new Promise(r => setTimeout(r, 5000));

    url = await send(31, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    const body2 = await send(32, 'Runtime.evaluate', {
        expression: 'document.body?.innerText?.slice(0, 4000) || "NULL"',
        returnByValue: true
    });
    console.log('   URL:', url?.result?.value);
    const t2 = body2?.result?.value || '';
    console.log('   大盘点金:', t2.includes('大盘点金'));
    console.log('   盘前速递:', t2.includes('盘前速递'));
    console.log('   阳谱:', t2.includes('阳谱'));

    const shot2 = await send(33, 'Page.captureScreenshot', { format: 'png' });
    if (shot2?.data) writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/briefing_v5.png', Buffer.from(shot2.data, 'base64'));

    t2.split('\n').filter(l => l.trim()).slice(0, 15).forEach(l => console.log('   ', l));

    ws.close();
    console.log('\nDone. Screenshots: ma_v5.png, briefing_v5.png');
}

run().catch(e => console.error('FAIL:', e.message));

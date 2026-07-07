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
    const tab = await cdp('PUT', '/json/new');
    console.log('Tab:', tab.id);

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(r => { ws.onopen = r; setTimeout(r, 2000); });

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

    ws.addEventListener('message', e => {
        try {
            const d = JSON.parse(e.data);
            if (d.method === 'Runtime.exceptionThrown')
                console.log('ERROR:', (d.params?.exceptionDetails?.text || '').slice(0, 300));
        } catch {}
    });

    await send(1, 'Page.enable');
    await send(2, 'Runtime.enable');

    // Navigate to root first
    console.log('1. Go to root...');
    await send(10, 'Page.navigate', { url: 'http://127.0.0.1:5173/' });
    await waitLoad();
    await new Promise(r => setTimeout(r, 3000));

    // Inject token in CORRECT format: JSON object with access_token + token_type
    const tokenData = JSON.stringify({ access_token: TOKEN, token_type: 'bearer' });
    console.log('2. Inject token (as JSON object)...');
    await send(11, 'Runtime.evaluate', {
        expression: `localStorage.setItem('ta-access-token', '${tokenData.replace(/'/g, "\\'")}'); 'done'`,
        returnByValue: true
    });
    const check = await send(12, 'Runtime.evaluate', {
        expression: `(function(){ try { var d=JSON.parse(localStorage.getItem('ta-access-token')||'{}'); return d.access_token?'HAS_'+d.token_type:'NO_TOKEN'; } catch(e) { return 'PARSE_ERR:'+e.message; } })()`,
        returnByValue: true
    });
    console.log('   Check:', check?.result?.value);

    // Test MarketAnalysis
    console.log('3. Test MarketAnalysis...');
    await send(20, 'Page.navigate', { url: 'http://127.0.0.1:5173/market-analysis' });
    await waitLoad();
    await new Promise(r => setTimeout(r, 5000));

    const url1 = await send(21, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    const body1 = await send(22, 'Runtime.evaluate', {
        expression: 'document.body?.innerText?.slice(0, 4000) || "NULL"',
        returnByValue: true
    });
    console.log('   URL:', url1?.result?.value);
    const t1 = body1?.result?.value || '';
    console.log('   大盘点金:', t1.includes('大盘点金'), '| 阳谱:', t1.includes('阳谱'), '| 智能分析:', t1.includes('智能分析'));

    const s1 = await send(23, 'Page.captureScreenshot', { format: 'png' });
    if (s1?.data) writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/ma_v6.png', Buffer.from(s1.data, 'base64'));

    // Test Briefing
    console.log('4. Test Briefing...');
    await send(30, 'Page.navigate', { url: 'http://127.0.0.1:5173/briefing' });
    await waitLoad();
    await new Promise(r => setTimeout(r, 5000));

    const url2 = await send(31, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
    const body2 = await send(32, 'Runtime.evaluate', {
        expression: 'document.body?.innerText?.slice(0, 4000) || "NULL"',
        returnByValue: true
    });
    console.log('   URL:', url2?.result?.value);
    const t2 = body2?.result?.value || '';
    console.log('   大盘点金:', t2.includes('大盘点金'), '| 盘前速递:', t2.includes('盘前速递'), '| 阳谱:', t2.includes('阳谱'));

    const s2 = await send(33, 'Page.captureScreenshot', { format: 'png' });
    if (s2?.data) writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/briefing_v6.png', Buffer.from(s2.data, 'base64'));

    ws.close();
    console.log('\nDone.');
}

run().catch(e => console.error('FAIL:', e.message));

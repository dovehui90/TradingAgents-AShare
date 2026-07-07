import http from 'http';
import { writeFileSync, readFileSync } from 'fs';

const TOKEN = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf-8').trim();
const USER = JSON.parse(readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_user.json', 'utf-8'));

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
                try { const d = JSON.parse(e.data); if (d.id === id) { clearTimeout(t); ws.removeEventListener('message', h); resolve(d.result || d.error); } } catch {}
            };
            ws.addEventListener('message', h);
            ws.send(JSON.stringify({ id, method, params }));
        });
    }

    function waitLoad(t = 20000) {
        return new Promise(r => {
            const h = e => { try { const d = JSON.parse(e.data); if (d.method === 'Page.loadEventFired') { ws.removeEventListener('message', h); r(); } } catch {} };
            ws.addEventListener('message', h); setTimeout(r, t);
        });
    }

    ws.addEventListener('message', e => {
        try { const d = JSON.parse(e.data); if (d.method === 'Runtime.exceptionThrown') console.log('ERR:', (d.params?.exceptionDetails?.text || '').slice(0, 200)); } catch {}
    });

    await send(1, 'Page.enable');
    await send(2, 'Runtime.enable');

    // Navigate to root
    console.log('1. Root...');
    await send(10, 'Page.navigate', { url: 'http://127.0.0.1:5173/' });
    await waitLoad(); await new Promise(r => setTimeout(r, 3000));

    // Inject token + user (authStore needs both)
    const tokenJSON = JSON.stringify(TOKEN);
    const userJSON = JSON.stringify(USER);
    console.log('2. Inject auth...');
    await send(11, 'Runtime.evaluate', {
        expression: `localStorage.setItem('ta-access-token', ${tokenJSON}); localStorage.setItem('ta-user', ${userJSON}); 'done'`,
        returnByValue: true
    });

    // Verify
    const chk = await send(12, 'Runtime.evaluate', {
        expression: `localStorage.getItem('ta-access-token') ? localStorage.getItem('ta-access-token').substring(0,20)+'...' : 'MISSING'`,
        returnByValue: true
    });
    const chk2 = await send(13, 'Runtime.evaluate', {
        expression: `localStorage.getItem('ta-user') ? JSON.parse(localStorage.getItem('ta-user')).email : 'MISSING'`,
        returnByValue: true
    });
    console.log('   Token:', chk?.result?.value);
    console.log('   User:', chk2?.result?.value);

    // Test pages
    for (const [name, path] of [['Analysis', '/analysis'], ['Briefing', '/briefing']]) {
        console.log(`\n=== ${name} ===`);
        await send(30, 'Page.navigate', { url: 'http://127.0.0.1:5173' + path });
        await waitLoad(); await new Promise(r => setTimeout(r, 5000));

        const u = await send(31, 'Runtime.evaluate', { expression: 'location.href', returnByValue: true });
        const b = await send(32, 'Runtime.evaluate', {
            expression: 'document.body?.innerText?.slice(0, 4000) || "NULL"',
            returnByValue: true
        });
        console.log('   URL:', u?.result?.value);
        const t = b?.result?.value || '';
        console.log('   大盘点金:', t.includes('大盘点金'));
        console.log('   阳谱:', t.includes('阳谱'));
        console.log('   阴谱:', t.includes('阴谱'));

        // Show first lines
        t.split('\n').filter(l => l.trim()).slice(0, 12).forEach(l => console.log('   ', l.trim()));

        const s = await send(33, 'Page.captureScreenshot', { format: 'png' });
        if (s?.data) writeFileSync(`d:/AIProjects/TradingAgents-AShare/frontend/screenshots/${name}_v7.png`, Buffer.from(s.data, 'base64'));
    }

    ws.close();
    console.log('\nDone.');
}

run().catch(e => console.error('FAIL:', e.message));

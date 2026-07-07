import http from 'http';
import { writeFileSync } from 'fs';

function cdp(method, path) {
    return new Promise((resolve, reject) => {
        http.request({ hostname: '127.0.0.1', port: 9222, path, method }, res => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try { resolve(JSON.parse(d)); } catch (e) { reject(new Error('Parse: ' + d.slice(0, 300))); }
            });
        }).on('error', reject).end();
    });
}

async function main() {
    const tab = await cdp('PUT', `/json/new?url=${encodeURIComponent('http://127.0.0.1:5173/market-analysis')}`);
    console.log('Tab:', tab.id);

    const ws = new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(r => { ws.onopen = r; });

    function send(id, method, params) {
        return new Promise(resolve => {
            const timer = setTimeout(() => resolve(null), 8000);
            const h = e => {
                const d = JSON.parse(e.data);
                if (d.id === id) { clearTimeout(timer); ws.removeEventListener('message', h); resolve(d.result || d.error); }
            };
            ws.addEventListener('message', h);
            ws.send(JSON.stringify({ id, method, params }));
        });
    }

    // Error capture
    ws.addEventListener('message', e => {
        try {
            const d = JSON.parse(e.data);
            if (d.method === 'Runtime.exceptionThrown') {
                console.log('JS ERROR:', d.params?.exceptionDetails?.text || d.params?.exceptionDetails?.exception?.description);
            }
            if (d.method === 'Runtime.consoleAPICalled' && d.params?.type === 'error') {
                console.log('CONSOLE ERROR:', d.params.args?.map(a => a.value).join(' '));
            }
        } catch {}
    });

    await send(1, 'Page.enable');
    await send(2, 'Runtime.enable');
    await send(3, 'Log.enable');
    await send(4, 'Console.enable');

    console.log('Navigating...');
    await send(5, 'Page.navigate', { url: 'http://127.0.0.1:5173/market-analysis' });

    await new Promise(r => {
        const h = e => {
            try {
                const d = JSON.parse(e.data);
                if (d.method === 'Page.loadEventFired') { ws.removeEventListener('message', h); r(); }
            } catch {}
        };
        ws.addEventListener('message', h);
        setTimeout(r, 20000);
    });
    console.log('Loaded, waiting for React...');
    await new Promise(r => setTimeout(r, 5000));

    const checks = [
        'document.readyState',
        'document.title',
        '!!document.body',
        '!!document.getElementById("root")',
        'document.getElementById("root")?.innerHTML?.length || 0',
    ];
    for (const e of checks) {
        const r = await send(90, 'Runtime.evaluate', { expression: e, returnByValue: true });
        console.log(`  ${e} = ${r?.result?.value}`);
    }

    const body = await send(91, 'Runtime.evaluate', { expression: 'document.body?.innerText?.slice(0, 1500) || "NULL"', returnByValue: true });
    console.log('Body:', body?.result?.value);

    const shot = await send(92, 'Page.captureScreenshot', { format: 'png' });
    if (shot?.data) {
        writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/frontend-debug.png', Buffer.from(shot.data, 'base64'));
        console.log('Screenshot saved');
    }

    ws.close();
}

main().catch(e => console.error('FAIL:', e.message));

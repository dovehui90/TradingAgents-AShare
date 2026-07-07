import { readFileSync, writeFileSync } from 'fs';

const CDP = 'http://127.0.0.1:9222';
const TOKEN = readFileSync('d:/AIProjects/TradingAgents-AShare/_tmp_test_token.txt', 'utf-8').trim();

async function fetchJSON(url, opts = {}) {
    const r = await fetch(url, opts);
    return r.json();
}

async function newTab(url) {
    const tab = await fetchJSON(`${CDP}/json/new?url=${encodeURIComponent(url)}`);
    return { id: tab.id, wsUrl: tab.webSocketDebuggerUrl };
}

function wsSend(ws, msg) {
    return new Promise((resolve, reject) => {
        ws.send(JSON.stringify(msg));
        const handler = (e) => {
            const data = JSON.parse(e.data);
            if (data.id === msg.id) {
                ws.removeEventListener('message', handler);
                if (data.error) reject(data.error);
                else resolve(data.result);
            }
        };
        ws.addEventListener('message', handler);
    });
}

async function waitForLoad(ws, timeout = 8000) {
    return new Promise((resolve) => {
        ws.addEventListener('message', function handler(e) {
            const d = JSON.parse(e.data);
            if (d.method === 'Page.loadEventFired') {
                ws.removeEventListener('message', handler);
                setTimeout(resolve, 2000);
            }
        });
        ws.send(JSON.stringify({ id: 99, method: 'Page.enable' }));
        setTimeout(resolve, timeout);
    });
}

async function screenshot(ws, filepath) {
    const r = await wsSend(ws, { id: 50, method: 'Page.captureScreenshot', params: { format: 'png' } });
    writeFileSync(filepath, Buffer.from(r.data, 'base64'));
    console.log('Screenshot saved:', filepath);
}

async function getText(ws, selector) {
    const r = await wsSend(ws, {
        id: 60, method: 'Runtime.evaluate', params: {
            expression: `document.querySelector('${selector}')?.innerText || 'NOT_FOUND'`,
            returnByValue: true
        }
    });
    return r.result?.value || 'NOT_FOUND';
}

async function pageContains(ws, text) {
    const r = await wsSend(ws, {
        id: 61, method: 'Runtime.evaluate', params: {
            expression: `document.body.innerText.includes('${text}')`,
            returnByValue: true
        }
    });
    return r.result?.value || false;
}

async function injectToken(ws) {
    await wsSend(ws, {
        id: 70, method: 'Runtime.evaluate', params: {
            expression: `localStorage.setItem('ta-access-token', '${TOKEN}')`,
            returnByValue: true
        }
    });
    console.log('Token injected');
}

// ── Main Test ──
async function main() {
    console.log('=== 大盘点金前端自测 ===\n');

    // Test 1: Briefing page
    console.log('--- Test 1: Briefing page ---');
    const { wsUrl: wsUrl1 } = await newTab('http://127.0.0.1:5173/briefing');
    const ws1 = new WebSocket(wsUrl1);
    await new Promise(r => { ws1.onopen = r; setTimeout(r, 3000); });
    await waitForLoad(ws1);

    // Inject token and reload
    await injectToken(ws1);
    await wsSend(ws1, { id: 1, method: 'Page.navigate', params: { url: 'http://127.0.0.1:5173/briefing' } });
    await waitForLoad(ws1);

    // Select date 2026-06-18
    await wsSend(ws1, {
        id: 80, method: 'Runtime.evaluate', params: {
            expression: `
                const input = document.querySelector('input[type="date"]');
                if (input) { input.value = '2026-06-18'; input.dispatchEvent(new Event('change', { bubbles: true })); }
                'date_set'
            `,
            returnByValue: true
        }
    });
    await new Promise(r => setTimeout(r, 3000));

    // Verify DapanDianJin exists
    const yyTable1 = await pageContains(ws1, '大盘点金');
    const yyDate1 = await pageContains(ws1, '阳谱');
    const hasYang = await pageContains(ws1, '41.5');
    console.log('Briefing - 大盘点金 visible:', yyTable1);
    console.log('Briefing - 阳谱 label visible:', yyDate1);
    console.log('Briefing - yang_pct data visible:', hasYang);

    await screenshot(ws1, 'd:/AIProjects/TradingAgents-AShare/frontend/screenshots/briefing-test.png');
    ws1.close();

    // Test 2: MarketAnalysis page
    console.log('\n--- Test 2: MarketAnalysis page ---');
    const { wsUrl: wsUrl2 } = await newTab('http://127.0.0.1:5173/market-analysis');
    const ws2 = new WebSocket(wsUrl2);
    await new Promise(r => { ws2.onopen = r; setTimeout(r, 3000); });
    await waitForLoad(ws2);

    // Verify DapanDianJin exists
    const yyTable2 = await pageContains(ws2, '大盘点金');
    const yyDate2 = await pageContains(ws2, '阳谱');
    const hasYang2 = await pageContains(ws2, '41.5');
    console.log('MarketAnalysis - 大盘点金 visible:', yyTable2);
    console.log('MarketAnalysis - 阳谱 label visible:', yyDate2);
    console.log('MarketAnalysis - yang_pct data visible:', hasYang2);

    await screenshot(ws2, 'd:/AIProjects/TradingAgents-AShare/frontend/screenshots/market-analysis-test.png');
    ws2.close();

    console.log('\n=== 自测完成 ===');
    console.log('截图:', 'frontend/screenshots/briefing-test.png');
    console.log('截图:', 'frontend/screenshots/market-analysis-test.png');
}

main().catch(e => console.error('Error:', e.message));

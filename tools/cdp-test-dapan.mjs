// CDP test: Verify DapanDianJin panel on Briefing + Analysis pages
import http from 'http';
import fs from 'fs';

const TOKEN = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwZjVmZjE1Ny1jYTMwLTQ0MGEtYWQxNi02MDg1OTE1YWVmNTciLCJlbWFpbCI6ImFkbWluQHRyYWRpbmdhZ2VudHMuY29tIiwiZXhwIjoxNzg0NTY0NjIyLCJpYXQiOjE3ODE5NzI2MjJ9.JGhA7_jPGmanzBGCo6QNymx2PXVwVmBhyW-qbC-H21M`;

function cdp(method, path) {
  return new Promise((resolve, reject) => {
    http.request({hostname:'127.0.0.1',port:9222,path,method}, res => {
      let d=''; res.on('data',c=>d+=c); res.on('end',()=>resolve(JSON.parse(d)));
    }).on('error', reject).end();
  });
}

async function newTab(url) {
  return cdp('PUT', `/json/new?${encodeURIComponent(url || 'about:blank')}`);
}

function wsCmd(ws, id) {
  return (method, params) => {
    ws.send(JSON.stringify({id, method, params}));
  };
}

function wsPromise(ws, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('WS timeout')), timeout);
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id !== undefined && msg.result) {
        clearTimeout(timer);
        resolve(msg.result);
      }
    };
  });
}

async function wsOpen(ws) {
  return new Promise((resolve) => {
    if (ws.readyState === 1) { resolve(); return; }
    ws.onopen = () => resolve();
  });
}

async function screenshot(tab, filepath) {
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await wsOpen(ws);
  const send = wsCmd(ws, 1);
  const recv = wsPromise(ws);

  send('Page.enable');
  await recv;

  await new Promise(r => setTimeout(r, 2000));

  const send2 = wsCmd(ws, 2);
  const recv2 = wsPromise(ws);
  send2('Page.captureScreenshot', {format: 'png'});
  const result = await recv2;

  fs.writeFileSync(filepath, Buffer.from(result.data, 'base64'));
  console.log(`Screenshot saved: ${filepath}`);
  ws.close();
}

async function injectToken(tab) {
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await wsOpen(ws);
  const send = wsCmd(ws, 1);
  const recv = wsPromise(ws);

  send('Runtime.enable');
  await recv;

  const send2 = wsCmd(ws, 2);
  const recv2 = wsPromise(ws);
  send2('Runtime.evaluate', {
    expression: `localStorage.setItem('ta-access-token', '${TOKEN}'); 'done'`,
    returnByValue: true
  });
  const result = await recv2;
  console.log('Token injected:', result.result?.value);
  ws.close();
}

async function checkDapanDianJin(tab) {
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await wsOpen(ws);

  const send = wsCmd(ws, 1);
  const recv = wsPromise(ws);
  send('Runtime.enable');
  await recv;

  const tests = [
    ['h3', `document.querySelector('h3')?.innerText || 'no h3 found'`],
    ['阳谱', `document.body.innerText.includes('阳谱') ? 'YES' : 'NO'`],
    ['金', `document.body.innerText.includes('金') ? 'YES' : 'NO'`],
    ['大盘点金', `document.body.innerText.includes('大盘点金') ? 'YES' : 'NO'`],
    ['趋势行', `document.body.innerText.includes('趋势') ? 'YES' : 'NO'`],
    ['红三角', `document.body.innerHTML.includes('▲') ? 'YES' : 'NO'`],
    ['绿三角', `document.body.innerHTML.includes('▼') ? 'YES' : 'NO'`],
    ['bg-red-50', `document.body.innerHTML.includes('bg-red-50') ? 'YES' : 'NO'`],
    ['bg-green-50', `document.body.innerHTML.includes('bg-green-50') ? 'YES' : 'NO'`],
  ];

  for (let i = 0; i < tests.length; i++) {
    const [label, expr] = tests[i];
    const s = wsCmd(ws, i + 2);
    const r = wsPromise(ws);
    s('Runtime.evaluate', { expression: expr, returnByValue: true });
    const res = await r;
    console.log(`${label} check:`, res.result?.value);
  }

  ws.close();
}

async function navigateAndWait(tab, url, waitMs = 4000) {
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await wsOpen(ws);
  const send = wsCmd(ws, 1);
  const recv = wsPromise(ws);

  send('Page.enable');
  await recv;

  const send2 = wsCmd(ws, 2);
  const recv2 = wsPromise(ws);
  send2('Page.navigate', {url});
  await recv2;

  await new Promise(r => setTimeout(r, waitMs));
  ws.close();
}

async function main() {
  try {
    // === Test 1: Briefing page ===
    console.log('\n=== Test 1: Briefing page ===');

    const briefingTab = await newTab('http://127.0.0.1:5173/briefing');
    console.log('Briefing tab opened:', briefingTab.id);
    await new Promise(r => setTimeout(r, 1500));

    await injectToken(briefingTab);
    await navigateAndWait(briefingTab, 'http://127.0.0.1:5173/briefing', 5000);
    await checkDapanDianJin(briefingTab);
    await screenshot(briefingTab, 'd:/AIProjects/TradingAgents-AShare/frontend/screenshots/briefing-dapan.png');

    // === Test 2: Analysis page ===
    console.log('\n=== Test 2: Analysis page ===');

    const analysisTab = await newTab('http://127.0.0.1:5173/market-analysis');
    console.log('Analysis tab opened:', analysisTab.id);
    await new Promise(r => setTimeout(r, 1500));

    await injectToken(analysisTab);
    await navigateAndWait(analysisTab, 'http://127.0.0.1:5173/market-analysis', 8000);
    await checkDapanDianJin(analysisTab);
    await screenshot(analysisTab, 'd:/AIProjects/TradingAgents-AShare/frontend/screenshots/analysis-dapan.png');

    console.log('\n=== Done ===');
  } catch (err) {
    console.error('Error:', err);
  }
}

main();

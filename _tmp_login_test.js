const http = require('http');
const fs = require('fs');

function cdpReq(method, path, body) {
  return new Promise((resolve, reject) => {
    const req = http.request({hostname:'127.0.0.1',port:9222,path,method,headers:{'Content-Type':'application/json'}}, res => {
      let d=''; res.on('data',c=>d+=c); res.on('end',()=>resolve(JSON.parse(d)));
    });
    req.on('error', reject);
    if(body) req.write(JSON.stringify(body));
    req.end();
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  const tab = await cdpReq('PUT', '/json/new?url=' + encodeURIComponent('http://119.23.155.192'));
  console.log('Tab:', tab.id);

  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  const messages = [];

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    messages.push(msg);
    if(msg.method === 'Page.loadEventFired') {
      console.log('Page loaded event fired');
    }
  };

  await new Promise(r => ws.onopen = r);
  console.log('Connected');

  // Enable Page domain
  ws.send(JSON.stringify({id:0, method:'Page.enable'}));

  // Wait longer for React to render
  await sleep(5000);

  // Check what's on the page
  ws.send(JSON.stringify({id:1, method:'Runtime.evaluate', params:{expression: `
    JSON.stringify({
      url: location.href,
      title: document.title,
      bodyLen: document.body.innerText.length,
      body: document.body.innerText.substring(0, 800),
      inputCount: document.querySelectorAll('input').length,
      buttonCount: document.querySelectorAll('button').length,
      allButtons: [...document.querySelectorAll('button')].map(b => b.textContent.trim())
    })
  `, returnByValue: true}}));

  await sleep(1000);
  const resp1 = messages.find(m => m.id === 1);
  if(resp1) {
    const info = JSON.parse(resp1.result.result.value);
    console.log('URL:', info.url);
    console.log('Title:', info.title);
    console.log('BodyLen:', info.bodyLen);
    console.log('Inputs:', info.inputCount);
    console.log('Buttons:', info.buttonCount, info.allButtons);
    console.log('Body:', info.body.substring(0, 500));
  }

  // Take screenshot
  ws.send(JSON.stringify({id:9, method:'Page.captureScreenshot', params:{format:'png'}}));
  await sleep(2000);
  const resp9 = messages.find(m => m.id === 9);
  if(resp9 && resp9.result) {
    fs.writeFileSync('d:/AIProjects/TradingAgents-AShare/frontend/screenshots/login_step2.png', Buffer.from(resp9.result.data, 'base64'));
    console.log('Screenshot saved');
  }

  ws.close();
  process.exit(0);
}

main().catch(e => { console.error(e); process.exit(1); });
setTimeout(() => { console.log('Timeout'); process.exit(1); }, 30000);

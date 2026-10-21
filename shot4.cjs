const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await (await b.newContext({viewport:{width:1280,height:900}})).newPage();
  p.on('console', m => { if (m.type()==='error') console.log('CONSOLE_ERR:', m.text().slice(0,200)); });
  p.on('pageerror', e => console.log('PAGE_ERR:', String(e).slice(0,300)));
  await p.goto('http://localhost:8787/',{waitUntil:'load',timeout:15000});
  await p.waitForTimeout(2500);
  const text = await p.evaluate(() => document.querySelector('#page').innerText.slice(0,200));
  console.log('PAGE_CONTENT:', JSON.stringify(text));
  await b.close();
})();

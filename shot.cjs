const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await (await b.newContext({viewport:{width:1280,height:900}})).newPage();
  for (const [url,name] of [['https://www.clay.com','clay-home'],['https://app.clay.com','clay-app']]) {
    try { await p.goto(url,{waitUntil:'networkidle',timeout:30000}); } catch(e){}
    await p.waitForTimeout(1500);
    await p.screenshot({path:'/tmp/'+name+'.png'});
  }
  await b.close();
})();

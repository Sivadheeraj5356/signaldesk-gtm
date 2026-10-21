const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await (await b.newContext({viewport:{width:1440,height:1600}})).newPage();
  await p.goto('http://127.0.0.1:8787/',{waitUntil:'load',timeout:20000});
  await p.waitForTimeout(1500);
  await p.evaluate(()=>window.scrollTo(0,700));
  await p.waitForTimeout(600);
  await p.screenshot({path:'/tmp/iso-landing-sample.png'});
  await b.close();
})();

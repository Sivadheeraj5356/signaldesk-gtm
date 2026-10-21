const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch();
  for (const enabled of [true,false]) {
    const html = fs.readFileSync('login.html','utf8').replace('__GOOGLE_ENABLED__', enabled ? 'true' : 'false');
    for (const [w,h,tag] of [[1280,900,'d'],[390,844,'m']]) {
      const p = await (await b.newContext({viewport:{width:w,height:h}})).newPage();
      await p.setContent(html, {waitUntil:'load'});
      await p.waitForTimeout(300);
      await p.screenshot({path:`/tmp/sd-login-${tag}${enabled?'-g':''}.png`});
      await p.close();
    }
  }
  await b.close();
})();

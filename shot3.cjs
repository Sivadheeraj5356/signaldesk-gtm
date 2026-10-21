const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const tabs = ['overview','accounts','workflow','drafts'];
  for (const [w,h,tag] of [[1280,900,'d'],[390,844,'m']]) {
    const ctx = await b.newContext({viewport:{width:w,height:h}});
    const p = await ctx.newPage();
    await p.goto('http://localhost:8787/',{waitUntil:'load',timeout:15000});
    for (const t of tabs) {
      if (t!=='overview') { await p.click(`button[data-tab="${t}"]`); await p.waitForTimeout(700); }
      await p.screenshot({path:`/tmp/sd-app-${tag}-${t}.png`});
    }
    await ctx.close();
  }
  await b.close();
})();

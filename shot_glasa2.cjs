const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const shots = [
    ['landing-d','http://127.0.0.1:8787/',{width:1280,height:900}],
    ['landing-m','http://127.0.0.1:8787/',{width:390,height:844}],
    ['signin-d','http://127.0.0.1:8787/sign-in',{width:1280,height:900}],
    ['dash-d','http://127.0.0.1:8788/',{width:1280,height:900}],
    ['dash-m','http://127.0.0.1:8788/',{width:390,height:844}],
  ];
  for (const [name,url,vp] of shots){
    const ctx = await b.newContext({viewport:vp});
    const p = await ctx.newPage();
    p.on('pageerror', e => console.log(name,'PAGE_ERR:', String(e).slice(0,150)));
    await p.goto(url,{waitUntil:'networkidle',timeout:20000}).catch(e=>console.log(name,'nav',e.message));
    await p.waitForTimeout(2200);
    await p.screenshot({path:'/tmp/sd-glasa-'+name+'.png'});
    console.log(name,'done');
    await ctx.close();
  }
  await b.close();
})();

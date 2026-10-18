import { test, expect } from '@playwright/test';
import { status, history, triage, issue, pr, commit } from './fixtures.js';

async function bootstrap(page, options={}) {
  await page.context().route('https://github.com/**',route=>route.fulfill({contentType:'text/html',body:'<p>Test source page</p>'}));
  await page.route('https://fonts.googleapis.com/**',route=>route.abort());
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/status') return route.fulfill({json:options.status || status});
    if(path==='/api/evaluation') return route.fulfill({status:404,json:{detail:'No saved evaluation'}});
    return route.fulfill({status:503,json:{detail:'Unexpected test request'}});
  });
}
async function openApp(page) {
  await page.goto('/');
  await expect(page.getByText('FalkorDB connected',{exact:true})).toBeVisible();
}
async function preview(page, result=triage()) {
  await page.route('**/api/query',route=>route.fulfill({json:result}));
  await page.getByRole('button',{name:'Issue triage',exact:true}).click();
  await page.getByRole('button',{name:'Preview triage →',exact:true}).click();
  await expect(page.getByText('1 likely functions')).toBeVisible();
}

function queryCompletion(page) {
  return new Promise(resolve=>{
    const complete=request=>{
      if (!request.url().endsWith('/api/query')) return;
      page.off('requestfinished',complete);
      page.off('requestfailed',complete);
      resolve();
    };
    page.on('requestfinished',complete);
    page.on('requestfailed',complete);
  });
}

for(const edit of ['title','description','issue number','cutoff','workflow']) {
  test(`pending preview is ignored after changing ${edit}`,async({page})=>{
    await bootstrap(page);
    let release, received, delivered;
    const gate=new Promise(resolve=>release=resolve);
    const arrived=new Promise(resolve=>received=resolve);
    const responseDelivered=new Promise(resolve=>delivered=resolve);
    const completed=queryCompletion(page);
    await page.route('**/api/query',async route=>{
      received();
      await gate;
      // The browser may already have aborted this request.
      await route.fulfill({json:triage()}).catch(()=>{});
      delivered();
    });
    await openApp(page);
    await page.getByRole('button',{name:'Issue triage',exact:true}).click();
    await expect(page.getByText('Describe an issue. Follow the evidence.')).toBeVisible();
    await page.getByRole('button',{name:'Preview triage →',exact:true}).click();
    await arrived;
    await expect(page.getByRole('button',{name:'Following graph evidence…'})).toBeVisible();
    if(edit==='title') await page.getByLabel('Issue title',{exact:true}).fill('Edited while loading');
    if(edit==='description') await page.getByLabel('Description',{exact:true}).fill('Edited description');
    if(edit==='issue number') await page.getByLabel('Fork issue number').fill('2');
    if(edit==='cutoff') {
      await page.getByText('Historical cutoff',{exact:true}).click();
      await page.getByLabel('As of (ISO timestamp, with timezone)',{exact:true}).fill('2020-01-01T00:00:00Z');
    }
    if(edit==='workflow') await page.getByRole('button',{name:'Function history',exact:true}).click();
    release();
    await responseDelivered;
    await completed;
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    // Verify after releasing the old response, then run a newer request and prove it wins.
    await expect(page.locator('.candidate')).toHaveCount(0);
    await expect(page.locator('.graph')).toHaveCount(0);
    await page.unroute('**/api/query');
    await page.route('**/api/query',route=>route.fulfill({json:history()}));
    await page.getByRole('button',{name:'Function history',exact:true}).click();
    await page.getByRole('button',{name:'Trace function history →',exact:true}).click();
    await expect(page.getByText('1 historical records across 1 commits',{exact:false})).toBeVisible();
    await expect(page.locator('.candidate')).toHaveCount(0);
  });
}

test('late history response cannot appear in the triage tab',async({page})=>{
  await bootstrap(page);
  let release,received,delivered;
  const gate=new Promise(resolve=>release=resolve),arrived=new Promise(resolve=>received=resolve);
  const responseDelivered=new Promise(resolve=>delivered=resolve);
  const completed=queryCompletion(page);
  await page.route('**/api/query',async route=>{received();await gate;await route.fulfill({json:history()}).catch(()=>{});delivered();});
  await openApp(page);
  await page.getByRole('button',{name:'Trace function history →',exact:true}).click();
  await arrived;
  await page.getByRole('button',{name:'Issue triage',exact:true}).click();
  release();
  await responseDelivered;
  await completed;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await expect(page.getByText('Describe an issue. Follow the evidence.')).toBeVisible();
  await expect(page.locator('.timeline')).toHaveCount(0);
});

test('backend query failure clears old findings and can be retried',async({page})=>{
  await bootstrap(page);
  await openApp(page);
  await preview(page);
  await page.route('**/api/query',route=>route.fulfill({status:503,json:{detail:'Operation failed. Check the local backend logs and FalkorDB connection.'}}));
  await page.getByRole('button',{name:'Preview triage →',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('FalkorDB connection');
  await expect(page.locator('.candidate')).toHaveCount(0);
  await page.route('**/api/query',route=>route.fulfill({json:triage()}));
  await page.getByRole('button',{name:'Preview triage →',exact:true}).click();
  await expect(page.getByText('1 likely functions')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('unreachable backend shows a readable connection error',async({page})=>{
  await bootstrap(page);
  await page.route('**/api/status',route=>route.abort('connectionrefused'));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Cannot reach the backend');
  await expect(page.getByRole('button',{name:'Trace function history →',exact:true})).toBeDisabled();
});

test('validation errors are readable, including structured API errors',async({page})=>{
  await bootstrap(page);
  await page.route('**/api/query',route=>route.fulfill({status:422,json:{detail:'Enter a valid ISO timestamp with a timezone, for example 2026-10-04T00:00:00Z.'}}));
  await openApp(page);
  await page.getByText('Historical cutoff',{exact:true}).click();
  await page.getByLabel('As of (ISO timestamp, with timezone)',{exact:true}).fill('abc');
  await page.getByRole('button',{name:'Trace function history →',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('2026-10-04T00:00:00Z');
  await page.route('**/api/query',route=>route.fulfill({status:422,json:{detail:[{msg:'Title must be shorter than 500 characters'}]}}));
  await page.getByRole('button',{name:'Trace function history →',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveText('Title must be shorter than 500 characters');
});

test('history groups duplicate commits, preserves paths, and shows remaining commits',async({page})=>{
  await bootstrap(page);
  await page.route('**/api/query',route=>route.fulfill({json:history(25)}));
  await openApp(page);
  await page.getByRole('button',{name:'Trace function history →',exact:true}).click();
  await expect(page.getByText('26 historical records across 25 commits',{exact:false})).toBeVisible();
  await expect(page.locator('.timeline > article')).toHaveCount(20);
  await expect(page.getByRole('link',{name:commit.sha.slice(0,8),exact:true})).toHaveCount(1);
  await page.getByText('2 evidence paths',{exact:true}).click();
  await expect(page.locator('.timeline article').first().getByText('click/_termui_impl.py',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Show more history',exact:true}).click();
  await expect(page.locator('.timeline > article')).toHaveCount(25);
  await expect(page.getByText('Showing 25 of 25 commits',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Show more history',exact:true})).toHaveCount(0);
});

test('source links open the right page and empty impact has a clear explanation',async({page})=>{
  await bootstrap(page);
  await openApp(page);
  await preview(page);
  for(const [name,url] of [['Issue #651',issue.url],['PR #706',pr.url],['8780a763',commit.url],['Verified source span ↗',pr.url]]) {
    const link=page.getByRole('link',{name,exact:true}).first();
    await expect(link).toHaveAttribute('href',url);
    const opened=page.waitForEvent('popup');
    await link.click();
    const popup=await opened;
    await expect(popup).toHaveURL(url);
    await popup.close();
  }
  await page.getByText('Blast radius and reviewers',{exact:true}).click();
  await expect(page.getByText('No statically resolved callers found. Dynamic calls may not be detected.')).toBeVisible();
  await expect(page.getByRole('link',{name:'evidence ↗',exact:true})).toHaveAttribute('href',pr.url);
});

test('graph supports zoom, pan, reset, and opening a source node',async({page})=>{
  await bootstrap(page);
  await openApp(page);
  await preview(page);
  const graph=page.getByRole('img',{name:'Interactive evidence graph connecting issues, pull requests, commits, and functions'});
  await expect(graph.locator('canvas').first()).toBeVisible();
  const zoom=page.getByRole('status',{name:'Graph zoom'});
  const initial=await zoom.textContent();
  await page.getByRole('button',{name:'Zoom in',exact:true}).click();
  await expect(zoom).not.toHaveText(initial);
  await page.getByRole('button',{name:'Reset view',exact:true}).click();
  await expect(zoom).toHaveText(initial);
  await graph.scrollIntoViewIfNeeded();
  const before=await graph.screenshot();
  const box=await graph.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height*.8);
  await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+55,box.y+box.height*.8+25,{steps:8});
  await page.mouse.up();
  expect((await graph.screenshot()).equals(before)).toBe(false);
  await page.getByRole('button',{name:'Reset view',exact:true}).click();
  await expect(zoom).toHaveText(initial);
  const fraction=Number((await zoom.textContent()).match(/\d+/)[0])/100;
  // Fixture nodes are at x=0,200,400,800 and y=0; fit centers their bounding box at x=400.
  await graph.click({position:{x:box.width/2-400*fraction,y:box.height/2}});
  const source=page.getByRole('link',{name:'Open selected source ↗'});
  await expect(source).toHaveAttribute('href',issue.url);
  const opened=page.waitForEvent('popup');
  await source.click();
  const popup=await opened;
  await expect(popup).toHaveURL(issue.url);
  await popup.close();
  await page.getByRole('button',{name:'All returned evidence'}).click();
  await expect(page.getByRole('button',{name:'Focus evidence path'})).toHaveAttribute('aria-pressed','true');
});

test('posting sends the reviewed preview ID and displays stale-issue rejection',async({page})=>{
  await bootstrap(page,{status:{...status,posting_configured:true,fork:'alice/click'}});
  const reviewed={...triage(),preview_id:'reviewed-preview',preview_expires_at:'2099-01-01T00:00:00Z'};
  let posted;
  await page.route('**/api/query',async route=>{
    const payload=route.request().postDataJSON();
    if(payload.post) {posted=payload;return route.fulfill({status:422,json:{detail:'Fork issue changed since preview; generate a fresh preview'}});}
    return route.fulfill({json:reviewed});
  });
  await openApp(page);
  await page.getByRole('button',{name:'Issue triage',exact:true}).click();
  await page.getByLabel('Fork issue number').fill('1');
  await page.getByRole('button',{name:'Preview triage →',exact:true}).click();
  await expect(page.getByText('1 likely functions')).toBeVisible();
  await page.getByText('GitHub comment preview',{exact:true}).click();
  await expect(page.getByText('Exact reviewed comment',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Post triage comment to my fork',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('changed since preview');
  expect(posted.preview_id).toBe('reviewed-preview');
  expect(posted.issue_number).toBe(1);
  await expect(page.getByText('Exact reviewed comment',{exact:true})).toBeVisible();
  await page.getByLabel('Issue title',{exact:true}).fill('Edited');
  await expect(page.getByRole('button',{name:'Post triage comment to my fork',exact:true})).toHaveCount(0);
});

test('successful posting keeps reviewed content and locks inputs until the outcome arrives',async({page})=>{
  await bootstrap(page,{status:{...status,posting_configured:true,fork:'alice/click'}});
  const reviewed={...triage(),preview_id:'reviewed-preview',preview_expires_at:'2099-01-01T00:00:00Z'};
  let release,received;
  const gate=new Promise(resolve=>release=resolve),arrived=new Promise(resolve=>received=resolve);
  const url='https://github.com/alice/click/issues/1#issuecomment-123';
  await page.route('**/api/query',async route=>{
    if(route.request().postDataJSON().post) {received();await gate;return route.fulfill({json:{...reviewed,action:{url,already_posted:false}}});}
    return route.fulfill({json:reviewed});
  });
  await openApp(page);
  await page.getByRole('button',{name:'Issue triage',exact:true}).click();
  await page.getByLabel('Fork issue number').fill('1');
  await page.getByRole('button',{name:'Preview triage →',exact:true}).click();
  await expect(page.getByText('1 likely functions')).toBeVisible();
  await page.getByText('GitHub comment preview',{exact:true}).click();
  await page.getByRole('button',{name:'Post triage comment to my fork',exact:true}).click();
  await arrived;
  await expect(page.getByLabel('Issue title',{exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Function history',exact:true})).toBeDisabled();
  await expect(page.getByText('Exact reviewed comment',{exact:true})).toBeVisible();
  release();
  await expect(page.getByRole('link',{name:'Open posted comment ↗',exact:true})).toHaveAttribute('href',url);
  await expect(page.getByLabel('Issue title',{exact:true})).toBeEnabled();
  await expect(page.getByRole('button',{name:'Function history',exact:true})).toBeEnabled();
  await expect(page.getByText('Exact reviewed comment',{exact:true})).toBeVisible();
});

const repoA={repository_id:'repo-a',identity:'fixture/alpha',status:'ready',indexed_ref:'a'.repeat(40),counts:{Symbol:2,Commit:1,Issue:0}};
const repoB={...repoA,repository_id:'repo-b',identity:'fixture/beta',indexed_ref:'b'.repeat(40)};
const chatResult={answer:'Verified source in alpha',mode:'retrieval_only',repository_id:'repo-a',conversation_id:'conversation-a',findings:[],evidence:[],tools_used:['search_code'],trace:[]};
async function repositoryBootstrap(page) {
  await bootstrap(page);
  await page.route('**/api/repositories',route=>route.fulfill({json:{repositories:[{repository_id:'default',identity:'pallets/click',status:'default'},repoA,repoB]}}));
  await openApp(page);
  await page.getByLabel('Selected repository').selectOption('repo-a');
  await page.getByLabel('Describe what is happening').fill('Where is retry implemented?');
}

test('repository switch clears findings and conversation context',async({page})=>{
  await repositoryBootstrap(page);
  const requests=[];
  await page.route('**/api/chat',route=>{requests.push(route.request().postDataJSON());return route.fulfill({json:chatResult});});
  await page.getByRole('button',{name:'Investigate →',exact:true}).click();
  await expect(page.getByText(chatResult.answer,{exact:true})).toBeVisible();
  await page.getByLabel('Selected repository').selectOption('repo-b');
  await expect(page.getByText(chatResult.answer,{exact:true})).toHaveCount(0);
  await page.getByLabel('Describe what is happening').fill('Where is authentication?');
  await page.getByRole('button',{name:'Investigate →',exact:true}).click();
  await expect.poll(()=>requests.length).toBe(2);
  expect(requests[1].repo_id).toBe('repo-b');
  expect(requests[1].conversation_id).toBeNull();
});

test('late investigation cannot restore a prior repository conversation',async({page})=>{
  await repositoryBootstrap(page);
  let release, arrived;
  const gate=new Promise(resolve=>release=resolve);
  const received=new Promise(resolve=>arrived=resolve);
  const requests=[];
  await page.route('**/api/chat',async route=>{requests.push(route.request().postDataJSON());if(requests.length===1){arrived();await gate;}await route.fulfill({json:chatResult}).catch(()=>{});});
  await page.getByRole('button',{name:'Investigate →',exact:true}).click();
  await received;
  await page.getByLabel('Selected repository').selectOption('repo-b');
  release();
  await page.getByLabel('Describe what is happening').fill('network retry');
  await page.getByRole('button',{name:'Investigate →',exact:true}).click();
  await expect.poll(()=>requests.length).toBe(2);
  expect(requests[1].conversation_id).toBeNull();
  expect(requests[1].repo_id).toBe('repo-b');
});

test('failed ingestion is visible and refresh starts recovery',async({page})=>{
  await bootstrap(page);
  await page.route('**/api/repositories',route=>route.fulfill({json:{repositories:[{...repoA,status:'failed',error:'Clone failed: rate limit'}]}}));
  await page.route('**/api/repositories/repo-a/refresh',route=>route.fulfill({json:{job_id:'refresh-1',status:'queued',stage:'queued',progress:0}}));
  await openApp(page);
  await page.getByLabel('Selected repository').selectOption('repo-a');
  await expect(page.getByRole('alert')).toContainText('Clone failed');
  await expect(page.getByRole('button',{name:'Investigate →',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Refresh repository',exact:true}).click();
  await expect(page.getByRole('button',{name:'Refresh repository',exact:true})).toBeDisabled();
});

test('repository refresh sends the configured admin token',async({page})=>{
  await repositoryBootstrap(page);
  await page.getByText('Admin access',{exact:true}).click();
  await page.getByLabel('Admin token (if configured)').fill('fixture-admin-secret');
  let authorization;
  await page.route('**/api/repositories/repo-a/refresh',route=>{
    authorization=route.request().headers().authorization;
    return route.fulfill({json:{job_id:'authorized-refresh',status:'queued',stage:'queued',progress:0}});
  });
  await page.getByRole('button',{name:'Refresh repository',exact:true}).click();
  await expect.poll(()=>authorization).toBe('Bearer fixture-admin-secret');
});

test('investigation separates model-selected calls from retrieval and shows stop reasons',async({page})=>{
  await bootstrap(page);
  await openApp(page);
  await page.route('**/api/chat',route=>route.fulfill({json:{
    mode:'model_assisted',answer:'Inspect the verified implementation.',findings:[],evidence:[],
    agent_execution:{status:'completed',steps:[{round:1,tool:'trace_callers',status:'completed',purpose:'Check which function invokes the generator.',arguments:{symbol:'ProgressBar.generator'},result:'{"trace_callers":[{"qualified_name":"ProgressBar.__iter__"}]}',evidence_ids:[],elapsed_ms:12}],stop_reason:'Answer cites verified evidence; investigation complete.'},
    trace:['Bootstrap retrieval'],
  }}));
  await page.getByRole('button',{name:'Investigate',exact:true}).click();
  await page.getByLabel('Describe what is happening').fill('Why does progress advance early?');
  await page.getByRole('button',{name:'Investigate →',exact:true}).click();
  const record=page.getByRole('region',{name:'Model execution record'});
  await expect(record).toContainText('trace_callers');
  await expect(record).toContainText('Check which function invokes the generator.');
  await record.getByText('Arguments and returned evidence').click();
  await expect(record).toContainText('ProgressBar.__iter__');
  await expect(record).toContainText('investigation complete');
  await page.route('**/api/chat',route=>route.fulfill({json:{mode:'retrieval_only',answer:'Verified retrieval results.',findings:[],evidence:[],agent_execution:{status:'not_configured',steps:[],stop_reason:'Configure model credentials and restart.'},trace:[]}}));
  await page.getByRole('button',{name:'Investigate →',exact:true}).click();
  await expect(record).toContainText('No model-selected tool calls were executed.');
  await expect(record).toContainText('not configured');
  await expect(record).not.toContainText('trace_callers');
});

test('focused graph stays legible and inspectable in a narrow browser panel',async({page})=>{
  await page.setViewportSize({width:390,height:1000});
  await bootstrap(page);
  await openApp(page);
  await preview(page);
  const graph=page.getByRole('img',{name:'Interactive evidence graph connecting issues, pull requests, commits, and functions'});
  await graph.scrollIntoViewIfNeeded();
  const zoom=Number((await page.getByRole('status',{name:'Graph zoom'}).textContent()).match(/\d+/)[0])/100;
  expect(zoom).toBeGreaterThan(.7);
  const box=await graph.boundingBox();
  // Narrow layouts put stages vertically at y=0,100,200,400.
  await graph.click({position:{x:box.width/2,y:box.height/2-200*zoom}});
  await expect(page.getByRole('link',{name:'Open selected source ↗'})).toHaveAttribute('href',issue.url);
});

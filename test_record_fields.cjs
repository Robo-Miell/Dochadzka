const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('quality/static/app.js','utf8');
const context={esc:v=>String(v).replaceAll('<','&lt;').replaceAll('>','&gt;')};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function searchText'),source.indexOf('function multiSelectMarkup')),context);
test('duration inserts colon while typing numeric HHMM and accepts explicit colon',()=>{
  for(const [value,expected] of [['1','1'],['12','12'],['122','12:2'],['12:23','12:23'],['1223','12:23'],['0120','01:20'],['1:20','1:20'],['','']])
    assert.equal(context.maskWorkTime(value),expected);
});
test('work duration pads hours and minutes without changing invalid input',()=>{
  for(const [value,expected] of [['1:20','01:20'],['0:5','00:05'],['08:00','08:00'],['1:90','1:90'],['','']])
    assert.equal(context.normalizeWorkTime(value),expected);
});
test('filter text ignores case and accents',()=>{
  assert.equal(context.searchText('ŠKRABANEC').includes(context.searchText('skraba')),true);
});
test('error column uses saved names, counts, and escapes markup',()=>{
  assert.equal(context.recordErrors({job_snapshot_obj:{errors:[{id:1,name:'<chyba>'},{id:2,name:'Other'}]},error_counts_obj:{'1':3,'2':0}}),'&lt;chyba&gt; — 3 ks');
});

function operatorDetailHarness(api){
  const elements=new Map([['#view',{innerHTML:''}]]),downloads=[];
  const ctx={URLSearchParams,Intl,Date,state:{user:{role:'operator'},view:'jobdetail'},api,
    $:s=>{if(elements.has(s))return elements.get(s);if(elements.get('#view').innerHTML.includes(`id="${s.slice(1)}"`)){const el={value:''};elements.set(s,el);return el}return null},
    esc:context.esc,setTitle:()=>{},kpi:(name,value)=>`${name}=${value}`,
    recordHeader:(admin,actions)=>{assert.equal(admin,false);assert.equal(actions,false);return ''},
    tableRows:(rows,admin,actions)=>{assert.equal(admin,false);assert.equal(actions,false);return 'own-records'},
    bindOpenJobs:()=>{},go:()=>{},downloadFile:url=>downloads.push(url)};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('async function renderJobDetail'),source.indexOf('function recordHeader')),ctx);
  return {ctx,elements,downloads};
}

test('operator job link loads own records without admin summary or controls',async()=>{
  const calls=[];
  const {ctx,elements,downloads}=operatorDetailHarness(async url=>{
    calls.push(url);
    if(url==='/api/jobs/7')return {job:{order_number:'TEST',brief_description:'Description'}};
    if(url==='/api/records?job_id=7')return {records:[{checked_items:10,ok_items:8,nok_items:2}]};
    throw new Error('Forbidden admin endpoint: '+url);
  });
  await ctx.renderJobDetail(7);
  assert.equal(calls.length,2);
  const html=elements.get('#view').innerHTML;
  assert.match(html,/Checked=10/);assert.match(html,/NOK rate=20.00%/);
  assert.doesNotMatch(html,/Načítavam|jobEdit|jobDelete|jdSendNow/);
  ctx.$('#opFrom').value='2026-09-01';ctx.$('#opTo').value='2026-09-24';
  elements.get('#opPdf').onclick();
  assert.equal(downloads[0],'/api/export/pdf?job_id=7&date_from=2026-09-01&date_to=2026-09-24');
});

test('operator detail replaces loading with error and can retry',async()=>{
  let fail=true;
  const {ctx,elements}=operatorDetailHarness(async url=>{
    if(fail)throw new Error('HTTP 403');
    return url.startsWith('/api/jobs/')?{job:{order_number:'TEST'}}:{records:[]};
  });
  await ctx.renderJobDetail(7);
  assert.match(elements.get('#view').innerHTML,/HTTP 403/);
  assert.doesNotMatch(elements.get('#view').innerHTML,/Načítavam/);
  fail=false;await elements.get('#opRetry').onclick();
  assert.match(elements.get('#view').innerHTML,/Records=0/);
});

const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
  const events = [];
  const field = {id:'rDelivery', value:'old', isConnected:true,
    dispatchEvent:e=>events.push(e.type), focus:()=>{}};
  let click, requests = 0;
  const window = {MiellScanner:{postMessage:id=>{
    assert.equal(id,'rDelivery'); requests++;
  }}};
  const document = {addEventListener:(name,handler)=>{if(name==='click')click=handler;},
    getElementById:()=>field};
  vm.runInNewContext(fs.readFileSync(__dirname+'/quality/static/scanner.js','utf8'),
    {window,document,Event:class {constructor(type){this.type=type;}}});
  return {field,events,window,requests:()=>requests,click:()=>click({
    target:{closest:()=>({dataset:{scanTarget:'rDelivery'}})},preventDefault:()=>{},
  })};
}
test('confirmed scan preserves leading zeroes and only fills the requested field',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult('000123/AB');
  assert.equal(s.field.value,'000123/AB');assert.deepEqual(s.events,['input','change']);
});
test('cancel leaves existing value unchanged and allows retry',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult(null);s.click();
  assert.equal(s.field.value,'old');assert.equal(s.requests(),2);
});
test('duplicate taps do not open two cameras',()=>{
  const s=setup();s.click();s.click();assert.equal(s.requests(),1);
});
test('leaving the form discards a late scan result',()=>{
  const s=setup();s.click();s.field.isConnected=false;s.window.miellBarcodeResult('new');
  assert.equal(s.field.value,'old');
});
test('barcode text is never interpreted as HTML',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult('<script>alert(1)</script>');
  assert.equal(s.field.value,'<script>alert(1)</script>');
});

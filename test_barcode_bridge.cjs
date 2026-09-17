const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup() {
  const alerts=[];
  const make=(id,value)=>({id,value,isConnected:true,events:[],dispatchEvent(e){this.events.push(e.type);}});
  const field=make('rDelivery','old');
  const part=make('rPart','1'); part.options=[{value:'2',dataset:{itemNumber:'00123'}}];
  const checked=make('rChecked','7');
  let click,requests=0;
  const window={MiellScanner:{postMessage:()=>requests++}};
  const document={addEventListener:(n,h)=>{if(n==='click')click=h;},getElementById:id=>({rDelivery:field,rPart:part,rChecked:checked})[id]};
  vm.runInNewContext(fs.readFileSync(__dirname+'/quality/static/scanner.js','utf8'),{window,document,alert:s=>alerts.push(s),Event:class{constructor(type){this.type=type;}}});
  return {field,part,checked,alerts,window,requests:()=>requests,click:()=>click({target:{closest:()=>({dataset:{scanTarget:'rDelivery'}})},preventDefault:()=>{}})};
}
test('P S Q fill their fields without prefixes and preserve text zeroes',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult(['P00123','S000456','Q0020']);
  assert.equal(s.part.value,'2');assert.equal(s.field.value,'000456');assert.equal(s.checked.value,'20');
  assert.deepEqual(s.checked.events,['input','change']);assert.equal(s.alerts.length,0);
});
test('combined label and repeated identical codes',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult(['P00123\nS000456\x1dQ0','S000456']);
  assert.equal(s.field.value,'000456');assert.equal(s.checked.value,'0');assert.equal(s.alerts.length,0);
});
test('unknown prefix does not overwrite',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult('X123');assert.equal(s.field.value,'old');assert.equal(s.checked.value,'7');
});
test('invalid quantities do not overwrite',()=>{
  for(const code of ['Q-1','Q1.5','Qabc','Q9007199254740992']){
    const s=setup();s.click();s.window.miellBarcodeResult(code);assert.equal(s.checked.value,'7');assert.equal(s.alerts.length,1);
  }
});
test('unknown part retains selection while valid delivery is applied',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult(['Punknown','S123']);assert.equal(s.part.value,'1');assert.equal(s.field.value,'123');assert.equal(s.alerts.length,1);
});
test('conflicting codes do not overwrite their field',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult(['S123','S456']);assert.equal(s.field.value,'old');assert.equal(s.alerts.length,1);
});
test('cancel and duplicate taps preserve values and allow retry',()=>{
  const s=setup();s.click();s.click();assert.equal(s.requests(),1);s.window.miellBarcodeResult(null);s.click();assert.equal(s.requests(),2);assert.equal(s.field.value,'old');
});
test('late scan after leaving form is ignored',()=>{
  const s=setup();s.click();s.field.isConnected=false;s.window.miellBarcodeResult('Snew');assert.equal(s.field.value,'old');
});
test('scanned values remain editable manually',()=>{
  const s=setup();s.click();s.window.miellBarcodeResult(['Sabc','Q20']);s.field.value='manual';s.checked.value='25';assert.equal(s.field.value,'manual');assert.equal(s.checked.value,'25');
});

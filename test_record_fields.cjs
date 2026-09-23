const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('quality/static/app.js','utf8');
const context={esc:v=>String(v).replaceAll('<','&lt;').replaceAll('>','&gt;')};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function searchText'),source.indexOf('function multiSelectMarkup')),context);
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

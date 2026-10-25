'use strict';
const $ = id => document.getElementById(id);
const state = {step:0, requirements:[], files:[], results:null, inspected:[], busy:false, ai:false};
const names = ['The brief','Your files','Final check','Pack & relax'];
const kinds = {exists:'File exists',max_pages:'Maximum pages',min_count:'Minimum file count',contains:'Contains exact text',filename:'Original filename equals',manual:'Human review'};
const targets = {report:'Report',code:'Source code',screenshot:'Screenshots',other:'Other files',any:'All files'};
const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let toastTimer;
function toast(message, error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,error?10000:5000);}
function invalidate(){state.results=null;state.inspected=[];$('acknowledge').checked=false;updateExport();}
function navigate(step){
 if(state.busy)return;
 if(step>=2&&!state.results){toast('Upload your files and run final checks first.');return;}
 state.step=step;
 for(let i=0;i<4;i++)$('step'+i).hidden=i!==step;
 document.querySelectorAll('[data-step]').forEach(el=>{el.classList.toggle('active',Number(el.dataset.step)===step);el.classList.toggle('done',Number(el.dataset.step)<step);});
 $('crumb').textContent=names[step];if(step===3)renderPackage();
 document.querySelector('.stepper').scrollIntoView({behavior:'smooth',block:'start'});
}
async function api(path,options={}){
 const res=await fetch(path,options);
 if(!res.ok){let msg='Request failed. Please try again.';try{msg=(await res.json()).error||msg;}catch{}throw new Error(msg);}
 return res;
}
async function busy(button,label,job){
 if(state.busy)return;state.busy=true;
 const controls=[...document.querySelectorAll('button,input,select,textarea')].map(el=>[el,el.disabled]);
 controls.forEach(([el])=>el.disabled=true);
 const old=button.textContent;button.textContent=label;button.classList.add('busy');
 try{await job();}catch(err){toast(err.message||'Could not complete this action.',true);}
 finally{controls.forEach(([el,d])=>el.disabled=d);button.textContent=old;button.classList.remove('busy');state.busy=false;updateAI();updateExport();}
}
function updateAI(){$('extractBtn').disabled=!state.ai||state.busy;}
function options(map,current){return Object.entries(map).map(([v,l])=>`<option value="${v}" ${v===current?'selected':''}>${l}</option>`).join('');}
function renderRequirements(){
 $('reqCount').textContent=state.requirements.length;$('reqEmpty').hidden=state.requirements.length>0;
 $('requirements').innerHTML=state.requirements.map((r,i)=>`<div class="req-row" data-index="${i}"><div class="req-top"><span class="req-index">${String(i+1).padStart(2,'0')}</span><input aria-label="Requirement ${i+1} description" data-field="label" value="${escape(r.label)}" maxlength="300" placeholder="What needs to be included?"><button class="remove" data-remove-req="${i}" aria-label="Remove requirement ${i+1}">×</button></div><div class="req-controls"><label>Check type<select data-field="kind">${options(kinds,r.kind)}</select></label><label>Applies to<select data-field="target">${options(targets,r.target)}</select></label><label>Value<input data-field="value" value="${escape(r.value)}" maxlength="300" placeholder="${r.kind==='manual'||r.kind==='exists'?'Not required':'e.g. 2, Imran, report.pdf'}" ${r.kind==='manual'||r.kind==='exists'?'disabled':''}></label></div>${r.source_quote?`<p class="source-quote">Source: ${escape(r.source_quote)}</p>`:''}</div>`).join('');
}
$('requirements').addEventListener('input',e=>{const field=e.target.dataset.field;if(!field)return;const i=+e.target.closest('[data-index]').dataset.index;state.requirements[i][field]=e.target.value;invalidate();if(field==='kind')renderRequirements();});
$('requirements').addEventListener('click',e=>{const b=e.target.closest('[data-remove-req]');if(!b)return;state.requirements.splice(+b.dataset.removeReq,1);invalidate();renderRequirements();});
$('addReq').onclick=()=>{if(state.requirements.length>=50)return toast('Maximum 50 requirements.',true);state.requirements.push({label:'',kind:'manual',target:'report',value:'',source_quote:''});invalidate();renderRequirements();$('requirements').lastElementChild.querySelector('input').focus();};
$('brief').addEventListener('input',()=>{$('charCount').textContent=$('brief').value.length+' / 20,000';});
$('sampleBtn').onclick=()=>{
 if(state.requirements.length&&!confirm('Replace your current brief and checklist with the sample?'))return;
 $('brief').value='Submit a PDF report of no more than 2 pages. Include Python source code and at least 3 screenshots. Include the text "Imran Ghafoor" in the report. Explain your approach clearly. Name the ZIP Team07_CV.zip.';
 $('brief').dispatchEvent(new Event('input'));
 state.requirements=[
 {label:'Include a report',kind:'exists',target:'report',value:'',source_quote:'Submit a PDF report'},
 {label:'Report has at most 2 pages',kind:'max_pages',target:'report',value:'2',source_quote:'no more than 2 pages'},
 {label:'Include source code',kind:'exists',target:'code',value:'',source_quote:'Include Python source code'},
 {label:'Include at least 3 screenshots',kind:'min_count',target:'screenshot',value:'3',source_quote:'at least 3 screenshots'},
 {label:'Include the specified student name',kind:'contains',target:'report',value:'Imran Ghafoor',source_quote:'Include the text "Imran Ghafoor" in the report'},
 {label:'Approach is clearly explained',kind:'manual',target:'report',value:'',source_quote:'Explain your approach clearly'},
 {label:'Output ZIP is named Team07_CV.zip',kind:'manual',target:'any',value:'',source_quote:'Name the ZIP Team07_CV.zip'}
 ];
 $('zipName').value='Team07_CV.zip';invalidate();renderRequirements();toast('Sample brief + hand-written example checklist loaded. No AI call was made.');
};
$('extractBtn').onclick=()=>{
 if(!$('consent').checked)return toast('Please confirm sending instructions to your configured AI provider.',true);
 if($('brief').value.trim().length<10)return toast('Add at least 10 characters of instructions.',true);
 if(state.requirements.length&&!confirm('Replace this checklist with new AI suggestions?'))return;
 busy($('extractBtn'),'Extracting requirements…',async()=>{
 const res=await (await api('/api/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:$('brief').value,consent:true})})).json();
 state.requirements=res.requirements;invalidate();renderRequirements();toast('Suggestions ready. Review every row against the original brief.');
 });
};
$('instructionFile').onchange=()=>{const file=$('instructionFile').files[0];if(!file)return;
 if(file.size>12*1024*1024)return toast('Instruction file must be 12 MB or smaller.',true);
 if($('brief').value&&!confirm('Replace the current instruction text with this file?')){$('instructionFile').value='';return;}
 busy($('sampleBtn'),'Reading file…',async()=>{const form=new FormData();form.append('file',file);const res=await(await api('/api/instructions',{method:'POST',body:form})).json();$('brief').value=res.text;$('brief').dispatchEvent(new Event('input'));toast(res.warning||'Instructions imported. Review the text, then create your checklist.');});$('instructionFile').value='';
};
function guessRole(name){const ext=name.split('.').pop().toLowerCase();if(['pdf','docx'].includes(ext))return 'report';if(['png','jpg','jpeg','webp'].includes(ext))return 'screenshot';if(['py','js','ts','tsx','jsx','java','cpp','c','h','html','css','ipynb','sql','r','m','go','rs'].includes(ext))return 'code';return 'other';}
function safeName(name){return name.replace(/[^\p{L}\p{N}_.() -]/gu,'_').replace(/^[ .]+|[ .]+$/g,'').slice(0,120)||'unnamed';}
function addFiles(files){
 if(state.busy)return;
 let sum=state.files.reduce((s,f)=>s+f.file.size,0),added=0,skipped=[];
 for(const file of files){
 if(state.files.length>=60||file.size>12*1024*1024||sum+file.size>29*1024*1024||file.size===0){skipped.push(file.name);continue;}
 const role=guessRole(file.name),name=safeName(file.name);let path=role+'/'+name,n=2;
 while(state.files.some(f=>f.path.toLowerCase()===path.toLowerCase())){path=role+'/'+n+++'_'+name;}
 state.files.push({file,role,path});sum+=file.size;added++;
 }
 if(added){invalidate();renderFiles();}
 if(skipped.length)toast('Skipped empty/oversized files or files beyond the total limit: '+skipped.join(', '),true);
}
function renderFiles(){
 $('fileCount').textContent=state.files.length+' FILES';
 $('fileList').innerHTML=state.files.map((f,i)=>`<div class="file-row" data-index="${i}"><div class="file-top"><span class="file-glyph">${escape(f.file.name.split('.').pop().toUpperCase().slice(0,4))}</span><div class="file-name">${escape(f.file.name)}<small>${(f.file.size/1024).toFixed(1)} KB · original preserved</small></div><button class="remove" data-remove-file="${i}" aria-label="Remove ${escape(f.file.name)}">×</button></div><div class="file-details"><label>File role<select data-file-field="role">${options(Object.fromEntries(Object.entries(targets).filter(([k])=>k!=='any')),f.role)}</select></label><label>Path inside ZIP<input data-file-field="path" value="${escape(f.path)}" maxlength="220"></label></div></div>`).join('');
}
$('fileList').addEventListener('input',e=>{const field=e.target.dataset.fileField;if(!field)return;const i=+e.target.closest('[data-index]').dataset.index;state.files[i][field]=e.target.value;invalidate();});
$('fileList').addEventListener('click',e=>{const b=e.target.closest('[data-remove-file]');if(!b)return;state.files.splice(+b.dataset.removeFile,1);invalidate();renderFiles();});
$('assignmentFiles').onchange=()=>{addFiles($('assignmentFiles').files);$('assignmentFiles').value='';};
const drop=$('dropzone');['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();if(!state.busy)drop.classList.add('over');}));['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('over');}));drop.addEventListener('drop',e=>addFiles(e.dataTransfer.files));drop.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(!state.busy)$('assignmentFiles').click();}});
function formData(){const form=new FormData();state.files.forEach(f=>form.append('files',f.file));form.append('metadata',JSON.stringify({requirements:state.requirements,files:state.files.map(({role,path})=>({role,path})),zip_name:$('zipName').value,acknowledge:$('acknowledge').checked}));return form;}
$('checkBtn').onclick=async()=>{
 if(!state.files.length)return toast('Upload at least one file first.',true);
 if(!state.requirements.length)return toast('Add at least one requirement in The brief.',true);
 let success=false;
 await busy($('checkBtn'),'Inspecting your files…',async()=>{
 const res=await(await api('/api/check',{method:'POST',body:formData()})).json();state.results=res.results;state.inspected=res.files;renderResults();success=true;
 });if(success)navigate(2);
};
function renderResults(){
 const counts={pass:0,fail:0,review:0};state.results.forEach(r=>counts[r.status]++);
 $('passCount').textContent=counts.pass;$('failCount').textContent=counts.fail;$('reviewCount').textContent=counts.review;
 $('reviewTitle').textContent=counts.fail?'A few things to fix.':counts.review?'Nearly there. Take a look.':'Your structural checks passed.';
 $('reviewSub').textContent=`${state.results.length} checks completed. These checks do not assess correctness or grading.`;
 $('results').innerHTML=state.results.map(r=>`<div class="card result-row ${r.status}"><span class="result-icon">${{pass:'✓',fail:'!',review:'?'}[r.status]}</span><div class="result-body"><strong>${escape(r.label)}</strong><p>${escape(r.evidence)}</p></div><span class="result-status">${{pass:'PASSED',fail:'NEEDS A FIX',review:'NEEDS REVIEW'}[r.status]}</span></div>`).join('');
 $('warnings').innerHTML=state.inspected.filter(f=>f.warning).map(f=>`<div class="warning"><strong>${escape(f.name)}</strong> — ${escape(f.warning)}</div>`).join('');updateExport();
}
function renderPackage(){
 $('packageTree').innerHTML=state.files.map(f=>`<div class="tree-item"><span>↳</span><span>${escape(f.path)}</span></div>`).join('')+'<div class="tree-item"><span>↳</span><span>_submitsloth/review.json</span></div>';updateExport();
}
function updateExport(){
 const unresolved=state.results&&(state.results.some(r=>r.status!=='pass')||state.inspected.some(f=>f.warning||!f.valid));
 $('exportBtn').disabled=state.busy||!state.results||(unresolved&&!$('acknowledge').checked);
 $('exportHint').textContent=!state.results?'Run checks after your last edit.':unresolved?'Acknowledge unresolved checks and file warnings to export.':'Structural checks passed. Review the contents before submitting.';
}
$('acknowledge').onchange=updateExport;
$('exportBtn').onclick=()=>busy($('exportBtn'),'Packing your files…',async()=>{
 const res=await api('/api/export',{method:'POST',body:formData()});const blob=await res.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;let name=safeName($('zipName').value||'submission');a.download=name.toLowerCase().endsWith('.zip')?name:name+'.zip';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);toast('Package downloaded. Open it and review before submitting.');
});
document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>navigate(+b.dataset.step));document.querySelectorAll('[data-next]').forEach(b=>b.onclick=()=>navigate(+b.dataset.next));
$('helpBtn').onclick=()=>$('helpDialog').showModal();$('closeHelp').onclick=()=>$('helpDialog').close();
window.addEventListener('beforeunload',e=>{if(state.files.length){e.preventDefault();e.returnValue='';}});
async function init(){
 try{const res=await(await api('/api/status')).json();state.ai=res.ai_configured;$('aiBadge').textContent=state.ai?'✦ AI connected · '+res.model:'○ Manual mode · AI not configured';$('aiHint').textContent=state.ai?'Review AI suggestions before checking files.':'Set AI_BASE_URL + AI_MODEL to enable AI. Manual mode works now.';}
 catch{$('aiBadge').textContent='Server unavailable';toast('Cannot reach the Python backend. Start the app using the README instructions.',true);}
 updateAI();updateExport();
}
init();

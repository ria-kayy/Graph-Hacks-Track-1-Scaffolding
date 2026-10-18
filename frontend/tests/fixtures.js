export const symbol={id:'pallets/click:src/click/_termui_impl.py:click._termui_impl.ProgressBar.generator',qualified_name:'click._termui_impl.ProgressBar.generator',file_path:'src/click/_termui_impl.py',start_line:349};
export const issue={id:'issue:651',number:651,url:'https://github.com/pallets/click/issues/651'};
export const pr={id:'pr:706',number:706,url:'https://github.com/pallets/click/pull/706'};
export const commit={sha:'8780a763aab11f69258acccbcb9d0d97e92ebadb',timestamp:'2018-05-14T00:00:00Z',message:'Fix progress update',url:'https://github.com/pallets/click/commit/8780a763aab11f69258acccbcb9d0d97e92ebadb'};
export const claim={id:'claim:1',source_span:'Update progress after processing.',source_url:pr.url,claim_type:'direct'};
export const status={repository:{id:'pallets/click',url:'https://github.com/pallets/click'},counts:{Commit:3378,Issue:28},current_symbols:626,symbols:[{id:symbol.id,name:symbol.qualified_name}],posting_configured:false};
export function history(size=1) {
  const timeline=Array.from({length:size},(_,i)=>({commit:{...commit,sha:(i===0?commit.sha:`${i.toString().padStart(8,'0')}${'a'.repeat(32)}`),message:`History change ${i}`,url:i===0?commit.url:`https://github.com/pallets/click/commit/${i}`},pr,issue,modified_symbol:symbol}));
  if (size>1) timeline.splice(1,0,{...timeline[0],modified_symbol:{...symbol,id:'old:symbol',file_path:'click/_termui_impl.py'}});
  return {symbol,timeline,claims:[claim],as_of:'2026-10-04T00:00:00Z'};
}
export function triage() {
  const candidate={symbol,score:.736,components:{semantic_issue_similarity:.56,historical_fix_frequency:1},paths:[{issue,pr,commit,modified_symbol:symbol.id,expansion:null}]};
  return {localization:{candidates:[candidate],confidence:'medium',as_of:'2026-10-04T00:00:00Z'},findings:[{history:{claims:[claim]},impact:{impacted_files:[],transitive_callers:[]},experts:{experts:[{login:'jojje',direct_changes:1,fix_count:1,sources:[pr.url]}]}}],trace:['graph evidence'],markdown:'Exact reviewed comment',action:{posted:false}};
}

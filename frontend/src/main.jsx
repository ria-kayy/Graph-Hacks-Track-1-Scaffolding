import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import cytoscape from 'cytoscape';
import './style.css';

async function api(path, payload, signal, adminToken='') {
  let response;
  try {
    response = await fetch('/api/' + path, {
      ...(payload ? {method:'POST', headers:{'Content-Type':'application/json',...(adminToken?{Authorization:'Bearer '+adminToken}:{})}, body:JSON.stringify(payload)} : {}),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the backend. Check that it is running, then try again.');
  }
  let data;
  try { data = await response.json(); }
  catch { throw new Error('The backend returned an unreadable response. Please try again.'); }
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join('; ') : data.detail;
    throw new Error(detail || 'Request failed. Please try again.');
  }
  return data;
}
const short = name => name.split('.').slice(-2).join('.');

function graphElements(result, full=false) {
  const nodes = new Map(), edges = new Map(), slots = [0,0,0,0,0];
  function node(id, label, kind, stage, url) { if (!nodes.has(id)) nodes.set(id, { data:{id,label,kind,url}, position:{x:stage*200,y:slots[stage]++*100} }); else if(url) nodes.get(id).data.url=url; }
  function edge(from,to,label) { if (from === to) return; const id=from+':'+to+':'+label; edges.set(id,{ data:{id,source:from,target:to,label} }); }
  const candidates = result?.localization?.candidates || result?.candidates || [];
  for (const candidate of (full ? candidates : candidates.slice(0,1))) {
    const s=candidate.symbol;
    node(s.id,short(s.qualified_name),'symbol',4,candidate.direct_evidence?.source_url);
    for (const path of (full ? candidate.paths : candidate.paths.slice(0,1))) {
      node(path.issue.id,'Issue #'+path.issue.number,'issue',0,path.issue.url);
      node(path.pr.id,'PR #'+path.pr.number,'pr',1,path.pr.url);
      node(path.commit.sha,path.commit.sha.slice(0,8),'commit',2,path.commit.url);
      node(path.modified_symbol,short(path.modified_symbol.split(':').at(-1)),'symbol',3);
      edge(path.pr.id,path.issue.id,'CLOSES'); edge(path.pr.id,path.commit.sha,'CONTAINS_COMMIT'); edge(path.commit.sha,path.modified_symbol,'MODIFIED_SYMBOL');
      if (path.modified_symbol !== s.id) edge(path.modified_symbol,s.id,path.expansion || 'GIT RENAME');
    }
  }
  if (result?.timeline) {
    const s=result.symbol; node(s.id,short(s.qualified_name),'symbol',3);
    const linked=result.timeline.filter(record=>record.pr);
    const records=full ? result.timeline : (linked.length ? linked : result.timeline).slice(0,1);
    for (const record of records) {
      const c=record.commit, changed=record.modified_symbol || s; node(c.sha,c.sha.slice(0,8),'commit',2,c.url); node(changed.id,short(changed.qualified_name),'symbol',3); edge(c.sha,changed.id,'MODIFIED_SYMBOL');
      if (changed.id !== s.id) edge(changed.id,s.id,'GIT RENAME');
      if (record.pr) { node(record.pr.id,'PR #'+record.pr.number,'pr',1,record.pr.url); edge(record.pr.id,c.sha,'CONTAINS_COMMIT'); }
      if (record.issue && record.pr) { node(record.issue.id,'Issue #'+record.issue.number,'issue',0,record.issue.url); edge(record.pr.id,record.issue.id,'CLOSES'); }
    }
  }
  if (result?.evidence?.length) {
    for (const item of (full ? result.evidence : result.evidence.filter(item=>item.symbol).slice(0,1))) {
      const symbol=item.symbol;
      if (!symbol) continue;
      const fileId='file:'+item.file_path;
      node(fileId,item.file_path,'file',1,item.source_url);
      node(symbol.id,short(symbol.qualified_name),'symbol',3,item.source_url);
      edge(fileId,symbol.id,'CONTAINS · '+item.start_line+'-'+item.end_line);
    }
  }
  for (const finding of (full ? result?.findings||[] : (result?.findings||[]).slice(0,1))) {
    if (!finding.symbol || !finding.structure) continue;
    const s=finding.symbol;
    const source=result.evidence?.find(item=>item.symbol_id===s.id);
    node(s.id,short(s.qualified_name),'symbol',3,source?.source_url);
    for (const caller of (full?finding.structure.callers:finding.structure.callers.slice(0,1))) {
      const id='caller:'+caller.qualified_name;
      node(id,short(caller.qualified_name),'symbol',2);edge(id,s.id,'CALLS');
    }
    for (const callee of (full?finding.structure.callees:finding.structure.callees.slice(0,1))) {
      const id='callee:'+callee.qualified_name;
      node(id,short(callee.qualified_name),'symbol',4);edge(s.id,id,'CALLS');
    }
  }
  return [...nodes.values(), ...edges.values()];
}

function EvidenceGraph({ result }) {
  const container=useRef(null), graphRef=useRef(null);
  const [zoom,setZoom]=useState(1);
  const [full,setFull]=useState(false), [selected,setSelected]=useState(null);
  const elements=graphElements(result,full);
  useEffect(()=>{setFull(false);setSelected(null);},[result]);
  useEffect(()=>{
    if (!elements.length || !container.current) return;
    const positions=new Map(elements.filter(item=>item.position).map(item=>[item.data.id,{...item.position}]));
    const positionFor=(item)=>{const original=positions.get(item.id());return container.current.clientWidth<600?{x:original.y*1.8,y:original.x*.5}:{...original};};
    const graph=cytoscape({ container:container.current, elements, layout:{name:'preset',positions:positionFor}, minZoom:.2,maxZoom:2,
      style:[
        {selector:'node',style:{shape:'round-rectangle',width:144,height:48,'background-color':'#f2e5d7',label:'data(label)',color:'#202a32','font-size':11,'text-valign':'center','text-halign':'center','text-wrap':'ellipsis','text-max-width':132,'border-width':1,'border-color':'#d8c7b5'}},
        {selector:'node[kind="symbol"]',style:{'background-color':'#213d43',color:'#fff','border-color':'#213d43'}},
        {selector:'node[kind="issue"]',style:{'background-color':'#f2d5c6','border-color':'#dba58b'}},
        {selector:'edge',style:{width:1.5,'line-color':'#a3aaa7','target-arrow-color':'#a3aaa7','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(label)','font-size':8,'text-background-color':'#fffefa','text-background-opacity':1,'text-background-padding':3}},
        {selector:'node[url]',style:{'border-width':2}},
        {selector:'.dimmed',style:{opacity:.2}},
        {selector:'edge.highlighted',style:{width:3,'line-color':'#b7693d','target-arrow-color':'#b7693d'}},
        {selector:'node.highlighted',style:{'border-width':3,'border-color':'#b7693d'}}
      ]});
    graphRef.current=graph;
    graph.on('zoom',()=>setZoom(graph.zoom()));
    graph.on('tap','node',event=>{
      const focus=event.target.closedNeighborhood();
      graph.elements().removeClass('highlighted dimmed');
      graph.elements().difference(focus).addClass('dimmed');focus.addClass('highlighted');
      setSelected(event.target.data());
    });
    function fitLayout() {
      graph.resize();
      graph.nodes().forEach(item=>item.position(positionFor(item)));
      graph.fit(undefined,25);
    }
    fitLayout();
    const observer=new ResizeObserver(fitLayout); observer.observe(container.current);
    return ()=>{observer.disconnect();graphRef.current=null;graph.destroy();};
  },[result,full]);
  if (!elements.length) return <div className="empty-graph"><svg viewBox="0 0 240 90" aria-hidden="true"><path d="M40 45H120H200"/><circle cx="40" cy="45" r="14"/><circle cx="120" cy="45" r="14"/><circle cx="200" cy="45" r="14"/></svg><h3>Every recommendation has a path.</h3><p>Run a history query or triage an issue to follow its evidence through the graph.</p></div>;
  function zoomBy(factor) {
    const graph=graphRef.current;
    if (graph) graph.zoom({level:Math.min(2,Math.max(.2,graph.zoom()*factor)),renderedPosition:{x:graph.width()/2,y:graph.height()/2}});
  }
  return <React.Fragment key="active-graph"><div className="graph-controls"><button onClick={()=>zoomBy(1.25)} aria-label="Zoom in">+</button><button onClick={()=>zoomBy(.8)} aria-label="Zoom out">−</button><button onClick={()=>{graphRef.current?.elements().removeClass('highlighted dimmed');setSelected(null);graphRef.current?.fit(undefined,25);}}>Reset view</button><button aria-pressed={full} onClick={()=>{setFull(value=>!value);setSelected(null);}}>{full?'Focus evidence path':'All returned evidence'}</button><span role="status" aria-label="Graph zoom">Zoom: {Math.round(zoom*100)}%</span></div><div key="canvas" ref={container} className="graph" role="img" aria-label="Interactive evidence graph connecting issues, pull requests, commits, and functions"/>{selected&&<div className="graph-selection" role="status"><b>{selected.label}</b><code>{selected.id}</code>{selected.url?<a href={selected.url} target="_blank" rel="noreferrer">Open selected source ↗</a>:<span>No direct source URL for this node; inspect its linked evidence.</span>}</div>}<p className="graph-hint">{full?'All evidence returned by this query.':'Focused evidence path.'} Scroll to zoom · drag to explore · select a node to inspect its connections.</p></React.Fragment>;
}

function AgentExecution({ execution }) {
  if (!execution) return null;
  return <section className="agent-execution" aria-label="Model execution record"><div className="panel-title"><h2>Model execution</h2><span className="tag">{execution.status.replaceAll('_',' ')}</span></div><p className="execution-note">Automatic retrieval runs first. Calls below are selected by the model using local read-only tools, also exposed through MCP. This record appears when the request finishes.</p>
    {!execution.steps.length&&<p className="execution-note">No model-selected tool calls were executed.</p>}
    <ol>{execution.steps.map((step,index)=><li key={index}><div className="execution-heading"><code>{step.tool}</code><span>{step.status} · {step.elapsed_ms} ms · round {step.round}</span></div><p>{step.purpose}</p><details><summary>Arguments and returned evidence</summary><pre>{JSON.stringify(step.arguments,null,2)}</pre><pre>{step.result}</pre>{step.evidence_ids?.length>0&&<p>Evidence IDs: {step.evidence_ids.join(', ')}</p>}</details></li>)}</ol><p className="execution-stop"><b>Stopped:</b> {execution.stop_reason}</p></section>;
}

function Claim({ claim }) { return <div className="claim"><blockquote>{claim.claim_type === 'derived' ? claim.text : claim.source_span}</blockquote><a href={claim.source_url} target="_blank" rel="noreferrer">{claim.claim_type === 'derived' ? 'Derived interpretation' : 'Verified source span'} ↗</a></div>; }

function HistoryFindings({ result }) {
  const [visible,setVisible]=useState(20);
  const grouped=new Map();
  for (const record of result.timeline) {
    if (!grouped.has(record.commit.sha)) grouped.set(record.commit.sha,{commit:record.commit,paths:new Map()});
    const key=JSON.stringify([record.modified_symbol?.id,record.pr?.id,record.issue?.id]);
    grouped.get(record.commit.sha).paths.set(key,record);
  }
  const commits=[...grouped.values()];
  return <div className="findings">
    <h2>{result.symbol.qualified_name}</h2>
    <p className="muted">{result.timeline.length} historical records across {commits.length} commits · {result.claims.length} verified rationale claims</p>
    {result.claims.map(claim=><Claim key={claim.id} claim={claim}/>)}
    {!result.claims.length && <p className="muted">No verified rationale found for this function.</p>}
    <p className="muted">Records for the same commit are grouped. Expand evidence paths to see the affected symbol locations and issue links.</p>
    <div className="timeline">{commits.slice(0,visible).map(({commit,paths})=>{
      const records=[...paths.values()];
      const sources=new Map(records.flatMap(r=>[r.pr,r.issue]).filter(Boolean).map(entity=>[entity.id,entity]));
      return <article key={commit.sha}>
        <time>{commit.timestamp.slice(0,10)}</time>
        <a href={commit.url} target="_blank" rel="noreferrer"><code>{commit.sha.slice(0,8)}</code></a>
        <p>{commit.message.split('\n')[0]}</p>
        <div className="timeline-links">{[...sources.values()].map(source=><a key={source.id} href={source.url} target="_blank" rel="noreferrer">{records.some(r=>r.pr?.id===source.id)?'PR':'Issue'} #{source.number} ↗</a>)}</div>
        <details><summary>{records.length} evidence {records.length===1?'path':'paths'}</summary><ul>{records.map((record,i)=><li key={i}>
          <code>{(record.modified_symbol || result.symbol).qualified_name}</code><br/>
          <span>{(record.modified_symbol || result.symbol).file_path}</span>
          {record.pr && <> · <a href={record.pr.url} target="_blank" rel="noreferrer">PR #{record.pr.number}</a></>}
          {record.issue && <> · <a href={record.issue.url} target="_blank" rel="noreferrer">Issue #{record.issue.number}</a></>}
        </li>)}</ul></details>
      </article>;
    })}</div>
    <p className="muted">Showing {Math.min(visible,commits.length)} of {commits.length} commits</p>
    {visible<commits.length && <button className="secondary" onClick={()=>setVisible(value=>value+20)}>Show more history</button>}
  </div>;
}

function Findings({ result, mode }) {
  if (!result) return <div className="empty-answer"><p>{mode==='triage'?'Describe an issue. Follow the evidence.':'Start with a function. Follow the reason.'}</p><span>{mode==='triage'?'Preview likely functions, historical fixes and suggested reviewers.':'History reconstructs the commits, pull requests and issues behind your code.'}</span></div>;
  const candidates=result.localization?.candidates || result.candidates;
  if (candidates) return <div className="findings">
    <div className="result-heading"><span>{candidates.length} likely functions</span><span className="tag">{result.localization?.confidence || result.confidence} confidence</span></div>
    {!candidates.length && <p>No supported candidates existed before this cutoff. Try a current report or ingest more history.</p>}
    {candidates.map((c,index)=>{
      const finding=result.findings?.[index];
      return <article className="candidate" key={c.symbol.id}>
        <div className="candidate-title"><b>{index+1}</b><code>{c.symbol.qualified_name}</code><strong>{c.score.toFixed(3)}</strong></div>
        <small>{c.symbol.file_path}:{c.symbol.start_line}</small>
        <div className="score-line">{Object.entries(c.components).map(([key,value])=><span key={key} title={key}>{key.replaceAll('_',' ')} <b>{value.toFixed(2)}</b></span>)}</div>
        {c.paths.slice(0,2).map((p,i)=><p className="path-text" key={i}><a href={p.issue.url} target="_blank" rel="noreferrer">Issue #{p.issue.number}</a> ← <a href={p.pr.url} target="_blank" rel="noreferrer">PR #{p.pr.number}</a> → <a href={p.commit.url} target="_blank" rel="noreferrer">{p.commit.sha.slice(0,8)}</a>{p.expansion && ' → '+p.expansion}</p>)}
        {finding?.history.claims.slice(0,2).map(claim=><Claim key={claim.id} claim={claim}/>)}
        {finding && <details><summary>Blast radius and reviewers</summary>
          {finding.impact.impacted_files.length ? <p>{finding.impact.impacted_files.length} impacted files · call depth ≤ 3</p> : <p>No statically resolved callers found. Dynamic calls may not be detected.</p>}
          {finding.impact.transitive_callers.slice(0,5).map((caller,i)=><p key={i}><code>{caller.path.join(' → ')}</code></p>)}
          {finding.experts.experts.map(person=><p key={person.login}>@{person.login} · {person.direct_changes} changes · {person.fix_count} fixes {person.sources[0] && <a href={person.sources[0]} target="_blank" rel="noreferrer">evidence ↗</a>}</p>)}
          {!finding.experts.experts.length && <p>Insufficient verified reviewer evidence.</p>}
        </details>}
      </article>;
    })}
    {result.markdown && <details><summary>GitHub comment preview</summary><pre className="markdown-preview">{result.markdown}</pre></details>}
  </div>;
  if (result.timeline) return <HistoryFindings key={result.symbol.id+result.as_of} result={result}/>;
  return <pre className="raw-result">{JSON.stringify(result,null,2)}</pre>;
}

function Evaluation({ evaluation }) {
  if (!evaluation) return <p className="muted">No measured results yet. Run the documented evaluation command.</p>;
  const keys=['top1','top3','top5','mrr','recall5'];
  return <div className="evaluation"><span className="eyebrow">Measured, not estimated</span><h2>Does the graph improve localization?</h2><p>{evaluation.dataset_size} closed issues · original opening text · historical Git snapshots</p><div className="table-wrap"><table><thead><tr><th>Approach</th><th>Top-1</th><th>Top-3</th><th>Top-5</th><th>MRR</th><th>Recall@5</th></tr></thead><tbody>{Object.entries(evaluation.summary).map(([name,metrics])=><tr key={name}><th>{name === 'whygraph' ? 'WhyGraph' : name === 'vector' ? 'Vector only' : 'Keyword'}</th>{keys.map(key=><td key={key}>{key === 'mrr' ? metrics[key].toFixed(3) : (metrics[key]*100).toFixed(1)+'%'}</td>)}</tr>)}</tbody></table></div><p className="eval-note">WhyGraph ties vector-only retrieval in this sample. Graph expansion adds traceable context, but did not improve measured accuracy. The small, sparse fix corpus limits this result.</p><details><summary>Leakage controls and limitations</summary><pre className="raw-result">{JSON.stringify(evaluation.methodology,null,2)}</pre></details></div>;
}

function App() {
  const [status,setStatus]=useState(null), [evaluation,setEvaluation]=useState(null), [mode,setMode]=useState('history');
  const [repositories,setRepositories]=useState([]), [repoInput,setRepoInput]=useState(''), [selectedRepo,setSelectedRepo]=useState('default'), [job,setJob]=useState(null), [conversation,setConversation]=useState(null);
  const [chatQuestion,setChatQuestion]=useState(''), [chatContext,setChatContext]=useState('');
  const [adminToken,setAdminToken]=useState('');
  const [symbol,setSymbol]=useState('click._termui_impl.ProgressBar.generator'), [title,setTitle]=useState('Progress bar does not update after each item is processed'), [body,setBody]=useState('The displayed progress is out of sync with processing inside the loop.'), [issueNumber,setIssueNumber]=useState(''), [asOf,setAsOf]=useState('');
  const [result,setResult]=useState(null), [busy,setBusy]=useState(false), [posting,setPosting]=useState(false), [error,setError]=useState('');
  const request=useRef({version:0,controller:null});
  useEffect(()=>{api('status').then(setStatus).catch(e=>setError(e.message));api('evaluation').then(setEvaluation).catch(()=>{});api('repositories').then(data=>setRepositories(data.repositories||[])).catch(()=>{});},[]);
  useEffect(()=>{
    if (!job?.job_id || !['queued','running'].includes(job.status)) return;
    let active=true;
    const timer=setInterval(()=>api('ingestion-jobs/'+job.job_id).then(next=>{if(!active)return;setJob(next);if(next.status==='completed'||next.status==='failed') api('repositories').then(data=>{if(active)setRepositories(data.repositories||[]);});}).catch(e=>{if(active)setError(e.message);}),1500);
    return ()=>{active=false;clearInterval(timer);};
  },[job?.job_id,job?.status]);
  useEffect(()=>()=>{request.current.version++;request.current.controller?.abort();},[]);
  function invalidate() {
    request.current.version++;
    request.current.controller?.abort();
    request.current.controller=null;
    setBusy(false);setResult(null);setError('');
  }
  function change(setter,value) { invalidate();setter(value); }
  async function addRepository(event) {
    event?.preventDefault(); invalidate();
    const version=request.current.version;
    try { const data=await api('repositories',{repository:repoInput},undefined,adminToken); if(version!==request.current.version)return;setRepositories(old=>[data.repository,...old.filter(item=>item.repository_id!==data.repository.repository_id)]);setSelectedRepo(data.repository.repository_id);setMode('chat');setJob(data.job);setConversation(null);invalidate(); }
    catch(e){if(version===request.current.version)setError(e.message);}
  }
  async function refreshRepository() {
    invalidate();const version=request.current.version;setConversation(null);
    try {const next=await api('repositories/'+selectedRepo+'/refresh',{},undefined,adminToken);if(version===request.current.version){setJob(next);setRepositories(old=>old.map(item=>item.repository_id===selectedRepo?{...item,status:'queued'}:item));}}
    catch(e){if(version===request.current.version)setError(e.message);}
  }
  function selectRepository(id) { setSelectedRepo(id);setConversation(null);setJob(repositories.find(item=>item.repository_id===id)?.job||null);setChatQuestion('');setChatContext('');setSymbol('');if(id)setMode('chat');invalidate(); }
  async function run(post=false) {
    if (posting) return;
    request.current.controller?.abort();
    const version=++request.current.version;
    const controller=new AbortController();
    request.current.controller=controller;
    setBusy(true);setPosting(post);setError('');
    if (!post) setResult(null);
    try {
      const payload=mode==='chat' ? {repo_id:selectedRepo,query:chatQuestion,context:chatContext,conversation_id:conversation,as_of:asOf||null} : {tool:mode === 'triage' ? 'triage' : 'history',symbol,title,body,post,issue_number:issueNumber ? Number(issueNumber) : null,as_of:asOf || null,preview_id:post?result?.preview_id:null,repo_id:selectedRepo||null};
      const next=await api(mode==='chat'?'chat':'query',payload,controller.signal,post?adminToken:'');
      if (version===request.current.version) {if(mode==='chat')setConversation(next.conversation_id);setResult(next);}
    } catch(e) {
      if (version===request.current.version && e.name!=='AbortError') setError(e.message);
    } finally {
      if (version===request.current.version) {setBusy(false);setPosting(false);request.current.controller=null;}
    }
  }
  const trace=result?.trace || (result?.timeline ? ['Resolve deterministic symbol identity','Follow MODIFIED_SYMBOL ← Commit ← PR → Issue','Filter claims by their validity interval','Return verified spans and source URLs'] : []);
  const selected = repositories.find(item=>item.repository_id===selectedRepo);
  return <div className="app">
    <header><a className="brand" href="/" aria-label="WhyGraph home"><svg viewBox="0 0 30 30" aria-hidden="true"><path d="M7 7L23 15L7 23"/><circle cx="7" cy="7" r="4"/><circle cx="23" cy="15" r="4"/><circle cx="7" cy="23" r="4"/></svg>WhyGraph</a><span className="brand-note">Repository memory. With reasons.</span><div className="connection"><i className={status ? 'online' : ''}/>{status ? 'FalkorDB connected' : 'Connecting to FalkorDB'}</div></header>
    <main>
      <section className="intro"><div><span className="eyebrow">Code has a history</span><h1>Find the why behind the code.</h1><p>Trace a function to its fixes, decisions and the people who know it.</p></div><a className="repo" href={selectedRepo!=='default'?selected?.url||`https://github.com/${selected?.identity}`:status?.repository?.url || 'https://github.com/pallets/click'} target="_blank" rel="noreferrer"><span>Indexed repository ↗</span><strong>{selectedRepo!=='default'?selected?.identity:status?.repository?.id || 'pallets/click'}</strong><small>{selectedRepo!=='default'?selected?.counts?.Symbol??'—':status?.current_symbols || '—'} symbols · {selectedRepo!=='default'?selected?.counts?.Commit??'—':status?.counts.Commit || '—'} commits · {selectedRepo!=='default'?selected?.counts?.Issue??'—':status?.counts.Issue || '—'} issues</small></a></section>
      <section className="repo-select">
        <form onSubmit={addRepository}><label htmlFor="repo-url">Add a public GitHub repository</label><input id="repo-url" value={repoInput} disabled={posting} onChange={e=>setRepoInput(e.target.value)} placeholder="https://github.com/owner/repo"/><button className="secondary" disabled={posting}>Add and index</button></form>
        <details><summary>Admin access</summary><label htmlFor="admin-token">Admin token (if configured)</label><input id="admin-token" type="password" value={adminToken} onChange={e=>setAdminToken(e.target.value)} autoComplete="off" disabled={posting}/><small>Kept only in this tab. Required for administration through a proxy.</small></details>
        <label htmlFor="repo-choice">Selected repository</label><select id="repo-choice" value={selectedRepo} disabled={posting} onChange={e=>selectRepository(e.target.value)}>{repositories.map(item=><option key={item.repository_id} value={item.repository_id}>{item.identity} · {item.status}</option>)}</select>
        {selectedRepo!=='default'&&<button className="secondary" onClick={refreshRepository} disabled={posting||['queued','running'].includes(job?.status)}>Refresh repository</button>}
        {(selected?.error||job?.error)&&<div className="error" role="alert">{selected?.error||job.error}</div>}
        {selectedRepo==='default' ? <span>Default graph · {status?.repository?.indexed_ref || 'current indexed revision'}</span> : selected && <span>{selected.indexed_ref || job?.stage || 'Waiting for indexing'} {job?.status==='running'&&` · ${job.progress}% · ${job.stage}`}</span>}
        {selected?.counts && <small>{selected.counts.Symbol??(selectedRepo==='default'?status?.counts.Symbol:0)??0} symbols · {selected.counts.Commit??(selectedRepo==='default'?status?.counts.Commit:0)??0} commits · {selected.counts.Issue??(selectedRepo==='default'?status?.counts.Issue:0)??0} issues{selected.warnings?.length>0&&' · partial indexing warnings'}</small>}
        {selected?.warnings?.length>0&&<small>{selected.warnings.join(' · ')}</small>}
      </section>
      <nav aria-label="Workflow">{[['history','Function history'],['chat','Investigate'],['triage','Issue triage'],['evaluation','Evaluation']].map(([key,label])=><button key={key} disabled={posting||(key==='triage'&&selectedRepo!=='default')} onClick={()=>change(setMode,key)} className={mode===key?'active':''} aria-current={mode===key?'page':undefined}>{label}</button>)}</nav>
      {mode==='chat'&&result?.agent_execution&&<AgentExecution execution={result.agent_execution}/>}
      {mode==='evaluation' ? <Evaluation evaluation={evaluation}/> : <div className="workspace">
        <section className="query-panel">
          <div className="panel-title"><h2>{mode==='history'?'Function history':mode==='chat'?'Investigate your repository':'Triage a report'}</h2><span className="step">01 / Query</span></div>
          <form onSubmit={e=>{e.preventDefault();run();}}><fieldset disabled={posting}>
            {mode==='history' ? <><label htmlFor="symbol">Function or method</label><input id="symbol" value={symbol} onChange={e=>change(setSymbol,e.target.value)} list="symbols" required spellCheck="false"/><datalist id="symbols">{(selectedRepo==='default'?status?.symbols:[])?.map(s=><option key={s.id} value={s.name}/>)}</datalist><p className="form-hint">What changed, when it changed, and why.</p></> : <>
              <label htmlFor="title">{mode==='chat'?'Describe what is happening':'Issue title'}</label><input id="title" value={mode==='chat'?chatQuestion:title} onChange={e=>mode==='chat'?change(setChatQuestion,e.target.value):change(setTitle,e.target.value)} required={mode==='chat'||(mode==='triage'&&!issueNumber)}/>
              <label htmlFor="body">{mode==='chat'?'Additional context (optional)':'Description'}</label><textarea id="body" value={mode==='chat'?chatContext:body} onChange={e=>mode==='chat'?change(setChatContext,e.target.value):change(setBody,e.target.value)} rows="3"/>
              <p className="form-hint">{mode==='chat'?'Ask in plain English. Source candidates are checked against the indexed revision.':'Historical fixes guide the functions, impact and reviewer recommendations.'}</p>
              {mode==='triage'&&<><label htmlFor="issue-number">Fork issue number <span className="muted">(optional)</span></label><input id="issue-number" type="number" min="1" value={issueNumber} onChange={e=>change(setIssueNumber,e.target.value)} placeholder="Preview an existing issue"/></>}
            </>}
            <details className="cutoff"><summary>Historical cutoff</summary><label htmlFor="as-of">As of (ISO timestamp, with timezone)</label><input id="as-of" value={asOf} onChange={e=>change(setAsOf,e.target.value)} placeholder="2026-10-04T00:00:00Z"/><small>Explicit cutoffs are used for reproducible historical analysis.</small></details>
            <button className="primary" disabled={busy || !status || (selectedRepo && selectedRepo!=='default' && (!selected?.indexed_ref||!['ready','ready_with_warnings'].includes(selected?.status)))}>{busy?(mode==='triage'?'Following graph evidence…':'Investigating…'):mode==='history'?'Trace function history →':mode==='chat'?'Investigate →':'Preview triage →'}</button>
          </fieldset></form>
          {error && <div className="error" role="alert">{error}</div>}
          {mode==='triage'&&result&&<div className="posting"><p>{status?.posting_configured?`Comments are restricted to ${status.fork}.`:'Configure a valid GitHub token and your fork to enable posting.'}</p><button disabled={!status?.posting_configured||!issueNumber||busy||!result.preview_id||!result.findings?.length} onClick={()=>run(true)}>Post triage comment to my fork</button>{result.action?.url&&<a href={result.action.url} target="_blank" rel="noreferrer">Open posted comment ↗</a>}</div>}
        </section>
        <section className="evidence-panel"><div className="panel-title"><h2>Graph evidence</h2><span className="step">02 / Trace</span></div><div className="legend"><span><i className="issue-dot"/>Issue</span><span><i className="pr-dot"/>Pull request</span><span><i className="commit-dot"/>Commit</span><span><i className="symbol-dot"/>Function</span></div><EvidenceGraph result={result}/><div className="evidence-footer"><b>Evidence before inference.</b><p>Edges preserve source URLs and timestamps. Quotes must match their source text.</p>{result?.as_of||result?.localization?.as_of?<small>Evidence cutoff: {result.as_of||result.localization.as_of}</small>:<small>Recommendations follow explicit FalkorDB traversals.</small>}</div></section>
        <section className="results-panel" aria-label="Investigation findings">
          {mode==='chat'&&result&&<div className="findings"><h3>{result.mode==='retrieval_only'?'Retrieval-only investigation':'Model-assisted investigation'}</h3><p>{result.answer}</p>
            {result.mode==='model_assisted'&&<div className="answer-citations"><h4>Verified answer citations</h4>{result.evidence?.map(item=><details key={item.evidence_id}><summary>{item.evidence_type} · {item.file_path||item.commit_sha?.slice(0,8)||item.evidence_id}</summary><a href={item.source_url} target="_blank" rel="noreferrer">Open verified source ↗</a><pre>{item.excerpt}</pre></details>)}</div>}
            {result.findings?.map((finding,index)=>{const source=result.evidence.find(item=>item.symbol_id===finding.symbol.id);return <article className="candidate" key={finding.symbol.id}><b>{index+1}. <code>{finding.symbol.qualified_name}</code></b><p>{finding.reason}</p>{source&&<><a href={source.source_url} target="_blank" rel="noreferrer">{source.file_path}:{source.start_line}-{source.end_line} · indexed source ↗</a><pre>{source.excerpt}</pre></>}<p>Callers: {finding.structure.callers.map(item=>item.qualified_name).join(', ')||'none statically resolved'}<br/>Calls: {finding.structure.callees.map(item=>item.qualified_name).join(', ')||'none statically resolved'}</p>{finding.history?.timeline?.map(record=><p key={record.commit.sha}><a href={record.commit.url} target="_blank" rel="noreferrer">{record.commit.sha.slice(0,8)}</a> · {record.commit.message.split('\n')[0]}{record.pr&&<> · <a href={record.pr.url} target="_blank" rel="noreferrer">PR #{record.pr.number}</a></>}</p>)}{finding.history?.claims?.map(claim=><Claim key={claim.id} claim={claim}/>)}</article>;})}
            {result.historical_matches?.length>0&&<details><summary>Historical issue matches (background only)</summary>{result.historical_matches.map(match=><p key={match.issue.id}><a href={match.issue.url} target="_blank" rel="noreferrer">{match.issue.title}</a> · similarity {match.similarity.toFixed(2)} · not causal evidence</p>)}</details>}
            {result.commit_matches?.length>0&&<details><summary>Matching commit messages (historical background)</summary>{result.commit_matches.map(commit=><p key={commit.sha}><a href={commit.url} target="_blank" rel="noreferrer">{commit.sha.slice(0,8)}</a> · {commit.message.split('\n')[0]}{commit.verified_paths?.map((path,index)=><span key={index}>{path.pr&&<> · <a href={path.pr.url} target="_blank" rel="noreferrer">PR #{path.pr.number}</a></>}{path.issue&&<> · <a href={path.issue.url} target="_blank" rel="noreferrer">Issue #{path.issue.number}</a></>}</span>)}{commit.modified_symbols?.map((symbol,index)=><small key={index}> · modified {symbol.qualified_name} ({symbol.file_path})</small>)}</p>)}</details>}
          </div>}
          {mode!=='chat'&&<Findings result={result} mode={mode}/>}
        </section>
      </div>}
      <section className="trace-panel"><div><span className="eyebrow">Retrieval workflow</span><h2>{trace.length?'The path to this answer':'Ready when you are'}</h2></div><ol>{trace.length?trace.map((step,i)=><li key={i}>{step}</li>):<li>Your query will reveal the retrieval, graph traversal and ranking steps here.</li>}</ol></section>
    </main><footer><span>WhyGraph · Repository-aware engineering investigations.</span><span>Powered by FalkorDB</span></footer>
  </div>;
}

createRoot(document.getElementById('root')).render(<App/>);

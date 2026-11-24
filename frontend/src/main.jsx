import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Upload, Scissors, Download, Sparkles, Film, LoaderCircle, CheckCircle2, WandSparkles, Captions} from 'lucide-react';
import './style.css';

function App(){
 const [file,setFile]=useState(null),[sourceUrl,setSourceUrl]=useState(''),[uploaded,setUploaded]=useState(null);
 const [duration,setDuration]=useState(30),[busy,setBusy]=useState(false),[stage,setStage]=useState(''),[error,setError]=useState('');
 const [analysis,setAnalysis]=useState(null),[captions,setCaptions]=useState(true),[uploadProgress,setUploadProgress]=useState(0),[clipCount,setClipCount]=useState(10);
 const [clips,setClips]=useState([]),[clipProgress,setClipProgress]=useState({done:0,total:0}),[selectedMoments,setSelectedMoments]=useState([]),[captionStyle,setCaptionStyle]=useState('classic');
 const api=import.meta.env.VITE_API_URL||'';
 async function readResponse(r){
   const raw=await r.text();let d={};
   try{d=raw?JSON.parse(raw):{}}catch{throw new Error('Server se invalid response mila. Service restart/deploy ho sakta hai. Thodi der baad retry karein.')}
   if(!r.ok)throw new Error(d.detail||d.error||('Request failed (HTTP '+r.status+').'));
   return d;
 }
 async function request(path,body){
   const r=await fetch(api+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   return readResponse(r);
 }
 async function waitForJob(jobId){
   const deadline=Date.now()+45*60*1000;
   while(Date.now()<deadline){
     await new Promise(resolve=>setTimeout(resolve,2500));
     const r=await fetch(api+'/api/jobs/'+jobId);
     const d=await readResponse(r);
     if(d.status==='completed')return d.result;
     if(d.status==='failed')throw new Error(d.error||'Video processing failed.');
   }
   throw new Error('Processing took too long. Try fewer clips or a shorter video.');
 }
 function resetOutput(){setClips([]);setAnalysis(null);setSelectedMoments([]);setError('');setClipProgress({done:0,total:0});}
 async function upload(){
   if(!file)return;setBusy(true);setStage('Uploading video…');setUploadProgress(0);resetOutput();
   try{
     const fd=new FormData();fd.append('file',file);
     const d=await new Promise((resolve,reject)=>{
       const xhr=new XMLHttpRequest();xhr.open('POST',api+'/api/upload');xhr.timeout=30*60*1000;
       xhr.upload.onprogress=e=>{if(e.lengthComputable)setUploadProgress(Math.round(e.loaded/e.total*100));};
       xhr.onload=()=>{let body={};try{body=xhr.responseText?JSON.parse(xhr.responseText):{};}catch{reject(new Error('Server ne invalid response diya. Upload retry karein.'));return;}
         if(xhr.status>=200&&xhr.status<300)resolve(body);else reject(new Error(body.detail||'Upload failed (HTTP '+xhr.status+').'));};
       xhr.onerror=()=>reject(new Error('Network connection lost. Stable Wi-Fi ya smaller video try karein.'));
       xhr.ontimeout=()=>reject(new Error('Upload timeout. Free server ki upload limit ho sakti hai.'));
       xhr.send(fd);
     });
     setUploadProgress(100);setUploaded(d);
   }catch(e){setError(e.message);}finally{setBusy(false);setStage('');}
 }
 async function importUrl(){
   if(!sourceUrl.trim())return;setBusy(true);setStage('Importing video from link…');resetOutput();
   try{const d=await request('/api/import-url',{url:sourceUrl.trim()});setUploaded(d);setFile(null);setUploadProgress(100);}
   catch(e){setError(e.message);}finally{setBusy(false);setStage('');}
 }
 async function generateAll(){
   if(!uploaded)return;
   setBusy(true);setError('');setClips([]);setSelectedMoments([]);setClipProgress({done:0,total:0});
   try{
     setStage('Transcribing video and ranking highlight moments…');
     const job=await request('/api/analyze',{filename:uploaded.filename,clip_length:Number(duration),clip_count:Number(clipCount)});
     const data=await waitForJob(job.job_id);setAnalysis(data);
     const moments=(data.highlights||[]).slice(0,Number(clipCount));
     if(!moments.length)throw new Error('Is video mein clear speech/moments nahi mile. Audio wala video try karein.');
     setSelectedMoments(moments.map((m,i)=>({...m,id:i,selected:true})));
     setStage('Moments ready. Select the clips you want to create.');
   }catch(e){setError(e.message);}
   finally{setBusy(false);}
 }
 async function renderSelected(){
   const chosen=selectedMoments.filter(m=>m.selected);
   if(!uploaded||!chosen.length)return;
   setBusy(true);setError('');setClips([]);setClipProgress({done:0,total:chosen.length});
   try{
     const ready=[];
     for(let i=0;i<chosen.length;i++){
       setStage('Creating clip '+(i+1)+' of '+chosen.length+'…');
       const h=chosen[i];
       const renderJob=await request('/api/render',{filename:uploaded.filename,start:Number(h.start),duration:Math.max(1,Math.min(Number(duration),Number(h.duration))),captions,caption_style:captionStyle});
       const result=await waitForJob(renderJob.job_id);
       ready.push({...result,index:i+1,start:h.start,score:h.score,text:h.text});
       setClips([...ready]);setClipProgress({done:ready.length,total:chosen.length});
     }
     setStage('All selected clips are ready!');
   }catch(e){setError(e.message);}
   finally{setBusy(false);}
 }
 return <main>
  <nav><div className="brand"><span className="logo"><Scissors size={19}/></span>clipai</div><span className="tag">AI VIDEO WORKSPACE</span></nav>
  <section className="hero"><div className="eyebrow"><Sparkles size={14}/> YOUR SHORT-FORM STUDIO</div><h1>Long videos.<br/><span>Ready-to-post clips.</span></h1><p>Upload once. AI finds moments, creates vertical clips and lets you download every result.</p></section>
  <section className="workspace">
   <div className="panel-head"><div><div className="step">01 / VIDEO</div><h2>Upload your long video</h2></div><Film size={22}/></div>
   <label className="drop"><input type="file" accept="video/mp4,video/quicktime,video/webm,.m4v" onChange={e=>{setFile(e.target.files?.[0]||null);setUploaded(null);resetOutput();}}/><Upload size={28}/><strong>{file?file.name:'Choose a video from your device'}</strong><span>{file?Math.round(file.size/1024/1024)+' MB · Ready':'MP4, MOV or WEBM'}</span></label>
   <button className="primary" disabled={!file||busy} onClick={upload}><Upload size={17}/> Upload video</button>
   <div className="link-import"><div className="step">OR PASTE A PUBLIC VIDEO LINK</div><input aria-label="Video link" type="url" placeholder="YouTube, TikTok, Instagram, Facebook, Twitch or X" value={sourceUrl} onChange={e=>setSourceUrl(e.target.value)}/><button className="secondary" disabled={!sourceUrl.trim()||busy} onClick={importUrl}>Import video link</button><small>Public videos only. Private/login-required links may not work.</small></div>
   {uploaded&&<div className="success"><CheckCircle2 size={17}/> Video ready: {uploaded.original_name||uploaded.filename}</div>}
   {busy&&stage.includes('Uploading')&&<div className="progress">{stage}<b>{uploadProgress}%</b><div className="upload-track"><span style={{width:uploadProgress+'%'}}/></div></div>}
   <div className="divider"></div>
   <div className="panel-head"><div><div className="step">02 / AUTO CLIP GENERATOR</div><h2>Generate all clips</h2></div><WandSparkles size={22}/></div>
   <p className="hint">Speech recognition ranks possible highlight moments. Review the suggestions, choose your favourites, then render them in 9:16.</p>
   <div className="controls">
    <label>Clip length<select className="choice" value={duration} onChange={e=>setDuration(Number(e.target.value))}><option value="30">30 seconds</option><option value="60">60 seconds</option></select></label>
    <label>Number of clips<select className="choice" value={clipCount} onChange={e=>setClipCount(Number(e.target.value))}><option value="10">10 clips</option><option value="20">20 clips</option><option value="30">30 clips</option><option value="40">40 clips</option></select></label>
   </div>
   <label className="caption-toggle"><input type="checkbox" checked={captions} onChange={e=>setCaptions(e.target.checked)}/><Captions size={17}/> Burn subtitles into video</label>
   <div className="format"><span>OUTPUT</span><strong>9:16 <small>VERTICAL SHORT VIDEO</small></strong></div>
   <button className="primary render" disabled={!uploaded||busy} onClick={generateAll}>{busy?<LoaderCircle className="spin" size={17}/>:<Sparkles size={17}/>} {busy?'Working…':'Find highlight moments'}</button>
   {analysis&&selectedMoments.length>0&&<div className="analysis"><div className="panel-head"><div><div className="step">03 / REVIEW HIGHLIGHTS</div><h2>Choose your moments</h2></div><span className="tag">{selectedMoments.filter(m=>m.selected).length} SELECTED</span></div><p className="hint">These are speech-based suggestions, not guaranteed viral predictions. Untick anything you do not want.</p>{selectedMoments.map(m=><div className="highlight" key={m.id}><input type="checkbox" checked={!!m.selected} disabled={busy} onChange={e=>setSelectedMoments(old=>old.map(x=>x.id===m.id?{...x,selected:e.target.checked}:x))}/><span className="score">{Math.round(m.score)}</span><span className="moment"><b>{Math.floor(m.start/60)}:{String(Math.floor(m.start%60)).padStart(2,'0')} · {Math.round(m.duration)} sec</b><small>{m.text}</small><span className="trim-fields"><label>Start (sec)<input type="number" min="0" step="0.5" value={m.start} disabled={busy} onChange={e=>setSelectedMoments(old=>old.map(x=>x.id===m.id?{...x,start:Math.max(0,Number(e.target.value)||0)}:x))}/></label><label>Length (sec)<input type="number" min="1" max={duration} step="1" value={m.duration} disabled={busy} onChange={e=>setSelectedMoments(old=>old.map(x=>x.id===m.id?{...x,duration:Math.max(1,Math.min(Number(duration),Number(e.target.value)||1))}:x))}/></label></span></span></div>)}<label className="style-select">Caption style<select className="choice" value={captionStyle} onChange={e=>setCaptionStyle(e.target.value)}><option value="classic">Classic white</option><option value="bold">Bold highlight</option><option value="minimal">Minimal clean</option></select></label><button className="primary render" disabled={busy||!selectedMoments.some(m=>m.selected)} onClick={renderSelected}><Scissors size={17}/> Create selected clips</button></div>}
   {busy&&!stage.includes('Uploading')&&<div className="progress">{stage}{clipProgress.total>0&&<><b>{clipProgress.done} / {clipProgress.total} clips ready</b><div className="upload-track"><span style={{width:(clipProgress.done/clipProgress.total*100)+'%'}}/></div></>}</div>}
   {error&&<div className="error">{error}</div>}
   {clips.length>0&&<div className="results"><div className="success"><CheckCircle2 size={17}/> {clips.length} clip(s) ready to download</div><div className="clip-grid">{clips.map(c=><article className="clip-card" key={c.filename}><div className="clip-title">CLIP {c.index} · {Math.round(c.score||0)} SCORE</div><video controls playsInline preload="metadata" src={api+c.url}/><p>{c.text||'AI selected moment'}</p><a className="download" href={api+c.url} download={'clipai-clip-'+c.index+'.mp4'} type="video/mp4"><Download size={17}/> Download to device</a></article>)}</div><p className="gallery-note">On Android, tap Download to device. The MP4 is saved in Downloads; your Gallery app may show it automatically or after scanning the file.</p></div>}
  </section>
  <footer>CLIPAI <span>·</span> MADE FOR THE NEXT SCROLL</footer>
 </main>;
}
createRoot(document.getElementById('root')).render(<App/>);

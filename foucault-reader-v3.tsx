import { useState, useEffect, useCallback, useRef } from "react";

/* ============ CONFIG ============ */
var MODELS = {
  sonnet: { id: "claude-sonnet-4-6", label: "Sonnet 4.6" },
  opus: { id: "claude-opus-4-6", label: "Opus 4.6" }
};
var GLOSSARY_INIT = [
  ["gouvernementalit\u00e9","治理术"],["conduite","引导"],["police","公共管理"],
  ["raison d\u2019\u00c9tat","国家理由"],["biopolitique","生命政治"],
  ["art de gouverner","治理技艺"],["r\u00e9gime de v\u00e9rit\u00e9","真理体制"],
  ["gouvernement frugal","节制的治理"],["lib\u00e9ralisme","自由主义"],
  ["ordolib\u00e9ralisme","秩序自由主义"],["n\u00e9olib\u00e9ralisme","新自由主义"],
  ["homo \u0153conomicus","经济人"],["soci\u00e9t\u00e9 civile","市民社会"],
  ["souverainet\u00e9","主权"],["v\u00e9ridiction","真言体制"]
];
var SK = { meta:"v4-meta", entries:"v4-entries", gloss:"v4-gloss", src:"v4-src", docs:"v4-docs", model:"v4-model" };

/* ============ STORAGE ============ */
async function sGet(k,fb){try{var r=await window.storage.get(k);return r?JSON.parse(r.value):fb;}catch(e){return fb;}}
async function sSet(k,v){try{await window.storage.set(k,JSON.stringify(v));}catch(e){}}
async function sPSave(pages){var SZ=40,n=Math.ceil(pages.length/SZ);for(var i=0;i<n;i++)await sSet("v4p-"+i,pages.slice(i*SZ,(i+1)*SZ));return{n:n,total:pages.length};}
async function sPLoad(info){if(!info)return[];var a=[];for(var i=0;i<info.n;i++){var c=await sGet("v4p-"+i,[]);for(var j=0;j<c.length;j++)a.push(c[j]);}return a;}
async function sPClear(){for(var i=0;i<50;i++)try{await window.storage.delete("v4p-"+i);}catch(e){}}

/* ============ PROMPT ============ */
function buildPrompt(glossStr){
  return [
    "你是福柯(Foucault)法兰西学院课程(Cours au Coll\u00e8ge de France)的专业翻译。",
    "","任务：校正法语原文，翻译为中文，提取脚注，简要解释。",
    "","校正规则：",
    "- 修复断词(gouvernement-talité→gouvernementalité)、多余空格、OCR错字",
    "- 保留原文分段（用\\n\\n分隔段落）",
    "- 希腊文/拉丁文保留不译；专有名词在中文翻译中标注原文",
    "","仅输出一个JSON对象，不要```json标记或JSON之外的文字：",
    "{",
    '  "pages": "页码",',
    '  "original": "校正后法语原文",',
    '  "footnotes": "脚注原文(*标记)，无则空",',
    '  "translation": "中文翻译(段落与原文对应)",',
    '  "footnotes_translation": "脚注中文翻译，无则空",',
    '  "explanation": "2-3句论证要点"',
    "}","","术语词典：",glossStr
  ].join("\n");
}

/* ============ API (non-streaming) ============ */
async function apiCall(sys, msg, modelId, maxTok){
  var controller=new AbortController();
  var tid=setTimeout(function(){controller.abort();},180000);
  try{
    var r=await fetch("https://api.anthropic.com/v1/messages",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({model:modelId,max_tokens:maxTok||4096,system:sys,messages:[{role:"user",content:msg}]}),
      signal:controller.signal
    });
    clearTimeout(tid);
    if(!r.ok){var et="";try{et=await r.text();}catch(x){}throw new Error("API "+r.status+": "+et.slice(0,300));}
    var data=await r.json();
    var full="";
    if(data.content){for(var i=0;i<data.content.length;i++){if(data.content[i].type==="text")full+=data.content[i].text;}}
    if(!full)throw new Error("API返回空内容");
    return full;
  }catch(e){clearTimeout(tid);if(e.name==="AbortError")throw new Error("API超时180s");throw e;}
}

/* ============ JSON PARSE ============ */
function parseJSON(text){
  if(!text)return null;
  var s=text.replace(/```json\s*/gi,"").replace(/```\s*/g,"").trim();
  try{return JSON.parse(s);}catch(e){}
  // find outermost {}
  var depth=0,start=-1,end=-1;
  for(var i=0;i<s.length;i++){if(s[i]==="{"){if(depth===0)start=i;depth++;}if(s[i]==="}"){depth--;if(depth===0){end=i;break;}}}
  if(start===-1||end===-1)return null;
  var sub=s.substring(start,end+1);
  try{return JSON.parse(sub);}catch(e2){}
  // fix unescaped newlines inside JSON string values
  try{
    var fixed=sub.replace(/"([^"]*?)"/g,function(m,inner){
      return '"'+inner.replace(/\n/g,"\\n").replace(/\r/g,"").replace(/\t/g,"\\t")+'"';
    });
    return JSON.parse(fixed);
  }catch(e3){}
  return null;
}

/* ============ PDF.JS ============ */
var pdfLoaded=false;
function loadPdfJs(){if(pdfLoaded)return Promise.resolve();return new Promise(function(ok,no){var s=document.createElement("script");s.src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";s.onload=function(){window.pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";pdfLoaded=true;ok();};s.onerror=function(){no(new Error("pdf.js加载失败"));};document.head.appendChild(s);});}

/* ============ OCR JSON PARSE (Layout) ============ */
function stripHtml(s){return s.replace(/<[^>]+>/g,"");}

function parseOCR(data){
  var log=[],raw=Array.isArray(data)?data:null;
  if(!raw&&data&&Array.isArray(data.pages))raw=data.pages;
  if(!raw&&data&&Array.isArray(data.results))raw=data.results;
  if(!raw)return{pages:[],log:["ERROR: 无法识别JSON结构"]};
  log.push(raw.length+" pages in file");

  var allPages=[];
  for(var pi=0;pi<raw.length;pi++){
    var pg=raw[pi],pr=pg.prunedResult||pg;
    var blocks=pr&&Array.isArray(pr.parsing_res_list)?pr.parsing_res_list:(pg.parsing_res_list||null);
    var imgW=pr.width||767,imgH=pr.height||1274;
    var detectedPage=null,textBlocks=[],fnBlocks=[],footnotes=[];

    if(blocks&&blocks.length>0){
      var sorted=blocks.slice().sort(function(a,b){return(a.block_bbox?a.block_bbox[1]:0)-(b.block_bbox?b.block_bbox[1]:0);});
      for(var k=0;k<sorted.length;k++){
        var b=sorted[k],label=(b.block_label||"").toLowerCase(),content=stripHtml(b.block_content||"").trim(),bbox=b.block_bbox||null;
        if(label==="number"){var m=(content||"").match(/^(\d{1,4})$/);if(m)detectedPage=parseInt(m[1]);}
        else if(label==="header"||label==="header_image"||label==="footer"||label==="footer_image"||label==="aside_text"){/* skip */}
        else if(label==="footnote"){footnotes.push(content||"");if(bbox)fnBlocks.push({text:content||"",x:bbox[0],bbox:bbox,label:"footnote"});}
        else{textBlocks.push({text:content||"",x:bbox?bbox[0]:null,bbox:bbox,label:label||"text"});}
      }
    } else {
      var md=pg.markdown&&pg.markdown.text?pg.markdown.text:"";
      if(md){var parts=md.split(/\n\n+/);for(var mi=0;mi<parts.length;mi++){var mp=parts[mi].trim();if(mp.length>5)textBlocks.push({text:stripHtml(mp),x:null,bbox:null,label:"text"});}}
    }

    if(textBlocks.length>0||fnBlocks.length>0){
      allPages.push({fileIdx:pi,bookPage:null,detectedPage:detectedPage,imgW:imgW,imgH:imgH,blocks:textBlocks,fnBlocks:fnBlocks,footnotes:footnotes.join("\n"),indent:null,textSource:"ocr"});
    }
  }

  // Compute indent per page
  for(var ii=0;ii<allPages.length;ii++){
    var p=allPages[ii];if(p.blocks.length<=1)continue;
    var xs=[];for(var ti=0;ti<p.blocks.length;ti++)if(p.blocks[ti].x!==null)xs.push(p.blocks[ti].x);
    if(xs.length>0){xs.sort(function(a,b){return a-b;});p.indent=xs[0]+10;}
  }

  // Interpolate page numbers
  var anchors=[];
  for(var ai=0;ai<allPages.length;ai++){if(allPages[ai].detectedPage!==null&&allPages[ai].detectedPage>0)anchors.push({idx:ai,bp:allPages[ai].detectedPage});}
  log.push(anchors.length+"/"+allPages.length+" pages have detected numbers");
  if(anchors.length>=2){
    var cl=[anchors[0]];for(var ci=1;ci<anchors.length;ci++){if(anchors[ci].bp>=cl[cl.length-1].bp)cl.push(anchors[ci]);else log.push("WARN: 非递增 idx="+anchors[ci].idx+" bp="+anchors[ci].bp);}anchors=cl;
    for(var si=0;si<anchors.length-1;si++){var a1=anchors[si],a2=anchors[si+1],is2=a2.idx-a1.idx,bs=a2.bp-a1.bp;for(var fi=a1.idx;fi<=a2.idx;fi++)allPages[fi].bookPage=Math.round(a1.bp+(fi-a1.idx)/is2*bs);}
    var r0=(anchors[1].bp-anchors[0].bp)/(anchors[1].idx-anchors[0].idx);if(r0<=0)r0=1;
    for(var bi=anchors[0].idx-1;bi>=0;bi--){allPages[bi].bookPage=Math.round(anchors[0].bp-(anchors[0].idx-bi)*r0);if(allPages[bi].bookPage<1)allPages[bi].bookPage=bi+1;}
    var rN=(anchors[anchors.length-1].bp-anchors[anchors.length-2].bp)/(anchors[anchors.length-1].idx-anchors[anchors.length-2].idx);if(rN<=0)rN=1;
    for(var ei=anchors[anchors.length-1].idx+1;ei<allPages.length;ei++)allPages[ei].bookPage=Math.round(anchors[anchors.length-1].bp+(ei-anchors[anchors.length-1].idx)*rN);
  } else if(anchors.length===1){for(var qi=0;qi<allPages.length;qi++){allPages[qi].bookPage=anchors[0].bp+(qi-anchors[0].idx);if(allPages[qi].bookPage<1)allPages[qi].bookPage=qi+1;}}
  else{log.push("WARN: 无页码，用文件序号");for(var ni=0;ni<allPages.length;ni++)allPages[ni].bookPage=ni+1;}
  for(var oi=0;oi<allPages.length;oi++){if(allPages[oi].detectedPage!==null&&allPages[oi].detectedPage>0)allPages[oi].bookPage=allPages[oi].detectedPage;}

  var pages=allPages.filter(function(p){return p.bookPage>0&&(p.blocks.length>0||p.fnBlocks.length>0);});
  if(pages.length>0)log.push("Range: p."+pages[0].bookPage+"-"+pages[pages.length-1].bookPage+" ("+pages.length+"页)");
  return{pages:pages,log:log};
}

/* ============ HEADER/FOOTER DETECTION & REMOVAL ============ */
/*
 * 策略：
 * 1) Y坐标区域: 页面顶部12%和底部8%为页眉/页脚区
 * 2) 统计频率: 在这些区域出现的短文本(<120字)，如果在>25%的页面中重复出现 → 页眉/页脚
 * 3) 固定模式: 书名 "Naissance de la biopolitique", 课标题 "Leçon du...", 纯数字
 * 4) 移除匹配的区块，并记录日志
 */
function cleanHeaderFooter(pages){
  if(pages.length<3)return{pages:pages,log:["页数太少，跳过页眉页脚检测"]};
  var log=[], removed=0;
  var HF_TOP_RATIO=0.12, HF_BOT_RATIO=0.08;

  // Collect candidate texts from header/footer zones
  var topTexts={}, botTexts={};
  for(var i=0;i<pages.length;i++){
    var pg=pages[i], h=pg.imgH;
    var topY=h*HF_TOP_RATIO, botY=h*(1-HF_BOT_RATIO);
    for(var bi=0;bi<pg.blocks.length;bi++){
      var blk=pg.blocks[bi];
      if(!blk.bbox||blk.text.length>120)continue;
      var by1=blk.bbox[1], by2=blk.bbox[3];
      var midY=(by1+by2)/2;
      var norm=blk.text.replace(/\s+/g," ").trim().toLowerCase();
      if(norm.length<2)continue;
      if(midY<topY){topTexts[norm]=(topTexts[norm]||0)+1;}
      if(midY>botY){botTexts[norm]=(botTexts[norm]||0)+1;}
    }
  }

  // Find recurring patterns (appear in >25% of pages)
  var threshold=Math.max(3, Math.floor(pages.length*0.25));
  var hfPatterns={};
  var addP=function(t,zone){if(!hfPatterns[t])hfPatterns[t]=zone;};
  for(var t in topTexts){if(topTexts[t]>=threshold)addP(t,"header");}
  for(var t2 in botTexts){if(botTexts[t2]>=threshold)addP(t2,"footer");}

  // Also add hardcoded patterns for this book
  var FIXED_RE=[
    /^naissance\s+de\s+la\s+biopolitique$/i,
    /^le[çc]on\s+du\s+\d/i,
    /^cours\s+au\s+coll[èe]ge/i,
    /^\d{1,4}$/,  // standalone page numbers
    /^\d{1,4}\s+naissance/i,
    /^naissance.*\d{1,4}$/i
  ];

  if(Object.keys(hfPatterns).length>0)log.push("检测到"+Object.keys(hfPatterns).length+"种重复页眉/页脚模式");

  // Remove matching blocks
  for(var pi2=0;pi2<pages.length;pi2++){
    var pg2=pages[pi2], h2=pg2.imgH;
    var topY2=h2*HF_TOP_RATIO, botY2=h2*(1-HF_BOT_RATIO);
    var kept=[];
    for(var bi2=0;bi2<pg2.blocks.length;bi2++){
      var blk2=pg2.blocks[bi2];
      var shouldRemove=false;

      if(blk2.bbox&&blk2.text.length<=120){
        var midY2=(blk2.bbox[1]+blk2.bbox[3])/2;
        var inHFZone=midY2<topY2||midY2>botY2;

        if(inHFZone){
          var norm2=blk2.text.replace(/\s+/g," ").trim().toLowerCase();
          // Check frequency-based patterns
          if(hfPatterns[norm2])shouldRemove=true;
          // Check fixed regex patterns
          if(!shouldRemove){
            for(var ri=0;ri<FIXED_RE.length;ri++){if(FIXED_RE[ri].test(norm2)){shouldRemove=true;break;}}
          }
          // Short text in HF zone that's not a real paragraph (< 50 chars)
          if(!shouldRemove&&norm2.length<50&&!norm2.match(/[.;:?!]$/)){
            shouldRemove=true;
          }
        }
      }

      if(shouldRemove){removed++;}
      else{kept.push(blk2);}
    }
    pg2.blocks=kept;
  }

  // Remove pages that became empty after cleaning
  pages=pages.filter(function(p){return p.blocks.length>0||p.fnBlocks.length>0;});
  log.push("移除了"+removed+"个页眉/页脚区块");
  return{pages:pages,log:log};
}

/* ============ PDF TEXT EXTRACTION ============ */
async function extractPdfText(file,onProgress){
  await loadPdfJs();
  var doc=await window.pdfjsLib.getDocument({data:await file.arrayBuffer()}).promise;
  var pdfPages=[],total=doc.numPages;
  for(var i=1;i<=total;i++){
    if(onProgress&&(i%10===0||i===1))onProgress(i,total);
    var page=await doc.getPage(i);var vp=page.getViewport({scale:1.0});var tc=await page.getTextContent();
    var items=[];
    for(var j=0;j<tc.items.length;j++){var item=tc.items[j];if(!item.str||item.str.trim().length===0)continue;var tx=item.transform;items.push({str:item.str,x:tx[4],y:vp.height-tx[5],w:item.width||0,h:Math.abs(tx[0])||Math.abs(tx[3])||12});}
    pdfPages.push({pageIdx:i-1,pdfW:vp.width,pdfH:vp.height,items:items,fullText:items.map(function(it){return it.str;}).join(" ").replace(/\s+/g," ").trim()});
  }
  return pdfPages;
}

/* ============ COMBINE SOURCES ============ */
/*
 * combineSources: match PDF text items to JSON layout blocks.
 *
 * Root cause of overlap: adjacent OCR blocks can have bbox gaps of only
 * 2-3 pixels. Any padding causes the same PDF text item to fall inside
 * multiple blocks. Fix: each PDF text item is assigned to AT MOST ONE
 * block (the one whose bbox center is closest). We use a "used" flag.
 */
function combineSources(layoutPages,pdfPages){
  var log=[],matched=0,total=0;

  for(var i=0;i<layoutPages.length;i++){
    var lp=layoutPages[i],pp=pdfPages[lp.fileIdx];
    if(!pp||pp.items.length===0)continue;
    var sx=pp.pdfW/lp.imgW,sy=pp.pdfH/lp.imgH;
    // Mark all items as unused
    var used=new Array(pp.items.length);
    for(var u=0;u<used.length;u++)used[u]=false;

    var allBlocks=lp.blocks.concat(lp.fnBlocks||[]);

    // Sort blocks by Y position (top to bottom) so top blocks claim items first
    var blockOrder=[];
    for(var bo=0;bo<allBlocks.length;bo++)blockOrder.push(bo);
    blockOrder.sort(function(a,b){
      var ay=allBlocks[a].bbox?allBlocks[a].bbox[1]:0;
      var by2=allBlocks[b].bbox?allBlocks[b].bbox[1]:0;
      return ay-by2;
    });

    for(var boi=0;boi<blockOrder.length;boi++){
      var blk=allBlocks[blockOrder[boi]];
      total++;
      if(!blk.bbox)continue;

      // Scale bbox to PDF coords, with modest padding only on outer edges
      // Use small PAD (3pt) to handle minor misalignment, but rely on
      // the "used" flag to prevent cross-block duplication
      var PAD=3;
      var bx1=blk.bbox[0]*sx-PAD, by1=blk.bbox[1]*sy-PAD;
      var bx2=blk.bbox[2]*sx+PAD, by2=blk.bbox[3]*sy+PAD;

      // Collect UNUSED items within this bbox
      var hits=[];
      for(var pi2=0;pi2<pp.items.length;pi2++){
        if(used[pi2])continue;
        var it=pp.items[pi2];
        if(it.x>=bx1&&it.x<=bx2&&it.y>=by1&&it.y<=by2){
          hits.push({item:it,idx:pi2});
        }
      }

      if(hits.length>0){
        // Mark these items as used
        for(var hi=0;hi<hits.length;hi++)used[hits[hi].idx]=true;

        // Sort by Y then X
        hits.sort(function(a,b){var dy=a.item.y-b.item.y;return Math.abs(dy)>3?dy:a.item.x-b.item.x;});

        // Group into lines
        var lines=[],curLine=[hits[0].item],curY=hits[0].item.y;
        for(var hi2=1;hi2<hits.length;hi2++){
          if(Math.abs(hits[hi2].item.y-curY)<4)curLine.push(hits[hi2].item);
          else{lines.push(curLine);curLine=[hits[hi2].item];curY=hits[hi2].item.y;}
        }
        lines.push(curLine);

        // Build text per line
        var lineTexts=[];
        for(var li=0;li<lines.length;li++){
          var lineItems=lines[li].sort(function(a,b){return a.x-b.x;});
          var ls="";
          for(var lii=0;lii<lineItems.length;lii++){
            if(lii>0&&lineItems[lii].x-(lineItems[lii-1].x+lineItems[lii-1].w)>2)ls+=" ";
            ls+=lineItems[lii].str;
          }
          lineTexts.push(ls.trim());
        }

        // Join lines with dehyphenation
        var result="";
        for(var ri=0;ri<lineTexts.length;ri++){
          if(ri>0){
            if(result.slice(-1)==="-"||result.slice(-1)==="\u2010")result=result.slice(0,-1);
            else result+=" ";
          }
          result+=lineTexts[ri];
        }

        var cl=result.replace(/\s+/g," ").trim();
        if(cl.length>0){blk.text=cl;blk.textSource="pdf";matched++;}
      }
    }

    // Rebuild footnotes
    if(lp.fnBlocks&&lp.fnBlocks.length>0){
      var fnT=[];
      for(var fi=0;fi<lp.fnBlocks.length;fi++)if(lp.fnBlocks[fi].text)fnT.push(lp.fnBlocks[fi].text);
      if(fnT.length>0)lp.footnotes=fnT.join("\n");
    }
    lp.textSource="pdf";
  }
  log.push("匹配: "+matched+"/"+total+" blocks (无重复分配)");
  return{pages:layoutPages,log:log};
}

/* ============ PARAGRAPH ENGINE ============ */
function endsMid(text){if(!text||text.trim().length<10)return false;var c=text.trim().slice(-1);return".;:?!\u00bb\"')".indexOf(c)===-1;}
function startsLow(text){if(!text||text.trim().length<3)return false;var c=text.trim().charAt(0);return(c>="a"&&c<="z")||"\u00e0\u00e2\u00e4\u00e9\u00e8\u00ea\u00eb\u00ef\u00ee\u00f4\u00f9\u00fb\u00fc\u00ff\u00e7\u0153\u00e6".indexOf(c)!==-1;}

function buildParagraphs(pages,fromBP,toBP){
  var units=[];
  for(var i=0;i<pages.length;i++){
    var pg=pages[i];if(pg.bookPage<fromBP||pg.bookPage>toBP)continue;
    for(var bi=0;bi<pg.blocks.length;bi++){
      var blk=pg.blocks[bi],txt=blk.text.trim();
      if(txt.length<3)continue;
      if(txt.slice(-1)==="-"||txt.slice(-1)==="\u2010")txt=txt.slice(0,-1);
      var merge=false;
      if(bi===0&&units.length>0){
        if(startsLow(txt))merge=true;
        else if(endsMid(units[units.length-1].text))merge=true;
        else if(blk.x!==null&&pg.indent!==null&&blk.x<pg.indent)merge=true;
      }
      if(merge){var u=units[units.length-1];u.text+=(u.text.slice(-1)===" "?"":" ")+txt;u.endBP=pg.bookPage;}
      else units.push({text:txt,startBP:pg.bookPage,endBP:pg.bookPage});
    }
  }
  return units;
}

function fmtP(u){return u.startBP===u.endBP?String(u.startBP):u.startBP+"-"+u.endBP;}

function findParaAt(pages,bp){
  var units=buildParagraphs(pages,Math.max(1,bp-5),bp+5);
  for(var i=0;i<units.length;i++){if(units[i].startBP<=bp&&units[i].endBP>=bp)return{text:units[i].text,pages:fmtP(units[i]),startBP:units[i].startBP,endBP:units[i].endBP,all:units};}
  for(var j=0;j<units.length;j++){if(units[j].startBP>=bp)return{text:units[j].text,pages:fmtP(units[j]),startBP:units[j].startBP,endBP:units[j].endBP,all:units};}
  return null;
}

function findNextParas(pages,endBP,rawText,count){
  if(!count)count=1;
  var units=buildParagraphs(pages,Math.max(1,endBP-3),endBP+20);
  if(units.length===0)return[];
  var norm=function(s){return s.replace(/\s+/g," ").trim();};
  var rn=norm(rawText||"");
  var matchIdx=-1;
  // Match by text overlap
  for(var i=0;i<units.length;i++){
    var un=norm(units[i].text);
    if(units[i].endBP>=endBP-1&&units[i].endBP<=endBP+1){
      var tail=Math.min(60,rn.length);
      if(tail>10&&un.indexOf(rn.slice(-tail))!==-1){matchIdx=i;break;}
      var head=Math.min(60,rn.length);
      if(head>10&&un.indexOf(rn.slice(0,head))!==-1){matchIdx=i;break;}
    }
  }
  // Fallback: find by endBP
  if(matchIdx===-1){for(var j=0;j<units.length;j++){if(units[j].endBP===endBP){matchIdx=j;break;}}}
  if(matchIdx===-1){for(var k=0;k<units.length;k++){if(units[k].startBP>endBP){matchIdx=k-1;break;}}}
  if(matchIdx===-1)matchIdx=0;
  var results=[];
  for(var ri=matchIdx+1;ri<units.length&&results.length<count;ri++)results.push({text:units[ri].text,pages:fmtP(units[ri]),startBP:units[ri].startBP,endBP:units[ri].endBP});
  return results;
}

function getFootnotes(pages,fromBP,toBP){var r=[];for(var i=0;i<pages.length;i++)if(pages[i].bookPage>=fromBP&&pages[i].bookPage<=toBP&&pages[i].footnotes)r.push(pages[i].footnotes);return r.join("\n");}

/* ============ TERM HIGHLIGHT ============ */
function highlightTerms(text,glossary){
  if(!text||!glossary||glossary.length===0)return[{text:text,term:false}];
  var terms=glossary.slice().sort(function(a,b){return b[0].length-a[0].length;});
  var parts=[],rem=text;
  while(rem.length>0){
    var bi2=rem.length,bl=0,bt=null;
    for(var t=0;t<terms.length;t++){var p=rem.toLowerCase().indexOf(terms[t][0].toLowerCase());if(p!==-1&&p<bi2){bi2=p;bl=terms[t][0].length;bt=terms[t];}}
    if(!bt){parts.push({text:rem,term:false});break;}
    if(bi2>0)parts.push({text:rem.slice(0,bi2),term:false});
    parts.push({text:rem.slice(bi2,bi2+bl),term:true,def:bt[1]});
    rem=rem.slice(bi2+bl);
  }
  return parts;
}

/* ============ THEME ============ */
var T={bg:"#f5f0e8",bg2:"#ede7db",card:"#fff",cardA:"#faf6ef",bdr:"#d4cdbf",bdrL:"#e8e2d6",
  acc:"#8b6914",red:"#c0392b",grn:"#27ae60",blu:"#2563eb",
  txt:"#2c2416",txS:"#6b5d4d",txL:"#9b8e7e",fr:"#3a3028",cn:"#4a3520",fnB:"#f0ebe0",hdr:"#e8e0d0",
  termBg:"#fef3c7",termBdr:"#f59e0b"};
var sBtn={border:"none",borderRadius:6,padding:"8px 16px",cursor:"pointer",fontWeight:600,fontSize:13};
var sPri=Object.assign({},sBtn,{background:T.acc,color:"#fff"});
var sSec=Object.assign({},sBtn,{background:T.bg2,color:T.txt,border:"1px solid "+T.bdr});
var sGho=Object.assign({},sBtn,{background:"transparent",color:T.txS});
var sInp={width:"100%",background:T.bg,border:"1px solid "+T.bdrL,borderRadius:8,padding:"8px 14px",color:T.txt,fontSize:14,boxSizing:"border-box"};
var sCard={background:T.card,borderRadius:10,padding:20,marginBottom:14,border:"1px solid "+T.bdr,boxShadow:"0 1px 4px rgba(0,0,0,0.04)"};
var sLbl={fontSize:11,color:T.txL,marginBottom:8,textTransform:"uppercase",letterSpacing:1.5,fontWeight:600};

function SourceBadge(p){var isPdf=p.source==="pdf";return <span style={{fontSize:10,padding:"2px 7px",borderRadius:8,fontWeight:600,background:isPdf?"#dbeafe":"#fef3c7",color:isPdf?T.blu:"#92400e",border:"1px solid "+(isPdf?"#93c5fd":"#fcd34d")}}>{isPdf?"PDF文字":"OCR文字"}</span>;}

/* ============ MAIN ============ */
export default function App(){
  var _=useState;
  var _phase=_("loading"),phase=_phase[0],setPhase=_phase[1];
  var _srcPages=_([]),srcPages=_srcPages[0],setSrcPages=_srcPages[1];
  var _srcMeta=_(null),srcMeta=_srcMeta[0],setSrcMeta=_srcMeta[1];
  var _docs=_({pdf:null,json:null}),docs=_docs[0],setDocs=_docs[1];
  var _logs=_([]),logs=_logs[0],setLogs=_logs[1];
  var _entries=_([]),entries=_entries[0],setEntries=_entries[1];
  var _meta=_({title:"",idx:0}),meta=_meta[0],setMeta=_meta[1];
  var _glossary=_(GLOSSARY_INIT),glossary=_glossary[0],setGlossary=_glossary[1];
  var _modelKey=_("sonnet"),modelKey=_modelKey[0],setModelKey=_modelKey[1];
  var _startPage=_(""),startPage=_startPage[0],setStartPage=_startPage[1];
  var _docTitle=_(""),docTitle=_docTitle[0],setDocTitle=_docTitle[1];
  var _busy=_(false),busy=_busy[0],setBusy=_busy[1];
  var _prefetching=_(false),prefetching=_prefetching[0],setPrefetching=_prefetching[1];
  var _pfCount=_(0),pfCount=_pfCount[0],setPfCount=_pfCount[1];
  var _atEnd=_(false),atEnd=_atEnd[0],setAtEnd=_atEnd[1];
  var _err=_(""),err=_err[0],setErr=_err[1];
  var _pMsg=_(""),pMsg=_pMsg[0],setPMsg=_pMsg[1];
  var _pState=_(""),pState=_pState[0],setPState=_pState[1];
  var _showExport=_(false),showExport=_showExport[0],setShowExport=_showExport[1];
  var _showGloss=_(false),showGloss=_showGloss[0],setShowGloss=_showGloss[1];
  var _showExpl=_(true),showExpl=_showExpl[0],setShowExpl=_showExpl[1];
  var _sideBySide=_(true),sideBySide=_sideBySide[0],setSideBySide=_sideBySide[1];
  var pfRef=useRef(false),exRef=useRef(null),pdfTextRef=useRef(null);

  var modelId=MODELS[modelKey].id;
  var glossStr=glossary.map(function(g){return g[0]+"\u2192"+g[1];}).join("\n");
  var sysPrompt=buildPrompt(glossStr);

  function bpFirst(){return srcPages.length>0?srcPages[0].bookPage:1;}
  function bpLast(){return srcPages.length>0?srcPages[srcPages.length-1].bookPage:1;}
  function clrP(){setPState("");setPMsg("");}
  async function tick(){await new Promise(function(r){setTimeout(r,30);});}

  useEffect(function(){(async function(){
    var m=await sGet(SK.meta,null),e=await sGet(SK.entries,[]),g=await sGet(SK.gloss,GLOSSARY_INIT);
    var sm=await sGet(SK.src,null),d=await sGet(SK.docs,{pdf:null,json:null}),mk=await sGet(SK.model,"sonnet");
    setGlossary(g);setDocs(d);setModelKey(mk);
    if(sm){setSrcMeta(sm);setSrcPages(await sPLoad(sm.pi));}
    if(m&&e.length>0&&sm){setMeta(m);setEntries(e);setPhase("reading");}else setPhase("home");
  })();},[]);
  useEffect(function(){if(phase==="reading")sSet(SK.meta,meta);},[meta,phase]);
  useEffect(function(){if(entries.length>0)sSet(SK.entries,entries);},[entries]);
  useEffect(function(){sSet(SK.gloss,glossary);},[glossary]);
  useEffect(function(){sSet(SK.model,modelKey);},[modelKey]);

  async function saveSrc(pages,name,info,mode){
    setSrcPages(pages);var pi=await sPSave(pages);
    var sm={name:name,total:pages.length,pi:pi};setSrcMeta(sm);await sSet(SK.src,sm);
    var nd=Object.assign({},docs);nd[mode]=info;setDocs(nd);await sSet(SK.docs,nd);
  }

  /* --- Upload JSON --- */
  async function uploadJSON(file){
    setErr("");setPState("loading");setPMsg("读取JSON\u2026");await tick();
    try{
      var text=await file.text();setPMsg("解析布局\u2026");await tick();
      var result=parseOCR(JSON.parse(text));
      if(result.pages.length===0)throw new Error("解析失败");
      // Header/footer cleanup
      setPMsg("检测页眉页脚\u2026");await tick();
      var hf=cleanHeaderFooter(result.pages);
      var finalPages=hf.pages,allLogs=result.log.concat(hf.log);
      // Combine with PDF if available
      if(pdfTextRef.current){setPMsg("匹配PDF文字\u2026");await tick();var c=combineSources(finalPages,pdfTextRef.current);finalPages=c.pages;allLogs=allLogs.concat(c.log);}
      setPMsg("保存\u2026");await tick();
      await saveSrc(finalPages,file.name,{name:file.name,size:(file.size/1024).toFixed(0)+"KB"},"json");
      setLogs(allLogs);
      setPMsg("\u2713 "+finalPages.length+"页 (p."+finalPages[0].bookPage+"-"+finalPages[finalPages.length-1].bookPage+")");
      setPState("success");
    }catch(e){setErr(e.message);setPState("error");setPMsg("\u2717 "+e.message.slice(0,80));}
  }

  /* --- Upload PDF --- */
  async function uploadPDF(file){
    setErr("");setPState("loading");setPMsg("加载PDF引擎\u2026");await tick();
    try{
      await loadPdfJs();setPMsg("提取PDF文字\u2026");await tick();
      var pdfPages=await extractPdfText(file,function(cur,tot){setPMsg("提取 "+cur+"/"+tot+"\u2026");});
      pdfTextRef.current=pdfPages;
      var nd=Object.assign({},docs,{pdf:{name:file.name,size:(file.size/1048576).toFixed(1)+"MB",pageCount:pdfPages.length}});
      setDocs(nd);await sSet(SK.docs,nd);
      if(srcPages.length>0){
        setPMsg("匹配PDF文字到布局\u2026");await tick();
        var copy=JSON.parse(JSON.stringify(srcPages));
        var combined=combineSources(copy,pdfPages);
        setSrcPages(combined.pages);var pi=await sPSave(combined.pages);
        var sm=Object.assign({},srcMeta,{pi:pi});setSrcMeta(sm);await sSet(SK.src,sm);
        setLogs(function(prev){return prev.concat(["--- PDF匹配 ---"]).concat(combined.log);});
        setPMsg("\u2713 PDF文字已匹配");
      } else {
        var raw2=[];for(var i=0;i<pdfPages.length;i++)raw2.push({prunedResult:{width:Math.round(pdfPages[i].pdfW),height:Math.round(pdfPages[i].pdfH),parsing_res_list:[{block_label:"text",block_content:pdfPages[i].fullText,block_bbox:[0,80,Math.round(pdfPages[i].pdfW),Math.round(pdfPages[i].pdfH)-80]}]}});
        var result=parseOCR(raw2);
        if(result.pages.length>0){var hf2=cleanHeaderFooter(result.pages);await saveSrc(hf2.pages,file.name,nd,"pdf");setLogs(result.log.concat(hf2.log));}
        setPMsg("\u2713 "+pdfPages.length+"页PDF文字");
      }
      setPState("success");
    }catch(e){setErr(e.message);setPState("error");setPMsg("\u2717 "+e.message.slice(0,60));}
  }

  /* --- Translate --- */
  async function translatePara(paraText,paraPages,startBP,endBP,fn){
    var msg="请翻译以下法语段落。页码："+paraPages+"\n\n"+paraText;
    if(fn)msg+="\n\n脚注：\n"+fn;
    var raw=await apiCall(sysPrompt,msg,modelId,4096);
    var p=parseJSON(raw);
    if(!p)p={pages:paraPages,original:paraText,translation:raw,footnotes:"",footnotes_translation:"",explanation:"(JSON解析失败)"};
    if(!p.pages)p.pages=paraPages;
    if(p.original)p.original=p.original.replace(/^>\s*/gm,"").trim();
    p._rawText=paraText;p._startBP=startBP;p._endBP=endBP;p._model=modelKey;
    return p;
  }

  /* --- Start reading --- */
  async function handleStart(){
    var bp=parseInt(startPage);
    if(!bp){setErr("请输入书籍页码");return;}
    if(srcPages.length===0){setErr("请先上传参考文件");return;}
    if(bp<bpFirst()||bp>bpLast()){setErr("页码范围: "+bpFirst()+"-"+bpLast());return;}
    setBusy(true);setErr("");clrP();setPState("loading");setPMsg("定位段落\u2026");await tick();
    try{
      var result=findParaAt(srcPages,bp);
      if(!result)throw new Error("第"+bp+"页未找到段落");
      var fn=getFootnotes(srcPages,result.startBP-1,result.endBP+1);
      setPMsg("p."+result.pages+"（"+result.text.length+"字），调用"+MODELS[modelKey].label+"\u2026");await tick();
      var p=await translatePara(result.text,result.pages,result.startBP,result.endBP,fn);
      var title=docTitle||(srcMeta&&srcMeta.name)||"Foucault";
      setEntries([p]);setMeta({title:title,idx:0});setAtEnd(false);
      await sSet(SK.entries,[p]);await sSet(SK.meta,{title:title,idx:0});
      setPMsg("\u2713 p."+p.pages);setPState("success");await tick();
      setTimeout(function(){clrP();setPhase("reading");},500);
    }catch(e){setErr(e.message);setPState("error");setPMsg("\u2717 "+e.message.slice(0,100));}
    finally{setBusy(false);}
  }

  /* --- Fetch one next --- */
  var fetchOneNext=useCallback(async function(lastEntry,silent){
    if(srcPages.length===0||!lastEntry)return null;
    var nexts=findNextParas(srcPages,lastEntry._endBP||1,lastEntry._rawText||"",1);
    if(nexts.length===0){if(!silent)setErr("未找到下一段");setAtEnd(true);return null;}
    var next=nexts[0];
    var fn=getFootnotes(srcPages,next.startBP-1,next.endBP+1);
    if(!silent){setBusy(true);clrP();setPState("loading");setPMsg("p."+next.pages+"，调用"+MODELS[modelKey].label+"\u2026");await tick();}
    else setPrefetching(true);
    try{
      var p=await translatePara(next.text,next.pages,next.startBP,next.endBP,fn);
      if(!silent){setPMsg("\u2713 p."+p.pages);setPState("success");setTimeout(clrP,400);}
      return p;
    }catch(e){if(!silent){setErr(e.message);setPState("error");setPMsg("\u2717 "+e.message.slice(0,80));}return null;}
    finally{if(!silent)setBusy(false);else setPrefetching(false);}
  },[srcPages,sysPrompt,modelId,modelKey]);

  async function goNext(){
    var ni=meta.idx+1;
    if(ni<entries.length){setMeta({title:meta.title,idx:ni});return;}
    setErr("");clrP();
    var p=await fetchOneNext(entries[entries.length-1],false);
    if(p){setEntries(function(prev){return prev.concat([p]);});setMeta({title:meta.title,idx:ni});}
  }

  /* --- Prefetch 2 ahead --- */
  useEffect(function(){
    if(phase!=="reading"||atEnd||pfRef.current||entries.length===0)return;
    var buffered=entries.length-1-meta.idx;
    if(buffered>=2)return;
    pfRef.current=true;
    var snap=entries.slice();
    (async function(){
      var need=2-buffered,cur=snap,fetched=[];
      for(var i=0;i<need;i++){
        var last=cur[cur.length-1];
        setPrefetching(true);setPfCount(need-i);
        var p=await fetchOneNext(last,true);
        if(!p){setAtEnd(true);break;}
        fetched.push(p);cur=cur.concat([p]);
      }
      if(fetched.length>0)setEntries(function(prev){return prev.concat(fetched);});
      setPrefetching(false);setPfCount(0);pfRef.current=false;
    })();
  },[meta.idx,phase,entries.length,atEnd,fetchOneNext]);

  /* --- Retranslate --- */
  async function retranslate(idx,useMK){
    setBusy(true);setErr("");clrP();setPState("loading");
    var mk2=useMK||modelKey,mid2=MODELS[mk2].id;
    setPMsg("调用"+MODELS[mk2].label+" 重译\u2026");await tick();
    try{
      var e=entries[idx],paraText=e._rawText||(e.original||"");
      var msg="请重新翻译以下法语段落。页码："+(e.pages||"")+"\n\n"+paraText;
      var fn=getFootnotes(srcPages,(e._startBP||1)-1,(e._endBP||999)+1);
      if(fn)msg+="\n\n脚注：\n"+fn;
      var raw=await apiCall(sysPrompt,msg,mid2,4096);
      var p=parseJSON(raw);
      if(p){if(p.original)p.original=p.original.replace(/^>\s*/gm,"").trim();p._rawText=paraText;p._startBP=e._startBP;p._endBP=e._endBP;p._model=mk2;
        setEntries(function(prev){var n=prev.slice();n[idx]=p;return n;});setPState("success");setPMsg("\u2713 完成");setTimeout(clrP,600);
      }else{setPState("error");setPMsg("\u2717 JSON解析失败");}
    }catch(e2){setErr(e2.message);setPState("error");setPMsg("\u2717 "+e2.message.slice(0,60));}
    finally{setBusy(false);}
  }

  /* --- Export --- */
  function genMD(){
    var md="";
    for(var i=0;i<entries.length;i++){
      var e=entries[i];
      // Original French: add > prefix to each line
      var orig=(e.original||"").replace(/^>\s*/gm,"").trim();
      var origLines=orig.split("\n");
      for(var li=0;li<origLines.length;li++){
        var line=origLines[li].trim();
        md+=(line.length>0?"> "+line:"")+"\n";
      }
      md+="\n";
      // Chinese translation
      md+=(e.translation||"").trim()+"\n\n";
      // Footnotes if any
      if(e.footnotes){
        var fn=(e.footnotes||"").trim();
        var fnTr=(e.footnotes_translation||"").trim();
        md+=fn+"\n\n";
        if(fnTr)md+=fnTr+"\n\n";
      }
    }
    return md.trim()+"\n";
  }
  function copyMD(){navigator.clipboard.writeText(genMD()).then(function(){alert("已复制");});}
  function dlMD(){var u=URL.createObjectURL(new Blob(["\uFEFF"+genMD()],{type:"text/markdown;charset=utf-8"}));var a=document.createElement("a");a.href=u;a.download=(meta.title||"foucault")+".md";a.click();URL.revokeObjectURL(u);}

  async function resetText(){setEntries([]);setMeta({title:"",idx:0});setStartPage("");setDocTitle("");setErr("");setAtEnd(false);setShowExport(false);clrP();await sSet(SK.entries,[]);await sSet(SK.meta,null);setPhase("input");}
  async function resetAll(){await resetText();setSrcPages([]);setSrcMeta(null);pdfTextRef.current=null;setLogs([]);setDocs({pdf:null,json:null});await sSet(SK.src,null);await sSet(SK.docs,{pdf:null,json:null});await sPClear();setPhase("home");}

  /* --- Sub-Components --- */
  function StatusBar(props){
    if(!pState||!props.show)return null;
    var ic=pState==="error"?T.red:pState==="success"?T.grn:T.acc;
    var sym=pState==="loading"?"\u23f3":pState==="success"?"\u2713":"\u2717";
    return <div style={{marginTop:8,marginBottom:8,padding:"8px 14px",background:T.card,borderRadius:8,border:"1px solid "+T.bdrL,display:"flex",alignItems:"center",gap:8}}>
      <span style={{color:ic,fontSize:15}}>{sym}</span>
      <span style={{fontSize:13,color:ic,flex:1}}>{pMsg}</span>
      {pState==="loading"?<span style={{fontSize:11,color:T.txL}}>请稍候\u2026</span>:null}
    </div>;
  }

  function ModelPicker(props){return <div style={{display:"flex",gap:4}}>{Object.keys(MODELS).map(function(k){return <button key={k} onClick={function(){setModelKey(k);}} style={Object.assign({},sBtn,{padding:props.compact?"3px 8px":"5px 12px",fontSize:props.compact?11:12,background:modelKey===k?T.acc:T.bg2,color:modelKey===k?"#fff":T.txS,border:"1px solid "+(modelKey===k?T.acc:T.bdrL)})}>{MODELS[k].label}</button>;})}</div>;}

  function TermText(props){var parts=highlightTerms(props.text,glossary);return <span>{parts.map(function(p,i){return p.term?<span key={i} title={p.def} style={{background:T.termBg,borderBottom:"2px solid "+T.termBdr,cursor:"help",padding:"0 1px"}}>{p.text}</span>:<span key={i}>{p.text}</span>;})}</span>;}

  function GlossaryPanel(){return <div style={Object.assign({},sCard,{marginTop:12})}>
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}><span style={{fontWeight:700,fontSize:14}}>术语词典</span><button onClick={function(){setGlossary(function(g){return g.concat([["",""]]);});}} style={Object.assign({},sBtn,{background:T.grn,color:"#fff",padding:"4px 12px",fontSize:12})}>+</button></div>
    <div style={{maxHeight:200,overflowY:"auto"}}>{glossary.map(function(pair,i){return <div key={i} style={{display:"flex",gap:6,marginBottom:4,alignItems:"center"}}>
      <input value={pair[0]} onChange={function(e){var g=glossary.slice();g[i]=[e.target.value,g[i][1]];setGlossary(g);}} style={Object.assign({},sInp,{flex:1,padding:"3px 8px",fontSize:12,color:T.fr})}/>
      <span style={{color:T.txL,fontSize:11}}>{"\u2192"}</span>
      <input value={pair[1]} onChange={function(e){var g=glossary.slice();g[i]=[g[i][0],e.target.value];setGlossary(g);}} style={Object.assign({},sInp,{flex:1,padding:"3px 8px",fontSize:12,color:T.cn})}/>
      <button onClick={function(){setGlossary(function(g){return g.filter(function(_,j){return j!==i;});});}} style={{background:"transparent",border:"none",color:T.red,cursor:"pointer",fontSize:14}}>{"\u00d7"}</button>
    </div>;})}</div>
  </div>;}

  function SourceStatus(){
    var hj=!!docs.json,hp=!!docs.pdf,combined=hj&&hp&&srcPages.length>0&&srcPages[0].textSource==="pdf";
    return <div style={{background:T.bg,borderRadius:8,padding:12,marginBottom:8}}>
      <div style={{display:"flex",gap:16,flexWrap:"wrap",marginBottom:6}}>
        <div style={{flex:1,minWidth:140}}><div style={{fontSize:11,color:T.txL,marginBottom:4,fontWeight:600}}>布局来源</div>{hj?<div style={{fontSize:13,color:T.grn}}>{"\u2713 "+docs.json.name+" ("+docs.json.size+")"}</div>:<div style={{fontSize:13,color:T.txL}}>未上传</div>}</div>
        <div style={{flex:1,minWidth:140}}><div style={{fontSize:11,color:T.txL,marginBottom:4,fontWeight:600}}>文字来源</div>{hp?<div style={{fontSize:13,color:T.blu}}>{"\u2713 "+docs.pdf.name+" ("+docs.pdf.size+")"}</div>:<div style={{fontSize:13,color:T.txL}}>{hj?"用OCR文字":"未上传"}</div>}</div>
      </div>
      {combined?<div style={{fontSize:12,color:T.grn,fontWeight:600,borderTop:"1px solid "+T.bdrL,paddingTop:4,marginTop:4}}>{"\u2713 已合并: JSON布局 + PDF文字"}</div>:null}
      {srcPages.length>0?<div style={{fontSize:12,color:T.txS,marginTop:4}}>{"p."+bpFirst()+" \u2192 p."+bpLast()+" ("+srcPages.length+"页)"}</div>:null}
    </div>;
  }

  /* ============ RENDER ============ */
  if(phase==="loading")return <div style={{minHeight:"100vh",background:T.bg,display:"flex",alignItems:"center",justifyContent:"center",color:T.txS,fontFamily:"Georgia,serif"}}>{"加载中\u2026"}</div>;

  if(phase==="home")return(
    <div style={{minHeight:"100vh",background:T.bg,color:T.txt,fontFamily:"'Noto Serif SC',Georgia,serif"}}>
      <div style={{maxWidth:640,margin:"0 auto",padding:"60px 24px"}}>
        <div style={{textAlign:"center",marginBottom:48}}>
          <h1 style={{fontSize:28,fontWeight:700,marginBottom:6}}>福柯文本阅读辅助器</h1>
          <p style={{color:T.txS,fontSize:15,fontStyle:"italic"}}>{"Cours au Coll\u00e8ge de France"}</p>
          <p style={{color:T.txL,fontSize:12,marginTop:8}}>JSON布局 + PDF文字 → 清洗翻译</p>
        </div>
        <div style={sCard}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16,flexWrap:"wrap",gap:8}}>
            <span style={{fontSize:15,fontWeight:600}}>数据来源</span><ModelPicker/>
          </div>
          <div style={{display:"flex",gap:10,marginBottom:14,flexWrap:"wrap"}}>
            <label style={Object.assign({},sPri,{display:"inline-flex",gap:6})}>{"📐 "+(docs.json?"更换":"上传")+" OCR JSON"}<input type="file" accept=".json" style={{display:"none"}} onChange={function(e){if(e.target.files&&e.target.files[0])uploadJSON(e.target.files[0]);}}/></label>
            <label style={Object.assign({},docs.json?sPri:sSec,{display:"inline-flex",gap:6,background:docs.json?T.blu:T.bg2,color:docs.json?"#fff":T.txt})}>{"📄 "+(docs.pdf?"更换":"上传")+" PDF"}<input type="file" accept=".pdf" style={{display:"none"}} onChange={function(e){if(e.target.files&&e.target.files[0])uploadPDF(e.target.files[0]);}}/></label>
          </div>
          <StatusBar show={true}/>
          {(docs.json||docs.pdf)?<SourceStatus/>:
            <div style={{background:T.bg,borderRadius:8,padding:16,textAlign:"center"}}><p style={{fontSize:13,color:T.txS,lineHeight:1.8,margin:0}}><strong>推荐：</strong>先上传OCR JSON（布局），再上传PDF（文字）。<br/><span style={{fontSize:12,color:T.txL}}>坐标自动匹配合并。页眉页脚自动检测移除。</span></p></div>}
          {logs.length>0?<details style={{marginTop:8}}><summary style={{color:T.txL,fontSize:12,cursor:"pointer"}}>解析日志</summary><div style={{background:T.bg,borderRadius:6,padding:10,marginTop:6,maxHeight:200,overflowY:"auto"}}>{logs.map(function(l,i){return <div key={i} style={{fontSize:11,color:l.indexOf("ERROR")!==-1?T.red:l.indexOf("\u2713")!==-1||l.indexOf("移除")!==-1?T.grn:T.txL,fontFamily:"monospace"}}>{l}</div>;})}</div></details>:null}
        </div>
        <div style={{display:"flex",gap:12,flexWrap:"wrap",marginTop:16}}>
          <button disabled={srcPages.length===0} onClick={function(){clrP();setPhase("input");}} style={Object.assign({},sPri,{padding:"12px 24px",fontSize:15,flex:1,opacity:srcPages.length>0?1:0.4})}>开始新阅读</button>
          {entries.length>0?<button onClick={function(){clrP();setPhase("reading");}} style={Object.assign({},sSec,{padding:"12px 24px",fontSize:15,flex:1})}>{"继续 \u00a7"+(meta.idx+1)+"/"+entries.length}</button>:null}
        </div>
        {err?<p style={{color:T.red,fontSize:13,marginTop:12}}>{err}</p>:null}
        <div style={{marginTop:24}}><button onClick={function(){setShowGloss(!showGloss);}} style={Object.assign({},sGho,{padding:"8px 0",fontSize:13})}>{showGloss?"收起词典 \u25b2":"术语词典 \u25bc"}</button>{showGloss?<GlossaryPanel/>:null}</div>
        {(entries.length>0||srcMeta)?<div style={{marginTop:24,textAlign:"center"}}><button onClick={resetAll} style={Object.assign({},sGho,{color:T.red,fontSize:12})}>清除所有数据</button></div>:null}
      </div>
    </div>
  );

  if(phase==="input")return(
    <div style={{minHeight:"100vh",background:T.bg,color:T.txt,fontFamily:"'Noto Serif SC',Georgia,serif"}}>
      <div style={{maxWidth:560,margin:"0 auto",padding:"48px 24px"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:32}}>
          <button onClick={function(){clrP();setPhase("home");}} style={Object.assign({},sGho,{fontSize:13})}>{"\u2190 首页"}</button>
          <div style={{display:"flex",gap:8,alignItems:"center"}}>{srcPages.length>0?<SourceBadge source={srcPages[0].textSource||"ocr"}/>:null}<ModelPicker compact/></div>
        </div>
        <div style={{marginBottom:20}}><label style={{fontSize:12,color:T.txS}}>文档标题</label><input value={docTitle} onChange={function(e){setDocTitle(e.target.value);}} placeholder={"Le\u00e7on du 7 f\u00e9vrier 1979"} style={Object.assign({},sInp,{fontSize:15,fontFamily:"Georgia,serif",marginTop:4,background:T.card})}/></div>
        <div style={Object.assign({},sCard,{padding:28})}>
          <div style={{fontSize:16,fontWeight:600,marginBottom:12}}>输入起始页码</div>
          <p style={{color:T.txS,fontSize:14,marginBottom:16,lineHeight:1.7}}>定位该页完整段落（跨页合并），翻译后自动预取后续两段。</p>
          <div style={{display:"flex",gap:12,alignItems:"center"}}>
            <input value={startPage} onChange={function(e){setStartPage(e.target.value);}} type="number" placeholder="如 38" style={Object.assign({},sInp,{width:180,fontSize:18,textAlign:"center",fontFamily:"Georgia,serif",padding:"12px 16px"})} onKeyDown={function(e){if(e.key==="Enter")handleStart();}}/>
            <button onClick={handleStart} disabled={busy} style={Object.assign({},sPri,{padding:"12px 24px",fontSize:15,opacity:busy?0.5:1})}>{busy?"处理中\u2026":"开始阅读"}</button>
          </div>
          {srcPages.length>0?<p style={{color:T.txL,fontSize:12,marginTop:10}}>{"范围: "+bpFirst()+"-"+bpLast()}</p>:null}
          <StatusBar show={true}/>
        </div>
        {err?<p style={{color:T.red,fontSize:13,marginTop:12}}>{err}</p>:null}
      </div>
    </div>
  );

  /* --- READING --- */
  var idx=meta.idx,cur=entries[idx],tot=entries.length,hasN=idx<tot-1;
  var curML=cur&&cur._model&&MODELS[cur._model]?MODELS[cur._model].label:null;
  var textSrc=srcPages.length>0&&srcPages[0].textSource==="pdf"?"pdf":"ocr";
  var buffered=tot-1-idx;

  return(
    <div style={{minHeight:"100vh",background:T.bg,color:T.txt,fontFamily:"'Noto Serif SC',Georgia,serif"}}>
      {showExport?<div style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.3)",zIndex:999,display:"flex",alignItems:"center",justifyContent:"center",padding:20}} onClick={function(e){if(e.target===e.currentTarget)setShowExport(false);}}>
        <div style={{background:T.card,borderRadius:14,padding:24,maxWidth:700,width:"100%",maxHeight:"85vh",display:"flex",flexDirection:"column",border:"1px solid "+T.bdr}}>
          <div style={{display:"flex",justifyContent:"space-between",marginBottom:16}}><span style={{fontWeight:700,fontSize:16}}>导出</span><button onClick={function(){setShowExport(false);}} style={{background:"transparent",border:"none",color:T.txL,fontSize:20,cursor:"pointer"}}>{"\u00d7"}</button></div>
          <div style={{display:"flex",gap:8,marginBottom:12}}><button onClick={copyMD} style={sPri}>复制</button><button onClick={dlMD} style={Object.assign({},sBtn,{background:T.grn,color:"#fff"})}>下载.md</button></div>
          <textarea ref={exRef} readOnly value={genMD()} style={{flex:1,minHeight:300,background:T.bg,border:"1px solid "+T.bdrL,borderRadius:8,padding:16,color:T.txt,fontSize:13,fontFamily:"monospace",lineHeight:1.6,resize:"none"}}/>
        </div>
      </div>:null}

      <div style={{background:T.hdr,borderBottom:"1px solid "+T.bdr,padding:"10px 20px",display:"flex",justifyContent:"space-between",alignItems:"center",flexWrap:"wrap",gap:8}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <button onClick={function(){clrP();setPhase("home");}} style={Object.assign({},sGho,{padding:"4px 8px",fontSize:12})}>{"\u2190"}</button>
          <span style={{fontWeight:700,fontSize:14}}>{meta.title}</span>
          <span style={{color:T.txS,fontSize:12}}>{"\u00a7"+(idx+1)+"/"+tot}</span>
          {cur&&cur.pages?<span style={{color:T.acc,fontSize:12,fontStyle:"italic"}}>{"p."+cur.pages}</span>:null}
          <SourceBadge source={textSrc}/>
          {prefetching?<span style={{color:T.acc,fontSize:11}}>{"预取("+pfCount+")\u2026"}</span>:null}
          {!prefetching&&buffered>0?<span style={{color:T.grn,fontSize:11}}>{"\u2713 缓存"+buffered+"段"}</span>:null}
        </div>
        <div style={{display:"flex",gap:6,flexWrap:"wrap",alignItems:"center"}}>
          <ModelPicker compact/>
          <button onClick={function(){setSideBySide(!sideBySide);}} style={Object.assign({},sSec,{fontSize:11,padding:"5px 10px"})}>{sideBySide?"上下":"左右"}</button>
          <button onClick={function(){setShowExpl(!showExpl);}} style={Object.assign({},sSec,{fontSize:11,padding:"5px 10px"})}>{showExpl?"隐藏解释":"解释"}</button>
          <button onClick={function(){setShowGloss(!showGloss);}} style={Object.assign({},sSec,{fontSize:11,padding:"5px 10px"})}>词典</button>
          <button onClick={function(){setShowExport(true);}} style={Object.assign({},sBtn,{background:T.grn,color:"#fff",fontSize:11,padding:"5px 10px"})}>导出</button>
          <button onClick={resetText} style={Object.assign({},sGho,{fontSize:11,padding:"5px 10px",border:"1px solid "+T.bdrL})}>新文本</button>
        </div>
      </div>
      {showGloss?<div style={{padding:"0 20px",maxWidth:960,margin:"0 auto"}}><GlossaryPanel/></div>:null}
      {err?<p style={{color:T.red,fontSize:13,padding:"8px 20px"}}>{err}</p>:null}
      <div style={{padding:"0 20px",maxWidth:960,margin:"0 auto"}}><StatusBar show={true}/></div>

      <div style={{display:"flex",alignItems:"center",justifyContent:"center",gap:10,padding:"16px 20px 0"}}>
        <button onClick={function(){setMeta({title:meta.title,idx:Math.max(0,meta.idx-1)});}} disabled={idx===0} style={Object.assign({},sSec,{opacity:idx===0?0.4:1})}>{"\u2190 上一段"}</button>
        <select value={idx} onChange={function(e){setMeta({title:meta.title,idx:parseInt(e.target.value)});}} style={{background:T.card,border:"1px solid "+T.bdr,borderRadius:6,padding:"6px 10px",color:T.txt,fontSize:13}}>
          {entries.map(function(ent,j){return <option key={j} value={j}>{"\u00a7"+(j+1)+(ent.pages?" p."+ent.pages:"")}</option>;})}
        </select>
        <button onClick={goNext} disabled={busy||(atEnd&&!hasN)} style={Object.assign({},sPri,{opacity:(busy||(atEnd&&!hasN))?0.4:1})}>{busy?"加载中\u2026":hasN?"下一段 \u2192":atEnd?"已到末尾":"下一段 \u2192"}</button>
      </div>

      <div style={{padding:"20px 20px 80px",maxWidth:960,margin:"0 auto"}}>
        {cur?<div>
          <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:10}}>
            {curML?<span style={{fontSize:11,color:T.txL,background:T.bg2,padding:"2px 8px",borderRadius:8}}>{curML}</span>:null}
            {cur.pages?<span style={{background:T.bg2,color:T.acc,fontSize:12,padding:"3px 10px",borderRadius:10,fontWeight:600,border:"1px solid "+T.bdrL}}>{"p."+cur.pages}</span>:null}
          </div>

          {sideBySide?(
            <div style={{display:"flex",gap:16,alignItems:"stretch"}}>
              <div style={{flex:1,minWidth:0}}>
                <div style={sCard}><div style={sLbl}>{"Texte fran\u00e7ais"}</div><div style={{color:T.fr,fontSize:15,lineHeight:2,fontFamily:"Georgia,'Noto Serif',serif",whiteSpace:"pre-wrap"}}><TermText text={cur.original||""}/></div></div>
                {cur.footnotes?<div style={{background:T.fnB,borderRadius:10,padding:14,marginBottom:14,borderLeft:"3px solid "+T.bdr}}><div style={sLbl}>Notes</div><div style={{color:T.txS,fontSize:13,lineHeight:1.7,fontFamily:"Georgia,serif",whiteSpace:"pre-wrap"}}>{cur.footnotes}</div></div>:null}
              </div>
              <div style={{flex:1,minWidth:0}}>
                <div style={Object.assign({},sCard,{background:T.cardA})}><div style={sLbl}>中文翻译</div><div style={{color:T.cn,fontSize:15,lineHeight:2.1,fontFamily:"'Noto Serif SC','Source Han Serif SC',SimSun,serif",whiteSpace:"pre-wrap"}}>{cur.translation||""}</div></div>
                {cur.footnotes_translation?<div style={{background:T.fnB,borderRadius:10,padding:14,marginBottom:14,borderLeft:"3px solid "+T.acc+"44"}}><div style={sLbl}>脚注翻译</div><div style={{color:T.cn,fontSize:13,lineHeight:1.8,fontFamily:"'Noto Serif SC',SimSun,serif",whiteSpace:"pre-wrap"}}>{cur.footnotes_translation}</div></div>:null}
              </div>
            </div>
          ):(
            <div>
              <div style={sCard}><div style={sLbl}>{"Texte fran\u00e7ais"}</div><div style={{color:T.fr,fontSize:16,lineHeight:2,fontFamily:"Georgia,'Noto Serif',serif",whiteSpace:"pre-wrap"}}><TermText text={cur.original||""}/></div></div>
              {cur.footnotes?<div style={{background:T.fnB,borderRadius:10,padding:16,marginBottom:14,borderLeft:"3px solid "+T.bdr}}><div style={sLbl}>Notes</div><div style={{color:T.txS,fontSize:14,lineHeight:1.8,fontFamily:"Georgia,serif",whiteSpace:"pre-wrap"}}>{cur.footnotes}</div></div>:null}
              <div style={Object.assign({},sCard,{background:T.cardA})}><div style={sLbl}>中文翻译</div><div style={{color:T.cn,fontSize:16,lineHeight:2.1,fontFamily:"'Noto Serif SC','Source Han Serif SC',SimSun,serif",whiteSpace:"pre-wrap"}}>{cur.translation||""}</div></div>
              {cur.footnotes_translation?<div style={{background:T.fnB,borderRadius:10,padding:16,marginBottom:14,borderLeft:"3px solid "+T.acc+"44"}}><div style={sLbl}>脚注翻译</div><div style={{color:T.cn,fontSize:14,lineHeight:1.9,fontFamily:"'Noto Serif SC',SimSun,serif",whiteSpace:"pre-wrap"}}>{cur.footnotes_translation}</div></div>:null}
            </div>
          )}

          {showExpl&&cur.explanation?<div style={Object.assign({},sCard,{borderLeft:"3px solid "+T.grn})}><div style={sLbl}>解释</div><div style={{color:T.txt,fontSize:14,lineHeight:1.9,whiteSpace:"pre-wrap"}}>{cur.explanation}</div></div>:null}

          <div style={{display:"flex",justifyContent:"center",gap:8,marginTop:12,flexWrap:"wrap"}}>
            <button onClick={function(){retranslate(idx);}} disabled={busy} style={Object.assign({},sGho,{fontSize:12,opacity:busy?0.4:1})}>{"用"+MODELS[modelKey].label+"重译"}</button>
            {Object.keys(MODELS).filter(function(k){return k!==modelKey;}).map(function(k){return <button key={k} onClick={function(){retranslate(idx,k);}} disabled={busy} style={Object.assign({},sGho,{fontSize:12,color:T.acc,opacity:busy?0.4:1,border:"1px solid "+T.bdrL})}>{"换"+MODELS[k].label+"重译"}</button>;})}
          </div>
        </div>:null}

        {busy&&!cur?<div style={{textAlign:"center",padding:48,color:T.txS}}>{"加载中\u2026"}</div>:null}

        <div style={{marginTop:28}}>
          <div style={{display:"flex",gap:3,flexWrap:"wrap"}}>{entries.map(function(_2,j){return <div key={j} onClick={function(){setMeta({title:meta.title,idx:j});}} style={{width:18,height:5,borderRadius:3,cursor:"pointer",background:j===idx?T.acc:j<=idx?T.grn:T.bdr,opacity:j===idx?1:j<=idx?0.6:0.3}}/>;})}</div>
          <div style={{fontSize:11,color:T.txL,marginTop:6}}>{"已处理"+tot+"段"+(atEnd?" · 末尾":"")+(buffered>0?" · 缓存"+buffered+"段":"")}</div>
        </div>
      </div>
    </div>
  );
}

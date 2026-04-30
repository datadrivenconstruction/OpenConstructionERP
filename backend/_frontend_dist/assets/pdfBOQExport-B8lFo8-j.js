import{c as x,aB as w}from"./index-lb0kK4Wd.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const P=x("Printer",[["path",{d:"M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2",key:"143wyd"}],["path",{d:"M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6",key:"1itne7"}],["rect",{x:"6",y:"14",width:"12",height:"8",rx:"1",key:"1ue0tg"}]]);function S(e){return e.split(/\r?\n/).filter(s=>s.trim()).map(s=>{const n=[];let t="",r=!1;for(const c of s)c==='"'?r=!r:(c===","||c===";"||c==="	")&&!r?(n.push(t.trim()),t=""):t+=c;return n.push(t.trim()),n})}function C(e){const i={},s=e.map(n=>n.toLowerCase().trim());for(let n=0;n<s.length;n++){const t=s[n]??"";if(!t)continue;const r=String(n);/^(ordinal|pos|no\.?|item|ref|code)$/i.test(t)?i.ordinal=r:/^(description|desc|text|bezeichnung|libellé|désignation)$/i.test(t)?i.description=r:/^(unit|uom|einheit|unité)$/i.test(t)?i.unit=r:/^(qty|quantity|menge|quantité)$/i.test(t)?i.quantity=r:/^(rate|unit.?rate|price|ep|einheitspreis|prix.?unitaire)$/i.test(t)?i.unitRate=r:/^(total|amount|gp|gesamtpreis|montant)$/i.test(t)?i.total=r:/^(section|group|trade|lot|gewerk)$/i.test(t)?i.section=r:/^(class|classification|code|nrm|masterformat|din)$/i.test(t)&&(i.classification=r)}return i}function m(e){const i=e.replace(/[^\d.,\-]/g,"");return i?/\d\.\d{3}(,|$)/.test(i)?parseFloat(i.replace(/\./g,"").replace(",","."))||0:parseFloat(i.replace(",","."))||0:0}function F(e,i,s=!0){const n=s?e.slice(1):e,t=[],r=[],c=[];for(let o=0;o<n.length;o++){const u=n[o];if(!u||u.every(g=>!g))continue;const l=g=>{const $=i[g];return $==null?"":u[parseInt($,10)]??""},p=l("description");if(!p)continue;const a=m(l("quantity")),h=m(l("unitRate")),y=l("total"),b=y&&m(y)||a*h;t.push({ordinal:l("ordinal")||String(o+1),description:p,unit:l("unit")||"pcs",quantity:a,unitRate:h,total:b,section:l("section")||void 0,classification:l("classification")?{code:l("classification")}:void 0})}return t.length===0&&c.push("No valid positions found in the file."),{positions:t,warnings:r,errors:c,metadata:{positionCount:t.length,totalValue:t.reduce((o,u)=>o+u.total,0)}}}async function R(e,i){const s=await e.text(),n=S(s);if(n.length<2)return{positions:[],warnings:[],errors:["File is empty or has insufficient data."]};const t=i??C(n[0]);return F(n,t)}function f(e){return e.includes(",")||e.includes('"')||e.includes(`
`)||e.includes(";")?`"${e.replace(/"/g,'""')}"`:e}function q(e,i,s){const n=(s==null?void 0:s.separator)??",",t=(s==null?void 0:s.includePrices)??!0,r=["No.","Description","Unit","Quantity"];t&&r.push("Unit Rate","Total"),i.classification&&r.push(i.classification),e.some(o=>o.section)&&r.push("Section");const c=[r.map(f).join(n)];for(const o of e){if(o.isSection){c.push([f(o.ordinal),f(`** ${o.description} **`),"","",...t?["",""]:[]].join(n));continue}const u=[f(o.ordinal),f(o.description),f(o.unit),o.quantity.toFixed(3)];if(t&&u.push(o.unitRate.toFixed(2),o.total.toFixed(2)),i.classification&&o.classification){const l=Object.values(o.classification)[0]??"";u.push(f(l))}e.some(l=>l.section)&&u.push(f(o.section??"")),c.push(u.join(n))}return c.join(`\r
`)}function j(e,i,s,n){const t=q(e,i,n);return{blob:new Blob(["\uFEFF"+t],{type:"text/csv;charset=utf-8"}),filename:s.endsWith(".csv")?s:`${s}.csv`,positionCount:e.filter(c=>!c.isSection).length,totalValue:e.reduce((c,o)=>c+(o.isSection?0:o.total),0)}}function T(e,i){w(e,i)}const d=e=>String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");function v(e,i,s={}){const{projectName:n="Project",boqName:t="Bill of Quantities",includePrices:r=!0,date:c=new Date().toLocaleDateString()}=s,o=e.reduce((a,h)=>a+(h.isSection?0:h.total),0),u=e.filter(a=>!a.isSection).length,l=a=>`${d(i.currencySymbol)}${a.toLocaleString(void 0,{minimumFractionDigits:2,maximumFractionDigits:2})}`,p=e.map(a=>a.isSection?`<tr class="section"><td colspan="${r?6:4}"><strong>${d(a.ordinal)} ${d(a.description)}</strong></td></tr>`:`<tr>
        <td>${d(a.ordinal)}</td>
        <td>${d(a.description)}</td>
        <td class="center">${d(a.unit)}</td>
        <td class="right">${a.quantity.toFixed(3)}</td>
        ${r?`<td class="right">${l(a.unitRate)}</td><td class="right">${l(a.total)}</td>`:""}
      </tr>`).join(`
`);return`<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>${d(t)}</title>
<style>
  body { font-family: Arial, sans-serif; font-size: 10pt; margin: 20mm; color: #222; }
  h1 { font-size: 16pt; margin-bottom: 4px; }
  h2 { font-size: 12pt; color: #555; margin-top: 0; }
  .meta { color: #777; font-size: 9pt; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th { background: #f5f5f5; padding: 6px 8px; text-align: left; border-bottom: 2px solid #ddd; font-size: 9pt; }
  td { padding: 4px 8px; border-bottom: 1px solid #eee; }
  .right { text-align: right; }
  .center { text-align: center; }
  .section td { background: #f9f9f9; padding: 8px; }
  .total { font-weight: bold; border-top: 2px solid #333; font-size: 11pt; }
  @media print { body { margin: 10mm; } }
</style>
</head><body>
  <h1>${d(n)}</h1>
  <h2>${d(t)} — ${d(i.name)} (${d(i.country)})</h2>
  <div class="meta">${d(c)} | ${u} positions | Standard: ${d(i.classification)} | Currency: ${d(i.currency)}</div>
  <table>
    <thead>
      <tr>
        <th style="width:8%">No.</th>
        <th>Description</th>
        <th style="width:6%" class="center">Unit</th>
        <th style="width:10%" class="right">Qty</th>
        ${r?'<th style="width:12%" class="right">Rate</th><th style="width:12%" class="right">Total</th>':""}
      </tr>
    </thead>
    <tbody>
      ${p}
    </tbody>
    ${r?`<tfoot><tr class="total"><td colspan="5" class="right">Grand Total:</td><td class="right">${l(o)}</td></tr></tfoot>`:""}
  </table>
</body></html>`}function V(e,i,s){const n=v(e,i,s),t=window.open("","_blank");t&&(t.document.write(n),t.document.close(),t.focus(),setTimeout(()=>t.print(),500))}export{P,V as a,T as d,j as e,R as p};

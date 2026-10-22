/* SAURon Lovelace card. No external UI dependencies. */
const DOMAIN = "sauron";
const KEYS = ["estimated_index","daily_liters","daily_date","weekly_m3","previous_week_m3","monthly_m3","yearly_m3","last_index","last_index_date","data_freshness_hours","last_successful_poll","meter_serial","meter_brand","meter_model","meter_diameter","telereleve_tech"];
const LABELS = {estimated_index:"Index estimé",daily_liters:"Dernière consommation",daily_date:"Date de consommation",weekly_m3:"Cette semaine",previous_week_m3:"Semaine précédente",monthly_m3:"Ce mois",yearly_m3:"Cette année",last_index:"Index physique",last_index_date:"Dernier relevé physique",data_freshness_hours:"Âge des données",last_successful_poll:"Dernier polling",meter_serial:"N° de série",meter_brand:"Fabricant",meter_model:"Modèle",meter_diameter:"Diamètre",telereleve_tech:"Télérelève"};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (s) => !s || ["unknown","unavailable"].includes(s.state) ? "—" : esc(s.state + (s.attributes?.unit_of_measurement ? " " + s.attributes.unit_of_measurement : ""));
const style = `
:host {display:block;color:var(--primary-text-color)}
ha-card {padding:18px;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color)}
header {display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}
h2 {font-size:1.2rem;font-weight:600;margin:0} h3{font-size:1rem;margin:18px 0 10px}
.muted{color:var(--secondary-text-color);font-size:.85rem}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px}
.metric{border-radius:12px;background:var(--secondary-background-color);padding:12px;min-width:0}
.metric .value{font-size:1.35rem;font-weight:650;margin-top:6px;overflow-wrap:anywhere}
.rows{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}
.row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--divider-color)}
.row span:last-child{text-align:right;overflow-wrap:anywhere}
.controls{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button,select{border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color);padding:7px 10px;cursor:pointer}
button[aria-pressed=true]{background:var(--primary-color);color:var(--text-primary-color,#fff)}
.chart{width:100%;height:auto;display:block;overflow:visible}
details{margin-top:14px}summary{cursor:pointer;font-weight:600}
.diagnostic-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:12px;margin-top:14px}
.diagnostic-group{background:var(--secondary-background-color);border-radius:12px;padding:14px;min-width:0}
.diagnostic-group h4{font-size:.9rem;margin:0 0 12px;font-weight:600}
.diagnostic-items{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,170px),1fr));gap:14px}
.diagnostic-item{min-width:0}
.diagnostic-label{font-size:.78rem;color:var(--secondary-text-color);margin-bottom:5px}
.diagnostic-value{font-size:.95rem;font-weight:500;overflow-wrap:anywhere;line-height:1.4}
.notice{font-size:.85rem;color:var(--secondary-text-color);margin-top:10px}
`;
class SauronCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:"open"});this._config={};this._days=7;this._registry=null;this._entries=null;this._stats=[];this._error="";this._busy=false;}
  setConfig(config){this._config={show_diagnostics:true,show_chart:true,mode:"detailed",...config};this._days=Number(config.days)||7;this._registry=null;this._entries=null;this._render();}
  set hass(hass){const first=!this._hass;this._hass=hass;if(first||!this._registry){this._discover();}else{this._render();}}
  getCardSize(){return this._config.mode==="compact"?3:7;}
  getGridOptions(){return {columns:this._config.mode==="compact"?4:12,min_columns:3,rows:"auto"};}
  static getConfigElement(){return document.createElement("sauron-card-editor");}
  static getStubConfig(){return {type:"custom:sauron-card",mode:"detailed",days:7};}
  async _discover(){
    if(!this._hass||this._busy)return;
    this._busy=true;
    try{
      const registry=await this._hass.callWS({type:"config/entity_registry/list"});
      this._registry=(Array.isArray(registry)?registry:[]).filter(e=>e.platform===DOMAIN && e.entity_id?.startsWith("sensor."));
      this._entries=[];
      this._error="";
      await this._loadStats();
    }catch(e){this._error="Découverte SAUron impossible : "+String(e.message||e);}
    finally{this._busy=false;this._render();}
  }
  _entryId(){
    const ids=[...new Set((this._registry||[]).map(e=>e.config_entry_id).filter(Boolean))];
    return ids.includes(this._config.entry_id)?this._config.entry_id:ids[0];
  }
  _entities(){
    const entry=this._entryId(),result={};
    for(const e of this._registry||[]){
      if(e.config_entry_id!==entry)continue;
      for(const key of KEYS){
        if(e.unique_id?.endsWith("_"+key))result[key]=e.entity_id;
      }
    }
    return result;
  }
  async _loadStats(){
    const entry=this._entryId();
    if(!entry||!this._hass)return;
    const statisticId="sauron:daily_water_"+entry.toLowerCase();
    const start=new Date(Date.now()-(this._days+3)*86400000).toISOString();
    try{
      const response=await this._hass.callWS({type:"recorder/statistics_during_period",start_time:start,statistic_ids:[statisticId],period:"day",types:["sum"]});
      const rows=(response?.[statisticId]||[]).filter(r=>r.sum!==null && Number.isFinite(Number(r.sum)));
      this._stats=rows.slice(1).map((r,i)=>({...r,change:Math.max(0,Number(r.sum)-Number(rows[i].sum))})).slice(-this._days);
      this._error="";
    }catch(e){this._stats=[];this._error="Historique indisponible : "+String(e.message||e);}
    this._render();
  }
  _metric(key,entities){const state=this._hass?.states[entities[key]];return '<div class="metric"><div class="muted">'+LABELS[key]+'</div><div class="value">'+fmt(state)+'</div></div>';}
  _rows(keys,entities){return '<div class="rows">'+keys.filter(k=>entities[k]).map(k=>'<div class="row"><span>'+LABELS[k]+'</span><span>'+fmt(this._hass?.states[entities[k]])+'</span></div>').join("")+'</div>';}
  _diagnosticValue(key,entities){
    const state=this._hass?.states[entities[key]];
    if(!state||["unknown","unavailable"].includes(state.state))return "—";
    if(key==="daily_date"||key==="last_successful_poll"){
      const date=new Date(state.state);
      if(!Number.isNaN(date.getTime())){
        const options=key==="daily_date"?{dateStyle:"medium"}:{dateStyle:"medium",timeStyle:"short"};
        return esc(new Intl.DateTimeFormat(this._hass?.locale?.language||"fr-FR",options).format(date));
      }
    }
    if(key==="data_freshness_hours"){
      const hours=Number(state.state);
      if(Number.isFinite(hours)&&hours>=0){
        const minutes=Math.round(hours*60);
        return esc(minutes>=60?Math.floor(minutes/60)+" h"+(minutes%60?" "+minutes%60+" min":""):minutes+" min");
      }
    }
    return fmt(state);
  }
  _diagnostics(entities){
    const groups=[
      ["Suivi des données",["daily_date","last_successful_poll","data_freshness_hours"]],
      ["Compteur",["meter_serial","meter_brand","meter_model","meter_diameter"]],
      ["Communication",["telereleve_tech"]]
    ];
    return '<div class="diagnostic-groups">'+groups.map(([title,keys])=>{
      const items=keys.filter(key=>entities[key]).map(key=>
        '<div class="diagnostic-item"><div class="diagnostic-label">'+LABELS[key]+'</div><div class="diagnostic-value">'+this._diagnosticValue(key,entities)+'</div></div>'
      ).join("");
      return items?'<section class="diagnostic-group"><h4>'+title+'</h4><div class="diagnostic-items">'+items+'</div></section>':"";
    }).join("")+'</div>';
  }
  _chart(){
    if(!this._stats.length)return '<p class="muted">Aucune statistique disponible sur la période.</p>';
    const data=this._stats.map(r=>{
      const raw=r.start;
      const numeric=/^\d+(?:\.\d+)?$/.test(String(raw));
      const date=new Date(numeric?(Number(raw)<1e11?Number(raw)*1000:Number(raw)):raw);
      return {date,value:Number(r.change ?? r.state ?? 0)};
    }).filter(x=>Number.isFinite(x.value)&&!Number.isNaN(x.date.getTime()));
    if(!data.length)return '<p class="muted">Aucune donnée exploitable.</p>';
    const locale=this._hass?.locale?.language||"fr-FR";
    const formatDate=date=>date.toLocaleDateString(locale,{day:"numeric",month:"short"});
    const max=Math.max(.001,...data.map(x=>x.value));
    const width=800,height=250,left=62,right=12,top=14,base=208;
    const plotWidth=width-left-right,plotHeight=base-top,step=plotWidth/data.length;
    const tickCount=4;
    const grid=Array.from({length:tickCount+1},(_,i)=>{
      const value=max*i/tickCount,y=base-(value/max)*plotHeight;
      const label=value.toLocaleString(locale,{maximumFractionDigits:3});
      return '<line x1="'+left+'" x2="'+(width-right)+'" y1="'+y+'" y2="'+y+'" stroke="var(--divider-color)" stroke-dasharray="'+(i===0?"none":"3 5")+'" opacity=".65"/>'+
        '<text x="'+(left-9)+'" y="'+(y+4)+'" text-anchor="end" font-size="11" fill="var(--secondary-text-color)">'+esc(label)+'</text>';
    }).join("");
    const labelEvery=Math.max(1,Math.ceil(data.length/9));
    const bars=data.map((x,i)=>{
      const h=Math.max(0,x.value/max*plotHeight),xx=left+i*step+step*.13;
      const label=formatDate(x.date),barWidth=Math.max(1,step*.74);
      const tooltip=x.date.toLocaleDateString(locale,{dateStyle:"full"})+" : "+x.value.toLocaleString(locale,{maximumFractionDigits:3})+" m³";
      const bar='<rect x="'+xx+'" y="'+(base-h)+'" width="'+barWidth+'" height="'+h+'" rx="'+Math.min(3,barWidth/2)+'" fill="var(--primary-color)" opacity=".82"><title>'+esc(tooltip)+'</title></rect>';
      const showLabel=i===0||i===data.length-1||(i%labelEvery===0&&i+labelEvery<data.length);
      return bar+(showLabel?'<text x="'+(xx+barWidth/2)+'" y="232" text-anchor="middle" font-size="11" fill="var(--secondary-text-color)">'+esc(label)+'</text>':"");
    }).join("");
    return '<svg class="chart" viewBox="0 0 '+width+' '+height+'" role="img" aria-label="Historique de consommation en mètres cubes">'+
      '<text x="8" y="11" font-size="11" fill="var(--secondary-text-color)">m³</text>'+grid+bars+'</svg>';
  }
  _render(){
    if(!this.shadowRoot)return;
    const entities=this._entities(),ids=[...new Set((this._registry||[]).map(e=>e.config_entry_id).filter(Boolean))];
    const compact=this._config.mode==="compact";
    const detailsOpen=this.shadowRoot.querySelector("details")?.open||false;
    const options=ids.map(id=>'<option value="'+esc(id)+'" '+(id===this._entryId()?'selected':'')+'>'+esc(this._entries?.find(e=>e.entry_id===id)?.title||id)+'</option>').join("");
    this.shadowRoot.innerHTML='<style>'+style+'</style><ha-card><header><div><h2>💧 SAUron</h2><div class="muted">Consommation d’eau</div></div>'+(ids.length>1?'<select id="meter" aria-label="Compteur">'+options+'</select>':'')+'</header>'+(ids.length===0?'<p class="muted">Recherche des compteurs SAUron…</p>':'<div class="metrics">'+["daily_liters","weekly_m3","monthly_m3","yearly_m3"].filter(k=>entities[k]).map(k=>this._metric(k,entities)).join("")+'</div>'+(compact?"":'<h3>Index</h3>'+this._rows(["estimated_index","last_index","last_index_date"],entities))+(this._config.show_chart===false?"":'<h3>Historique</h3><div class="controls">'+[7,30,90].map(d=>'<button data-days="'+d+'" aria-pressed="'+(d===this._days)+'">'+d+' j</button>').join("")+'</div>'+this._chart())+(this._config.show_diagnostics===false||compact?"":'<details><summary>Informations et diagnostic</summary>'+this._diagnostics(entities)+'</details>'))+(this._error?'<p class="notice">'+esc(this._error)+'</p>':'')+'</ha-card>';
    if(detailsOpen && this.shadowRoot.querySelector("details"))this.shadowRoot.querySelector("details").open=true;
    this.shadowRoot.querySelector("#meter")?.addEventListener("change",e=>{this._config={...this._config,entry_id:e.target.value};this._stats=[];this._loadStats();});
    this.shadowRoot.querySelectorAll("[data-days]").forEach(b=>b.addEventListener("click",()=>{this._days=Number(b.dataset.days);this._stats=[];this._loadStats();}));
  }
}
class SauronCardEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:"open"});}
  setConfig(config){this._config=config;this._render();}
  set hass(hass){this._hass=hass;this._render();}
  _render(){
    if(!this._config)return;
    this.shadowRoot.innerHTML='<style>label{display:block;margin:12px 0}select,input{margin-left:8px}</style><label>Présentation <select id="mode"><option value="detailed">Détaillée</option><option value="compact">Compacte</option></select></label><label>Période initiale <select id="days"><option value="7">7 jours</option><option value="30">30 jours</option><option value="90">90 jours</option></select></label><label><input type="checkbox" id="show_chart"> Afficher le graphique</label><label><input type="checkbox" id="show_diagnostics"> Afficher les diagnostics</label>';
    for(const key of ["mode","days","show_chart","show_diagnostics"]){const el=this.shadowRoot.getElementById(key);el.checked=this._config[key]!==false; if(key==="mode"||key==="days")el.value=String(this._config[key]??(key==="mode"?"detailed":7));el.addEventListener("change",()=>{const value=key==="mode"?el.value:key==="days"?Number(el.value):el.checked;this._config={...this._config,[key]:value};this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._config},bubbles:true,composed:true}));});}
  }
}
if(!customElements.get("sauron-card"))customElements.define("sauron-card",SauronCard);
if(!customElements.get("sauron-card-editor"))customElements.define("sauron-card-editor",SauronCardEditor);
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==="sauron-card"))window.customCards.push({type:"sauron-card",name:"SAUron",description:"Consommation d’eau SAUR et historique Recorder"});

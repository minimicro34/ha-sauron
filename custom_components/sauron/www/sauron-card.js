/* SAURon Lovelace card — v0.7.0 beta 1. No external UI dependencies. */
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
.notice{font-size:.85rem;color:var(--secondary-text-color);margin-top:10px}
`;
class SauronCard extends HTMLElement {
  constructor(){super();this.attachShadow({mode:"open"});this._config={};this._days=7;this._registry=null;this._entries=null;this._stats=[];this._error="";this._busy=false;}
  setConfig(config){this._config={show_diagnostics:true,show_chart:true,mode:"detailed",...config};this._days=Number(config.days)||7;this._registry=null;this._entries=null;this._render();}
  set hass(hass){const first=!this._hass;this._hass=hass;if(first||!this._registry){this._discover();}else{this._render();}}
  getCardSize(){return this._config.mode==="compact"?3:7;}
  static getConfigElement(){return document.createElement("sauron-card-editor");}
  static getStubConfig(){return {type:"custom:sauron-card",mode:"detailed",days:7};}
  async _discover(){
    if(!this._hass||this._busy)return;
    this._busy=true;
    try{
      const [registry,entries]=await Promise.all([
        this._hass.callWS({type:"config/entity_registry/list"}),
        this._hass.callWS({type:"config_entries/get"})
      ]);
      this._registry=registry.filter(e=>e.platform===DOMAIN && e.domain==="sensor");
      this._entries=(Array.isArray(entries)?entries:entries?.entries||[]).filter(e=>e.domain===DOMAIN);
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
    const start=new Date(Date.now()-(this._days+2)*86400000).toISOString();
    try{
      const response=await this._hass.callWS({type:"recorder/statistics_during_period",start_time:start,statistic_ids:[statisticId],period:"day",types:["sum","state","change"]});
      this._stats=(response?.[statisticId]||[]).slice(-this._days);
      this._error="";
    }catch(e){this._stats=[];this._error="Historique indisponible : "+String(e.message||e);}
    this._render();
  }
  _metric(key,entities){const state=this._hass?.states[entities[key]];return '<div class="metric"><div class="muted">'+LABELS[key]+'</div><div class="value">'+fmt(state)+'</div></div>';}
  _rows(keys,entities){return '<div class="rows">'+keys.filter(k=>entities[k]).map(k=>'<div class="row"><span>'+LABELS[k]+'</span><span>'+fmt(this._hass?.states[entities[k]])+'</span></div>').join("")+'</div>';}
  _chart(){
    if(!this._stats.length)return '<p class="muted">Aucune statistique disponible sur la période.</p>';
    const data=this._stats.map(r=>({date:new Date(r.start*1000),value:Number(r.change ?? r.state ?? 0)})).filter(x=>Number.isFinite(x.value)&&!Number.isNaN(x.date.getTime()));
    if(!data.length)return '<p class="muted">Aucune donnée exploitable.</p>';
    const max=Math.max(.001,...data.map(x=>x.value));const width=800,height=225,base=185,step=width/data.length;
    const bars=data.map((x,i)=>{const h=Math.max(0,(x.value/max)*160);const xx=i*step+step*.13;const label=x.date.toLocaleDateString(undefined,{day:"numeric",month:"short"});return '<rect x="'+xx+'" y="'+(base-h)+'" width="'+(step*.74)+'" height="'+h+'" rx="3" fill="var(--primary-color)" opacity=".78"><title>'+esc(label+" : "+x.value.toFixed(3)+" m³")+'</title></rect>'+(data.length<=15||i%Math.ceil(data.length/10)===0?'<text x="'+(xx+step*.37)+'" y="207" text-anchor="middle" font-size="12" fill="var(--secondary-text-color)">'+esc(label)+'</text>':"");}).join("");
    return '<svg class="chart" viewBox="0 0 800 225" role="img" aria-label="Historique de consommation en mètres cubes"><line x1="0" x2="800" y1="185" y2="185" stroke="var(--divider-color)"/>'+bars+'</svg>';
  }
  _render(){
    if(!this.shadowRoot)return;
    const entities=this._entities(),ids=[...new Set((this._registry||[]).map(e=>e.config_entry_id).filter(Boolean))];
    const compact=this._config.mode==="compact";
    const options=ids.map(id=>'<option value="'+esc(id)+'" '+(id===this._entryId()?'selected':'')+'>'+esc(this._entries?.find(e=>e.entry_id===id)?.title||id)+'</option>').join("");
    this.shadowRoot.innerHTML='<style>'+style+'</style><ha-card><header><div><h2>💧 SAUron</h2><div class="muted">Consommation d’eau</div></div>'+(ids.length>1?'<select id="meter" aria-label="Compteur">'+options+'</select>':'')+'</header>'+(ids.length===0?'<p class="muted">Recherche des compteurs SAUron…</p>':'<div class="metrics">'+["daily_liters","weekly_m3","monthly_m3","yearly_m3"].filter(k=>entities[k]).map(k=>this._metric(k,entities)).join("")+'</div>'+(compact?"":'<h3>Index</h3>'+this._rows(["estimated_index","last_index","last_index_date"],entities))+(this._config.show_chart===false?"":'<h3>Historique</h3><div class="controls">'+[7,30,90].map(d=>'<button data-days="'+d+'" aria-pressed="'+(d===this._days)+'">'+d+' j</button>').join("")+'</div>'+this._chart())+(this._config.show_diagnostics===false||compact?"":'<details><summary>Informations et diagnostic</summary>'+this._rows(["daily_date","data_freshness_hours","last_successful_poll","meter_serial","meter_brand","meter_model","meter_diameter","telereleve_tech"],entities)+'</details>'))+(this._error?'<p class="notice">'+esc(this._error)+'</p>':'')+'</ha-card>';
    this.shadowRoot.querySelector("#meter")?.addEventListener("change",e=>{this._config={...this._config,entry_id:e.target.value};this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this._config},bubbles:true,composed:true}));this._loadStats();});
    this.shadowRoot.querySelectorAll("[data-days]").forEach(b=>b.addEventListener("click",()=>{this._days=Number(b.dataset.days);this._loadStats();}));
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

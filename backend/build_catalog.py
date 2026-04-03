"""Build DDC CWICR ENG Resource Catalog - single clean file."""
import pandas as pd
import math, os

df = pd.read_parquet('../DDC_Toolkit/pricing/data/parquet/ENG_TORONTO_workitems_costs_resources_DDC_CWICR.parquet')
df.columns = [str(c).strip().lower() for c in df.columns]

def sf(v):
    if v is None or (isinstance(v,float) and math.isnan(v)): return None
    try: return round(float(v),4)
    except: return None

def ss(v):
    if v is None or (isinstance(v,float) and math.isnan(v)): return ''
    return str(v).strip()

def rtype(row):
    rt=ss(row.get('row_type',''))
    if rt=='Machinist': return 'Operator'
    if rt=='Electricity': return 'Electricity'
    if bool(row.get('is_abstract',False)): return 'Abstract Material'
    if bool(row.get('is_machine',False)): return 'Equipment'
    if bool(row.get('is_material',False)):
        u=ss(row.get('resource_unit','')).lower()
        if u in ('hrs','h','person-hour','person-hours'): return 'Labor'
        return 'Material'
    return 'Other'

M={'Concrete & Cement':['concrete','cement','mortar'],'Steel & Metal':['steel','metal','iron','forging','structure'],'Welding Consumables':['weld','electrode'],'Wood & Timber':['wood','timber','plywood','board','sleeper'],'Pipes & Fittings':['pipe','tube','valve','fitting'],'Paint & Coatings':['paint','primer','varnish','enamel'],'Insulation':['insulation','thermal','mineral wool'],'Aggregates':['sand','gravel','crushed','rock','soil'],'Fasteners':['bolt','nut','screw','nail','anchor'],'Waterproofing':['waterproof','bitumen','membrane'],'Electrical':['cable','wire','insulating tape'],'Glass':['glass','window'],'Chemicals':['oxygen','acetylene','propane','acid','alcohol','kerosene'],'Water':['water','tap water'],'Rubber':['rubber','gasket','seal']}
E={'Cranes':['crane','lifting'],'Trucks':['truck','flatbed','tractor'],'Welding Equip.':['weld','inverter'],'Excavators':['excavator'],'Bulldozers':['bulldozer'],'Hoists':['winch','hoist'],'Compressors':['compressor'],'Pumps':['pump']}

def cat(name,typ):
    nl=name.lower()
    cs=M if typ in('Material','Abstract Material') else E if typ=='Equipment' else {}
    for c,ks in cs.items():
        if any(k in nl for k in ks): return c
    return {'Labor':'Labor','Operator':'Operators','Electricity':'Electricity'}.get(typ,'General')

res=df[(df['row_type']!='Scope of work')&(df['resource_name'].notna())&(df['resource_name'].str.strip()!='')].copy()
res['_t']=res.apply(rtype,axis=1)
g=res.groupby(['resource_code','_t'],sort=False)
print(f'{len(g):,} unique resources')

rows=[]
for(code,tp),gr in g:
    f=gr.iloc[0]
    ra=gr['resource_price_per_unit_eur_current'].dropna(); ra=ra[ra>0]
    co=gr['resource_cost_eur'].dropna(); co=co[co>0]
    qt=gr['resource_quantity'].dropna(); qt=qt[qt>0]
    nm=ss(f.get('resource_name',''))
    un=ss(f.get('resource_unit',''))
    r={'resource_code':code,'name':nm,'type':tp,'category':cat(nm,tp),'unit':un,
       'price_avg':round(float(ra.mean()),2) if len(ra) else 0,
       'price_min':round(float(ra.min()),2) if len(ra) else 0,
       'price_max':round(float(ra.max()),2) if len(ra) else 0,
       'price_median':round(float(ra.median()),2) if len(ra) else 0,
       'price_variants':int(ra.nunique()) if len(ra) else 0,
       'currency':'EUR',
       'avg_cost_per_use':round(float(co.mean()),2) if len(co) else 0,
       'avg_qty_per_use':round(float(qt.mean()),4) if len(qt) else 0,
       'usage_count':len(gr),
       'used_in_work_items':int(gr['rate_code'].nunique()),
       'parent_category':ss(f.get('category_type','')),
       'parent_collection':ss(f.get('collection_name','')),
       'parent_department':ss(f.get('department_name',''))[:100],
       'parent_section':ss(f.get('section_name',''))[:100]}
    if tp=='Equipment':
        r['machine_class']=ss(f.get('machine_class2_name',''))
        r['elec_kwh_per_hr']=sf(f.get('electricity_consumption_kwh_per_machine_hour'))
    if tp=='Abstract Material':
        r['abstract_name']=ss(f.get('price_abstract_resource_common_start',''))[:150]
        r['abstract_variants']=sf(f.get('price_abstract_resource_position_count'))
        r['abstract_price_min']=sf(f.get('price_abstract_resource_est_price_min'))
        r['abstract_price_max']=sf(f.get('price_abstract_resource_est_price_max'))
        r['abstract_parts']=ss(f.get('price_abstract_resource_variable_parts',''))[:200]
    rows.append(r)

out=pd.DataFrame(rows).sort_values('usage_count',ascending=False)
d=os.path.join('..','data','catalog')
os.makedirs(d,exist_ok=True)

n='DDC_CWICR_ENG_Resource_Catalog'
out.to_csv(os.path.join(d,f'{n}.csv'),index=False,encoding='utf-8')
with pd.ExcelWriter(os.path.join(d,f'{n}.xlsx'),engine='openpyxl') as w:
    out.to_excel(w,sheet_name='All Resources',index=False)
    for t in ['Material','Equipment','Abstract Material','Labor','Operator','Electricity']:
        s=out[out['type']==t]
        if len(s): s.to_excel(w,sheet_name=t,index=False)

print(f"\n{n}")
print(f"CSV: {os.path.getsize(os.path.join(d,n+'.csv'))//1024} KB")
print(f"Excel: {os.path.getsize(os.path.join(d,n+'.xlsx'))/1024/1024:.1f} MB")
print(f"Total: {len(out):,} | Cols: {len(out.columns)}")
for t,c in out['type'].value_counts().items(): print(f"  {t}: {c}")

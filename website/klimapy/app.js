const root='./docs/';
const examples={
extremes:{title:'extreme_indices.py',doc:'etccdi.html',note:'年度有效覆盖率默认至少 90%；结果保留缺测。',code:`from klimapy import ETCCDI
from klimapy.native import read_field

pr = read_field("daily_pr.nc", "pr", indexers={
    "lat": slice(0, 16), "lon": slice(0, 16)
})

indices = ETCCDI.compute_indices(
    pr, ["PRCPTOT", "RX1DAY", "CDD"]
)
indices["RX1DAY"].to_netcdf("rx1day.nc")`},
regrid:{title:'spatial_interpolation.py',doc:'interpolation.html',note:'一维单调经纬网格；普通双线性插值不向区域外外推。',code:`import numpy as np
from klimapy import Interpolation as interp
from klimapy.native import read_field

data = read_field("daily_pr.nc", "pr")
target = {
    "lat": np.arange(20, 41, 0.5),
    "lon": np.arange(100, 121, 0.5),
}
with interp.Regridder(data, target,
                     method="bilinear") as regridder:
    result = regridder(data)`},
bcsd:{title:'bias_correction_downscaling.py',doc:'bcsd.html',note:'路径为示例；基准期必须覆盖观测与历史模拟共同日期。',code:`from klimapy.BCSD.BiasCorrection import BC, close_result
from klimapy.BCSD.SpatialDownscaling import SD

result = BC(
    "obs.nc", "historical.nc", "future.nc",
    "model", 1981, 2010, strict=True,
    time_chunk_size=128, work_dir="work/model"
)
try:
    SD("obs.nc", result, "results", 1981, 2010,
       strict=True, time_chunk_size=32)
finally:
    close_result(result, remove_work_files=True)`},
eof:{title:'climate_modes.py',doc:'linalg.html',note:'输入为 time × lat × lon；示例保留前三个模态。',code:`from klimapy import eof
from klimapy.native import read_field

field = read_field("daily_temperature.nc", "tas")
result = eof(
    field.values,
    lat=field.coords["lat"],
    n_modes=3
)
pcs = result.pcs
eofs = result.eofs
fraction = result.variance_fraction
reconstructed = result.reconstruct()`},
variability:{title:'precipitation_variability.py',doc:'variability.html',note:'先去除年循环与线性趋势，再计算年度总体标准差。',code:`from klimapy import PrecipitationVariability as pv
from klimapy.native import read_field

pr = read_field("daily_pr.nc", "pr", indexers={
    "lat": slice(0, 16), "lon": slice(0, 16)
})
annual = pv.compute_precip_variability(
    pr,
    baseline_years=(1981, 2010),
    spatial_chunk_size=32
)
annual.to_netcdf("annual_variability.nc")`}
};
function selectExample(key){const e=examples[key];document.getElementById('api-code').textContent=e.code;document.getElementById('api-code').setAttribute('aria-labelledby','api-'+key);document.getElementById('example-title').textContent=e.title;document.getElementById('example-note').textContent=e.note;document.getElementById('example-doc').href=root+e.doc;document.querySelectorAll('[data-example]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.example===key)));}
const installs={pip:'python -m pip install --upgrade klimapy\n\n# 查看已安装版本\npython -m pip show klimapy',source:'git clone https://github.com/aipc-org/Klimapy.git\ncd Klimapy\n\n# 需预先安装 Rust / Cargo\npython -m pip install .'};
document.querySelectorAll('[data-example]').forEach(b=>b.addEventListener('click',()=>selectExample(b.dataset.example)));
document.querySelectorAll('[data-install]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('install-code').textContent=installs[b.dataset.install];document.getElementById('install-code').setAttribute('aria-labelledby',b.id);document.querySelectorAll('[data-install]').forEach(t=>t.setAttribute('aria-selected',String(t===b)));}));
let toastTimer;function toast(message){const t=document.getElementById('toast');t.textContent=message;t.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),2400);}
document.querySelectorAll('[data-copy],[data-target]').forEach(b=>b.addEventListener('click',async()=>{const text=b.dataset.copy||document.getElementById(b.dataset.target).textContent;try{await navigator.clipboard.writeText(text);toast('已复制');}catch{toast('无法自动复制，请选择代码手动复制');}}));
document.querySelectorAll('[role=tablist]').forEach(list=>list.addEventListener('keydown',event=>{const tabs=[...list.querySelectorAll('[role=tab]')];const index=tabs.indexOf(document.activeElement);if(index<0)return;let next;if(['ArrowRight','ArrowDown'].includes(event.key))next=(index+1)%tabs.length;else if(['ArrowLeft','ArrowUp'].includes(event.key))next=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=tabs.length-1;else return;event.preventDefault();tabs[next].focus();tabs[next].click();}));
selectExample('extremes');

"""Compare eager public climate operations against independent community libraries.

The orchestrator executes native work in Test and references in Test1. Plotting
uses only the resulting public timing summary, never a second production backend.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def execute(mode, folder, repeats):
    import numpy as np
    f=np.load(folder/'input.npz');values=f['values'];lat=f['lat'];lon=f['lon'];times=f['time']
    target_lat=(lat[:-1]+lat[1:])/2;target_lon=(lon[:-1]+lon[1:])/2
    if mode=='native':
        sys.path.insert(0,str(ROOT/'tools'))
        from test_environment import verify
        verify()
        from klimapy.native import Field
        from klimapy import etccdi
        from klimapy.statistics import svd,eof,compute_climatology
        from klimapy.statistics.interpolation import interpolate
        field=Field(values,('time','lat','lon'),{'time':times,'lat':lat,'lon':lon},{'units':'mm/day'},'pr',{'time':{'units':'days since 2019-01-01','calendar':'standard'}})
        small=field.isel(time=slice(0,30))
        tasks={
          'PRCPTOT':lambda:etccdi.PRCPTOT(field).values,
          'RX5DAY':lambda:etccdi.RX5DAY(field).values,
          'Bilinear':lambda:interpolate(small,{'lat':target_lat,'lon':target_lon},'bilinear').values,
          'SVD':lambda:svd(values.reshape(len(values),-1))[1],
          'EOF':lambda:eof(values,lat=lat,n_modes=3).eigenvalues,
          'Climatology':lambda:compute_climatology(field,baseline_years=(2019,2020)).values,
        }
        versions={'klimapy':'development','numpy':np.__version__}
    else:
        # Independent process: never import klimapy in the reference environment.
        import xarray as xr
        import xclim
        from xclim import indices
        import scipy
        from scipy.interpolate import RegularGridInterpolator
        import eofs
        from eofs.standard import Eof
        from importlib.metadata import version
        dates=np.datetime64('2019-01-01')+times.astype('timedelta64[D]')
        array=xr.DataArray(values,dims=('time','lat','lon'),coords={'time':dates,'lat':lat,'lon':lon},attrs={'units':'mm/day'})
        points=np.stack(np.meshgrid(target_lat,target_lon,indexing='ij'),axis=-1)
        def interpolate():
            result=RegularGridInterpolator((lat,lon),values[:30].transpose(1,2,0),method='linear',bounds_error=False,fill_value=np.nan)(points)
            return result.transpose(2,0,1)
        def eof_values():
            solver=Eof(values,weights=np.sqrt(np.cos(np.deg2rad(lat)))[:,None],ddof=1)
            return solver.eigenvalues(neigs=3)
        tasks={
          'PRCPTOT':lambda:indices.prcptot(array,thresh='1 mm/day',freq='YS').values,
          'RX5DAY':lambda:indices.max_n_day_precipitation_amount(array,window=5,freq='YS').values,
          'Bilinear':interpolate,
          'SVD':lambda:np.linalg.svd(values.reshape(len(values),-1),full_matrices=False)[1],
          'EOF':eof_values,
          'Climatology':lambda:array.groupby('time.month').mean('time',skipna=True).values,
        }
        versions={p:version(p) for p in ('numpy','xarray','xclim','scipy','eofs')}
    results={};arrays={}
    for name,call in tasks.items():
        call();call()  # exclude first-call initialization/JIT from steady-state timing
        samples=[]
        for _ in range(repeats):
            start=time.perf_counter();result=call();samples.append(time.perf_counter()-start)
        arrays[name]=np.asarray(result);results[name]={'seconds':samples,'median_seconds':statistics.median(samples)}
    np.savez(folder/(mode+'.npz'),**arrays)
    (folder/(mode+'.json')).write_text(json.dumps({'versions':versions,'results':results},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',choices=('native','reference'))
    parser.add_argument('--directory',type=Path,default=ROOT/'outputs/community-benchmark')
    parser.add_argument('--repeats',type=int,default=7)
    args=parser.parse_args()
    if args.worker:return execute(args.worker,args.directory,args.repeats)
    import numpy as np
    sys.path.insert(0,str(ROOT/'src'))
    from klimapy.native import read_field
    folder=args.directory;folder.mkdir(parents=True,exist_ok=True)
    base=ROOT/'data/CN05.1/汇总/逐日/Pre'
    fields=[read_field(base/f'CN05.1_Pre_{year}_daily_025x025.nc','pre',indexers={'lat':slice(68,74),'lon':slice(155,163)}) for year in (2019,2020)]
    values=np.concatenate([f.values for f in fields]);dates=np.concatenate([f.time.dates()[1] for f in fields]);dates-=dates[0]
    if not np.isfinite(values).all():raise ValueError('Choose an explicit complete-data tile for common-domain SVD/EOF comparisons')
    np.savez(folder/'input.npz',values=values,time=dates,lat=fields[0].coords['lat'],lon=fields[0].coords['lon'])
    env=os.environ.copy();env.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','VECLIB_MAXIMUM_THREADS')})
    env['NUMBA_CACHE_DIR']='/tmp/klimapy-comparison-numba';env['MPLCONFIGDIR']='/tmp/klimapy-comparison-mpl';env['PYTHONNOUSERSITE']='1'
    for mode,environment in (('native','Test'),('reference','Test1')):
        env['PYTHONPATH']=str(ROOT/'src') if mode=='native' else ''
        subprocess.run([f'/opt/miniconda3/envs/{environment}/bin/python',str(Path(__file__).resolve()),'--worker',mode,'--directory',str(folder),'--repeats',str(args.repeats)],env=env,check=True,cwd=ROOT)
    native=json.loads((folder/'native.json').read_text());reference=json.loads((folder/'reference.json').read_text())
    n=np.load(folder/'native.npz');r=np.load(folder/'reference.npz');rows=[]
    references={'PRCPTOT':'xclim','RX5DAY':'xclim','Bilinear':'SciPy RegularGridInterpolator','SVD':'NumPy LAPACK','EOF':'eofs','Climatology':'xarray groupby'}
    for name in native['results']:
        np.testing.assert_allclose(n[name],r[name],rtol=1e-8,atol=1e-8,equal_nan=True,err_msg=name)
        a=native['results'][name]['median_seconds'];b=reference['results'][name]['median_seconds']
        rows.append({'name':name,'reference':references[name],'klimapy_ms':1000*a,'reference_ms':1000*b,'speed_ratio':b/a,'time_saved_percent':100*(1-a/b),'max_abs_error':float(np.nanmax(np.abs(n[name]-r[name]))),'rtol':1e-8,'atol':1e-8,'native_samples_seconds':native['results'][name]['seconds'],'reference_samples_seconds':reference['results'][name]['seconds']})
    cpu=platform.processor()
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),cpu)
    report={'date':'2026-10-29','shape':list(values.shape),'repeats':args.repeats,'warmup':2,'threads':1,'cpu':cpu,'os':platform.system()+' '+platform.machine(),'python':platform.python_version(),'versions':reference['versions'],'rows':rows,'scope':'steady-state eager compute; input file I/O and process startup excluded; Bilinear includes weight construction on 30 daily fields; SVD/EOF use all 731 daily fields'}
    target=ROOT/'website/klimapy/assets/community-benchmark.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

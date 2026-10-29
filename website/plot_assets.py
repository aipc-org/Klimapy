"""Render site figures from computed climate fields and measured timings.

Run in the plotting/reference environment; production calculations are separate.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import PowerNorm, LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'website/klimapy/assets'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none','pdf.fonttype':42,'axes.labelcolor':'#355749','xtick.color':'#557161','ytick.color':'#557161','text.color':'#183e34'})


def precipitation(source):
    f=np.load(source);values=f['values'];lat=f['lat'];lon=f['lon']
    lon_mask=(lon>=108)&(lon<=118);lat_mask=(lat>=25)&(lat<=36)
    if not np.any(lon_mask) or not np.any(lat_mask):
        raise ValueError('Precipitation field does not cover the East China display region')
    lon=lon[lon_mask];lat=lat[lat_mask];values=values[np.ix_(lat_mask,lon_mask)]
    x,y=np.meshgrid(lon,lat);z=np.log1p(values)
    fig=plt.figure(figsize=(7.1,5.4),layout='constrained');fig.set_facecolor('#f6f7f0')
    ax=fig.add_subplot(111,projection='3d');ax.set_facecolor('#edf1e8')
    cmap=LinearSegmentedColormap.from_list('climate-rain',['#f1f3cd','#c0daaa','#78b69b','#329184','#1a665e','#123e45'])
    norm=PowerNorm(.65,vmin=0,vmax=6.5)
    surface=ax.plot_surface(x,y,z,cmap=cmap,norm=norm,rstride=1,cstride=1,
                            linewidth=0,antialiased=True,shade=True)
    levels=[1,2,3,5,6]
    ax.contour(x,y,values,levels=levels,zdir='z',offset=-.35,
               colors='#315f55',linewidths=1,alpha=.9)
    ax.set_xlim(float(lon.min()),float(lon.max()))
    ax.set_ylim(float(lat.min()),float(lat.max()))
    ax.set_zlim(-.35,float(np.nanmax(z))*1.08)
    ax.set_box_aspect((1.45,1,.62));ax.view_init(elev=31,azim=-56)
    ax.set_xticks([110,114,118]);ax.set_yticks([26,30,34,36]);ax.set_zticks([])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x,_:f'{x:g}°E'))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y,_:f'{y:g}°N'))
    ax.tick_params(length=0,pad=1,labelsize=8)
    ax.xaxis.pane.set_facecolor('#f5f7ed');ax.yaxis.pane.set_facecolor('#f5f7ed')
    ax.zaxis.pane.set_facecolor('#e7eee2')
    ax.xaxis.pane.set_edgecolor('#d2dfd1');ax.yaxis.pane.set_edgecolor('#d2dfd1')
    ax.zaxis.pane.set_edgecolor('#d2dfd1')
    ax.grid(color='white',alpha=.3,linewidth=.5)
    bar=fig.colorbar(surface,ax=ax,shrink=.58,pad=.08,aspect=22)
    bar.set_label('Mean daily precipitation (mm day⁻¹)',fontsize=9,labelpad=7)
    bar.outline.set_visible(False);bar.set_ticks([0,1,2,4,6])
    bar.ax.tick_params(labelsize=8,length=0,pad=4)
    fig.savefig(OUT/'precipitation.png',dpi=220)
    fig.savefig(ROOT/'outputs/site-assets/precipitation.pdf')
    plt.close(fig)


def efficiency():
    report=json.loads((OUT/'community-benchmark.json').read_text());rows=report['rows']
    fig,ax=plt.subplots(figsize=(8.4,4.7),layout='constrained');fig.set_facecolor('#ffffff');ax.set_facecolor('#ffffff')
    ratios=[r['speed_ratio'] for r in rows];positions=np.arange(len(rows))
    ax.barh(positions,ratios,color=['#37775d' if x>=1 else '#bd8a5f' for x in ratios],height=.54)
    ax.set_yticks(positions,[r['name']+'  /  '+r['reference'] for r in rows],fontsize=10)
    ax.invert_yaxis();ax.set_xscale('log');ax.axvline(1,color='#79877a',linestyle='--',linewidth=1)
    ax.set_xlim(min(.01,min(ratios)/2),max(ratios)*3);ax.grid(axis='x',alpha=.15)
    ax.set_xlabel('Reference time / Klimapy time (×)  ·  higher is faster',fontsize=10,labelpad=12)
    for y,x in zip(positions,ratios):ax.text(x*1.12,y,f'{x:.3g}×',va='center',fontsize=10)
    ax.spines[['left','bottom']].set_visible(False);ax.tick_params(length=0,pad=8)
    fig.savefig(OUT/'efficiency.png',dpi=180)
    fig.savefig(ROOT/'outputs/site-assets/efficiency.pdf')
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--precipitation',type=Path);parser.add_argument('--efficiency',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.precipitation:precipitation(args.precipitation)
    if args.efficiency:efficiency()

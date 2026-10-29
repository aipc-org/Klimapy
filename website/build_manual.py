"""Build the static manual from repository docs (tool environment: markdown-it-py)."""
import ast
import html
import json
import posixpath
import re
from pathlib import Path
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'website/klimapy/docs'
PAGES = [
 ('开始使用','index','官方手册','website/manual/index.md'),
 ('开始使用','installation','安装与环境','website/manual/installation.md'),
 ('开始使用','data-model','Field 与数据入口','website/manual/data-model.md'),
 ('开始使用','quickstart','快速上手','docs/getting-started/quickstart.md'),
 ('功能指南','etccdi','极端气候指数','docs/etccdi/ETCCDI.md'),
 ('功能指南','interpolation','空间插值与重映射','docs/interpolation/SpatialInterpolation.md'),
 ('功能指南','bias-correction','BC 偏差校正','docs/bcsd/BiasCorrection.md'),
 ('功能指南','downscaling','SD 空间降尺度','docs/bcsd/SpatialDownscaling.md'),
 ('功能指南','bcsd','BCSD 完整流程','docs/bcsd/BiasCorrectionSpatialDownscaling.md'),
 ('功能指南','bcsd-method','BCSD 方法原理','docs/bcsd/method.md'),
 ('功能指南','variability','降水变率与趋势','docs/variability/PrecipVariability.md'),
 ('功能指南','linalg','SVD 与 EOF','docs/linalg/SVD-EOF.md'),
 ('功能指南','spatial','空间统计与区域掩膜','docs/tools/CSM.md'),
 ('功能指南','geotiff','GeoTIFF 导出','docs/tools/NCtoTIFF.md'),
 ('参考与开发','api','API 参考','website/manual/api.md'),
 ('参考与开发','migration','迁移与计算口径','docs/development/quality-and-migration.md'),
 ('参考与开发','backend','Rust 引擎','docs/development/RustBackend.md'),
 ('参考与开发','validation','验证与比对','docs/development/validation.md'),
 ('参考与开发','comparison','Test1 参考环境','docs/development/comparison-environment.md'),
 ('参考与开发','faq','常见问题','website/manual/faq.md'),
 ('参考与开发','contributing','参与贡献','CONTRIBUTING.md'),
 ('参考与开发','changelog','更新记录','CHANGELOG.md'),
]
MODULES = [
 ('数据模型','klimapy.native','src/klimapy/native/field.py',{'read_field','Field','TimeAxis'}),
 ('原生文件','klimapy.native','src/klimapy/native/io.py',{'Dataset','open_dataset'}),
 ('线性代数','klimapy.native','src/klimapy/native/linalg.py',{'svd','eof','EOFResult'}),
 ('ETCCDI','klimapy.ETCCDI','src/klimapy/ETCCDI/ETCCDI.py',None),
 ('偏差校正','klimapy.BCSD.BiasCorrection','src/klimapy/BCSD/BiasCorrection.py',{'BC','close_result'}),
 ('降尺度','klimapy.BCSD.SpatialDownscaling','src/klimapy/BCSD/SpatialDownscaling.py',{'SD'}),
 ('插值','klimapy.Interpolation','src/klimapy/Interpolation/spatial_interpolation.py',None),
 ('降水变率','klimapy.PrecipitationVariability','src/klimapy/PrecipitationVariability/precip_variability_netcdf.py',None),
 ('空间统计','klimapy.Supporting_Tools','src/klimapy/Supporting_Tools/CSM.py',{'calculate_spatial_mean'}),
 ('栅格输出','klimapy.Supporting_Tools','src/klimapy/Supporting_Tools/NCtoTIFF.py',{'nc_to_tiff'}),
 ('批处理','klimapy','src/klimapy/workflows/batch.py',{'process_models'}),
]

def api_markdown():
    parts=['# API 参考\n\n以下签名从本次源码静态提取，不导入生产包，也不执行数值计算。函数的科学口径、返回值和边界请结合功能指南阅读。动态生成的指标另列于页末。\n']
    for title,module,path,selected in MODULES:
        tree=ast.parse((ROOT/path).read_text())
        parts.append('## '+title+'\n')
        for item in tree.body:
            if not isinstance(item,(ast.FunctionDef,ast.ClassDef)) or item.name.startswith('_') or (selected is not None and item.name not in selected):
                continue
            parts.append('### '+item.name+'\n')
            if isinstance(item,ast.FunctionDef):
                parts.append('```python\n'+module+'.'+item.name+'('+ast.unparse(item.args)+')\n```\n')
            else:
                parts.append('```python\n'+module+'.'+item.name+'\n```\n')
                if item.name=='Field':
                    parts.append('`Field(values, dims, coords, attrs={}, name="value", coordinate_attrs={})`\n\n见 [Field 与数据入口](data-model.html)。\n')
                for method in item.body:
                    if isinstance(method,ast.FunctionDef) and not method.name.startswith('_'):
                        parts.append('```python\n'+item.name+'.'+method.name+'('+ast.unparse(method.args)+')\n```\n')
            doc=ast.get_docstring(item)
            if doc:
                parts.append(doc+'\n')
            parts.append('[源码](https://github.com/michalrees/Klimapy/blob/main/'+path+'#L'+str(item.lineno)+')\n')
    parts.append('''## 动态生成的 ETCCDI 指标

这些函数通过工厂创建，不会出现在静态 def 列表中。完整口径与返回频率见 [ETCCDI](etccdi.html)。

| 类别 | 函数与签名 |
| --- | --- |
| 固定阈值降水 | R10mm / R20mm / R25mm / R50mm 的 `_precipitation`、`_days`、`_intensity`、`_ratio`：`metric(pr, *, min_valid_fraction=0.9)` |
| 百分位降水 | R90mm / R95mm / R99mm 的相同四种后缀：`metric(pr, baseline_pr=None, baseline_years=None, *, min_valid_fraction=0.9)` |
| 温度阈值与极值 | FD(tn)、SU(tx)、ID(tx)、TR(tn)、TXx(tx)、TNx(tn)、TXn(tx)、TNn(tn)，带 `min_valid_fraction=0.9` |

这里的 `metric` 代表所选函数名称，不是额外导出的函数。百分位降水必须显式提供基准期；温度百分位函数的 bootstrap 默认行为见其独立签名及指南。
''')
    return '\n'.join(parts)

mapping={str(Path(p)):slug+'.html' for _,slug,_,p in PAGES}
md=MarkdownIt('commonmark',{'html':False}).enable('table')
search=[]
OUT.mkdir(parents=True,exist_ok=True)
for i,(group,slug,title,path) in enumerate(PAGES):
    source=api_markdown() if slug=='api' else (ROOT/path).read_text()
    # Keep repository-relative Markdown links valid after exporting into a flat site.
    def link(match):
        label,url=match.groups()
        if re.match(r'^[a-z]+:|^#|^/',url):return match.group(0)
        target,sep,anchor=url.partition('#')
        resolved=posixpath.normpath(posixpath.join(posixpath.dirname(path),target))
        if target.endswith('.html'):new=target
        elif resolved in mapping:new=mapping[resolved]  # heading anchors are generated locally
        else:new='https://github.com/michalrees/Klimapy/blob/main/'+resolved
        return '['+label+']('+new+(('#'+anchor) if sep and new.startswith('https:') else '')+')'
    source=re.sub(r'\[([^\]]+)\]\(([^\s)]+)\)',link,source)
    tokens=md.parse(source)
    toc=[]
    for j,t in enumerate(tokens):
        if t.type=='heading_open':
            content=tokens[j+1].content
            ident='section-'+str(len(toc)+1)
            t.attrSet('id',ident)
            toc.append((int(t.tag[1:]),ident,content))
    body=md.renderer.render(tokens,md.options,{})
    nav='';previous=None
    for g,s,t,p in PAGES:
        if g!=previous:nav+='<h3>'+g+'</h3>';previous=g
        nav+='<a '+('aria-current="page" ' if s==slug else '')+'href="'+s+'.html">'+html.escape(t)+'</a>'
    toc_html=''.join('<a class="level-'+str(level)+'" href="#'+ident+'">'+html.escape(t)+'</a>' for level,ident,t in toc if level in (2,3))
    pager=''
    for label,n in [('上一章',i-1),('下一章',i+1)]:
        if 0<=n<len(PAGES):
            _,s,t,_=PAGES[n];pager+='<a href="'+s+'.html"><small>'+label+'</small>'+t+' '+('←' if n<i else '→')+'</a>'
    doc=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Klimapy 官方手册：{html.escape(title)}。1.1.0 原生 Rust 架构的使用指南与 API 参考。"><link rel="canonical" href="https://michalrees.bid/klimapy/docs/{'' if slug=='index' else slug+'.html'}"><link rel="stylesheet" href="manual.css"><title>{html.escape(title)} — Klimapy 官方手册</title></head><body><a class="skip" href="#content">跳转正文</a><header class="mobile"><button id="menu" aria-expanded="false" aria-controls="sidebar">☰ 目录</button><a href="../">κ Klimapy</a><button class="theme" aria-label="切换明暗主题">◐</button></header><aside id="sidebar"><a class="logo" href="index.html"><span>κ</span><b>Klimapy</b></a><p class="subtitle">官方手册 <span>1.1.0</span></p><label class="search-label" for="search">搜索手册</label><input id="search" type="search" placeholder="搜索函数、参数、关键词…" autocomplete="off"><div id="results" role="region" aria-label="搜索结果" aria-live="polite" hidden></div><nav aria-label="手册目录">{nav}</nav><div class="side-bottom"><a href="../">← 项目主页</a><a href="https://github.com/michalrees/Klimapy">GitHub ↗</a></div></aside><div class="layout"><main id="content"><div class="topline"><span>Klimapy / {group} / {title}</span><button class="theme" aria-label="切换明暗主题">◐</button></div><div class="version-note"><b>1.1.0 原生架构</b> · 适用于 Field / Rust 接口；旧版使用者请先阅读<a href="migration.html">迁移说明</a>。</div><article>{body}</article><nav class="pager" aria-label="章节翻页">{pager}</nav><footer>MIT License · <a href="https://github.com/michalrees/Klimapy/issues">报告文档问题</a> · <a href="https://pypi.org/project/klimapy/">PyPI</a></footer></main><aside class="toc"><p>本页目录</p>{toc_html}</aside></div><div id="status" role="status" aria-live="polite"></div><script src="manual.js"></script><script defer src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js"></script></body></html>'''
    (OUT/(slug+'.html')).write_text(doc)
    plain=re.sub('<[^>]+>',' ',body)
    search.append({'title':title,'url':slug+'.html','text':html.unescape(re.sub(r'\s+',' ',plain))})
(OUT/'search-index.json').write_text(json.dumps(search,ensure_ascii=False))
print('Built',len(PAGES),'manual pages')

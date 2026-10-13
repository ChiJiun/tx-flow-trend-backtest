"""從回測底稿產生八頁繁體中文PDF、Word、圖表與工作簿附頁。"""
from pathlib import Path
import pandas as pd, numpy as np, html, json, io, zipfile
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from fontTools.ttLib import TTFont as FontToolsFont
from docx import Document
from docx.shared import Cm,Pt
from docx.oxml.ns import qn
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as ExcelImage

B=Path(__file__).resolve().parent;O=B/'output';read=lambda name:pd.read_csv(O/(name+'.csv'))
m=read('metrics_comparison');ms,mb=m.iloc[0],m.iloc[1];s=read('strategy_daily');bh=read('benchmark_daily')
rm=read('one_contract_risk_matched_summary').iloc[0];rmd=read('one_contract_risk_matched_daily');rmdist=read('one_contract_risk_matched_distribution')
market=read('market_normalized_daily');market_summary=read('market_normalized_summary')
mn,mt,mi=[market_summary.iloc[i] for i in range(3)]
reference_capital=float(mn.reference_capital)
tr=read('strategy_trades');annual=read('annual_results');sens=read('cost_sensitivity');ab=read('ablation');splits=read('descriptive_time_splits')
ev=read('strategy_events');bev=read('benchmark_events');v=json.loads((O/'validation.json').read_text())
near_prices=pd.read_csv(B/'input/prices.csv',parse_dates=['date'])
contracts=pd.read_csv(B/'input/all_contracts.csv')
institutional=pd.read_csv(B/'input/institutional.csv')
candidate_count=len(pd.read_csv(B/'source_audits/all_18_exploratory_candidates.csv'))
source_audit=json.loads((O/'institutional_source_audit.json').read_text(encoding='utf-8'))
roll_audit=json.loads((O/'roll_gap_summary.json').read_text(encoding='utf-8'))
price_vm=read('price_only_volatility_matched_summary').iloc[0]
flow_attribution=read('flow_incremental_attribution')
price_start,price_end=near_prices.date.min(),near_prices.date.max()
chip_dates=pd.to_datetime(institutional['日期'])
assumptions=v['parameters']
for d in [s,bh,rmd,market]:d['date']=pd.to_datetime(d.date)
tr['entry_date']=pd.to_datetime(tr.entry_date);tr['exit_date']=pd.to_datetime(tr.exit_date)
duration=(tr.exit_date-tr.entry_date).dt.days
pct=lambda x:f'{x*100:.2f}%';money=lambda x:f'{x:,.2f}';ratio=lambda x:f'{x:.3f}'
font=FontProperties(fname=str(B/'chinese_font.ttf'));plt.rcParams['axes.unicode_minus']=False

def validate_equity_for_log(*frames):
    for d in frames:
        if d.empty:raise ValueError('log equity chart requires non-empty data')
        equity=pd.to_numeric(d.equity,errors='coerce')
        if not np.isfinite(equity).all() or (equity<=0).any():raise ValueError('log equity chart requires strictly positive finite equity')

series=[
    ('strategy','V04一口（扣成本）','#146f91'),
    ('tx_buy_hold','TX一口買進持有（扣成本）','#ce7c2e'),
    ('taiex','加權指數價格報酬','#496c59'),
]
for water in [False,True]:
    fig,ax=plt.subplots(figsize=(9.4,3.75))
    for d,label,col,ls in [(s,'法人交易強度＋價格趨勢','#146f91','-'),(bh,'Buy-and-Hold（固定一口）','#ce7c2e','-'),(rmd,'一口等曝險代表路徑','#526977','--')]:
        ax.plot(d.date,d.drawdown_pct*100 if water else d.equity/1e6,label=label,color=col,lw=1.25,ls=ls)
    ax.set_xlim(s.date.min(),s.date.max());ax.set_ylabel('回撤（%）' if water else '帳戶資金（百萬元）',fontproperties=font)
    ax.set_title('成本後回撤深度比較' if water else '成本後資金曲線：一口TX起始參考資金',fontproperties=font)
    if not water:ax.axhline(reference_capital/1e6,color='gray',ls=':',lw=.8)
    ax.legend(prop=font,frameon=False);ax.grid(alpha=.18);ax.spines[['top','right']].set_visible(False)
    fig.tight_layout();fig.savefig(O/('underwater_comparison.png' if water else 'equity_comparison.png'),dpi=200);plt.close(fig)
validate_equity_for_log(s,bh,rmd)
fig,ax=plt.subplots(figsize=(9.4,3.75))
for d,label,col,ls in [(s,'法人交易強度＋價格趨勢','#146f91','-'),(bh,'Buy-and-Hold（固定一口）','#ce7c2e','-'),(rmd,'一口等曝險代表路徑','#526977','--')]:
    ax.plot(d.date,d.equity/1e6,label=label,color=col,lw=1.25,ls=ls)
ax.set_yscale('log');ax.set_xlim(s.date.min(),s.date.max());ax.set_ylabel('帳戶資金（百萬元，log scale）',fontproperties=font)
ax.set_title('成本後資金曲線（對數Y軸）：一口TX起始參考資金',fontproperties=font)
ax.legend(prop=font,frameon=False);ax.grid(alpha=.18,which='both');ax.spines[['top','right']].set_visible(False)
fig.tight_layout();fig.savefig(O/'equity_comparison_log.png',dpi=200);plt.close(fig)

pdfmetrics.registerFont(TTFont('TC',str(B/'chinese_font.ttf')))
styles={
 'body':ParagraphStyle('body',fontName='TC',fontSize=10.5,leading=16.6,spaceAfter=9),
 'small':ParagraphStyle('small',fontName='TC',fontSize=8.7,leading=12.4,spaceAfter=7),
 'cell':ParagraphStyle('cell',fontName='TC',fontSize=9.2,leading=13.3),
 'title':ParagraphStyle('title',fontName='TC',fontSize=18,leading=24,spaceAfter=15,textColor=colors.HexColor('#145879')),
 'sub':ParagraphStyle('sub',fontName='TC',fontSize=12.2,leading=18,spaceAfter=7,textColor=colors.HexColor('#145879'))}
story=[];pages=[];current=[];texts=[]
doc=Document();sec=doc.sections[0];sec.page_width=Cm(21);sec.page_height=Cm(29.7);sec.top_margin=sec.bottom_margin=Cm(1.2);sec.left_margin=sec.right_margin=Cm(1.4)
sty=doc.styles['Normal'];sty.font.name='Noto Sans TC';sty.font.size=Pt(9);sty.element.rPr.rFonts.set(qn('w:eastAsia'),'Noto Sans TC')
sty.paragraph_format.space_after=Pt(2);sty.paragraph_format.line_spacing=1.0
doc_page_break=False
def text(t,style='body'):
    texts.append(t);story.append(Paragraph(html.escape(t).replace('\n','<br/>'),styles[style]));current.append(t);doc.add_paragraph(t)
def title(t):
    global doc_page_break
    texts.append(t);story.append(Paragraph(html.escape(t),styles['title']));current.append('# '+t)
    paragraph=doc.add_heading(t,1)
    if doc_page_break:paragraph.paragraph_format.page_break_before=True;doc_page_break=False
def sub(t):text(t,'sub')
def page():
    global doc_page_break
    pages.append(current.copy());current.clear();story.append(PageBreak());doc_page_break=True
def table(rows,widths=None):
    for row in rows:texts.extend(str(x) for x in row)
    data=[[Paragraph(html.escape(str(x)),styles['cell']) for x in row] for row in rows]
    t=Table(data,colWidths=widths or [140,365],repeatRows=1);t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf2f6')),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#c4d3da')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story.extend([t,Spacer(1,9)]);current.extend([' | '.join(map(str,r)) for r in rows])
    tab=doc.add_table(rows=0,cols=len(rows[0]));tab.style='Table Grid'
    for row in rows:
        cells=tab.add_row().cells
        for cell,val in zip(cells,row):cell.text=str(val)
def image(name):story.append(Image(str(O/name),width=505,height=202));doc.add_picture(str(O/name),width=Cm(17))
def image_pair(left,right):
    story.append(Table([[Image(str(O/left),width=245,height=98),Image(str(O/right),width=245,height=98)]],colWidths=[252,252]))
    tab=doc.add_table(rows=1,cols=2)
    for cell,name in zip(tab.rows[0].cells,[left,right]):cell.paragraphs[0].add_run().add_picture(str(O/name),width=Cm(8.1))

title('1　研究目的與資料完整性')
sub('法人交易強度＋價格趨勢：跨日持倉策略')
text('研究假說：三大法人持續的淨買進活動，若同時伴隨價格上升趨勢，可能比單日部位異常更能辨識可持續的多頭環境。本研究以20日法人交易強度與20日價格均線建立一口多單／空手規則，以加權股價指數作大盤價格參考，另與計入轉倉成本的台指期近月Buy-and-Hold比較。')
table([['資料','來源、期間與清理'],['TX日盤行情',f'TAIFEX年度ZIP及月檔；{price_start:%Y/%m/%d}～{price_end:%Y/%m/%d}，{near_prices.date.nunique():,}日、{len(contracts):,}筆實際月契約、{contracts.contract.nunique()}個契約。僅保留一般交易時段、六碼月契約。'],['三大法人交易',f'FinMind TX歷史資料與TAIFEX格式原始資料；{chip_dates.min():%Y/%m/%d}～{chip_dates.max():%Y/%m/%d}，{chip_dates.nunique():,}日、{len(institutional):,}筆三類法人資料。'],['正式回測期間',f'{ms.start}～{ms.end}，共{int(ms.days):,}日；本策略需要20日暖身。'],['缺漏處理',f'行情與法人資料起點不同；法人資料前的{near_prices.loc[near_prices.date<chip_dates.min(),"date"].nunique():,}個行情交易日未補造籌碼。較早官方交易金額淨額空白，但本策略只用完整的交易口數。']])
text(f'較新期間以TAIFEX格式原始資料優先，以降低不同資料來源歷史值差異造成的影響；三類法人日期均與行情交易日曆一致。資料未混入MTX、週契約、夜盤或價差交易。原始月契約共有{contracts[['open','high','low','close']].isna().any(axis=1).sum()}筆OHLC缺值紀錄，但策略及基準實際使用的進出、轉倉與評價價格均完整。')
text(f'本策略由{candidate_count}個候選規則中篩選後固定參數重新回測，因此結果屬探索性全樣本分析，尚未以完全未參與策略選擇的資料進行獨立樣本外驗證。此限制在後續結論中另行討論。')
text(f'以首日一口TX名目價值{money(reference_capital)}元作共同起始資金，策略成本後累積報酬{pct(ms.cumulative_return)}、MDD {pct(ms.MDD_pct)}；同期加權指數價格報酬{pct(mi.cumulative_return)}、MDD {pct(mi.MDD_pct)}。固定一口TX買進持有為可交易期貨對照。各曲線逐日累加損益，回撤從各自的歷史高點計算。')
page();title('2　指標定義、經濟意涵與訊號')
table([['欄位／指標','定義與用途'],['日期／實際契約月份','交易日、TXYYYYMM；每日開、高、低、收都取同一實際月契約，未回溯調整。'],['多方／空方交易口數','法人當日買進／賣出成交口數。與仍未沖銷的未平倉口數是不同資料。[2]'],['法人淨交易口數 B','外資及陸資、投信、自營商的多方交易口數減空方交易口數，再合計。'],['法人總交易口數 V','三類法人多方與空方交易口數合計。只代表這三類法人，不是全市場成交量。'],['交易強度 Q=B/V','以口數標準化淨買進活動；B可為負，V為正。各類法人的成交流量可能含方向、避險與套利。'],['Q20／MA20','Q20為當日及前19交易日Q的算術平均；MA20為當日及前19日近月收盤均價。']])
text('例如三類法人合計淨買進5,000口、買賣總口數200,000口，交易強度為2.5%。20日平均為正，表示近期平均成交傾向淨買方；但它不是新增多單口數，也不能把多次買賣直接視為留倉增加。')
text('經濟直覺：持續淨買進可能反映資金配置或風險承擔；20日平均降低單日成交雜訊，價格高於MA20則要求市場價格同時呈現偏強狀態。這是「法人買方活動與價格趨勢一致」的條件假說，不預設它必然有預測能力。')
sub('明確數學規則與資訊時序')
text('第t日盤後：若Q20_t>0且收盤C_t>MA20_t，則目標多一口；其他情況目標空手。Q20=0或C=MA20均不持有。訊號只在t+1交易日08:45開盤執行，不使用t+1收盤決定t+1開盤交易。')
text('原本空手且目標多單：買進；原本多單且條件持續：跨日持有、不加碼；任一條件消失：次日開盤全部平倉。無放空、無日內停損停利。OHLC保留作稽核，但不能重建夜盤及盤中成交路徑，所以不加入未經驗證的盤中觸價出場。')
text('交易日配對按官方行情日曆，不以自然日加一天。條件產生、成交、持倉及轉倉均可在逐日底稿追溯。')
page();title('3　交易執行、轉倉與完整成本')
text('策略按訊號隔日開盤進出；若跨月仍持有，於到期前一個交易日13:45平舊約並買次月。基準在首日開盤買一口，持續持有並採相同提前轉倉路徑。到期日期由官方契約存續底稿核對第三個星期三／休市順延規則。[1]')
text('提前一日換倉可避免到期近月13:30、次月13:45收盤時點不同；不用最後結算價替代成交價。若策略在換倉日開盤已退出，就不再換倉。兩者在樣本結束時收盤全平，這是帳戶終止清算，並非日常開盤買、收盤賣規則。')
table([['設定','策略與基準共同口徑'],['起始資金／口數／乘數',f'共同起始資金{money(reference_capital)}元，等於首日TX開盤價乘以每點200元；持倉時固定一口，不加碼。'],['手續費','每邊每口50元，假設為券商總手續費；未另重複加交易所經手費。[3]'],['滑價','每次成交2點：買進價+2、賣出價−2。初始進出、轉倉與期末平倉皆計。'],['期交稅','每邊按含滑價成交價×200×0.00002。連續金額近似，未逐筆取整。[3]'],['資金與槓桿','共同起始資金不代表歷史保證金要求；未重建逐日保證金與追繳。全期策略與固定一口基準權益均維持正值。'],['日末評價與報酬','以共同起始資金逐日累加扣除全部成本後的淨損益，得到日末權益曲線；回撤取權益相對歷史高點的最大跌幅。日報酬為當日淨損益／前日權益，含空手日。'],['年化與利息','現金利息及rf=0；Sharpe採252日；CAGR依實際起訖含首尾日／365.25。']])
text('持有日損益按同一實際契約今日收盤減昨日評價價；退出日先計舊持倉至開盤的損益，進場日從開盤計至收盤。換倉日先結束舊約損益，再將新約收盤設為新評價基準，成交各扣成本。新舊約價差不直接列為本日損益，也不另外重複扣費。')
text(f'策略147筆完整方向交易、37次轉倉、368個成交腿；基準98段契約交易、97次轉倉、196個成交腿。策略總成本{money(ms.cost_total)}元，基準{money(mb.cost_total)}元。逐日損益、方向交易及實際契約分段損益皆獨立核對一致。')
page();title('4　績效指標與年度比較')
rows=[['成本後指標','法人交易強度＋趨勢','Buy-and-Hold基準']]
for label,key,fmt in [('累積總報酬','cumulative_return',pct),('CAGR','CAGR',pct),('期末資金（元）','final_equity',money),('交易次數／段數','trades',lambda z:str(int(z))),('勝率','win_rate',pct),('Profit Factor','profit_factor',ratio),('最大回撤（元）','MDD_amount',money),('最大回撤（%）','MDD_pct',pct),('最長回撤：交易日','longest_drawdown_trading_days',lambda z:str(int(z))),('最長回撤：日曆日','longest_drawdown_calendar_days',lambda z:str(int(z))),('Sharpe（rf=0）','Sharpe',ratio),('Calmar','Calmar',ratio),('年化波動','annual_volatility',pct),('全部成本（元）','cost_total',money)]:rows.append([label,fmt(ms[key]),fmt(mb[key])])
table(rows,[175,165,165])
text('同期間、同一口、同起始資金。固定一口Buy-and-Hold是可直接執行的曝險比較；策略有658個日末持倉日，基準幾乎全期持有，兩者承擔市場風險的時間不同。MDD金額及比例各自取全期最大值，可能發生於不同日期。','small')
ar=[['年度','策略損益（元）','策略報酬','基準損益（元）','基準報酬']]
for year,g in annual.groupby('year'):
    q=g[g.series=='strategy'].iloc[0];r=g[g.series=='benchmark'].iloc[0]
    ar.append([int(year),f'{q.net_pnl:,.0f}',pct(q.annual_return),f'{r.net_pnl:,.0f}',pct(r.annual_return)])
table(ar,[45,140,90,140,90])
text('2018、2026為部分年度；年度報酬未年化，以該年首日損益前權益為分母。PF=淨正損益合計／淨負損益絕對值合計。最長回撤包含期末未恢復區間，含初始本金高點及空手日。','small')
page();title('5　資金曲線、回撤與風險配平診斷')
image_pair('equity_comparison.png','equity_comparison_log.png')
text(f'圖一：左為線性Y軸、右為對數Y軸。三條權益曲線皆以{money(reference_capital)}元為起點，逐日累加含全部交易成本的淨損益；對數軸只改變顯示尺度。','small')
image('underwater_comparison.png')
text(f'圖二：MDD從各條權益曲線的歷史高點計算。V04策略為{pct(ms.MDD_pct)}，固定一口基準為{pct(mb.MDD_pct)}；兩者持倉時間不同。','small')
sub('一口等曝險風險診斷')
table([['指標','固定一口基準','等曝險代表路徑','V04策略'],['口數','1','1','持倉時1口'],['日末持倉日',str(int(mb.days)),str(int(rm.exposure_days)),str(int(ms.exposure_days))],['年化波動',pct(mb.annual_volatility),pct(rm.annual_volatility),pct(ms.annual_volatility)],['CAGR',pct(mb.CAGR),pct(rm.CAGR),pct(ms.CAGR)],['Sharpe',ratio(mb.Sharpe),ratio(rm.Sharpe),ratio(ms.Sharpe)],['MDD',pct(mb.MDD_pct),pct(rm.MDD_pct),pct(ms.MDD_pct)],['Calmar',ratio(mb.Calmar),ratio(rm.Calmar),ratio(ms.Calmar)]],[100,140,145,120])
text(f'診斷以257個事先等距設定的循環位移為候選，排除距離不足63日或與原持倉重疊超過50%的路徑後，共{int(rm.eligible_shifts)}條符合「固定一口、658個持倉日、147段持有」；每條均重新計算實際費稅、滑價與轉倉。代表路徑只按年化波動最接近策略挑選，未使用報酬作選擇。受整口限制，其最低可得波動仍為{pct(rmdist.annual_volatility.min())}，高於策略{pct(ms.annual_volatility)}，所以它是最接近的整口風險對照，不是假裝完全配平。','small')
text(f'{int(rm.eligible_shifts)}條對照的中位數為CAGR {pct(rm.CAGR_distribution_median)}、Sharpe {ratio(rm.Sharpe_distribution_median)}、MDD {pct(rm.MDD_pct_distribution_median)}。策略Sharpe高於全部合格位移，MDD低於{pct(rm.share_of_shifts_with_mdd_at_least_strategy)}的位移；但此診斷仍使用同一完整樣本，不是可交易規則或樣本外證據。','small')
page();title('6　成本敏感度與條件診斷')
sub('滑價增加後是否仍保留成果')
rows=[['每邊滑價','策略報酬','策略Sharpe','基準報酬','基準Sharpe']]
for slip,g in sens.groupby('slippage_per_leg'):
    q=g[g.series=='strategy'].iloc[0];r=g[g.series=='benchmark'].iloc[0]
    rows.append([f'{slip:g}點',pct(q.cumulative_return),ratio(q.Sharpe),pct(r.cumulative_return),ratio(r.Sharpe)])
table(rows,[75,105,110,105,110])
high_slip=sens[(sens.series=='strategy') & (sens.slippage_per_leg==sens.slippage_per_leg.max())].iloc[0]
text(f'基準{v["parameters"]["slippage_per_leg"]:g}點設定下，策略毛損益{money(ms.gross_pnl)}元，成本{money(ms.cost_total)}元，占毛獲利{pct(ms.cost_total/ms.gross_pnl)}。其中手續費{money(ms.fee)}元、期交稅{money(ms.tax)}元、滑價{money(ms.slippage_cost)}元。{high_slip.slippage_per_leg:g}點滑價時Sharpe為{ratio(high_slip.Sharpe)}；固定滑價不能完整模擬極端行情的成交失敗與流動性惡化。')
sub('拆開兩個條件：事後消融，不是樣本外')
rows=[['規則','報酬','Sharpe','MDD'],['交易強度＋價格趨勢',pct(ms.cumulative_return),ratio(ms.Sharpe),pct(ms.MDD_pct)]]
for r in ab.itertuples():rows.append([r.series,pct(r.cumulative_return),ratio(r.Sharpe),pct(r.MDD_pct)])
table(rows,[220,95,95,95])
text('消融表列出雙條件、單獨法人條件及單獨價格條件在同一期間的結果；報酬、回撤與曝險可分別對照。消融是在選定策略後作的描述，不能消除先前候選挑選造成的偏誤。')
sub('交易分布與成果集中')
strategy_annual=annual[annual.series=='strategy'].sort_values('year')
recent_years=strategy_annual.year.tail(2).astype(int).tolist()
recent_pnl=strategy_annual[strategy_annual.year.isin(recent_years)].net_pnl.sum()
text(f'{int(ms.trades)}筆交易勝率{pct(ms.win_rate)}、PF {ratio(ms.profit_factor)}；持有日曆日平均{duration.mean():.2f}日、中位數{duration.median():.0f}日，最長{duration.max()}日。前五筆獲利合計占總淨利{pct(tr.nlargest(5,"pnl").pnl.sum()/ms.net_pnl)}；最近兩個曆年（{recent_years[0]}、{recent_years[-1]}）合計占總淨利{pct(recent_pnl/ms.net_pnl)}，仍需注意少數交易及近期年份的影響。')
parts=[]
for r in splits[splits.series=='strategy'].itertuples():
    parts.append(f'{r.period}淨利{money(r.net_pnl)}元、描述性Sharpe {ratio(r.Sharpe)}')
negative_years=strategy_annual.loc[strategy_annual.net_pnl<0,'year'].astype(int).tolist()
negative_years_text='、'.join(map(str,negative_years)) if negative_years else '無'
text('；'.join(parts)+f'。年度虧損年份：{negative_years_text}。')
page();title('7　風險來源與策略限制')
sub('一、法人交易指標的解釋限制')
text('本研究的交易強度衡量三大法人的當日淨成交流量，而非收盤後仍持有的未平倉部位。以多空交易總口數作為分母，可降低不同交易活躍程度對原始淨口數的影響；然而三類法人交易同時可能包含方向投資、股票與選擇權避險、套利及造市活動，因此公開彙總資料無法識別各機構的實際交易動機。[2]')
text('20日平均用於降低單日成交流量雜訊，再以價格高於20日均線作為趨勢確認。回測中較高的Sharpe僅代表此規則在目前樣本中的歷史風險調整績效；由於策略採多單／空手架構，績效同時受到長期多頭趨勢與隔夜報酬影響，不能將全部成果歸因於法人資訊優勢。')
text(f'固定一口Buy-and-Hold的MDD為{pct(mb.MDD_pct)}，高於策略的{pct(ms.MDD_pct)}，主要原因之一是基準幾乎全期持有，而策略只有658個日末持倉日。改用相同一口、相同持倉日與相同147段持有的位移對照後，代表路徑MDD為{pct(rm.MDD_pct)}，全部位移的中位數MDD為{pct(rm.MDD_pct_distribution_median)}。這表示「一口」只相同化單次口數，沒有自動相同化時間曝險或實現波動。')
text(f'逐筆比對兩份法人來源共{source_audit["compared_rows"]:,}筆，其中{source_audit["differing_rows"]}筆在2026/07/06不同，造成{source_audit["affected_ma20_days"]}個交易日的Q20變化，但本樣本{source_audit["changed_signal_days"]}天訊號改變。歷史逐日初次發布快照與修訂軌跡未留存，故不能聲稱全期資料時點已獨立驗證。')
text(f'近月未調整價格均線有換月價差敏感度：以前一日兩契約收盤重疊價差調整訊號後，{roll_audit["changed_signal_days"]}天訊號不同，診斷版淨利{money(roll_audit["adjusted_net_pnl"])}元、Sharpe {ratio(roll_audit["adjusted_Sharpe"])}；原版為{money(roll_audit["raw_net_pnl"])}元、{ratio(roll_audit["raw_Sharpe"])}。此比較只變更訊號，實際成交仍按原契約，不取代正式V04。')
text(f'價格單獨策略按完整樣本事後配平至相同年波動的TX-equivalent為{price_vm.position_equivalent:.3f}，淨利{money(price_vm.net_pnl)}元、Sharpe {ratio(price_vm.Sharpe)}；V04為{money(ms.net_pnl)}元、{ratio(ms.Sharpe)}。這是風險尺度與曝險差異的描述，配平小數口不能直接交易，亦非樣本外證據。')
sub('二、盤整與快速反轉環境')
text('在盤整、急漲急跌或V形反轉環境中，20日平均具有滯後性，價格亦可能在MA20附近反覆穿越。當條件短暫失效後退出、再度成立後重新進場，可能造成追價、較低價格退出或錯失快速反彈。雙條件一致仍可能漏接行情或反覆進出。')
text('本回測未加入事後最佳化的固定點數停損。現有資料僅含日盤OHLC，缺乏完整夜盤價格路徑、委託排隊及極端行情成交資訊，因此若加入盤中觸價停損，將引入無法可靠驗證的成交假設。基準版本僅依訊號消退、轉倉與期末清算執行出場。')
sub('三、隔夜跳空與流動性風險')
text('本策略實際持有隔夜部位，因此海外市場、匯率與突發事件可能在臺指期日盤重新開市前改變價格。即使隔日日盤開盤已產生退出需求，仍須承受前一日收盤至下一交易日開盤的跳空風險；若開盤流動性不足，實際成交損失亦可能高於固定2點滑價假設。')
text(f'因此{pct(ms.MDD_pct)}的日末MDD不應解讀為單筆交易或盤中可能遭受的最大損失。共同起始資金取首日一口TX的開盤名目價值，並未重建歷史保證金與追繳；若進一步評估實際交易可行性，仍需納入夜盤價格、盤中極端波動、開盤成交品質與逐日保證金需求。')
page();title('8　結論與後續驗證')
sub('一、績效結論')
text(f'以{money(reference_capital)}元建立兩條權益曲線，逐日累加淨損益後，策略Sharpe為{ratio(ms.Sharpe)}、Calmar為{ratio(ms.Calmar)}，固定一口Buy-and-Hold為{ratio(mb.Sharpe)}與{ratio(mb.Calmar)}；策略MDD為{pct(ms.MDD_pct)}，基準為{pct(mb.MDD_pct)}。策略累積報酬{pct(ms.cumulative_return)}低於基準{pct(mb.cumulative_return)}。固定一口比較仍有持倉時間差異：策略持倉日約為基準三分之一。')
text(f'一口等曝險位移對照的中位數Sharpe為{ratio(rm.Sharpe_distribution_median)}、MDD為{pct(rm.MDD_pct_distribution_median)}；最接近策略波動的代表路徑Sharpe為{ratio(rm.Sharpe)}、MDD為{pct(rm.MDD_pct)}。策略在本樣本仍顯示較佳風險效率，但位移診斷是事後統計控制，不是可部署的交易基準，也不能取代獨立樣本外驗證。')
text('策略最長回撤期間為482個交易日，高於基準的366日，顯示較低回撤幅度不等同於較短的資金恢復時間。勝率約51.70%、Profit Factor約2.197，績效並非依賴高勝率，而較依賴部分趨勢延續期間的較大獲利；前五筆交易與近兩年績效占比較高，亦顯示成果存在集中性。')
text(f'加權指數價格報酬為{pct(mi.cumulative_return)}、MDD {pct(mi.MDD_pct)}，但未含股息或追蹤成本，僅作市場參考。')
sub('二、樣本選擇偏誤與驗證要求')
text(f'本策略由{candidate_count}個候選規則比較後選出，並非在完全未觀察資料的情況下事先固定。因此，即使滑價敏感度與時間分組結果仍為正，也不能視為獨立樣本外證據。目前的Sharpe可能包含策略挑選造成的選擇偏誤，應在解讀績效時明確納入。')
text('後續驗證應先凍結20日交易強度、20日價格均線、零門檻及成本假設，再以未參與策略設計的新資料進行樣本外檢驗。若進一步測試結算日排除、均線參數或停損規則，應事前限定假說與參數範圍，並完整報告所有結果，以降低多重嘗試造成的偏誤。')
text('綜合而言，策略規則可追溯且歷史成本後報酬為正，但同期大盤與TX買進持有累積報酬均較高；V04主要呈現較少持倉及較低回撤，未能據此認定法人訊號創造穩定超額報酬。仍須完成獨立樣本外驗證、夜盤與盤中風險及資料發布時點檢查。')
sub('三、資料來源與計算口徑')
text('[1] 臺灣期貨交易所，臺股期貨契約規格：https://www.taifex.com.tw/cht/2/tX\n[2] 臺灣期貨交易所，三大法人交易資訊：https://www.taifex.com.tw/cht/3/futContractsDateView\n[3] 臺灣期貨交易所，費率表：https://www.taifex.com.tw/cht/4/feeSchedules\n歷史行情：https://www.taifex.com.tw/cht/3/dlFutDailyMarketView\nFinMind：https://finmind.github.io/tutor/TaiwanMarket/Derivative/\n加權指數：臺灣證券交易所每日市場成交資訊與發行量加權股價指數歷史資料，來源與雜湊見source_audits/taiex_sources.json。','small')
text('Sharpe＝日報酬平均／日報酬樣本標準差×√252；Calmar＝CAGR／最大回撤比例。權益曲線以首日一口TX開盤名目價值起算，逐日累加淨損益，MDD取曲線相對歷史高點的最大跌幅；一口等曝險位移作風險尺度診斷。','small')
pages.append(current.copy())
cmap=FontToolsFont(B/'chinese_font.ttf').getBestCmap();missing=sorted(set(ch for t in texts for ch in t if not ch.isspace() and ord(ch) not in cmap))
assert not missing,missing
def footer(can,doc):
    can.setStrokeColor(colors.HexColor('#c4d3da'));can.line(45,35,550,35);can.setFont('TC',8);can.setFillColor(colors.HexColor('#526977'))
    can.drawString(45,23,'法人交易強度＋價格趨勢｜八年共同期間與轉倉基準');can.drawRightString(550,23,f'{doc.page} / 8')
SimpleDocTemplate(str(B/'TX_flow_trend_report.pdf'),pagesize=(595.28,841.89),leftMargin=45,rightMargin=45,topMargin=40,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer)
doc.save(B/'TX_flow_trend_report.docx');(B/'report_text.md').write_text('\n\n---\n\n'.join('\n\n'.join(p) for p in pages),encoding='utf-8')
# 工作簿附上中文欄位說明、圖表與交易期間資訊。
w=load_workbook(B/'TX_flow_trend_workbook.xlsx')
for name in ['欄位中文說明','資金回撤疊圖']:
    if name in w.sheetnames:del w[name]
ws=w.create_sheet('欄位中文說明');ws.append(['欄位','定義'])
dictionary=[('signal_date','昨日盤後訊號日期'),('institution_net_trade_qty','三法人淨交易口數合計'),('institution_total_trade_qty','三法人買進及賣出交易口數合計'),('trade_intensity','淨交易口數合計除以總交易口數'),('intensity_ma20','含訊號日的20日交易強度平均'),('signal_close / price_ma20','訊號日近月收盤／其20日平均'),('target / buy_condition','當日目標部位／昨日訊號條件'),('position_before / position_after','昨日收盤部位／本日收盤部位'),('contract_after','日末持有實際契約；空手時空白'),('gross_pnl / pnl','毛損益／淨損益，均為新臺幣'),('fee / tax / slippage_cost / cost','手續費／稅／滑價／逐日總成本'),('total_cost','完整方向交易的全部成本'),('entry_raw / exit_raw','未含滑價的實際進出成交價'),('entry_execution / exit_execution','含滑價進出價'),('episode_id / segment_id','完整方向交易／實際契約分段編號'),('roll / reason','是否轉倉／成交原因'),('equity / daily_return','以2,195,000元起始，逐日累加淨損益形成日末權益；日報酬為當日淨損益除以前日權益'),('drawdown_pct / drawdown_amount','相對權益曲線歷史高點的回撤比例／金額')]
for row in dictionary:ws.append(row)
ws.column_dimensions['A'].width=46;ws.column_dimensions['B'].width=66;ws.freeze_panes='A2'
ws=w.create_sheet('資金回撤疊圖');ws['A1']=f'同期間、固定一口／空手；共同起始資金為首日一口TX開盤名目價值{reference_capital:,.0f}元。'
for name,cell in [('equity_comparison.png','A3'),('equity_comparison_log.png','A31'),('underwater_comparison.png','A59')]:
    im=ExcelImage(O/name);im.width=940;im.height=374;ws.add_image(im,cell)
buf=io.BytesIO();w.save(buf);payload=buf.getvalue()
with zipfile.ZipFile(io.BytesIO(payload)) as z:assert z.testzip() is None
(B/'TX_flow_trend_workbook.xlsx').write_bytes(payload)
print('報告、Word、圖表及工作簿完成；字形檢查通過。')

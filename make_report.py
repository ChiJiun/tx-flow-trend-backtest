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
vm=read('volatility_matched_benchmark_summary').iloc[0];vmd=read('volatility_matched_benchmark_daily')
tr=read('strategy_trades');annual=read('annual_results');sens=read('cost_sensitivity');ab=read('ablation');splits=read('descriptive_time_splits')
ev=read('strategy_events');bev=read('benchmark_events');v=json.loads((O/'validation.json').read_text())
for d in [s,bh,vmd]:d['date']=pd.to_datetime(d.date)
tr['entry_date']=pd.to_datetime(tr.entry_date);tr['exit_date']=pd.to_datetime(tr.exit_date)
duration=(tr.exit_date-tr.entry_date).dt.days
pct=lambda x:f'{x*100:.2f}%';money=lambda x:f'{x:,.2f}';ratio=lambda x:f'{x:.3f}'
font=FontProperties(fname=str(B/'chinese_font.ttf'));plt.rcParams['axes.unicode_minus']=False

def validate_equity_for_log(*frames):
    for d in frames:
        if d.empty:raise ValueError('log equity chart requires non-empty data')
        equity=pd.to_numeric(d.equity,errors='coerce')
        if not np.isfinite(equity).all() or (equity<=0).any():raise ValueError('log equity chart requires strictly positive finite equity')

for water in [False,True]:
    fig,ax=plt.subplots(figsize=(9.4,3.75))
    for d,label,col in [(s,'法人交易強度＋價格趨勢','#146f91'),(bh,'Buy-and-Hold（含轉倉成本）','#ce7c2e')]:
        ax.plot(d.date,d.drawdown_pct*100 if water else d.equity/1e6,label=label,color=col,lw=1.35)
    ax.set_xlim(s.date.min(),s.date.max());ax.set_ylabel('回撤（%）' if water else '帳戶資金（百萬元）',fontproperties=font)
    ax.set_title('成本後回撤深度比較' if water else '成本後資金曲線：同期間、同本金、固定一口',fontproperties=font)
    if not water:ax.axhline(10,color='gray',ls='--',lw=.8)
    ax.legend(prop=font,frameon=False);ax.grid(alpha=.18);ax.spines[['top','right']].set_visible(False)
    fig.tight_layout();fig.savefig(O/('underwater_comparison.png' if water else 'equity_comparison.png'),dpi=200);plt.close(fig)
validate_equity_for_log(s,bh)
fig,ax=plt.subplots(figsize=(9.4,3.75))
for d,label,col in [(s,'法人交易強度＋價格趨勢','#146f91'),(bh,'Buy-and-Hold（含轉倉成本）','#ce7c2e')]:
    ax.plot(d.date,d.equity/1e6,label=label,color=col,lw=1.35)
ax.set_yscale('log');ax.set_xlim(s.date.min(),s.date.max());ax.set_ylabel('帳戶資金（百萬元，log scale）',fontproperties=font)
ax.set_title('成本後資金曲線（對數Y軸）：同期間、同本金、固定一口',fontproperties=font)
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
doc=Document();sec=doc.sections[0];sec.top_margin=sec.bottom_margin=Cm(1.7);sec.left_margin=sec.right_margin=Cm(1.7)
sty=doc.styles['Normal'];sty.font.name='Noto Sans TC';sty.font.size=Pt(10.5);sty.element.rPr.rFonts.set(qn('w:eastAsia'),'Noto Sans TC')
def text(t,style='body'):
    texts.append(t);story.append(Paragraph(html.escape(t).replace('\n','<br/>'),styles[style]));current.append(t);doc.add_paragraph(t)
def title(t):
    texts.append(t);story.append(Paragraph(html.escape(t),styles['title']));current.append('# '+t);doc.add_heading(t,1)
def sub(t):text(t,'sub')
def page():pages.append(current.copy());current.clear();story.append(PageBreak());doc.add_page_break()
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
text('研究假說：三大法人持續的淨買進活動，若同時伴隨價格上升趨勢，可能比單日部位異常更能辨識可持續的多頭環境。本研究以20日法人交易強度與20日價格均線建立一口多單／空手規則，並以計入轉倉成本的台指期近月Buy-and-Hold比較。')
table([['資料','來源、期間與清理'],['TX日盤行情','TAIFEX年度ZIP及2026年月檔；2016/10/05～2026/10/05，2,438日、14,202筆實際月契約、126個契約。僅保留一般交易時段、六碼月契約。'],['三大法人交易','FinMind TX歷史資料與TAIFEX格式原始資料；2018/06/05～2026/10/05，2,030日、6,090筆三類法人資料。'],['正式回測期間','2018/08/31～2026/10/05，共1,968日，約8.1年。沿用前版共同起點，以便比較；本策略本身需要20日暖身。'],['缺漏處理','2016/10/05～2018/06/04缺408日籌碼，未補造。較早官方交易金額淨額空白，但本策略只用完整的交易口數。']])
text('較新期間以TAIFEX格式原始資料優先，以降低不同資料來源歷史值差異造成的影響；三類法人日期均與行情交易日曆一致。資料未混入MTX、週契約、夜盤或價差交易。原始月契約共有179筆OHLC缺值紀錄，但策略及基準實際使用的進出、轉倉與評價價格均完整。')
text('本策略由18個候選規則中篩選後固定參數重新回測，因此結果屬探索性全樣本分析，尚未以完全未參與策略選擇的資料進行獨立樣本外驗證。此限制在後續結論中另行討論。')
text(f'主要結果：策略報酬{pct(ms.cumulative_return)}、Sharpe {ratio(ms.Sharpe)}、MDD {pct(ms.MDD_pct)}；基準報酬{pct(mb.cumulative_return)}、Sharpe {ratio(mb.Sharpe)}、MDD {pct(mb.MDD_pct)}。策略風險調整報酬較高，絕對收益較低。')
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
table([['設定','策略與基準共同口徑'],['本金／口數／乘數','本金1,000萬元；固定一口、不加碼；每點200元。'],['手續費','每邊每口50元，假設為券商總手續費；未另重複加交易所經手費。[3]'],['滑價','每次成交2點：買進價+2、賣出價−2。初始進出、轉倉與期末平倉皆計。'],['期交稅','每邊按含滑價成交價×200×0.00002。連續金額近似，未逐筆取整。[3]'],['資金與槓桿','資金足以覆蓋完整契約名目價值及估計成本；全期通過。未使用保證金槓桿或重建歷史追繳。'],['日末評價與報酬','用收盤價評價總權益，非以每日結算價重建現金流。日損益／前日權益，含空手日。'],['年化與利息','現金利息及rf=0；Sharpe採252日；CAGR依實際起訖含首尾日／365.25。']])
text('持有日損益按同一實際契約今日收盤減昨日評價價；退出日先計舊持倉至開盤的損益，進場日從開盤計至收盤。換倉日先結束舊約損益，再將新約收盤設為新評價基準，成交各扣成本。新舊約價差不直接列為本日損益，也不另外重複扣費。')
text(f'策略147筆完整方向交易、37次轉倉、368個成交腿；基準98段契約交易、97次轉倉、196個成交腿。策略總成本{money(ms.cost_total)}元，基準{money(mb.cost_total)}元。逐日損益、方向交易及實際契約分段損益皆獨立核對一致。')
page();title('4　績效指標與年度比較')
rows=[['成本後指標','法人交易強度＋趨勢','Buy-and-Hold基準']]
for label,key,fmt in [('累積總報酬','cumulative_return',pct),('CAGR','CAGR',pct),('期末資金（元）','final_equity',money),('交易次數／段數','trades',lambda z:str(int(z))),('勝率','win_rate',pct),('Profit Factor','profit_factor',ratio),('最大回撤（元）','MDD_amount',money),('最大回撤（%）','MDD_pct',pct),('最長回撤：交易日','longest_drawdown_trading_days',lambda z:str(int(z))),('最長回撤：日曆日','longest_drawdown_calendar_days',lambda z:str(int(z))),('Sharpe（rf=0）','Sharpe',ratio),('Calmar','Calmar',ratio),('年化波動','annual_volatility',pct),('全部成本（元）','cost_total',money)]:rows.append([label,fmt(ms[key]),fmt(mb[key])])
table(rows,[175,165,165])
text('同期間、同本金、同一口。策略按一次進場至訊號退出計交易，合併轉倉成本；基準在每次換月結束一段交易。因此勝率／PF的持有頻率不同。MDD金額及比例各自取全期最大值，可能發生於不同日期。','small')
ar=[['年度','策略損益（元）','策略報酬','基準損益（元）','基準報酬']]
for year,g in annual.groupby('year'):
    q=g[g.series=='strategy'].iloc[0];r=g[g.series=='benchmark'].iloc[0]
    ar.append([int(year),f'{q.net_pnl:,.0f}',pct(q.annual_return),f'{r.net_pnl:,.0f}',pct(r.annual_return)])
table(ar,[45,140,90,140,90])
text('2018、2026為部分年度；年度報酬未年化，以該年首日損益前權益為分母。PF=淨正損益合計／淨負損益絕對值合計。最長回撤包含期末未恢復區間，含初始本金高點及空手日。','small')
page();title('5　資金曲線、回撤與風險配平診斷')
image_pair('equity_comparison.png','equity_comparison_log.png')
text('圖一：左為線性Y軸、右為對數Y軸。兩者皆自1,000萬元起始並扣除所有成交與轉倉成本；log-y版本只改變視覺尺度，不改變任何報酬或風險計算。','small')
image('underwater_comparison.png')
text('圖二：日末權益相對含初始本金的歷史高點回撤。策略MDD 3.93%，基準11.12%；策略回撤較淺，但固定一口比較同時含有不同市場曝險。','small')
sub('波動配平診斷（事後分析）')
table([['指標','固定一口基準','波動配平診斷'],['TX-equivalent','1.000',f'{vm.position_equivalent:.3f}'],['年化波動',pct(mb.annual_volatility),pct(vm.annual_volatility)],['CAGR',pct(mb.CAGR),pct(vm.CAGR)],['Sharpe',ratio(mb.Sharpe),ratio(vm.Sharpe)],['MDD',pct(mb.MDD_pct),pct(vm.MDD_pct)],['Calmar',ratio(mb.Calmar),ratio(vm.Calmar)]],[165,165,165])
text(f'配平係數以完整樣本事後估計，使基準年化波動由{pct(mb.annual_volatility)}調整至策略的{pct(ms.annual_volatility)}；所得曝險約為{vm.position_equivalent:.3f}口TX-equivalent。基準毛損益、手續費、稅與滑價成本均按相同比例縮放，因此此結果僅用於同風險尺度比較，不代表可直接執行的整口TX交易策略。','small')
text('固定一口仍是主結果，因為它可直接對應實際合約；波動配平只用來避免把策略較低MDD完全誤解為訊號本身的優勢。圖表也沒有盤中及夜盤評價，不能代表最壞瞬時損失或精確保證金風險。','small')
page();title('6　成本敏感度與條件診斷')
sub('滑價增加後是否仍保留成果')
rows=[['每邊滑價','策略報酬','策略Sharpe','基準報酬','基準Sharpe']]
for slip,g in sens.groupby('slippage_per_leg'):
    q=g[g.series=='strategy'].iloc[0];r=g[g.series=='benchmark'].iloc[0]
    rows.append([f'{slip:g}點',pct(q.cumulative_return),ratio(q.Sharpe),pct(r.cumulative_return),ratio(r.Sharpe)])
table(rows,[75,105,110,105,110])
text(f'基準2點設定下，策略毛損益{money(ms.gross_pnl)}元，成本{money(ms.cost_total)}元，占毛獲利{pct(ms.cost_total/ms.gross_pnl)}。其中手續費18,400元、期交稅26,463.42元、滑價147,200元。4點滑價時Sharpe仍為1.241，但固定滑價不能完整模擬極端行情的成交失敗與流動性惡化。')
sub('拆開兩個條件：事後消融，不是樣本外')
rows=[['規則','報酬','Sharpe','MDD'],['交易強度＋價格趨勢',pct(ms.cumulative_return),ratio(ms.Sharpe),pct(ms.MDD_pct)]]
for r in ab.itertuples():rows.append([r.series,pct(r.cumulative_return),ratio(r.Sharpe),pct(r.MDD_pct)])
table(rows,[220,95,95,95])
text('合併條件降低了收益，也降低了日末回撤及波動。相較單獨交易強度或單獨價格均線，這個歷史樣本中的主要改善是風險效率，而不是提高總獲利。消融是在選定策略後作的描述，不能消除先前候選挑選造成的偏誤。')
sub('交易分布與成果集中')
text(f'147筆交易勝率{pct(ms.win_rate)}、PF {ratio(ms.profit_factor)}；持有日曆日平均{duration.mean():.2f}日、中位數{duration.median():.0f}日，最長{duration.max()}日。前五筆獲利合計占總淨利{pct(tr.nlargest(5,"pnl").pnl.sum()/ms.net_pnl)}；2025與2026合計約占61.73%，仍需注意少數交易及近期年份的影響。')
text('較早2018～2022淨利108.30萬元、描述性Sharpe 1.140；2023～2026淨利219.46萬元、Sharpe 1.481。兩段均為正，但2018、2022、2024年度為負。2024基準上漲而策略虧損，顯示趨勢過濾仍可能漏接行情或反覆進出。')
page();title('7　風險來源與策略限制')
sub('一、法人交易指標的解釋限制')
text('本研究的交易強度衡量三大法人的當日淨成交流量，而非收盤後仍持有的未平倉部位。以多空交易總口數作為分母，可降低不同交易活躍程度對原始淨口數的影響；然而三類法人交易同時可能包含方向投資、股票與選擇權避險、套利及造市活動，因此公開彙總資料無法識別各機構的實際交易動機。[2]')
text('20日平均用於降低單日成交流量雜訊，再以價格高於20日均線作為趨勢確認。回測中較高的Sharpe僅代表此規則在目前樣本中的歷史風險調整績效；由於策略採多單／空手架構，績效同時受到長期多頭趨勢與隔夜報酬影響，不能將全部成果歸因於法人資訊優勢。')
sub('二、盤整與快速反轉環境')
text('在盤整、急漲急跌或V形反轉環境中，20日平均具有滯後性，價格亦可能在MA20附近反覆穿越。當條件短暫失效後退出、再度成立後重新進場，可能造成追價、較低價格退出或錯失快速反彈。2024年基準為正報酬而策略為負，即顯示雙條件一致並不代表能捕捉所有上升行情。')
text('本回測未加入事後最佳化的固定點數停損。現有資料僅含日盤OHLC，缺乏完整夜盤價格路徑、委託排隊及極端行情成交資訊，因此若加入盤中觸價停損，將引入無法可靠驗證的成交假設。基準版本僅依訊號消退、轉倉與期末清算執行出場。')
sub('三、隔夜跳空與流動性風險')
text('本策略實際持有隔夜部位，因此海外市場、匯率與突發事件可能在臺指期日盤重新開市前改變價格。即使隔日日盤開盤已產生退出需求，仍須承受前一日收盤至下一交易日開盤的跳空風險；若開盤流動性不足，實際成交損失亦可能高於固定2點滑價假設。')
text('因此3.93%的日末MDD不應解讀為單筆交易或盤中可能遭受的最大損失。完整名目價值資金限制降低了槓桿造成的風險，但無法消除跳空與流動性風險；若進一步評估實際交易可行性，仍需納入夜盤價格、盤中極端波動與開盤成交品質。')
page();title('8　結論與後續驗證')
sub('一、績效結論')
text('策略Sharpe為1.302、Calmar為0.906，高於固定一口Buy-and-Hold基準的1.108與0.694，MDD亦由11.12%降至3.93%；但策略累積報酬32.78%，低於基準82.68%。因此主要優勢體現在歷史風險效率與回撤控制，而非絕對收益。較低市場曝險同時降低下跌風險，也犧牲部分多頭行情的收益。')
text('策略最長回撤期間為482個交易日，高於基準的366日，顯示較低回撤幅度不等同於較短的資金恢復時間。勝率約51.70%、Profit Factor約2.197，績效並非依賴高勝率，而較依賴部分趨勢延續期間的較大獲利；前五筆交易與近兩年績效占比較高，亦顯示成果存在集中性。')
sub('二、樣本選擇偏誤與驗證要求')
text('本版本由18個候選規則比較後選出，並非在完全未觀察資料的情況下事先固定。因此，即使滑價敏感度與時間分組結果仍為正，也不能視為獨立樣本外證據。目前的Sharpe可能包含策略挑選造成的選擇偏誤，應在解讀績效時明確納入。')
text('後續驗證應先凍結20日交易強度、20日價格均線、零門檻及成本假設，再以未參與策略設計的新資料進行樣本外檢驗。若進一步測試結算日排除、均線參數或停損規則，應事前限定假說與參數範圍，並完整報告所有結果，以降低多重嘗試造成的偏誤。')
text('綜合而言，法人交易強度與價格趨勢的雙條件策略具有規則簡單、交易邏輯可追溯及歷史風險效率較佳等特性，可作為後續研究候選。然而，現有證據不足以宣稱其具有穩定的樣本外超額報酬。若要提高結論可信度，應優先完成獨立樣本外驗證、夜盤與盤中風險評估，以及資料發布時點與歷史修訂的一致性檢查。')
sub('三、資料來源與計算口徑')
text('[1] 臺灣期貨交易所，臺股期貨契約規格：https://www.taifex.com.tw/cht/2/tX\n[2] 臺灣期貨交易所，三大法人交易資訊：https://www.taifex.com.tw/cht/3/futContractsDateView\n[3] 臺灣期貨交易所，費率表：https://www.taifex.com.tw/cht/4/feeSchedules\n歷史行情：https://www.taifex.com.tw/cht/3/dlFutDailyMarketView\nFinMind：https://finmind.github.io/tutor/TaiwanMarket/Derivative/','small')
text('Sharpe＝日報酬平均／日報酬樣本標準差×√252；Calmar＝CAGR／最大回撤比例。所有績效指標均依相同初始資金、交易期間與成本假設計算；波動配平結果僅作風險尺度診斷，不列為主要可執行基準。','small')
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
dictionary=[('signal_date','昨日盤後訊號日期'),('institution_net_trade_qty','三法人淨交易口數合計'),('institution_total_trade_qty','三法人買進及賣出交易口數合計'),('trade_intensity','淨交易口數合計除以總交易口數'),('intensity_ma20','含訊號日的20日交易強度平均'),('signal_close / price_ma20','訊號日近月收盤／其20日平均'),('target / buy_condition','當日目標部位／昨日訊號條件'),('position_before / position_after','昨日收盤部位／本日收盤部位'),('contract_after','日末持有實際契約；空手時空白'),('gross_pnl / pnl','毛損益／淨損益，均為新臺幣'),('fee / tax / slippage_cost / cost','手續費／稅／滑價／逐日總成本'),('total_cost','完整方向交易的全部成本'),('entry_raw / exit_raw','未含滑價的實際進出成交價'),('entry_execution / exit_execution','含滑價進出價'),('episode_id / segment_id','完整方向交易／實際契約分段編號'),('roll / reason','是否轉倉／成交原因'),('equity / daily_return','日末權益／當日損益除以前日權益'),('drawdown_pct / drawdown_amount','相對含期初本金高點的回撤比例／金額')]
for row in dictionary:ws.append(row)
ws.column_dimensions['A'].width=46;ws.column_dimensions['B'].width=66;ws.freeze_panes='A2'
ws=w.create_sheet('資金回撤疊圖');ws['A1']='同期間、同本金、全部成本後；日末評價。線性與log-y資金曲線均保留。'
for name,cell in [('equity_comparison.png','A3'),('equity_comparison_log.png','A31'),('underwater_comparison.png','A59')]:
    im=ExcelImage(O/name);im.width=940;im.height=374;ws.add_image(im,cell)
buf=io.BytesIO();w.save(buf);payload=buf.getvalue()
with zipfile.ZipFile(io.BytesIO(payload)) as z:assert z.testzip() is None
(B/'TX_flow_trend_workbook.xlsx').write_bytes(payload)
print('報告、Word、圖表及工作簿完成；字形檢查通過。')

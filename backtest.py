"""法人交易強度20日＋價格趨勢：策略與含轉倉成本Buy-and-Hold重現。"""
from pathlib import Path
import pandas as pd, numpy as np, json, io, zipfile, hashlib, platform
BASE=Path(__file__).resolve().parent; OUT=BASE/'output'; OUT.mkdir(exist_ok=True)
CAPITAL=10_000_000.; MULT=200.; FEE=50.; TAX=.00002; SLIP=2.
START=pd.Timestamp('2018-08-31'); END=pd.Timestamp('2026-10-05')
p=pd.read_csv(BASE/'input/prices.csv',parse_dates=['date']).sort_values('date').reset_index(drop=True)
a=pd.read_csv(BASE/'input/all_contracts.csv',parse_dates=['date'])
raw=pd.read_csv(BASE/'input/institutional.csv');raw['date']=pd.to_datetime(raw['日期'])
inv=pd.read_csv(BASE/'input/contract_inventory.csv',parse_dates=['last_observed_date'])
assert not a.duplicated(['date','contract']).any() and not raw.duplicated(['date','身份別']).any()
assert (raw.groupby('date').size()==3).all()
lookup=a.set_index(['date','contract']); prices=lookup; calendar=list(p.date)
expiry=dict(zip(inv.contract,inv.last_observed_date))
roll_dates={con:calendar[calendar.index(ed)-1] for con,ed in expiry.items() if ed in calendar and calendar.index(ed)>0 and con[2:]<END.strftime('%Y%m')}
for con,ed in expiry.items():
    if not (p.date.min()<=ed<END) or con[2:]>=END.strftime('%Y%m'):continue
    first=pd.Timestamp(int(con[2:6]),int(con[6:8]),1)
    third=first+pd.Timedelta(days=(2-first.weekday())%7+14)
    assert ed==next(d for d in calendar if d>=third)
# 僅用交易口數，沒有使用早期缺漏的官方交易金額淨額。
g=raw.groupby('date'); net=g['多空交易口數淨額'].sum()
den=g.apply(lambda y:(y['多方交易口數']+y['空方交易口數']).sum(),include_groups=False)
assert (den>0).all()
x=p.set_index('date').join((net/den).rename('trade_intensity')).join(net.rename('institution_net_trade_qty')).join(den.rename('institution_total_trade_qty'))
x['intensity_ma20']=x.trade_intensity.rolling(20,min_periods=20).mean()
x['price_ma20']=x.close.rolling(20,min_periods=20).mean()
x['buy_condition']=(x.intensity_ma20>0)&(x.close>x.price_ma20)
main_dates=p.loc[p.date.between(START,END),'date'];main_dates=pd.DatetimeIndex(main_dates)
assert x.loc[main_dates,['trade_intensity','intensity_ma20','price_ma20']].notna().all().all()

def enrich(df):
    df['cost']=df.fee+df.tax+df.slippage_cost
    df['daily_return']=df.pnl/df.equity.shift(fill_value=CAPITAL)
    peak=df.equity.cummax().clip(lower=CAPITAL)
    df['drawdown_pct']=df.equity/peak-1
    df['drawdown_amount']=df.equity-peak
    return df

def benchmark(frame, slip=SLIP):
    """到期前一交易日13:45以兩合約各自收盤價換倉。價差不直接算損益。"""
    rows=[]; events=[]; trades=[]; equity=CAPITAL; held=None; prev=None; tid=0
    def leg(dt,con,side,raw,reason):
        execution=raw+slip if side=='buy' else raw-slip
        event=dict(date=dt,contract=con,side=side,raw_price=raw,execution_price=execution,
                   fee=FEE,tax=execution*MULT*TAX,slippage_cost=slip*MULT,reason=reason,trade_id=tid)
        events.append(event)
        return event
    def close_trade(dt,con,raw,reason):
        e=leg(dt,con,'sell',raw,reason)
        x=trades[-1]; x.update(exit_date=dt,exit_raw=raw,exit=e['execution_price'])
        x['fee']+=e['fee']; x['tax']+=e['tax']; x['slippage_cost']+=e['slippage_cost']
        x['gross_pnl']=(raw-x['entry_raw'])*MULT
        x['pnl']=x['gross_pnl']-x['fee']-x['tax']-x['slippage_cost']
    def open_trade(dt,con,raw,reason):
        e=leg(dt,con,'buy',raw,reason)
        trades.append(dict(trade_id=tid,contract=con,entry_date=dt,entry_raw=raw,entry=e['execution_price'],
                           fee=e['fee'],tax=e['tax'],slippage_cost=e['slippage_cost']))
    for i,r in enumerate(frame.itertuples()):
        n0=len(events); roll=False; old=held; spread=0.
        if held is None:
            held=r.contract; tid+=1; raw=float(lookup.loc[(r.date,held),'open'])
            # 若首日即為已過預定換倉時點的到期日，直接持有次月。
            if expiry[held]==r.date:
                nxt=(pd.Period(held[2:],freq='M')+1).strftime('%Y%m'); held='TX'+nxt
                raw=float(lookup.loc[(r.date,held),'open'])
            assert equity>(raw+slip)*MULT+FEE+(raw+slip)*MULT*TAX
            open_trade(r.date,held,raw,'initial_entry'); prev=raw; old=held
        mark=float(lookup.loc[(r.date,held),'close']); assert np.isfinite(mark)
        gross=(mark-prev)*MULT
        if i==len(frame)-1:
            close_trade(r.date,held,mark,'final_exit'); closing_held=''
        elif roll_dates.get(held)==r.date:
            old=held; close_trade(r.date,held,mark,'roll_exit')
            held='TX'+(pd.Period(held[2:],freq='M')+1).strftime('%Y%m')
            new_mark=float(lookup.loc[(r.date,held),'close']); assert np.isfinite(new_mark)
            spread=new_mark-mark; tid+=1; open_trade(r.date,held,new_mark,'roll_entry')
            mark=new_mark; roll=True; closing_held=held
        else: closing_held=held
        legs=events[n0:]; fee=sum(e['fee'] for e in legs); tax=sum(e['tax'] for e in legs); sc=sum(e['slippage_cost'] for e in legs)
        pnl=gross-fee-tax-sc; equity+=pnl
        assert equity>0
        if closing_held: assert equity>mark*MULT, '完整名目價值資金限制不符'
        rows.append(dict(date=r.date,held_before=old,held_after=closing_held,mark_close=mark,roll=roll,
                         roll_spread_points=spread,gross_pnl=gross,fee=fee,tax=tax,slippage_cost=sc,
                         pnl=pnl,equity=equity,execution_legs=len(legs)))
        prev=mark
    d=enrich(pd.DataFrame(rows)); ev=pd.DataFrame(events); tr=pd.DataFrame(trades)
    # 以每段實際契約完整進出，獨立核對逐日評價帳。
    assert np.isclose(d.pnl.sum(),tr.pnl.sum(),atol=1e-6)
    assert np.isclose(d.cost.sum(),(ev.fee+ev.tax+ev.slippage_cost).sum(),atol=1e-6)
    assert np.isclose(d.gross_pnl.sum(),(tr.exit_raw.iloc[-1]-tr.entry_raw.iloc[0]-d.roll_spread_points.sum())*MULT)
    assert len(ev)==2*len(tr) and d['roll'].sum()==len(tr)-1
    return d,ev,tr

def metrics(df,tr):
    start,end=df.date.iloc[0],df.date.iloc[-1]
    years=((end-start).days+1)/365.25; ret=df.equity.iloc[-1]/CAPITAL-1
    cagr=(1+ret)**(1/years)-1; mdd=-df.drawdown_pct.min()
    run=longest=cal=0; peakdate=start
    for r in df.itertuples():
        if r.drawdown_pct < -1e-12:
            run+=1; longest=max(longest,run); cal=max(cal,(r.date-peakdate).days)
        else: run=0; peakdate=r.date
    win=tr.loc[tr.pnl>0,'pnl'].sum(); loss=-tr.loc[tr.pnl<0,'pnl'].sum()
    return dict(start=str(start.date()),end=str(end.date()),days=len(df),final_equity=df.equity.iloc[-1],net_pnl=df.pnl.sum(),
                gross_pnl=df.gross_pnl.sum(),cost_total=df.cost.sum(),cumulative_return=ret,CAGR=cagr,trades=len(tr),
                win_rate=float((tr.pnl>0).mean()),profit_factor=win/loss if loss else None,MDD_amount=-df.drawdown_amount.min(),
                MDD_pct=mdd,longest_drawdown_trading_days=longest,longest_drawdown_calendar_days=cal,
                Sharpe=df.daily_return.mean()/df.daily_return.std(ddof=1)*np.sqrt(252),Calmar=cagr/mdd if mdd else None,
                annual_volatility=df.daily_return.std(ddof=1)*np.sqrt(252),fee=df.fee.sum(),tax=df.tax.sum(),slippage_cost=df.slippage_cost.sum())


def volatility_matched_benchmark(df,target_annual_volatility):
    """事後將基準逐日損益與成本同比例縮放，使年化波動匹配策略。

    這是 fractional TX-equivalent 診斷，不是可直接交易的整口部位；縮放係數使用完整樣本求得。
    """
    if df.empty:raise ValueError('volatility-matched benchmark requires non-empty daily data')
    if not np.isfinite(target_annual_volatility) or target_annual_volatility<=0:raise ValueError('target volatility must be positive and finite')
    cols=['gross_pnl','fee','tax','slippage_cost','cost','pnl']
    if any(c not in df for c in cols):raise ValueError('benchmark daily data is missing P&L/cost columns')
    def scaled(scale):
        d=df[['date']].copy();d['position_equivalent']=scale
        for col in cols:d[col]=df[col].astype(float)*scale
        d['equity']=CAPITAL+d.pnl.cumsum()
        if not np.isfinite(d.equity).all() or (d.equity<=0).any():raise ValueError('scaled benchmark equity must remain positive and finite')
        d['daily_return']=d.pnl/d.equity.shift(fill_value=CAPITAL)
        peak=d.equity.cummax().clip(lower=CAPITAL)
        d['drawdown_pct']=d.equity/peak-1;d['drawdown_amount']=d.equity-peak
        return d
    def annual_vol(scale):
        d=scaled(scale);return float(d.daily_return.std(ddof=1)*np.sqrt(252))
    lo,hi=0.,1.
    while annual_vol(hi)<target_annual_volatility:
        hi*=2
        if hi>8:raise ValueError('could not bracket volatility-matching scale safely')
    for _ in range(100):
        mid=(lo+hi)/2
        if annual_vol(mid)<target_annual_volatility:lo=mid
        else:hi=mid
    scale=(lo+hi)/2;d=scaled(scale)
    start,end=d.date.iloc[0],d.date.iloc[-1];years=((end-start).days+1)/365.25
    ret=d.equity.iloc[-1]/CAPITAL-1;cagr=(1+ret)**(1/years)-1;mdd=-d.drawdown_pct.min()
    sd=d.daily_return.std(ddof=1);sharpe=d.daily_return.mean()/sd*np.sqrt(252)
    summary=dict(series='Buy-and-Hold波動配平診斷',matching_scope='full-sample post-hoc',directly_tradable=False,
        position_equivalent=scale,cost_treatment='gross P&L, fee, tax and slippage cost scaled proportionally',
        target_annual_volatility=target_annual_volatility,annual_volatility=sd*np.sqrt(252),start=str(start.date()),end=str(end.date()),days=len(d),
        final_equity=d.equity.iloc[-1],net_pnl=d.pnl.sum(),gross_pnl=d.gross_pnl.sum(),cost_total=d.cost.sum(),cumulative_return=ret,CAGR=cagr,
        MDD_amount=-d.drawdown_amount.min(),MDD_pct=mdd,Sharpe=sharpe,Calmar=cagr/mdd if mdd else np.nan,
        fee=d.fee.sum(),tax=d.tax.sum(),slippage_cost=d.slippage_cost.sum())
    return d,summary


def run(c):
    position=0;held=None;previous=None;equity=CAPITAL;episode=0;segment=0;rows=[];events=[];segments=[]
    def leg(date,con,side,raw,reason):
        ex=raw+side*SLIP;e=dict(date=date,contract=con,side='buy' if side==1 else 'sell',raw_price=raw,execution_price=ex,
            fee=FEE,tax=ex*MULT*TAX,slippage_cost=SLIP*MULT,reason=reason,episode_id=episode,segment_id=segment)
        events.append(e);return e
    def enter(date,con,raw,reason):
        nonlocal segment
        segment+=1;e=leg(date,con,1,raw,reason);segments.append(dict(segment_id=segment,episode_id=episode,contract=con,
            entry_date=date,entry_raw=raw,entry_execution=e['execution_price'],fee=e['fee'],tax=e['tax'],slippage_cost=e['slippage_cost']))
    def exit(date,raw,reason):
        e=leg(date,held,-1,raw,reason);a=segments[-1];a.update(exit_date=date,exit_raw=raw,exit_execution=e['execution_price'])
        for k in ['fee','tax','slippage_cost']:a[k]+=e[k]
        a['gross_pnl']=(raw-a['entry_raw'])*MULT;a['pnl']=a['gross_pnl']-a['fee']-a['tax']-a['slippage_cost']
    for i,date in enumerate(main_dates):
        n0=len(events);gross=0.;roll=False;before=position;desired=int(c['target'].loc[date]);skip=False
        if desired!=position:
            if position:
                op=float(prices.loc[(date,held),'open']);gross+=(op-previous)*MULT;exit(date,op,'signal_exit');position=0;held=None;previous=None
            if desired:
                held=str(schedule.loc[date,'held_before']);op=float(prices.loc[(date,held),'open'])
                if equity+gross>(op+SLIP)*MULT+FEE+(op+SLIP)*MULT*TAX+SLIP*MULT:
                    position=1;episode+=1;enter(date,held,op,'signal_entry');previous=op
                else:held=None;skip=True
        if position:
            assert held==str(schedule.loc[date,'held_before'])
            mark=float(prices.loc[(date,held),'close']);gross+=(mark-previous)*MULT
            if i==len(main_dates)-1:exit(date,mark,'final_exit');position=0;held=None;previous=None
            elif bool(schedule.loc[date,'roll']):
                exit(date,mark,'roll_exit');held=str(schedule.loc[date,'held_after']);mark=float(prices.loc[(date,held),'close'])
                enter(date,held,mark,'roll_entry');roll=True;previous=mark
            else:previous=mark
        legs=events[n0:];fee=sum(e['fee'] for e in legs);tax=sum(e['tax'] for e in legs);sc=sum(e['slippage_cost'] for e in legs)
        pnl=gross-fee-tax-sc;equity+=pnl;assert equity>0
        if position:assert equity>previous*MULT
        rows.append(dict(date=date,signal_date=x.index[x.index.get_loc(date)-1],target=desired,position_before=before,position_after=position,
            contract_after=held,roll=roll,gross_pnl=gross,fee=fee,tax=tax,slippage_cost=sc,cost=fee+tax+sc,pnl=pnl,equity=equity,capital_skip=skip))
    d=pd.DataFrame(rows);ev=pd.DataFrame(events);seg=pd.DataFrame(segments)
    tr=seg.groupby('episode_id').agg(entry_date=('entry_date','min'),exit_date=('exit_date','max'),contract_segments=('segment_id','count'),
        gross_pnl=('gross_pnl','sum'),fee=('fee','sum'),tax=('tax','sum'),slippage_cost=('slippage_cost','sum'),pnl=('pnl','sum')).reset_index()
    tr['total_cost']=tr.fee+tr.tax+tr.slippage_cost
    assert np.isclose(d.pnl.sum(),seg.pnl.sum()) and np.isclose(d.pnl.sum(),tr.pnl.sum())
    assert np.isclose(((seg.exit_execution-seg.entry_execution)*MULT-seg.fee-seg.tax).sum(),d.pnl.sum())
    d['daily_return']=d.pnl/d.equity.shift(fill_value=CAPITAL);peak=d.equity.cummax().clip(lower=CAPITAL)
    d['drawdown_pct']=d.equity/peak-1;d['drawdown_amount']=d.equity-peak
    years=((main_dates[-1]-main_dates[0]).days+1)/365.25;ret=equity/CAPITAL-1;cagr=(1+ret)**(1/years)-1;mdd=-d.drawdown_pct.min()
    loss=-tr.loc[tr.pnl<0,'pnl'].sum();gain=tr.loc[tr.pnl>0,'pnl'].sum();runlen=longest=cal=0;peakdate=main_dates[0]
    for r in d.itertuples():
        if r.drawdown_pct < -1e-12:runlen+=1;longest=max(longest,runlen);cal=max(cal,(r.date-peakdate).days)
        else:runlen=0;peakdate=r.date
    m=dict(code=c['code'],group=c['group'],series=c['name'],rule=c['rule'],initial_candidate=c['initial'],start=str(main_dates[0].date()),end=str(main_dates[-1].date()),days=len(d),
        cumulative_return=ret,CAGR=cagr,Sharpe=d.daily_return.mean()/d.daily_return.std(ddof=1)*np.sqrt(252),Calmar=cagr/mdd if mdd else np.nan,
        MDD_pct=mdd,MDD_amount=-d.drawdown_amount.min(),trades=len(tr),win_rate=(tr.pnl>0).mean(),profit_factor=gain/loss if loss else np.nan,
        net_pnl=d.pnl.sum(),final_equity=equity,gross_pnl=d.gross_pnl.sum(),cost_total=d.cost.sum(),rolls=int(d['roll'].sum()),capital_skips=int(d.capital_skip.sum()),
        longest_drawdown_trading_days=longest,longest_drawdown_calendar_days=cal,exposure_days=int((d.position_after!=0).sum()))
    d.to_csv(OUT/f'{c["code"]}_daily.csv',index=False,encoding='utf-8-sig');ev.to_csv(OUT/f'{c["code"]}_events.csv',index=False,encoding='utf-8-sig');tr.to_csv(OUT/f'{c["code"]}_trades.csv',index=False,encoding='utf-8-sig')
    seg.to_csv(OUT/f'{c["code"]}_contract_segments.csv',index=False,encoding='utf-8-sig')
    annual=[]
    for year,g in d.groupby(d.date.dt.year):annual.append(dict(code=c['code'],year=year,net_pnl=g.pnl.sum(),annual_return=g.equity.iloc[-1]/(g.equity.iloc[0]-g.pnl.iloc[0])-1))
    return m,pd.DataFrame(annual)



# 重跑基準並以它的提前轉倉路徑安排策略持有契約；不是讀取預先算好的基準損益。
main=p[p.date.between(START,END)].copy()
bh,events,contract_trades=benchmark(main)
schedule=bh.set_index('date')
target=x.buy_condition.astype(int).shift(1).reindex(main_dates)
c=dict(code='V04',group='法人交易強度',name='法人交易強度20日＋價格趨勢',rule='強度MA20>0且近月收盤>價格MA20；隔日開盤多單/空手',initial=False,target=target)
m,ann=run(c)
strategy_daily=pd.read_csv(OUT/'V04_daily.csv',parse_dates=['date','signal_date'])
strategy_trades=pd.read_csv(OUT/'V04_trades.csv')
strategy_events=pd.read_csv(OUT/'V04_events.csv')
# 日末留倉日數為隔夜曝險日數；退出日開盤前也有曝險，另列完整交易次數。
m['annual_volatility']=strategy_daily.daily_return.std(ddof=1)*np.sqrt(252)
m.update(fee=strategy_daily.fee.sum(),tax=strategy_daily.tax.sum(),slippage_cost=strategy_daily.slippage_cost.sum())
mb=metrics(bh,contract_trades)
vm_daily,vm_summary=volatility_matched_benchmark(bh,m['annual_volatility'])
assert np.isclose(vm_summary['annual_volatility'],m['annual_volatility'],rtol=0,atol=1e-12)
vm_summary_df=pd.DataFrame([vm_summary])
comparison=pd.DataFrame([dict(m),dict(series='Buy-and-Hold近月多單',**mb)])
annual=[ann.assign(series='strategy')]
for year,z in bh.groupby(bh.date.dt.year):
    annual.append(pd.DataFrame([dict(series='benchmark',year=year,net_pnl=z.pnl.sum(),annual_return=z.equity.iloc[-1]/(z.equity.iloc[0]-z.pnl.iloc[0])-1)]))
annual=pd.concat(annual,ignore_index=True)
sens=[]
for slip in [1.,2.,4.]:
    SLIP=slip
    cc=dict(c,code=f'sensitivity_{int(slip)}')
    mm,_=run(cc);dd,ee,tt=benchmark(main,slip=slip)
    sens.extend([dict(mm,series='strategy',slippage_per_leg=slip),dict(series='benchmark',slippage_per_leg=slip,**metrics(dd,tt))])
SLIP=2.
sensitivity=pd.DataFrame(sens)
# 消融只作事後描述：分別移除籌碼或價格條件，沒有據此改動主策略。
ablation=[]
for code,name,condition in [('flow_only','交易強度20日單獨',x.intensity_ma20>0),('price_only','價格20日趨勢單獨',x.close>x.price_ma20)]:
    mm,_=run(dict(c,code=code,name=name,target=condition.astype(int).shift(1).reindex(main_dates)));ablation.append(mm)
ablation=pd.DataFrame(ablation)
splits=[]
for name,df in [('strategy',strategy_daily),('benchmark',bh)]:
    for label,mask in [('2018–2022',df.date.dt.year<=2022),('2023–2026',df.date.dt.year>=2023)]:
        z=df[mask];splits.append(dict(series=name,period=label,net_pnl=z.pnl.sum(),Sharpe=z.daily_return.mean()/z.daily_return.std(ddof=1)*np.sqrt(252)))
splits=pd.DataFrame(splits)
# 將前一日特徵附在交易日底稿，方便逐筆核對訊號時序。
features=x[['institution_net_trade_qty','institution_total_trade_qty','trade_intensity','intensity_ma20','close','price_ma20','buy_condition']].reset_index()
features=features.rename(columns={'date':'signal_date','close':'signal_close'})
strategy_daily=strategy_daily.merge(features,on='signal_date',how='left')
assert (strategy_daily.target==strategy_daily.buy_condition.astype(int)).all()
assert np.isclose(m['net_pnl'],3277536.576) and np.isclose(m['Sharpe'],1.3020005980912697)
assert np.isclose(mb['net_pnl'],8268352.664)
frames={'metrics_comparison':comparison,'strategy_daily':strategy_daily,'strategy_trades':strategy_trades,
    'strategy_events':strategy_events,'strategy_contract_segments':pd.read_csv(OUT/'V04_contract_segments.csv'),
    'benchmark_daily':bh,'benchmark_events':events,'benchmark_contract_trades':contract_trades,
    'volatility_matched_benchmark_summary':vm_summary_df,'volatility_matched_benchmark_daily':vm_daily,
    'annual_results':annual,'cost_sensitivity':sensitivity,'ablation':ablation,'descriptive_time_splits':splits,'indicator_features':x.reset_index()}
for name,df in frames.items():df.to_csv(OUT/(name+'.csv'),index=False,encoding='utf-8-sig')
buf=io.BytesIO()
with pd.ExcelWriter(buf,engine='openpyxl') as w:
    labels=['指標比較','策略逐日含昨日訊號','策略完整交易','策略成交與轉倉','策略契約段損益','基準逐日','基準成交與轉倉','基準契約段損益','波動配平基準_摘要','波動配平基準_逐日','年度結果','滑價敏感度','條件消融_事後診斷','時間分組_非樣本外','全部指標特徵']
    for (name,df),label in zip(frames.items(),labels):
        df.to_excel(w,sheet_name=label,index=False);ws=w.sheets[label];ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=max(14,min(34,len(str(col[0].value))+2))
    pd.read_csv(BASE/'source_audits/all_18_exploratory_candidates.csv').to_excel(w,sheet_name='先前18候選_選擇紀錄',index=False)
payload=buf.getvalue()
with zipfile.ZipFile(io.BytesIO(payload)) as z:assert z.testzip() is None
(BASE/'TX_flow_trend_workbook.xlsx').write_bytes(payload)
validation=dict(period=[str(START.date()),str(END.date())],days=len(main),selected_from_prior_18_candidates=True,
    independent_out_of_sample=False,all_strategy_and_benchmark_pnl_reconciled=True,signal_dates_before_execution=True,
    first_strategy_overnight_days=m['exposure_days'],strategy_trades=m['trades'],strategy_rolls=m['rolls'],benchmark_rolls=int(bh['roll'].sum()),
    parameters=dict(capital=CAPITAL,multiplier=MULT,fee_per_leg=FEE,tax_rate=TAX,slippage_per_leg=SLIP,intensity_window=20,price_window=20),
    python=platform.python_version(),pandas=pd.__version__,input_sha256={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in (BASE/'input').glob('*.csv')})
(OUT/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2))
final_verification=dict(
    strategy=dict(days=len(strategy_daily),executions=len(strategy_events),net_pnl=float(m['net_pnl']),final_equity=float(m['final_equity'])),
    benchmark=dict(days=len(bh),executions=len(events),net_pnl=float(mb['net_pnl']),final_equity=float(mb['final_equity'])),
    volatility_matched_benchmark=dict(days=len(vm_daily),position_equivalent=float(vm_summary['position_equivalent']),
        annual_volatility=float(vm_summary['annual_volatility']),target_annual_volatility=float(vm_summary['target_annual_volatility']),
        final_equity=float(vm_summary['final_equity']),directly_tradable=False))
(OUT/'final_verification.json').write_text(json.dumps(final_verification,ensure_ascii=False,indent=2))
print(comparison[['series','cumulative_return','CAGR','Sharpe','Calmar','MDD_pct','MDD_amount','trades','win_rate','profit_factor','cost_total']].to_string(index=False))
print('波動配平診斷：',vm_summary_df[['position_equivalent','annual_volatility','CAGR','Sharpe','Calmar','MDD_pct','cost_total']].to_string(index=False))
print('消融診斷：',ablation[['series','Sharpe','cumulative_return','MDD_pct']].to_string(index=False))

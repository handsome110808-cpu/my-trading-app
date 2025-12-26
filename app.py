import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import datetime
import time
import pytz
import json
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. 網頁設定 ---
st.set_page_config(
    page_title="AlphaTrader - AI 量化交易終端",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. 自定義 CSS ---
st.markdown("""
<style>
    .control-panel { background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 1px solid #ddd; margin-bottom: 20px; }
    .metric-card { background-color: #f0f2f6; border-radius: 10px; padding: 15px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
    div.stButton > button { height: 3em; width: 100%; }
    .countdown-box { position: fixed; bottom: 10px; right: 10px; background-color: #ffffff; border: 1px solid #ddd; padding: 5px 10px; border-radius: 5px; font-size: 12px; color: #666; z-index: 999; }
    .snapshot-badge { background-color: #e3f2fd; color: #1565c0; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; border: 1px solid #bbdefb; }
    
    /* 分析報告樣式 */
    .analysis-box { background-color: #ffffff; padding: 20px; border-radius: 10px; border: 1px solid #e0e0e0; margin-bottom: 20px; }
    .trend-bull { color: #00c853; font-weight: bold; }
    .trend-bear { color: #d50000; font-weight: bold; }
    .trend-neutral { color: #ffab00; font-weight: bold; }
    .factor-row { margin-bottom: 8px; border-bottom: 1px solid #eee; padding-bottom: 8px; }
    
    /* 總表樣式優化 */
    .summary-header { font-size: 20px; font-weight: bold; margin-bottom: 10px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# --- 3. 全域設定與快照功能 ---
SNAPSHOT_FILE = 'options_history.json'
TARGET_TICKERS = sorted([
    "AAPL", "AMD", "APP", "ASML", "AVGO", "GOOG", "HIMS", "INTC",
    "LLY", "LRCX", "MSFT", "MU", "NBIS", "NVDA", "ORCL", "PLTR",
    "QQQ", "SPY", "XLV", "TEM", "TSLA", "TSM"
])

def load_snapshot(ticker):
    if not os.path.exists(SNAPSHOT_FILE): return None
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            data = json.load(f)
        return data.get(ticker)
    except: return None

def save_snapshot(ticker, price, pc_data):
    record = {
        "date": datetime.datetime.now().strftime('%Y-%m-%d'),
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "close_price": price,
        "pc_data": pc_data
    }
    all_data = {}
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f: all_data = json.load(f)
        except: pass
    all_data[ticker] = record
    with open(SNAPSHOT_FILE, 'w') as f: json.dump(all_data, f, indent=4)
    return True

# --- 4. 核心運算邏輯 ---
def calculate_technical_indicators(df, atr_mult):
    """共用的技術指標與訊號計算邏輯"""
    if len(df) < 50: return df, "數據不足"
    df = df.ffill()

    # 計算指標
    df['EMA_8'] = ta.ema(df['Close'], length=8)
    df['EMA_21'] = ta.ema(df['Close'], length=21)
    
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        cols_map = {
            df.columns[-3]: 'MACD_Line', 
            df.columns[-2]: 'MACD_Hist', 
            df.columns[-1]: 'MACD_Signal'
        }
        df.rename(columns=cols_map, inplace=True)

    df['Vol_SMA_10'] = ta.sma(df['Volume'], length=10)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    df['RSI'] = ta.rsi(df['Close'], length=14)
    df['Stop_Loss'] = df['Close'] - (df['ATR'] * atr_mult)

    # 訊號判定邏輯 (對應三種狀態)
    # 強力多頭 (BUY)
    conditions = [
        (df['Close'] > df['EMA_8']) & 
        (df['EMA_8'] > df['EMA_21']) & 
        (df['MACD_Hist'] > 0) & 
        (df['MACD_Hist'] > df['MACD_Hist'].shift(1)) & 
        (df['Volume'] > df['Vol_SMA_10'] * 1.2)
    ]
    df['Signal'] = np.select(conditions, ['強力多頭'], default='震盪')
    
    # 強力空頭 (SELL)
    sell_cond = (df['Close'] < df['EMA_21']) | (df['MACD_Hist'] < 0)
    df.loc[sell_cond, 'Signal'] = '強力空頭'
    
    return df, None

@st.cache_data(ttl=60)
def get_signal(ticker, atr_mult):
    try:
        df = yf.download(ticker, period="6mo", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        if len(df) > 0:
            last_row = df.iloc[-1]
            if pd.isna(last_row['Close']) or pd.isna(last_row['Open']): df = df.iloc[:-1]

        df, err = calculate_technical_indicators(df, atr_mult)
        if err: return None, err
        return df, None
    except Exception as e: return None, str(e)

@st.cache_data(ttl=60)
def scan_market_summary(tickers, atr_mult):
    """批次掃描全市場訊號"""
    # 儲存結構改為存放詳細資訊的列表
    summary = {"強力多頭": [], "震盪": [], "強力空頭": []}
    
    try:
        # 批次下載
        data = yf.download(tickers, period="3mo", group_by='ticker', progress=False, threads=True)
        
        for ticker in tickers:
            try:
                df_t = data[ticker].copy()
                if len(df_t) > 0:
                    if pd.isna(df_t.iloc[-1]['Close']): df_t = df_t.iloc[:-1]
                if df_t.empty: continue
                
                # 計算訊號
                df_t, err = calculate_technical_indicators(df_t, atr_mult)
                if err: continue
                
                last_row = df_t.iloc[-1]
                last_sig = last_row['Signal']
                
                # 準備顯示字串：代碼 + 價格 + 漲跌
                prev_close = df_t.iloc[-2]['Close']
                pct_chg = ((last_row['Close'] - prev_close) / prev_close) * 100
                display_str = f"{ticker} (${last_row['Close']:.2f} | {pct_chg:+.2f}%)"
                
                # 分類
                if last_sig in summary:
                    summary[last_sig].append(display_str)
                else:
                    summary["震盪"].append(display_str) # 預設
                    
            except: continue
    except Exception as e: return None
    return summary

@st.cache_data(ttl=300)
def get_advanced_pc_ratio(ticker, current_price):
    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations: return None, "無期權數據"
        today = datetime.date.today()
        valid_dates = []
        for date_str in expirations:
            try:
                exp_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                if 0 <= (exp_date - today).days <= 40: valid_dates.append(date_str)
            except: continue
        if not valid_dates: return None, "無 40 日內到期合約"

        total_call_vol = 0; total_put_vol = 0; details = []
        for date in valid_dates:
            try:
                opt = tk.option_chain(date)
                calls, puts = opt.calls, opt.puts
                if calls is None or puts is None or calls.empty or puts.empty: continue
                
                center_idx_c = (np.abs(calls['strike'] - current_price)).argmin()
                c_vol = calls.iloc[max(0,center_idx_c-5):min(len(calls),center_idx_c+6)]['volume'].fillna(0).sum()
                
                center_idx_p = (np.abs(puts['strike'] - current_price)).argmin()
                p_vol = puts.iloc[max(0,center_idx_p-5):min(len(puts),center_idx_p+6)]['volume'].fillna(0).sum()

                total_call_vol += c_vol; total_put_vol += p_vol
                details.append({"到期日": date, "Call": int(c_vol), "Put": int(p_vol)})
            except: continue
        
        ratio = total_put_vol / total_call_vol if total_call_vol > 0 else 2.0
        return {"ratio": ratio, "total_call": total_call_vol, "total_put": total_put_vol, "details": details}, None
    except Exception as e: return None, str(e)

# --- 綜合趨勢分析邏輯 ---
def get_comprehensive_analysis(row, prev_row, pc_data):
    analysis_report = []
    bull_score = 0
    bear_score = 0
    
    # 1. 均線分析
    if row['Close'] > row['EMA_8'] > row['EMA_21']:
        analysis_report.append(("均線系統", "多頭", "收盤價站上短長均線，呈現多頭排列發散。", 1))
        bull_score += 1
    elif row['Close'] < row['EMA_21']:
        analysis_report.append(("均線系統", "空頭", "收盤價跌破長期均線 (EMA21)，趨勢轉弱。", -1))
        bear_score += 1
    else:
        analysis_report.append(("均線系統", "中性", "價格介於均線之間，震盪整理中。", 0))

    # 2. MACD 分析
    if row['MACD_Hist'] > 0:
        if row['MACD_Hist'] > prev_row['MACD_Hist']:
            analysis_report.append(("MACD 動能", "多頭", "紅柱持續放大，上漲動能強勁。", 1))
            bull_score += 1
        else:
            analysis_report.append(("MACD 動能", "中性", "紅柱收斂，漲勢可能放緩。", 0))
    else:
        analysis_report.append(("MACD 動能", "空頭", "綠柱空方控盤，動能偏弱。", -1))
        bear_score += 1

    # 3. RSI 分析
    rsi = row['RSI']
    if rsi > 50:
        if rsi > 70:
            analysis_report.append(("RSI 指標", "強勢/過熱", f"RSI 為 {rsi:.1f}，進入超買區，需留意回調風險。", 0.5))
            bull_score += 0.5
        else:
            analysis_report.append(("RSI 指標", "多頭", f"RSI 為 {rsi:.1f}，位於多方強勢區。", 1))
            bull_score += 1
    else:
        if rsi < 30:
            analysis_report.append(("RSI 指標", "超賣", f"RSI 為 {rsi:.1f}，進入超賣區，可能醞釀反彈。", -0.5))
            bear_score += 0.5
        else:
            analysis_report.append(("RSI 指標", "空頭", f"RSI 為 {rsi:.1f}，位於弱勢區。", -1))
            bear_score += 1

    # 4. 量價分析
    vol_ratio = row['Volume'] / row['Vol_SMA_10']
    if row['Close'] > row['Open']:
        if vol_ratio > 1.2:
            analysis_report.append(("量價關係", "多頭", f"出量上漲 (量比 {vol_ratio:.1f}x)，攻擊量能充足。", 1))
            bull_score += 1
        elif vol_ratio < 0.8:
            analysis_report.append(("量價關係", "中性", "價漲量縮，追價意願不足。", 0))
    else:
        if vol_ratio > 1.2:
            analysis_report.append(("量價關係", "空頭", f"出量下跌 (量比 {vol_ratio:.1f}x)，賣壓沈重。", -1))
            bear_score += 1
    
    # 5. 期權 P/C Ratio 分析
    if pc_data:
        ratio = pc_data['ratio']
        if ratio < 0.7:
            analysis_report.append(("期權籌碼", "多頭", f"P/C Ratio ({ratio:.2f}) 偏低，市場看多情緒濃厚。", 1))
            bull_score += 1
        elif ratio > 1.1:
            analysis_report.append(("期權籌碼", "空頭", f"P/C Ratio ({ratio:.2f}) 偏高，市場避險情緒上升。", -1))
            bear_score += 1
        else:
            analysis_report.append(("期權籌碼", "中性", f"P/C Ratio ({ratio:.2f}) 位於正常區間。", 0))

    total_score = bull_score - bear_score
    if total_score >= 2.5: sentiment = "🚀 強力多頭"
    elif total_score >= 1: sentiment = "📈 偏多震盪"
    elif total_score <= -2.5: sentiment = "🩸 強力空頭"
    elif total_score <= -1: sentiment = "📉 偏空震盪"
    else: sentiment = "⚖️ 多空平衡"
    
    return sentiment, analysis_report

# --- 5. 介面佈局 ---
st.title("AlphaTrader 量化終端")

# 時間與存檔檢查
est = pytz.timezone('US/Eastern')
now_est = datetime.datetime.now(est)
is_market_open = (now_est.weekday() < 5) and (9 <= now_est.hour < 16) or (now_est.hour == 16 and now_est.minute == 0)
is_closing_window = (now_est.hour == 15 and now_est.minute >= 55)

with st.container():
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.5, 1.5, 1])
    with c1:
        selected_ticker = st.selectbox("美股標的", TARGET_TICKERS, index=TARGET_TICKERS.index('TSLA') if 'TSLA' in TARGET_TICKERS else 0)
    with c2:
        atr_multiplier = st.slider("ATR 止損乘數", 1.5, 4.0, 2.5, 0.1)
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        auto_refresh = st.checkbox("每分刷新", value=True)
        if st.button("🔄 刷新"): st.rerun()
        
    time_str = now_est.strftime('%H:%M EST')
    if is_closing_window: st.caption(f"⚡ 收盤前黃金時段 ({time_str}) - 系統將自動存檔")
    elif not is_market_open: st.caption(f"🌑 非交易時段 ({time_str}) - 載入參考資料中...")
    else: st.caption(f"🟢 盤中即時 ({time_str})")
    st.markdown('</div>', unsafe_allow_html=True)

# === A. 單一股票詳細分析 ===
df, error = get_signal(selected_ticker, atr_multiplier)

if error:
    st.error(f"錯誤: {error}")
else:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    # 更新 Signal 顯示文字
    signal = last['Signal']
    
    # 期權與存檔邏輯
    pc_data, pc_error = get_advanced_pc_ratio(selected_ticker, last['Close'])
    data_source_badge = ""
    
    if is_closing_window and pc_data:
        saved = load_snapshot(selected_ticker)
        if not saved or saved.get('date') != now_est.strftime('%Y-%m-%d'):
            save_snapshot(selected_ticker, last['Close'], pc_data)
            st.toast(f"✅ {selected_ticker} 已自動存檔", icon="💾")

    if not pc_data: 
        snap = load_snapshot(selected_ticker)
        if snap:
            pc_data = snap['pc_data']
            data_source_badge = f'<span class="snapshot-badge">📁 歷史快照 ({snap.get("date")})</span>'

    sentiment, analysis_report = get_comprehensive_analysis(last, prev, pc_data)

    # 頂部狀態
    if signal == '強力多頭': st.success(f"🔥 {selected_ticker} 訊號：強力多頭 (STRONG BUY)")
    elif signal == '強力空頭': st.error(f"🛑 {selected_ticker} 訊號：強力空頭 (STRONG SELL)")
    else: st.info(f"👀 {selected_ticker} 訊號：震盪整理 (OSCILLATION)")

    # KPI
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric("最新價格", f"${last['Close']:.2f}", f"{(last['Close']-prev['Close']):.2f}")
    with k2: st.metric("建議止損", f"${last['Stop_Loss']:.2f}")
    with k3: st.metric("風險/股", f"${(last['Close']-last['Stop_Loss']):.2f}")
    with k4:
        if pc_data:
            r = pc_data['ratio']
            lbl = "看多" if r < 0.7 else "看空" if r > 1.0 else "中性"
            st.metric("P/C Ratio", f"{r:.2f}", lbl, delta_color="inverse")
            if data_source_badge: st.markdown(data_source_badge, unsafe_allow_html=True)
        else: st.metric("P/C Ratio", "N/A", "無數據")

    st.markdown("---")
    
    # AI 分析區塊
    st.markdown("### 🤖 AI 多空趨勢深度解析")
    ana_col1, ana_col2 = st.columns([1, 2])
    with ana_col1:
        st.markdown(f"""
        <div class="analysis-box" style="text-align:center; height: 100%;">
            <h3 style="margin-bottom:0;">總結趨勢</h3>
            <h1 style="font-size: 3em; margin: 10px 0;">{sentiment.split(' ')[0]}</h1>
            <h4 style="color: #666;">{sentiment.split(' ')[1]}</h4>
            <hr>
            <p style="font-size: 0.9em; color: #888;">基於 期權、均線、MACD、RSI、量價 綜合運算</p>
        </div>
        """, unsafe_allow_html=True)
    with ana_col2:
        st.markdown('<div class="analysis-box">', unsafe_allow_html=True)
        for factor, trend, desc, score in analysis_report:
            if trend in ["多頭", "強勢/過熱"]: trend_cls = "trend-bull"
            elif trend in ["空頭", "超賣"]: trend_cls = "trend-bear"
            else: trend_cls = "trend-neutral"
            icon = "🟢" if score > 0 else "🔴" if score < 0 else "⚪"
            st.markdown(f'<div class="factor-row"><strong>{icon} {factor}</strong> <span class="{trend_cls}">[{trend}]</span> : {desc}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")

    # 圖表
    main_col, side_col = st.columns([2, 1])
    with main_col:
        st.subheader("📈 技術走勢")
        st.line_chart(df[['Close', 'EMA_8', 'EMA_21']].tail(60), color=["#000000", "#00ff00", "#ff0000"])
    with side_col:
        st.subheader("📊 籌碼分析")
        if pc_data:
            tot = pc_data['total_call'] + pc_data['total_put']
            c_p = (pc_data['total_call']/tot)*100 if tot>0 else 0
            p_p = (pc_data['total_put']/tot)*100 if tot>0 else 0
            st.caption("40日內，現價上下5檔")
            st.progress(int(c_p), text=f"Call: {int(pc_data['total_call']):,}")
            st.progress(int(p_p), text=f"Put: {int(pc_data['total_put']):,}")
            st.dataframe(pd.DataFrame(pc_data['details']).head(3), hide_index=True, use_container_width=True)
        else: st.warning("無資料")

    # 歷史數據
    with st.expander("查看技術數據"):
        cols_to_show = ['Close', 'Volume', 'EMA_8', 'EMA_21', 'MACD_Hist', 'RSI', 'Signal', 'Stop_Loss']
        format_dict = {'Close': '{:.2f}', 'Volume': '{:.0f}', 'EMA_8': '{:.2f}', 'EMA_21': '{:.2f}', 'MACD_Hist': '{:.2f}', 'RSI': '{:.1f}', 'Stop_Loss': '{:.2f}'}
        st.dataframe(df[cols_to_show].tail(5).style.format(format_dict))

# === B. 全市場選股濾網 (Market Screener) ===
st.markdown("---")
st.subheader("🌍 全市場戰情選股 (Market Screener)")

with st.spinner("正在掃描全市場訊號..."):
    market_signals = scan_market_summary(TARGET_TICKERS, atr_multiplier)

if market_signals:
    # 建立選股濾網 UI
    filter_option = st.selectbox(
        "🔍 選擇市場狀態進行篩選：",
        ["全部顯示 (All)", "強力多頭 (Strong Bull)", "震盪 (Oscillation)", "強力空頭 (Strong Bear)"]
    )
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 根據選擇顯示結果
    if filter_option == "全部顯示 (All)":
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"🐂 強力多頭 ({len(market_signals['強力多頭'])})")
            for item in market_signals['強力多頭']: st.write(item)
        with col2:
            st.warning(f"⚖️ 震盪整理 ({len(market_signals['震盪'])})")
            for item in market_signals['震盪']: st.write(item)
        with col3:
            st.error(f"🐻 強力空頭 ({len(market_signals['強力空頭'])})")
            for item in market_signals['強力空頭']: st.write(item)
            
    elif filter_option == "強力多頭 (Strong Bull)":
        st.success(f"🐂 目前符合「強力多頭」條件的股票 ({len(market_signals['強力多頭'])})：")
        if market_signals['強力多頭']:
            # 轉成 DataFrame 顯示更漂亮
            df_bull = pd.DataFrame(market_signals['強力多頭'], columns=["股票代碼 / 價格"])
            st.dataframe(df_bull, use_container_width=True, hide_index=True)
        else:
            st.write("目前無符合標的。")
            
    elif filter_option == "震盪 (Oscillation)":
        st.warning(f"⚖️ 目前處於「震盪整理」的股票 ({len(market_signals['震盪'])})：")
        if market_signals['震盪']:
            df_osc = pd.DataFrame(market_signals['震盪'], columns=["股票代碼 / 價格"])
            st.dataframe(df_osc, use_container_width=True, hide_index=True)
        else:
            st.write("目前無符合標的。")
            
    elif filter_option == "強力空頭 (Strong Bear)":
        st.error(f"🐻 目前符合「強力空頭」條件的股票 ({len(market_signals['強力空頭'])})：")
        if market_signals['強力空頭']:
            df_bear = pd.DataFrame(market_signals['強力空頭'], columns=["股票代碼 / 價格"])
            st.dataframe(df_bear, use_container_width=True, hide_index=True)
        else:
            st.write("目前無符合標的。")

else:
    st.error("無法取得市場總覽數據")

# 自動刷新
if auto_refresh:
    placeholder = st.empty()
    for s in range(60, 0, -1):
        now_str = datetime.datetime.now(est).strftime('%H:%M:%S')
        placeholder.markdown(f'<div class="countdown-box">🕒 {now_str} | ⏳ {s}s 刷新</div>', unsafe_allow_html=True)
        time.sleep(1)
    placeholder.empty()
    st.rerun()

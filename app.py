import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import io
import os
import json
import time
import requests
import xlrd
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')

# ===== 1. 初期設定 =====
st.set_page_config(
    page_title="デマーシア！！！",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== 2. スタイル設定と色定義 =====
def get_score_color(score):
    if score >= 80:
        return "#00d084"
    elif score >= 50:
        return "#ff9900"
    else:
        return "#ff0000"

st.markdown("""
    <style>
        .header-title {
            text-align: center; font-size: 2.5em; font-weight: bold;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px;
        }
        .positive { color: #00d084; font-weight: bold; }
        .negative { color: #ff0000; font-weight: bold; }
        .neutral  { color: #ff9900; font-weight: bold; }
        .detail-card { background:rgba(102,126,234,0.08); border:1px solid rgba(102,126,234,0.3); border-radius:12px; padding:20px; margin-bottom:16px; }
        .kpi-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:12px; margin-top:12px; }
        .kpi-box  { background:rgba(255,255,255,0.05); border:1px solid rgba(128,128,128,0.2); border-radius:8px; padding:12px; text-align:center; }
        .kpi-label { font-size:0.75em; color:#aaa; margin-bottom:4px; }
        .kpi-value { font-size:1.15em; font-weight:700; }
        @media (max-width:768px) {
            .block-container { padding-left:8px !important; padding-right:8px !important; }
            .kpi-grid { grid-template-columns:repeat(2,1fr); }
        }
    </style>
""", unsafe_allow_html=True)

# ===== 3. セクター日本語マッピング =====
SECTOR_MAPPING = {
    'Technology': 'テクノロジー（IT・半導体）',
    'Financial Services': '金融（銀行・保険）',
    'Consumer Cyclical': '景気敏感消費財（自動車・アパレル等）',
    'Healthcare': '医療・ヘルスケア',
    'Industrials': '工業・製造業',
    'Communication Services': '通信・メディア',
    'Energy': 'エネルギー（石油・電力）',
    'Real Estate': '不動産',
    'Utilities': 'インフラ・公共',
    'Consumer Defensive': '生活必需品',
    'Materials': '素材・鉱物',
    'Financial': '金融',
    'Information Technology': 'テクノロジー（IT・半導体）',
    'Consumer': '消費者向け',
    None: '未分類',
    'nan': '未分類'
}

def get_sector_jp(sector):
    if pd.isna(sector) or sector is None:
        return '未分類'
    return SECTOR_MAPPING.get(str(sector).strip(), str(sector).strip())

# ===== 4. サンプルデータセット =====
SAMPLE_STOCKS_JP = [
    '7203','9432','8306','9101','8058','8001','8031','8015',
    '6902','6954','9984','9983','7974','6758','6861',
    '6952','8316','6501','5401','6503',
]
SAMPLE_STOCKS_US = [
    'AAPL','MSFT','GOOG','AMZN','NVDA','TSLA','META','NFLX',
    'ADBE','CRM','ORCL','IBM','INTC','JNJ','PG',
    'KO','PFE','V','MA','DIS',
]

TICKER_CACHE_DIR = os.path.dirname(__file__)
JP_TICKERS_PATH = os.path.join(TICKER_CACHE_DIR, 'tickers_jp.json')
US_TICKERS_PATH = os.path.join(TICKER_CACHE_DIR, 'tickers_us.json')
JPX_TICKER_LIST_URL = 'https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls'
NASDAQ_API_URL = 'https://api.nasdaq.com/api/screener/stocks?tableonly=true&exchange={exchange}&limit=9999'

# 為替レートキャッシュの有効期限（秒）
EXCHANGE_RATE_TTL = 300  # 5分

# ===== 5. ファイル入出力ユーティリティ =====
FAVORITES_PATH = os.path.join(os.path.dirname(__file__), 'favorites.json')

def load_favorites():
    try:
        if os.path.exists(FAVORITES_PATH):
            with open(FAVORITES_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []

def save_favorites(favorites):
    try:
        with open(FAVORITES_PATH, 'w', encoding='utf-8') as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def save_ticker_cache(path, tickers):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(tickers, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_ticker_cache(path):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []

def fetch_jp_ticker_list():
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(JPX_TICKER_LIST_URL, headers=headers, timeout=30)
        response.raise_for_status()
        workbook = xlrd.open_workbook(file_contents=response.content, encoding_override='cp932')
        sheet = workbook.sheet_by_index(0)
        tickers = []
        for row_idx in range(1, sheet.nrows):
            raw_value = sheet.cell_value(row_idx, 1)
            if raw_value is None:
                continue
            code = str(raw_value).strip()
            if code.endswith('.0'):
                code = code[:-2]
            if code:
                tickers.append(code)
        return sorted(set(tickers))
    except Exception as e:
        st.warning(f"⚠️ 日本株の銘柄リスト取得に失敗しました: {str(e)}")
        return []

def fetch_us_ticker_list():
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        exchanges = ['NASDAQ', 'NYSE', 'AMEX']
        tickers = []
        for exchange in exchanges:
            response = requests.get(NASDAQ_API_URL.format(exchange=exchange), headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            rows = data.get('data', {}).get('table', {}).get('rows', [])
            tickers.extend([row.get('symbol') for row in rows if row.get('symbol')])
        return sorted(set(tickers))
    except Exception as e:
        st.warning(f"⚠️ 米国株の銘柄リスト取得に失敗しました: {str(e)}")
        return []

def get_market_tickers(market_mode):
    if market_mode == '日本株':
        path, loader, fallback = JP_TICKERS_PATH, fetch_jp_ticker_list, SAMPLE_STOCKS_JP
    else:
        path, loader, fallback = US_TICKERS_PATH, fetch_us_ticker_list, SAMPLE_STOCKS_US

    tickers = load_ticker_cache(path)
    if tickers:
        return tickers
    tickers = loader()
    if tickers:
        save_ticker_cache(path, tickers)
        return tickers
    return fallback

# ===== 6. セッションステート初期化 =====
_session_defaults = {
    'favorites': None,
    'market_mode': '日本株',
    'preset_selected': None,
    'selected_ticker': None,
    'per_max': 20.0,
    'universe_count': 0,
    'full_market_mode': False,
    'max_tickers': 100,
    'pbr_max': 2.0,
    'dividend_min': 2.0,
    'market_cap_min': 10.0,
    'revenue_growth_min': 0.0,
    'per_check': True,
    'pbr_check': False,
    'div_check': False,
    'mcap_check': False,
    'revgrow_check': False,
    'sector_check': False,
    '_exchange_rate': None,
    '_exchange_rate_fetched_at': 0.0,
    '_stock_cache': {},
}
for key, default in _session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default

if st.session_state.favorites is None:
    st.session_state.favorites = load_favorites()

# ===== 7. 為替レート =====
def get_exchange_rate() -> float:
    now = time.time()
    cached_rate = st.session_state._exchange_rate
    fetched_at  = st.session_state._exchange_rate_fetched_at

    if cached_rate is not None and (now - fetched_at) < EXCHANGE_RATE_TTL:
        return cached_rate

    try:
        rate_data = yf.download('USDJPY=X', period='1d', progress=False)
        if len(rate_data) > 0:
            rate = float(rate_data['Close'].iloc[-1])
            st.session_state._exchange_rate = rate
            st.session_state._exchange_rate_fetched_at = now
            return rate
    except Exception:
        pass

    if cached_rate is not None:
        return cached_rate
    st.session_state._exchange_rate = 150.0
    st.session_state._exchange_rate_fetched_at = now
    return 150.0

# ===== 8. ユーティリティ関数 =====
def safe_get(value, default='-'):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    return value

def format_price_jp(price, is_us=False, exchange_rate=None):
    if price is None or (isinstance(price, float) and np.isnan(price)):
        return '-'
    if is_us and exchange_rate:
        jpy = price * exchange_rate
        return f"${price:.2f}（≈ ¥{jpy:,.0f}）"
    return f"¥{price:,.0f}"

def format_market_cap(market_cap, is_us=False, exchange_rate=None):
    if market_cap is None or (isinstance(market_cap, float) and np.isnan(market_cap)):
        return '-'
    if is_us and exchange_rate:
        jpy = market_cap * exchange_rate
        if market_cap >= 1e9:
            return f"${market_cap/1e9:.1f}B（≈ ¥{jpy/1e12:.1f}兆）"
        return f"${market_cap/1e6:.0f}M（≈ ¥{jpy/1e9:.0f}B）"
    if market_cap >= 1e12:
        return f"¥{market_cap/1e12:.1f}兆"
    return f"¥{market_cap/1e9:.0f}B"

# ===== 9. データ取得 =====
def normalize_ticker_for_yfinance(ticker: str):
    ticker = str(ticker).strip()
    if ticker.isdigit():
        return ticker, f"{ticker}.T"
    normalized = ticker.upper()
    if normalized.endswith('.T'):
        return normalized[:-2], normalized
    return normalized, normalized

def _to_float(val, default=np.nan):
    if val is None:
        return default
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default

def _is_etf(info: dict) -> bool:
    qt = str(info.get('quoteType', '')).upper()
    if qt in ('ETF', 'MUTUALFUND', 'INDEX'):
        return True
    name = str(info.get('longName', '') or info.get('shortName', '')).lower()
    etf_keywords = ('etf', 'fund', 'index', 'topix', 'nikkei', 'trust', 'listed index')
    return any(k in name for k in etf_keywords)

def build_stock_data(ticker, info, stock_obj=None):
    if not info:
        return None

    is_etf = _is_etf(info)

    div_raw = _to_float(info.get('dividendYield') or info.get('yield'), 0.0)
    div_yield = div_raw * 100 if 0 <= div_raw <= 1 else div_raw

    rev_growth = np.nan
    if not is_etf:
        rg = _to_float(info.get('revenueGrowth'))
        if not np.isnan(rg):
            rev_growth = rg * 100 if -1 <= rg <= 10 else rg

    price = _to_float(
        info.get('currentPrice')
        or info.get('regularMarketPrice')
        or info.get('previousClose')
        or info.get('navPrice')
    )

    per = _to_float(info.get('trailingPE') or info.get('forwardPE') if not is_etf else None)
    pbr = _to_float(info.get('priceToBook') if not is_etf else None)

    mcap = _to_float(
        info.get('marketCap')
        or info.get('totalAssets')
    )

    sector_raw = info.get('sector') or info.get('fundFamily') or ('ETF' if is_etf else None)
    sector = get_sector_jp(sector_raw) if not is_etf else 'ETF・ファンド'

    return {
        'ticker': ticker,
        'name': info.get('longName') or info.get('shortName') or '不明',
        'sector': sector,
        'is_etf': is_etf,
        'price': price,
        'per': per,
        'pbr': pbr,
        'dividend_yield': div_yield,
        'market_cap': mcap,
        'revenue_growth': rev_growth,
        'stock_obj': stock_obj,
    }

def _session_cache_get(ticker: str):
    return st.session_state._stock_cache.get(ticker)

def _session_cache_set(ticker: str, data):
    st.session_state._stock_cache[ticker] = data

def fetch_stock_data(ticker: str):
    ticker = str(ticker).strip()
    if not ticker:
        return None

    cached = _session_cache_get(ticker)
    if cached is not None:
        return cached

    try:
        _, yf_symbol = normalize_ticker_for_yfinance(ticker)
        stock = yf.Ticker(yf_symbol)
        info = None
        for attempt in range(3):
            try:
                info = stock.info
                if info:
                    break
            except Exception:
                if attempt < 2:
                    time.sleep(1.0 + attempt * 0.5)
                else:
                    raise

        if not info:
            raise ValueError('yfinanceから銘柄情報を取得できませんでした')

        result = build_stock_data(ticker, info, stock)
        if result:
            _session_cache_set(ticker, result)
        return result
    except Exception as e:
        st.warning(f"⚠️ {ticker}のデータ取得エラー: {str(e)}")
        return None

def _fetch_single(original_ticker: str, yf_symbol: str):
    try:
        stock = yf.Ticker(yf_symbol)
        info = stock.info
        if not info:
            return original_ticker, None
        return original_ticker, build_stock_data(original_ticker, info, stock)
    except Exception:
        return original_ticker, None

def fetch_stock_data_batch(tickers: list, market_mode=None, max_workers: int = 10):
    normalized_batch = [normalize_ticker_for_yfinance(t) for t in tickers]

    need_fetch = [
        (orig, yf_sym)
        for orig, yf_sym in normalized_batch
        if _session_cache_get(orig) is None
    ]

    if need_fetch:
        progress_bar = st.progress(0, text="銘柄データを並列取得中...")
        total = len(need_fetch)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_single, orig, yf_sym): orig
                for orig, yf_sym in need_fetch
            }
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                try:
                    orig_ticker, stock_data = future.result()
                    if stock_data:
                        _session_cache_set(orig_ticker, stock_data)
                except Exception:
                    pass
                progress_bar.progress(done_count / total, text=f"取得中… {done_count}/{total} 銘柄")

        progress_bar.empty()

    return [_session_cache_get(orig) for orig, _ in normalized_batch]

# ===== 10. スコアリング =====
def calculate_buy_timing_score(stock_data, market_mode):
    score = 0
    max_score = 0

    per = stock_data.get('per')
    if per and not np.isnan(per) and per > 0:
        benchmark_per = 15 if market_mode == '日本株' else 22
        ratio = per / benchmark_per
        per_score = max(0, min(30, 30 * (1 - ratio * 0.8) if ratio < 1 else 30 * (1 - ratio)))
        score += per_score
        max_score += 30

    pbr = stock_data.get('pbr')
    if pbr and not np.isnan(pbr) and pbr > 0:
        benchmark_pbr = 1.0 if market_mode == '日本株' else 4.0
        ratio = pbr / benchmark_pbr
        pbr_score = max(0, min(20, 20 * (1 - ratio * 0.6) if ratio < 1 else 20 * (1 - ratio * 0.5)))
        score += pbr_score
        max_score += 20

    div_yield = stock_data.get('dividend_yield', 0)
    if   div_yield >= 3.5: div_score = 20
    elif div_yield >= 2.0: div_score = 15
    elif div_yield >= 1.0: div_score = 10
    elif div_yield >  0  : div_score = 5
    else:                  div_score = 0
    score += div_score
    max_score += 20

    revenue_growth = stock_data.get('revenue_growth')
    growth_score   = 0
    if revenue_growth and not np.isnan(revenue_growth) and revenue_growth > 0:
        growth_score += min(15, revenue_growth * 5)
    
    # 満点を調整するため、売上成長率が正常に計算できる場合は最高30点（成長スコア単体で評価できるように補正）
    growth_score = min(30, max(0, growth_score * 2 if not np.isnan(revenue_growth) else 0))
    score += growth_score
    max_score += 30

    return round((score / max_score * 100) if max_score > 0 else 0, 1)

# ===== 11. スクリーニング =====
def apply_screening(stocks_data, filters, market_mode):
    results = []
    exchange_rate = get_exchange_rate() if market_mode == '米国株' else 1.0

    for stock in stocks_data:
        if stock is None:
            continue
        if filters['per_enabled']:
            per = stock.get('per')
            if per is None or np.isnan(per) or per > filters['per_max']:
                continue
        if filters['pbr_enabled']:
            pbr = stock.get('pbr')
            if pbr is None or np.isnan(pbr) or pbr > filters['pbr_max']:
                continue
        if filters['dividend_enabled']:
            div = stock.get('dividend_yield', 0)
            if div < filters['dividend_min']:
                continue
        if filters['market_cap_enabled']:
            mcap = stock.get('market_cap')
            threshold = filters['market_cap_min'] * 1e9
            if mcap is None or np.isnan(mcap) or mcap < threshold:
                continue
        if filters['revenue_growth_enabled']:
            rev = stock.get('revenue_growth')
            if rev is None or np.isnan(rev) or rev < filters['revenue_growth_min']:
                continue
        if filters['sector_enabled'] and filters['sectors']:
            if stock.get('sector') not in filters['sectors']:
                continue
        results.append(stock)

    return results, exchange_rate

# ===== 12. 詳細パネル（タブ分割） =====
def _render_tab_analysis(selected_stock, selected_code, market_mode, exchange_rate):
    score = calculate_buy_timing_score(selected_stock, market_mode)
    score_color = get_score_color(score)
    is_etf_flag = selected_stock.get('is_etf', False)
    is_us = market_mode == '米国株'

    stars = '★' * int(score // 20) + '☆' * (5 - int(score // 20))
    st.markdown(
        f"<div class='detail-card' style='border-color:{score_color};'>"
        f"<div style='display:flex;align-items:center;gap:20px;flex-wrap:wrap;'>"
        f"<div><div style='font-size:0.85em;color:#aaa;'>現在の買い時スコア</div>"
        f"<div style='font-size:2.8em;font-weight:900;color:{score_color};'>{score:.0f}<span style='font-size:0.45em;color:#aaa;'>/100</span></div>"
        f"<div style='font-size:1.2em;color:{score_color};'>{stars}</div></div>"
        f"<div style='flex:1;min-width:160px;'>"
        f"<div style='font-size:1.1em;font-weight:700;'>{selected_stock['name']}</div>"
        f"<div style='color:#aaa;font-size:0.85em;'>{selected_stock['ticker']} | {selected_stock['sector']}"
        + (" | <span style='background:#6c757d;color:white;padding:1px 6px;border-radius:4px;font-size:0.8em;'>ETF</span>" if is_etf_flag else "")
        + f"</div></div></div></div>",
        unsafe_allow_html=True
    )

    def _kpi(label, value, color=None):
        color_style = f"color:{color};" if color else ""
        return (
            f"<div class='kpi-box'>"
            f"<div class='kpi-label'>{label}</div>"
            f"<div class='kpi-value' style='{color_style}'>{value}</div>"
            f"</div>"
        )

    per_v = selected_stock.get('per')
    pbr_v = selected_stock.get('pbr')
    div_v = selected_stock.get('dividend_yield')
    rev_v = selected_stock.get('revenue_growth')

    na_label = '<span style="color:#888;font-size:0.8em;">ETF</span>' if is_etf_flag else '<span style="color:#888;">N/A</span>'

    per_str = f"{per_v:.1f}倍" if per_v and not np.isnan(per_v) else na_label
    pbr_str = f"{pbr_v:.2f}倍" if pbr_v and not np.isnan(pbr_v) else na_label
    div_str = f"{div_v:.2f}%" if div_v and div_v > 0 else '0% / なし'
    rev_str = f"{rev_v:+.1f}%" if rev_v and not np.isnan(rev_v) else na_label

    per_color = ('#00d084' if per_v and per_v < (15 if market_mode=='日本株' else 22) else '#ff9900') if per_v and not np.isnan(per_v) else None
    div_color = '#00d084' if div_v and div_v >= 3 else ('#ff9900' if div_v and div_v > 0 else None)
    rev_color = '#00d084' if rev_v and not np.isnan(rev_v) and rev_v >= 10 else ('#ff9900' if rev_v and not np.isnan(rev_v) and rev_v >= 0 else '#ff5555' if rev_v and not np.isnan(rev_v) else None)

    kpis = "".join([
        _kpi("現在の株価", format_price_jp(selected_stock['price'], is_us, exchange_rate)),
        _kpi("PER", per_str, per_color),
        _kpi("PBR", pbr_str),
        _kpi("配当利回り", div_str, div_color),
        _kpi("時価総額", format_market_cap(selected_stock['market_cap'], is_us, exchange_rate)),
        _kpi("売上成長率", rev_str, rev_color),
    ])
    st.markdown(f"<div class='kpi-grid'>{kpis}</div>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    if not is_etf_flag and per_v and not np.isnan(per_v):
        benchmark_per = 15 if market_mode == '日本株' else 22
        ratio = per_v / benchmark_per
        label = "割安 🟢" if ratio < 0.7 else ("適正 🟡" if ratio < 1.0 else "割高 🔴")
        st.markdown(f"**📊 PER 割安・割高メーター** — {label}")
        st.progress(min(max(ratio, 0.0), 1.0))
        st.caption(f"PER {per_v:.1f}倍 ÷ 基準値 {benchmark_per}倍 = {ratio:.2f}")

    st.markdown("**📈 株価推移（直近1年）**")
    _render_price_chart(selected_code)

def _render_price_chart(selected_code):
    with st.spinner("📉 チャートを取得中..."):
        try:
            chart_ticker = f"{selected_code}.T" if str(selected_code).isdigit() else str(selected_code).upper()
            hist = yf.download(
                chart_ticker,
                start=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
                end=datetime.now().strftime('%Y-%m-%d'),
                progress=False,
                interval='1d',
                auto_adjust=True
            )
            if hist is None or len(hist) == 0:
                hist = yf.Ticker(chart_ticker).history(period='1y', interval='1d', auto_adjust=True)

            close_series = _extract_close_series(hist)
            if close_series is not None and len(close_series) > 0:
                st.line_chart(pd.DataFrame(close_series.rename('Close')), use_container_width=True)
            else:
                st.warning("チャートデータが取得できませんでした")
        except Exception as e:
            st.warning(f"⚠️ チャート取得エラー: {str(e)}")

def _extract_close_series(hist):
    if hist is None or len(hist) == 0:
        return None
    try:
        if isinstance(hist.columns, pd.MultiIndex):
            for col in hist.columns:
                if 'Close' in col or 'Adj Close' in col:
                    s = pd.to_numeric(hist[col], errors='coerce').dropna()
                    if len(s) > 0:
                        return s
        for name in ['Close', 'Adj Close']:
            if name in hist.columns:
                s = pd.to_numeric(hist[name], errors='coerce').dropna()
                if len(s) > 0:
                    return s
        for col in hist.columns:
            s = pd.to_numeric(hist[col], errors='coerce').dropna()
            if len(s) > 0:
                return s
    except Exception:
        pass
    return None

def _render_tab_news(selected_stock):
    st.subheader(f"{selected_stock['name']} の最新ニュース")
    with st.spinner("📰 ニュースを取得中..."):
        try:
            stock_obj = selected_stock['stock_obj']
            news = stock_obj.news
            if not news:
                st.info("ℹ️ ニュース情報が取得できませんでした")
                return

            negative_words = ['減益','下落','Down','Drop','Loss','赤字','損失','破産','閉鎖']
            positive_words = ['増益','上昇','Up','Gain','Profit','高成長','買収','拡大']

            for item in news[:5]:
                title, link = '不明', '#'
                try:
                    if isinstance(item, dict):
                        content = item.get('content', {})
                        if isinstance(content, dict):
                            title = content.get('title', '不明')
                            ctu = content.get('clickThroughUrl', {})
                            if isinstance(ctu, dict):
                                link = ctu.get('url', '#')
                except Exception:
                    pass

                title_display = (
                    f"📰 <a href='{link}' target='_blank'>{title}</a>"
                    if link and link != '#'
                    else f"📰 {title}"
                )
                color = (
                    '#ff0000' if any(w in title for w in negative_words)
                    else '#00d084' if any(w in title for w in positive_words)
                    else 'inherit'
                )
                st.markdown(
                    f"<p style='color:{color};font-weight:bold;'>{title_display}</p>",
                    unsafe_allow_html=True
                )
        except Exception as e:
            st.error(f"❌ ニュース取得エラー: {str(e)}")

def _render_tab_favorites(selected_stock, selected_code, market_mode, exchange_rate, results):
    st.subheader("⭐ お気に入り銘柄")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💕 お気に入りに追加", use_container_width=True, key='add_favorite'):
            if selected_code not in st.session_state.favorites:
                st.session_state.favorites.append(selected_code)
                save_favorites(st.session_state.favorites)
                st.success(f"✅ {selected_stock['name']}をお気に入りに追加しました！")
            else:
                st.info(f"ℹ️ {selected_stock['name']}は既にお気に入りに入っています")
    with col2:
        if st.button("🗑️ お気に入りから削除", use_container_width=True, key='remove_favorite'):
            if selected_code in st.session_state.favorites:
                st.session_state.favorites.remove(selected_code)
                save_favorites(st.session_state.favorites)
                st.success(f"✅ {selected_stock['name']}をお気に入りから削除しました！")

    if st.session_state.favorites:
        st.markdown("#### 保存済み銘柄")
        fav_rows = []
        for fav_code in st.session_state.favorites:
            fav_stock = next((s for s in results if s['ticker'] == fav_code), None)
            if fav_stock:
                fav_rows.append({
                    'コード': fav_code,
                    '企業名': fav_stock['name'],
                    '現在の株価': format_price_jp(fav_stock['price'], market_mode == '米国株', exchange_rate),
                    'セクター': fav_stock['sector'],
                })
        if fav_rows:
            st.dataframe(pd.DataFrame(fav_rows), use_container_width=True, hide_index=True)
    else:
        st.info("💡 お気に入りの銘柄がまだありません。分析画面から追加しましょう！")

def render_selected_stock_details(selected_stock, selected_code, market_mode, exchange_rate, results):
    tab1, tab2, tab3 = st.tabs(["📊 詳細分析", "📰 最新ニュース", "⭐ お気に入り"])
    with tab1:
        _render_tab_analysis(selected_stock, selected_code, market_mode, exchange_rate)
    with tab2:
        _render_tab_news(selected_stock)
    with tab3:
        _render_tab_favorites(selected_stock, selected_code, market_mode, exchange_rate, results)

# ===== 13. UI - サイドバー =====
st.markdown("---")

with st.sidebar:
    st.markdown("### デマーシア！！！")
    st.header("⚙️ スクリーニング設定")

    market_mode = st.radio("📍 **市場選択**", ('日本株', '米国株'), key='market_radio')
    st.session_state.market_mode = market_mode

    st.markdown("---")
    st.subheader("🎯 オススメプリセット")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("手堅く配当狙い", key='preset1', use_container_width=True):
            st.session_state.preset_selected = 'dividend'
            if market_mode == '日本株':
                st.session_state.per_max, st.session_state.pbr_max = 14.0, 0.9
                st.session_state.dividend_min = 3.8
                st.session_state.revenue_growth_min, st.session_state.market_cap_min = 0.0, 0.0
            else:
                st.session_state.per_max, st.session_state.pbr_max = 22.0, 5.0
                st.session_state.dividend_min = 3.5
                st.session_state.revenue_growth_min, st.session_state.market_cap_min = 0.0, 20.0
            st.session_state.per_check = True
            st.session_state.pbr_check = True
            st.session_state.div_check = True
            st.session_state.revgrow_check = True
            st.session_state.mcap_check = False

    with col2:
        if st.button("割安成長株狙い", key='preset2', use_container_width=True):
            st.session_state.preset_selected = 'growth'
            if market_mode == '日本株':
                st.session_state.per_max, st.session_state.pbr_max = 15.0, 1.5
                st.session_state.dividend_min = 1.0
                st.session_state.revenue_growth_min, st.session_state.market_cap_min = 5.0, 10.0
            else:
                st.session_state.per_max, st.session_state.pbr_max = 22.0, 100.0
                st.session_state.dividend_min = 1.0
                st.session_state.revenue_growth_min, st.session_state.market_cap_min = 10.0, 20.0
            st.session_state.per_check = True
            st.session_state.pbr_check = False
            st.session_state.div_check = True
            st.session_state.revgrow_check = True
            st.session_state.mcap_check = True

    if st.session_state.preset_selected:
        with st.expander("プリセットの解説", expanded=False):
            if st.session_state.preset_selected == 'dividend':
                st.info(
                    "💡 **手堅く配当狙い**\n\n"
                    "割安で元本割れリスクが低く、高い配当を出し続ける"
                    "優良大企業をあぶり出します。"
                )
            else:
                st.info(
                    "💡 **王道の割安成長株**\n\n"
                    "世界でビジネスを拡大している企業の中から、実力に対して"
                    "まだ株価が高すぎない「お宝成長株」を探します。"
                )

    if st.session_state.favorites:
        with st.expander("⭐ お気に入り一覧", expanded=True):
            fav_rows = []
            for fav in st.session_state.favorites:
                try:
                    data = fetch_stock_data(fav)
                    if data:
                        fav_rows.append({
                            'コード': data['ticker'],
                            '企業名': data['name'],
                        })
                except Exception:
                    continue
            if fav_rows:
                st.markdown("**コード / 企業名**")
                for fav in fav_rows:
                    name = fav['企業名'][:20] + ('...' if len(fav['企業名']) > 20 else '')
                    c = st.columns([1, 3, 1])
                    c[0].write(fav['コード'])
                    c[1].write(name)
                    if c[2].button("詳細", key=f"fav_detail_{fav['コード']}"):
                        st.session_state.selected_ticker = fav['コード']
                        st.rerun()
            else:
                st.info("お気に入り銘柄のデータを取得できませんでした")

    st.markdown("---")
    st.subheader("🔍 詳細条件")

    per_enabled = st.checkbox("PER制限", value=True, key='per_check')
    per_max = st.slider("PER上限（倍）", 0.0, 50.0, st.session_state.per_max, 0.5, key='per_slider') if per_enabled else 999

    pbr_enabled = st.checkbox("PBR制限", value=False, key='pbr_check')
    pbr_max = st.slider("PBR上限（倍）", 0.0, 10.0, st.session_state.pbr_max, 0.1, key='pbr_slider') if pbr_enabled else 999

    dividend_enabled = st.checkbox("配当利回り制限", value=False, key='div_check')
    dividend_min = st.slider("配当利回り下限（%）", 0.0, 10.0, st.session_state.dividend_min, 0.1, key='div_slider') if dividend_enabled else 0

    market_cap_enabled = st.checkbox("時価総額制限", value=False, key='mcap_check')
    cap_unit = "ドル" if market_mode == '米国株' else "円"
    market_cap_min = st.slider(f"時価総額下限（十億{cap_unit}）", 0.0, 100.0, st.session_state.market_cap_min, 1.0, key='mcap_slider') if market_cap_enabled else 0

    revenue_growth_enabled = st.checkbox("売上高成長率制限", value=False, key='revgrow_check')
    revenue_growth_min = st.slider("売上高成長率下限（%）", -50.0, 100.0, st.session_state.revenue_growth_min, 1.0, key='revgrow_slider') if revenue_growth_enabled else -999

    sector_enabled = st.checkbox("業種制限", value=False, key='sector_check')
    sectors_selected = []
    if sector_enabled:
        available_sectors = sorted([
            'テクノロジー（IT・半導体）','金融（銀行・保険）','景気敏感消費財（自動車・アパレル等）',
            '医療・ヘルスケア','工業・製造業','通信・メディア','エネルギー（石油・電力）',
            '不動産','インフラ・公共','生活必需品','素材・鉱物',
        ])
        sectors_selected = st.multiselect("業種選択", available_sectors, default=[], key='sector_select')

    st.markdown("---")
    st.subheader("⚡ 取得上限")
    full_market_mode = st.checkbox("全銘柄取得（時間がかかる）", value=st.session_state.full_market_mode, key='full_market_mode')
    max_tickers = st.slider("上位取得銘柄数", 50, 1000, st.session_state.max_tickers, 50, key='max_tickers')
    st.markdown("---")
    screening_button = st.button("🔎 スクリーニング実行", use_container_width=True, type="primary")

# ===== 14. メインエリア =====
if screening_button:
    with st.spinner("📊 データを取得中..."):
        all_tickers = get_market_tickers(market_mode)
        st.session_state.market_count = len(all_tickers)

        sample_stocks = all_tickers if full_market_mode else all_tickers[:max_tickers]
        if not full_market_mode and len(all_tickers) > len(sample_stocks):
            st.warning(
                f"全銘柄 {len(all_tickers)} 件中、先頭 {len(sample_stocks)} 件のみ取得しています。"
                "\n全件取得は非常に時間がかかります。"
            )

        st.session_state.used_count = len(sample_stocks)
        stocks_data = fetch_stock_data_batch(sample_stocks, market_mode)

        filters = {
            'per_enabled': per_enabled, 'per_max': per_max,
            'pbr_enabled': pbr_enabled, 'pbr_max': pbr_max,
            'dividend_enabled': dividend_enabled, 'dividend_min': dividend_min,
            'market_cap_enabled': market_cap_enabled, 'market_cap_min': market_cap_min,
            'revenue_growth_enabled': revenue_growth_enabled, 'revenue_growth_min': revenue_growth_min,
            'sector_enabled': sector_enabled, 'sectors': sectors_selected,
        }

        screening_results, exchange_rate = apply_screening(stocks_data, filters, market_mode)
        st.session_state.screening_results = screening_results
        st.session_state.current_exchange_rate = exchange_rate
        st.session_state.market_mode = market_mode

if 'screening_results' in st.session_state:
    results      = st.session_state.screening_results
    exchange_rate = st.session_state.current_exchange_rate
    total_count  = st.session_state.get('market_count', len(SAMPLE_STOCKS_JP if market_mode == '日本株' else SAMPLE_STOCKS_US))
    used_count   = st.session_state.get('used_count', total_count)
    result_count = len(results)

    label = (
        f"### 📋 全 {total_count} 銘柄中、先頭 {used_count} 件を取得し、条件に合う株が **{result_count}** 企業見つかりました！"
        if total_count != used_count
        else f"### 📋 全 {total_count} 銘柄中、条件に合う株が **{result_count}** 企業見つかりました！"
    )
    st.markdown(label)

    if result_count > 0:
        # 表の行選択（案A）を実装するためのデータフレーム作成
        is_us_csv = market_mode == '米国株'
        raw_df_data = []
        for stock in results:
            score = calculate_buy_timing_score(stock, market_mode)
            is_etf_flag = stock.get('is_etf', False)
            
            per_v = stock.get('per')
            pbr_v = stock.get('pbr')
            div_v = stock.get('dividend_yield')
            rev_v = stock.get('revenue_growth')

            raw_df_data.append({
                'コード': stock['ticker'],
                '企業名': stock['name'] + (' [ETF]' if is_etf_flag else ''),
                '株価': format_price_jp(stock['price'], is_us_csv, exchange_rate),
                'PER(倍)': per_v if per_v and not np.isnan(per_v) else None,
                'PBR(倍)': pbr_v if pbr_v and not np.isnan(pbr_v) else None,
                '配当利回り(%)': div_v if div_v else 0.0,
                '時価総額': format_market_cap(stock['market_cap'], is_us_csv, exchange_rate),
                '売上高成長率(%)': rev_v if rev_v and not np.isnan(rev_v) else None,
                'セクター': stock['sector'],
                '買い時スコア': score,
            })
        
        df_display = pd.DataFrame(raw_df_data)

        # セッションに入っている選択中のコードが結果に無ければ、先頭の銘柄を自動選択
        if st.session_state.selected_ticker not in [s['ticker'] for s in results]:
            st.session_state.selected_ticker = results[0]['ticker']

        selected_code = st.session_state.selected_ticker
        selected_stock = next((s for s in results if s['ticker'] == selected_code), None)
        
        if selected_stock:
            st.markdown("### 🔎 選択中の銘柄詳細")
            render_selected_stock_details(selected_stock, selected_code, market_mode, exchange_rate, results)
            st.markdown("---")

        # ===== 抽出結果エリア（案A：データフレームによるクリック連動） =====
        st.markdown("### 抽出結果")
        st.caption("💡 一覧表の **行をクリック** すると、上の詳細分析・チャート・ニュースが自動でその銘柄に切り替わります！")

        # CSVダウンロード用
        col_dl, _ = st.columns([1, 9])
        with col_dl:
            csv_data = df_display.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                "📥 CSVダウンロード",
                data=csv_data,
                file_name=f"screening_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        # 現在選択されている行のインデックスを探して初期ハイライト位置にする
        initial_selection = []
        matched_indices = df_display.index[df_display['コード'] == selected_code].tolist()
        if matched_indices:
            initial_selection = [matched_indices[0]]

        # スタイラーを使って、PER・配当・スコア等に条件付きの文字色を付与（旧HTMLデザインの移植）
        def _color_per(val):
            if val is None or np.isnan(val): return ''
            benchmark = 15 if market_mode == '日本株' else 22
            return 'color: #00d084; font-weight:600;' if val < benchmark else 'color: #ff9900; font-weight:600;'

        def _color_div(val):
            if val >= 3.5: return 'color: #00d084; font-weight:600;'
            elif val >= 2.0: return 'color: #ff9900; font-weight:600;'
            return ''

        def _color_rev(val):
            if val is None or np.isnan(val): return ''
            return 'color: #00d084; font-weight:600;' if val >= 10 else ('color: #ff9900; font-weight:600;' if val >= 0 else 'color: #ff5555; font-weight:600;')

        def _color_score(val):
            return f'color: {get_score_color(val)}; font-weight: bold;'

        styled_df = df_display.style.map(_color_per, subset=['PER(倍)'])\
                                      .map(_color_div, subset=['配当利回り(%)'])\
                                      .map(_color_rev, subset=['売上高成長率(%)'])\
                                      .map(_color_score, subset=['買い時スコア'])\
                                      .format({'PER(倍)': '{:.1f}', 'PBR(倍)': '{:.2f}', '配当利回り(%)': '{:.2f}%', '売上高成長率(%)': '{:+.1f}%'}, na_rep='N/A')

        # インタラクティブな次世代データフレームの表示
        event = st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "コード": st.column_config.TextColumn("コード", width="medium"),
                "企業名": st.column_config.TextColumn("企業名", width="large"),
                "買い時スコア": st.column_config.NumberColumn("買い時スコア", format="%.1f点"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="interactive_stock_table"
        )

        # 行がクリックされたらセッションステートを書き換えて即座にトリガー（リラン）
        if event and "rows" in event.get("selection", {}) and event["selection"]["rows"]:
            clicked_row_idx = event["selection"]["rows"][0]
            new_selected_code = df_display.iloc[clicked_row_idx]['コード']
            if new_selected_code != st.session_state.selected_ticker:
                st.session_state.selected_ticker = new_selected_code
                st.rerun()

elif st.session_state.selected_ticker:
    selected_code  = st.session_state.selected_ticker
    selected_stock = fetch_stock_data(selected_code)
    if selected_stock:
        exchange_rate = get_exchange_rate() if market_mode == '米国株' else 1.0
        render_selected_stock_details(selected_stock, selected_code, market_mode, exchange_rate, [])
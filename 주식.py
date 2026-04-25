"""
S&P 500 / Russell 2000 종목 데이터 크롤러
- 종목 목록: S&P 500 (Wikipedia), Russell 2000 (iShares IWM ETF)
- 주가 데이터: yfinance
- 결과: dictionary 형태로 반환
"""

import io
import time
from datetime import datetime
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
# 1. 종목 목록 수집
# ─────────────────────────────────────────────

def get_sp500_tickers() -> list[str]:
    """Wikipedia에서 S&P 500 구성 종목 티커 수집"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "html.parser")
    table = soup.find("table", {"id": "constituents"})
    if table is None:
        raise RuntimeError("S&P 500 테이블을 찾을 수 없습니다.")

    tickers = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if not cols:
            continue
        ticker = cols[0].text.strip().replace(".", "-")  # BRK.B → BRK-B
        tickers.append(ticker)

    return tickers


def get_russell2000_tickers() -> list[str]:
    """iShares IWM ETF 보유 종목 CSV에서 Russell 2000 티커 수집"""
    url = (
        "https://www.ishares.com/us/products/239710/"
        "ishares-russell-2000-etf/1467271812596.ajax"
        "?fileType=csv&fileName=IWM_holdings&dataType=fund"
    )
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MarketDataCrawler/1.0)"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    # 첫 9행은 메타데이터
    df = pd.read_csv(io.StringIO(resp.text), skiprows=9, on_bad_lines="skip")
    if "Asset Class" not in df.columns or "Ticker" not in df.columns:
        raise RuntimeError("Russell 2000 CSV 포맷이 예상과 다릅니다.")

    df = df[df["Asset Class"] == "Equity"]
    tickers = (
        df["Ticker"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", "-", regex=True)
        .tolist()
    )
    return [t for t in tickers if t and t != "nan"]


# ─────────────────────────────────────────────
# 2. 주가 데이터 수집 및 통계 계산
# ─────────────────────────────────────────────

def _compute_stats(close: pd.Series, volume: pd.Series, period: str) -> dict[str, Any]:
    """단일 종목의 가격·거래량 통계를 계산해 dict로 반환"""
    close = close.dropna()
    volume = volume.dropna()

    if close.empty:
        return {}

    total_volume = float(volume.sum())
    if total_volume > 0:
        weights = volume / total_volume
        weighted_avg_price = float((close * weights).sum())
    else:
        weighted_avg_price = float(close.mean())

    return {
        "current_price":       round(float(close.iloc[-1]), 4),
        "weighted_avg_price":  round(weighted_avg_price, 4),   # 거래량 가중 평균 가격
        "avg_daily_volume":    round(float(volume.mean()), 0),  # 일평균 거래량
        "total_volume":        round(total_volume, 0),
        "price_high":          round(float(close.max()), 4),
        "price_low":           round(float(close.min()), 4),
        "price_change_pct":    round(float((close.iloc[-1] / close.iloc[0] - 1) * 100), 4),
        "trading_days":        len(close),
        "period":              period,
    }


def fetch_stock_data(
    tickers: list[str],
    period: str = "1mo",
    batch_size: int = 50,
    sleep_sec: float = 0.5,
) -> dict[str, dict[str, Any]]:
    """
    yfinance로 배치 다운로드 후 종목별 통계를 계산.

    Parameters
    ----------
    tickers    : 티커 목록
    period     : yfinance 기간 문자열 (1d, 5d, 1mo, 3mo, 6mo, 1y, ...)
    batch_size : 한 번에 요청할 최대 종목 수
    sleep_sec  : 배치 간 대기 시간(초)
    """
    stock_data: dict[str, dict[str, Any]] = {}
    total_batches = (len(tickers) + batch_size - 1) // batch_size

    for batch_idx, start in enumerate(range(0, len(tickers), batch_size)):
        batch = tickers[start : start + batch_size]
        print(f"  배치 {batch_idx + 1}/{total_batches} ({len(batch)}개 종목) 처리 중...")

        try:
            raw = yf.download(
                tickers=batch,
                period=period,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            print(f"  [경고] 배치 다운로드 실패: {exc}")
            continue

        if raw.empty:
            continue

        # yfinance: 단일 티커 → 2D DataFrame, 복수 티커 → MultiIndex
        multi = isinstance(raw.columns, pd.MultiIndex)

        for ticker in batch:
            try:
                if multi:
                    close  = raw["Close"][ticker]
                    volume = raw["Volume"][ticker]
                else:
                    close  = raw["Close"]
                    volume = raw["Volume"]

                stats = _compute_stats(close, volume, period)
                if stats:
                    stock_data[ticker] = stats

            except KeyError:
                pass  # 해당 종목 데이터 없음
            except Exception as exc:
                print(f"  [경고] {ticker} 처리 오류: {exc}")

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    return stock_data


# ─────────────────────────────────────────────
# 3. 메인 실행 및 결과 구조화
# ─────────────────────────────────────────────

def build_market_dict(period: str = "1mo") -> dict[str, Any]:
    """
    S&P 500 + Russell 2000 종목 데이터를 수집해 dictionary로 반환.

    반환 구조
    ---------
    {
      "metadata": { fetched_at, period, sp500_count, russell2000_count, total_stocks },
      "sp500":     { TICKER: { current_price, weighted_avg_price, ... }, ... },
      "russell2000": { ... },
      "all_stocks":  { ... }   # 두 지수 합집합
    }
    """
    print("=" * 60)
    print("S&P 500 종목 목록 수집 중...")
    sp500 = get_sp500_tickers()
    print(f"  → {len(sp500)}개 종목")

    print("Russell 2000 종목 목록 수집 중...")
    try:
        r2000 = get_russell2000_tickers()
        print(f"  → {len(r2000)}개 종목")
    except Exception as exc:
        print(f"  [경고] Russell 2000 수집 실패, 빈 목록 사용: {exc}")
        r2000 = []

    all_tickers = list(dict.fromkeys(sp500 + r2000))  # 순서 유지 중복 제거
    print(f"\n총 고유 종목: {len(all_tickers)}개 | 기간: {period}")
    print("=" * 60)

    print("주가·거래량 데이터 수집 중...")
    all_data = fetch_stock_data(all_tickers, period=period)
    print(f"\n수집 완료: {len(all_data)}개 종목")

    result: dict[str, Any] = {
        "metadata": {
            "fetched_at":       datetime.now().isoformat(),
            "period":           period,
            "sp500_count":      len([t for t in sp500    if t in all_data]),
            "russell2000_count":len([t for t in r2000    if t in all_data]),
            "total_stocks":     len(all_data),
        },
        "sp500":      {t: all_data[t] for t in sp500 if t in all_data},
        "russell2000":{t: all_data[t] for t in r2000 if t in all_data},
        "all_stocks": all_data,
    }

    return result


# ─────────────────────────────────────────────
# 4. 실행 예시
# ─────────────────────────────────────────────

if __name__ == "__main__":
    market = build_market_dict(period="1mo")

    meta = market["metadata"]
    print("\n[메타데이터]")
    for k, v in meta.items():
        print(f"  {k}: {v}")

    # S&P 500 거래량 상위 5종목
    sp500_sorted = sorted(
        market["sp500"].items(),
        key=lambda kv: kv[1].get("avg_daily_volume", 0),
        reverse=True,
    )
    print("\n[S&P 500 일평균 거래량 상위 5]")
    for ticker, d in sp500_sorted[:5]:
        print(
            f"  {ticker:8s}  현재가: ${d['current_price']:>10,.2f}"
            f"  가중평균가: ${d['weighted_avg_price']:>10,.2f}"
            f"  일평균거래량: {d['avg_daily_volume']:>15,.0f}"
        )

    # Russell 2000 거래량 상위 5종목
    r2000_sorted = sorted(
        market["russell2000"].items(),
        key=lambda kv: kv[1].get("avg_daily_volume", 0),
        reverse=True,
    )
    print("\n[Russell 2000 일평균 거래량 상위 5]")
    for ticker, d in r2000_sorted[:5]:
        print(
            f"  {ticker:8s}  현재가: ${d['current_price']:>10,.2f}"
            f"  가중평균가: ${d['weighted_avg_price']:>10,.2f}"
            f"  일평균거래량: {d['avg_daily_volume']:>15,.0f}"
        )
